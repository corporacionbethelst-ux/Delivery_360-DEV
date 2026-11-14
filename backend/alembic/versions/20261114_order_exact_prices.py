"""Prospective exact order prices without casting or rewriting historical floats."""

from alembic import op
import sqlalchemy as sa

revision = "20261114_order_exact_prices"
down_revision = "20261114_explicit_usd"
branch_labels = None
depends_on = None

COLUMNS = (
    "pricing_version",
    "pricing_revision",
    "subtotal_exact",
    "delivery_fee_exact",
    "total_exact",
    "items_exact",
)


def upgrade():
    for name in COLUMNS:
        type_ = (
            sa.Integer()
            if name.startswith("pricing_")
            else sa.JSON() if name == "items_exact" else sa.Numeric(10, 2)
        )
        op.add_column("orders", sa.Column(name, type_, nullable=True))
    op.create_check_constraint(
        "ck_order_exact_price_pack",
        "orders",
        """
        (pricing_version IS NULL AND pricing_revision IS NULL AND subtotal_exact IS NULL
         AND delivery_fee_exact IS NULL AND total_exact IS NULL AND items_exact IS NULL)
        OR (pricing_version = 1 AND pricing_version IS NOT NULL AND currency_code IS NOT NULL AND currency_code = 'USD'
         AND pricing_revision IS NOT NULL AND pricing_revision BETWEEN 1 AND 2147483647
         AND subtotal_exact IS NOT NULL AND delivery_fee_exact IS NOT NULL AND total_exact IS NOT NULL AND items_exact IS NOT NULL
         AND subtotal_exact BETWEEN 0 AND 99999999.99 AND delivery_fee_exact BETWEEN 0 AND 99999999.99
         AND total_exact BETWEEN 0 AND 99999999.99 AND total_exact = subtotal_exact + delivery_fee_exact)
    """,
    )
    op.execute(
        r"""CREATE FUNCTION validate_order_exact_price() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE item jsonb; mirror jsonb; idx integer; amount numeric; summed numeric := 0;
      source jsonb; compatible jsonb; changed boolean;
    BEGIN
      IF TG_OP = 'UPDATE' AND OLD.pricing_version = 1 THEN
        IF NEW.pricing_version IS DISTINCT FROM 1 THEN
          RAISE EXCEPTION 'Exact pricing cannot be downgraded';
        END IF;
        changed := ROW(NEW.subtotal_exact,NEW.delivery_fee_exact,NEW.total_exact,NEW.items_exact::jsonb)
          IS DISTINCT FROM ROW(OLD.subtotal_exact,OLD.delivery_fee_exact,OLD.total_exact,OLD.items_exact::jsonb);
        IF (changed AND NEW.pricing_revision IS DISTINCT FROM OLD.pricing_revision+1)
          OR (NOT changed AND NEW.pricing_revision IS DISTINCT FROM OLD.pricing_revision) THEN
          RAISE EXCEPTION 'Exact price revision must match the price change';
        END IF;
      END IF;
      IF NEW.pricing_version IS NULL THEN RETURN NEW; END IF;
      IF (TG_OP = 'INSERT' OR OLD.pricing_version IS NULL) AND NEW.pricing_revision IS DISTINCT FROM 1 THEN
        RAISE EXCEPTION 'Exact pricing starts at revision one';
      END IF;
      source := NEW.items_exact::jsonb; compatible := NEW.items::jsonb;
      IF jsonb_typeof(source) IS DISTINCT FROM 'array' OR jsonb_array_length(source)>200
        OR jsonb_typeof(compatible) IS DISTINCT FROM 'array'
        OR jsonb_array_length(source) IS DISTINCT FROM jsonb_array_length(compatible) THEN
        RAISE EXCEPTION 'Exact line items must be bounded arrays';
      END IF;
      IF NEW.subtotal IS NULL OR NEW.delivery_fee IS NULL OR NEW.total IS NULL
        OR NEW.subtotal::numeric <> NEW.subtotal_exact OR NEW.delivery_fee::numeric <> NEW.delivery_fee_exact
        OR NEW.total::numeric <> NEW.total_exact THEN
        RAISE EXCEPTION 'Compatibility amounts must match exact prices';
      END IF;
      FOR idx IN 0..jsonb_array_length(source)-1 LOOP
        item := source->idx; mirror := compatible->idx;
        IF jsonb_typeof(item) IS DISTINCT FROM 'object' OR jsonb_typeof(mirror) IS DISTINCT FROM 'object'
          OR NOT (item ?& ARRAY['quantity','unit_price','subtotal'])
          OR jsonb_typeof(item->'subtotal') IS DISTINCT FROM 'string'
          OR (item->>'subtotal') !~ '^(0|[1-9][0-9]{0,7})\.[0-9]{2}$' THEN
          RAISE EXCEPTION 'Exact line subtotal is invalid';
        END IF;
        amount := (item->>'subtotal')::numeric;
        IF (item->>'quantity') IS NULL AND (item->>'unit_price') IS NULL THEN
          IF (mirror->>'quantity') IS NOT NULL OR (mirror->>'unit_price') IS NOT NULL THEN
            RAISE EXCEPTION 'Charge-only line must preserve its meaning';
          END IF;
        ELSE
          IF jsonb_typeof(item->'quantity') IS DISTINCT FROM 'string'
            OR jsonb_typeof(item->'unit_price') IS DISTINCT FROM 'string'
            OR (item->>'quantity') !~ '^(0|[1-9][0-9]{0,5})(\.[0-9]{1,3})?$'
            OR (item->>'unit_price') !~ '^(0|[1-9][0-9]{0,7})\.[0-9]{2}$' THEN
            RAISE EXCEPTION 'Exact quantity or unit price is invalid';
          END IF;
          IF (item->>'quantity')::numeric <= 0
            OR round((item->>'quantity')::numeric*(item->>'unit_price')::numeric,2) <> amount
            OR (mirror->>'quantity')::numeric IS DISTINCT FROM (item->>'quantity')::numeric
            OR (mirror->>'unit_price')::numeric IS DISTINCT FROM (item->>'unit_price')::numeric THEN
            RAISE EXCEPTION 'Exact line arithmetic or quantity does not match';
          END IF;
        END IF;
        IF (mirror->>'subtotal')::numeric IS DISTINCT FROM amount
          OR (mirror-'quantity'-'unit_price'-'subtotal') IS DISTINCT FROM (item-'quantity'-'unit_price'-'subtotal') THEN
          RAISE EXCEPTION 'Compatibility line must match its exact source';
        END IF;
        summed := summed + amount;
      END LOOP;
      IF jsonb_array_length(source)>0 AND summed <> NEW.subtotal_exact THEN
        RAISE EXCEPTION 'Exact subtotal must match line items';
      END IF;
      RETURN NEW;
    END; $$"""
    )
    op.execute(
        "CREATE TRIGGER validate_exact_order_price BEFORE INSERT OR UPDATE ON orders FOR EACH ROW EXECUTE FUNCTION validate_order_exact_price()"
    )


def downgrade():
    op.execute("LOCK TABLE orders IN ACCESS EXCLUSIVE MODE NOWAIT")
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM orders WHERE pricing_version IS NOT NULL)"
            )
        )
        .scalar()
    ):
        raise RuntimeError("Downgrade refused: preserve exact order prices first")
    op.execute("DROP TRIGGER validate_exact_order_price ON orders")
    op.execute("DROP FUNCTION validate_order_exact_price()")
    op.drop_constraint("ck_order_exact_price_pack", "orders", type_="check")
    for name in reversed(COLUMNS):
        op.drop_column("orders", name)
