"""Preserve BCV references and exact order price snapshots without rewriting history."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "20261114_order_bcv_quotes"
down_revision = "20261114_order_exact_prices"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "order_currency_quotes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("request_key", UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column(
            "order_id",
            UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("order_external_id", sa.String(100), nullable=True),
        sa.Column("pricing_revision", sa.Integer, nullable=False),
        sa.Column("pricing_snapshot", sa.JSON, nullable=False),
        sa.Column(
            "rate_id",
            UUID(as_uuid=True),
            sa.ForeignKey("bcv_rates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("amount_ves", sa.Numeric(24, 2), nullable=False),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.CheckConstraint(
            "pricing_revision BETWEEN 1 AND 2147483647 AND amount_usd BETWEEN 0 AND 99999999.99 AND amount_ves >= 0 AND amount_ves < 1000000000000000000000",
            name="ck_order_quote_amounts",
        ),
    )
    op.create_index(
        "ix_order_currency_quotes_order_created",
        "order_currency_quotes",
        ["order_id", "created_at", "id"],
    )
    op.execute(
        """CREATE FUNCTION validate_order_currency_quote() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE purchase orders%ROWTYPE; rate bcv_rates%ROWTYPE; pack jsonb; day date;
    BEGIN
      SELECT * INTO purchase FROM orders WHERE id=NEW.order_id FOR UPDATE;
      IF NOT FOUND THEN RAISE EXCEPTION 'Order quote requires an existing order'; END IF;
      IF purchase.currency_code IS DISTINCT FROM 'USD' OR purchase.pricing_version IS DISTINCT FROM 1
        OR purchase.pricing_revision IS DISTINCT FROM NEW.pricing_revision
        OR purchase.status IS NULL OR purchase.status::text IN ('CANCELADO','FALLIDO') THEN
        RAISE EXCEPTION 'Order quote requires the current eligible exact USD price';
      END IF;
      day := (clock_timestamp() AT TIME ZONE 'America/Caracas')::date;
      PERFORM pg_advisory_xact_lock(hashtext('bcv:day:'||day::text)::bigint);
      IF day IS DISTINCT FROM (clock_timestamp() AT TIME ZONE 'America/Caracas')::date THEN
        RAISE EXCEPTION 'Operating day changed during quotation';
      END IF;
      SELECT * INTO rate FROM bcv_rates WHERE valid_on=day ORDER BY revision DESC LIMIT 1;
      IF NOT FOUND OR rate.id IS DISTINCT FROM NEW.rate_id
        OR (NEW.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Caracas')::date IS DISTINCT FROM day THEN
        RAISE EXCEPTION 'Order quote requires the current BCV reference';
      END IF;
      pack := jsonb_build_object('version',1,'currency','USD','revision',purchase.pricing_revision,
        'subtotal',to_char(purchase.subtotal_exact,'FM999999990.00'),
        'delivery_fee',to_char(purchase.delivery_fee_exact,'FM999999990.00'),
        'total',to_char(purchase.total_exact,'FM999999990.00'),'items',purchase.items_exact::jsonb);
      IF NEW.pricing_snapshot::jsonb IS DISTINCT FROM pack
        OR NEW.order_external_id IS DISTINCT FROM purchase.external_id
        OR NEW.amount_usd IS DISTINCT FROM purchase.total_exact
        OR NEW.amount_ves IS DISTINCT FROM round(NEW.amount_usd*rate.ves_per_usd,2) THEN
        RAISE EXCEPTION 'Order quote must preserve its exact price and conversion';
      END IF;
      RETURN NEW;
    END; $$"""
    )
    op.execute(
        "CREATE TRIGGER validate_order_currency_quote BEFORE INSERT ON order_currency_quotes FOR EACH ROW EXECUTE FUNCTION validate_order_currency_quote()"
    )
    # The helper belongs to migration 90 and stays in place on this downgrade.
    op.execute(
        "CREATE TRIGGER immutable_order_currency_quotes BEFORE UPDATE OR DELETE ON order_currency_quotes FOR EACH ROW EXECUTE FUNCTION currency_history_immutable()"
    )
    op.execute(
        "CREATE TRIGGER immutable_truncate_order_currency_quotes BEFORE TRUNCATE ON order_currency_quotes EXECUTE FUNCTION currency_history_immutable()"
    )


def downgrade():
    op.execute("LOCK TABLE order_currency_quotes IN ACCESS EXCLUSIVE MODE NOWAIT")
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM order_currency_quotes)"))
        .scalar()
    ):
        raise RuntimeError("Downgrade refused: preserve order quotation receipts first")
    op.drop_table("order_currency_quotes")
    op.execute("DROP FUNCTION validate_order_currency_quote()")
