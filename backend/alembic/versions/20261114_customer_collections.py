"""Independent, append-only customer collections and manual decisions; no backfill."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "20261114_customer_collections"
down_revision = "20261114_order_bcv_quotes"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("orders", sa.Column("collection_revision", sa.Integer, nullable=True))
    op.add_column("orders", sa.Column("collection_locked", sa.Boolean, nullable=True))
    op.create_table(
        "customer_collections",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("request_key", UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column(
            "order_id",
            UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "quote_id",
            UUID(as_uuid=True),
            sa.ForeignKey("order_currency_quotes.id", ondelete="RESTRICT"),
        ),
        sa.Column("pricing_revision", sa.Integer, nullable=False),
        sa.Column("pricing_snapshot", sa.JSON, nullable=False),
        sa.Column("amount_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("paid_amount", sa.Numeric(24, 2), nullable=False),
        sa.Column("paid_currency", sa.String(3), nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("source_key", sa.String(80), nullable=False),
        sa.Column("reference_key", sa.String(120), nullable=False),
        sa.Column("received_on", sa.Date, nullable=False),
        sa.Column(
            "declared_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.CheckConstraint(
            "pricing_revision BETWEEN 1 AND 2147483647 AND amount_usd > 0 AND amount_usd <= 99999999.99 AND paid_amount > 0 AND paid_amount < 1000000000000000000000",
            name="ck_collection_amounts",
        ),
        sa.CheckConstraint(
            "paid_currency IN ('USD','VES') AND method IN ('EFECTIVO','TRANSFERENCIA','PAGO_MOVIL') AND (method <> 'PAGO_MOVIL' OR paid_currency='VES') AND ((paid_currency='VES') = (quote_id IS NOT NULL))",
            name="ck_collection_currency",
        ),
    )
    op.create_index(
        "ix_customer_collections_order_created",
        "customer_collections",
        ["order_id", "created_at", "id"],
    )
    op.create_index(
        "ix_customer_collections_reference",
        "customer_collections",
        ["source_key", "reference_key"],
    )
    op.create_table(
        "customer_collection_reviews",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("request_key", UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column(
            "collection_id",
            UUID(as_uuid=True),
            sa.ForeignKey("customer_collections.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("note", sa.String(500), nullable=False),
        sa.Column("verified_evidence", sa.Boolean, nullable=False),
        sa.Column("acknowledge_refund_due", sa.Boolean, nullable=False),
        sa.Column(
            "reviewed_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime, nullable=False),
        sa.CheckConstraint(
            "decision IN ('VERIFICADO','RECHAZADO') AND verified_evidence = (decision='VERIFICADO') AND length(btrim(note)) BETWEEN 10 AND 500 AND note !~ '[[:cntrl:]]'",
            name="ck_collection_review_decision",
        ),
    )
    op.execute(
        r"""CREATE FUNCTION validate_customer_collection() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE purchase orders%ROWTYPE; quote order_currency_quotes%ROWTYPE; rate bcv_rates%ROWTYPE;
      pack jsonb; reserved numeric; day date; actor users%ROWTYPE;
    BEGIN
      SELECT * INTO purchase FROM orders WHERE id=NEW.order_id FOR UPDATE;
      IF NOT FOUND OR purchase.currency_code IS DISTINCT FROM 'USD' OR purchase.pricing_version IS DISTINCT FROM 1
        OR purchase.pricing_revision IS DISTINCT FROM NEW.pricing_revision OR purchase.status IS NULL
        OR purchase.status::text IN ('CANCELADO','FALLIDO') THEN
        RAISE EXCEPTION USING ERRCODE='P0094', MESSAGE='Collection requires the current eligible USD order';
      END IF;
      IF NEW.source_key !~ '^[A-Z0-9][A-Z0-9 ._/#:\-]*$' OR NEW.reference_key !~ '^[A-Z0-9][A-Z0-9 ._/#:\-]*$'
        OR NEW.source_key IS DISTINCT FROM regexp_replace(btrim(NEW.source_key),' +',' ','g')
        OR NEW.reference_key IS DISTINCT FROM regexp_replace(btrim(NEW.reference_key),' +',' ','g') THEN
        RAISE EXCEPTION USING ERRCODE='P0094', MESSAGE='Collection reference must be canonical';
      END IF;
      PERFORM pg_advisory_xact_lock(hashtext('collection:reference:'||NEW.source_key||chr(31)||NEW.reference_key)::bigint);
      SELECT * INTO actor FROM users WHERE id=NEW.declared_by FOR SHARE;
      IF NOT FOUND OR actor.is_active IS DISTINCT FROM true OR actor.role::text NOT IN ('SUPERADMIN','GERENTE','OPERADOR') THEN
        RAISE EXCEPTION USING ERRCODE='P0094', MESSAGE='Collection requires an active staff declarer';
      END IF;
      IF EXISTS(SELECT 1 FROM customer_collections c LEFT JOIN customer_collection_reviews r ON r.collection_id=c.id
        WHERE c.source_key=NEW.source_key AND c.reference_key=NEW.reference_key AND r.decision IS DISTINCT FROM 'RECHAZADO') THEN
        RAISE EXCEPTION USING ERRCODE='P0094', MESSAGE='Collection reference already reserved';
      END IF;
      day := (clock_timestamp() AT TIME ZONE 'America/Caracas')::date;
      IF NEW.received_on IS DISTINCT FROM day OR
        (NEW.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Caracas')::date IS DISTINCT FROM day THEN
        RAISE EXCEPTION USING ERRCODE='P0094', MESSAGE='Collection must be declared on its operating day';
      END IF;
      pack := jsonb_build_object('version',1,'currency','USD','revision',purchase.pricing_revision,
        'subtotal',to_char(purchase.subtotal_exact,'FM999999990.00'),
        'delivery_fee',to_char(purchase.delivery_fee_exact,'FM999999990.00'),
        'total',to_char(purchase.total_exact,'FM999999990.00'),'items',purchase.items_exact::jsonb);
      IF NEW.pricing_snapshot::jsonb IS DISTINCT FROM pack THEN
        RAISE EXCEPTION USING ERRCODE='P0094', MESSAGE='Collection must preserve the exact price';
      END IF;
      SELECT coalesce(sum(c.amount_usd),0) INTO reserved FROM customer_collections c
        LEFT JOIN customer_collection_reviews r ON r.collection_id=c.id
        WHERE c.order_id=NEW.order_id AND r.decision IS DISTINCT FROM 'RECHAZADO';
      IF NEW.amount_usd > purchase.total_exact-reserved THEN
        RAISE EXCEPTION USING ERRCODE='P0094', MESSAGE='Collection exceeds unreserved amount';
      END IF;
      IF NEW.paid_currency='USD' THEN
        IF NEW.paid_amount IS DISTINCT FROM NEW.amount_usd THEN
          RAISE EXCEPTION USING ERRCODE='P0094', MESSAGE='USD payment must match the credit';
        END IF;
      ELSE
        SELECT * INTO quote FROM order_currency_quotes WHERE id=NEW.quote_id;
        IF NOT FOUND OR quote.order_id IS DISTINCT FROM NEW.order_id OR quote.pricing_revision IS DISTINCT FROM NEW.pricing_revision
          OR (actor.role::text='OPERADOR' AND quote.created_by IS DISTINCT FROM NEW.declared_by) THEN
          RAISE EXCEPTION USING ERRCODE='P0094', MESSAGE='VES collection requires its own current order quote';
        END IF;
        SELECT * INTO rate FROM bcv_rates WHERE id=quote.rate_id;
        IF NOT FOUND OR rate.valid_on IS DISTINCT FROM day OR NEW.paid_amount IS DISTINCT FROM round(NEW.amount_usd*rate.ves_per_usd,2) THEN
          RAISE EXCEPTION USING ERRCODE='P0094', MESSAGE='VES collection must preserve the agreed daily conversion';
        END IF;
      END IF;
      RETURN NEW;
    END; $$"""
    )
    op.execute(
        """CREATE FUNCTION validate_customer_collection_review() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE entry customer_collections%ROWTYPE; purchase orders%ROWTYPE; actor users%ROWTYPE;
    BEGIN
      SELECT * INTO entry FROM customer_collections WHERE id=NEW.collection_id;
      IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='P0094', MESSAGE='Collection not found'; END IF;
      SELECT * INTO purchase FROM orders WHERE id=entry.order_id FOR UPDATE;
      PERFORM pg_advisory_xact_lock(hashtext('collection:reference:'||entry.source_key||chr(31)||entry.reference_key)::bigint);
      SELECT * INTO actor FROM users WHERE id=NEW.reviewed_by FOR SHARE;
      IF NOT FOUND OR actor.is_active IS DISTINCT FROM true OR actor.role::text NOT IN ('SUPERADMIN','GERENTE')
        OR NEW.reviewed_by=entry.declared_by OR NEW.reviewed_at < entry.created_at THEN
        RAISE EXCEPTION USING ERRCODE='P0094', MESSAGE='Collection requires an independent active supervisor';
      END IF;
      IF EXISTS(SELECT 1 FROM customer_collection_reviews WHERE collection_id=NEW.collection_id) THEN
        RAISE EXCEPTION USING ERRCODE='P0094', MESSAGE='Collection decision already preserved';
      END IF;
      IF NEW.decision='VERIFICADO' AND purchase.status::text IN ('CANCELADO','FALLIDO') AND NOT NEW.acknowledge_refund_due THEN
        RAISE EXCEPTION USING ERRCODE='P0094', MESSAGE='Cancelled collection verification requires refund acknowledgement';
      END IF;
      RETURN NEW;
    END; $$"""
    )
    op.execute(
        """CREATE FUNCTION guard_order_collection_state() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE entries bigint; reviews bigint; locked boolean;
    BEGIN
      SELECT count(*),count(r.id),coalesce(bool_or(r.decision IS DISTINCT FROM 'RECHAZADO'),false)
        INTO entries,reviews,locked FROM customer_collections c LEFT JOIN customer_collection_reviews r ON r.collection_id=c.id
        WHERE c.order_id=NEW.id;
      IF NEW.collection_revision IS DISTINCT FROM (CASE WHEN entries=0 THEN NULL ELSE entries+reviews END)
        OR NEW.collection_locked IS DISTINCT FROM (CASE WHEN entries=0 THEN NULL ELSE locked END) THEN
        RAISE EXCEPTION USING ERRCODE='P0094', MESSAGE='Order collection state must match its immutable book';
      END IF;
      IF TG_OP='UPDATE' AND locked AND ROW(NEW.currency_code,NEW.pricing_version,NEW.pricing_revision,NEW.subtotal_exact,NEW.delivery_fee_exact,NEW.total_exact,NEW.items_exact::jsonb)
        IS DISTINCT FROM ROW(OLD.currency_code,OLD.pricing_version,OLD.pricing_revision,OLD.subtotal_exact,OLD.delivery_fee_exact,OLD.total_exact,OLD.items_exact::jsonb) THEN
        RAISE EXCEPTION USING ERRCODE='P0094', MESSAGE='Collected order price is locked';
      END IF;
      RETURN NEW;
    END; $$"""
    )
    op.execute(
        """CREATE FUNCTION refresh_order_collection_state() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE purchase_id uuid;
    BEGIN
      IF TG_TABLE_NAME='customer_collections' THEN purchase_id:=NEW.order_id;
      ELSE SELECT order_id INTO purchase_id FROM customer_collections WHERE id=NEW.collection_id; END IF;
      UPDATE orders SET collection_revision=s.revision,collection_locked=s.locked FROM
        (SELECT (count(*)+count(r.id))::integer AS revision,bool_or(r.decision IS DISTINCT FROM 'RECHAZADO') AS locked
         FROM customer_collections c LEFT JOIN customer_collection_reviews r ON r.collection_id=c.id
         WHERE c.order_id=purchase_id) s WHERE orders.id=purchase_id;
      RETURN NEW;
    END; $$"""
    )
    op.execute(
        "CREATE TRIGGER guard_order_collection_state BEFORE INSERT OR UPDATE ON orders FOR EACH ROW EXECUTE FUNCTION guard_order_collection_state()"
    )
    for table, validator in (
        ("customer_collections", "validate_customer_collection"),
        ("customer_collection_reviews", "validate_customer_collection_review"),
    ):
        op.execute(
            f"CREATE TRIGGER validate_{table} BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION {validator}()"
        )
        op.execute(
            f"CREATE TRIGGER refresh_{table} AFTER INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION refresh_order_collection_state()"
        )
        op.execute(
            f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION currency_history_immutable()"
        )
        op.execute(
            f"CREATE TRIGGER immutable_truncate_{table} BEFORE TRUNCATE ON {table} EXECUTE FUNCTION currency_history_immutable()"
        )


def downgrade():
    op.execute(
        "LOCK TABLE orders,customer_collections,customer_collection_reviews IN ACCESS EXCLUSIVE MODE NOWAIT"
    )
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM customer_collections) OR EXISTS(SELECT 1 FROM customer_collection_reviews)"
            )
        )
        .scalar()
    ):
        raise RuntimeError(
            "Downgrade refused: preserve customer collection declarations and reviews first"
        )
    op.execute("DROP TRIGGER guard_order_collection_state ON orders")
    op.drop_table("customer_collection_reviews")
    op.drop_table("customer_collections")
    for name in (
        "guard_order_collection_state",
        "refresh_order_collection_state",
        "validate_customer_collection_review",
        "validate_customer_collection",
    ):
        op.execute(f"DROP FUNCTION {name}()")
    op.drop_column("orders", "collection_locked")
    op.drop_column("orders", "collection_revision")
