"""Append-only refund requests and manual reconciliation, without historical updates."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "20261114_customer_refunds"
down_revision = "20261114_customer_collections"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "customer_refunds",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("request_key", UUID(as_uuid=True), unique=True, nullable=False),
        sa.Column(
            "collection_id",
            UUID(as_uuid=True),
            sa.ForeignKey("customer_collections.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("return_amount", sa.Numeric(24, 2), nullable=False),
        sa.Column("return_currency", sa.String(3), nullable=False),
        sa.Column("prior_refunded_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("prior_refunded_paid", sa.Numeric(24, 2), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column(
            "requested_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.CheckConstraint(
            "prior_refunded_usd >= 0 AND prior_refunded_paid >= 0 AND amount_usd > 0 AND amount_usd <= 99999999.99 AND return_amount > 0 AND return_amount < 1000000000000000000000",
            name="ck_customer_refund_amounts",
        ),
        sa.CheckConstraint(
            "return_currency IN ('USD','VES') AND length(btrim(reason)) BETWEEN 10 AND 500 AND reason !~ '[[:cntrl:]]'",
            name="ck_customer_refund_reason",
        ),
    )
    op.create_index(
        "ix_customer_refunds_collection_created",
        "customer_refunds",
        ["collection_id", "created_at", "id"],
    )
    op.create_table(
        "customer_refund_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("request_key", UUID(as_uuid=True), unique=True, nullable=False),
        sa.Column(
            "refund_id",
            UUID(as_uuid=True),
            sa.ForeignKey("customer_refunds.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("note", sa.String(500), nullable=False),
        sa.Column("verified_evidence", sa.Boolean, nullable=False),
        sa.Column("confirmed_no_execution", sa.Boolean, nullable=False),
        sa.Column("confirmed_execution", sa.Boolean, nullable=False),
        sa.Column("method", sa.String(20)),
        sa.Column("source_key", sa.String(80)),
        sa.Column("reference_key", sa.String(120)),
        sa.Column("paid_amount", sa.Numeric(24, 2)),
        sa.Column("paid_currency", sa.String(3)),
        sa.Column("executed_on", sa.Date),
        sa.Column(
            "actor_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint(
            "refund_id", "revision", name="uq_customer_refund_event_revision"
        ),
        sa.CheckConstraint(
            "revision BETWEEN 1 AND 2147483647 AND length(btrim(note)) BETWEEN 10 AND 500 AND note !~ '[[:cntrl:]]'",
            name="ck_customer_refund_event_note",
        ),
    )
    op.create_index(
        "ix_customer_refund_event_reference",
        "customer_refund_events",
        ["source_key", "reference_key"],
        unique=True,
        postgresql_where=sa.text("kind='DECLARAR_EJECUCION'"),
    )
    op.execute(
        """CREATE FUNCTION customer_refund_status(identity uuid) RETURNS text LANGUAGE sql VOLATILE AS $$
      SELECT coalesce((SELECT CASE kind WHEN 'APROBAR' THEN 'APROBADA' WHEN 'RECHAZAR' THEN 'RECHAZADA'
        WHEN 'DECLARAR_EJECUCION' THEN 'EJECUCION_DECLARADA' WHEN 'VERIFICAR_DEVOLUCION' THEN 'DEVUELTA'
        WHEN 'OBSERVAR_EJECUCION' THEN 'OBSERVADA' WHEN 'CONFIRMAR_NO_EJECUTADA' THEN 'APROBADA'
        WHEN 'ANULAR_APROBACION' THEN 'RECHAZADA' END FROM customer_refund_events WHERE refund_id=identity ORDER BY revision DESC LIMIT 1),'SOLICITADA'); $$"""
    )
    op.execute(
        """CREATE FUNCTION validate_customer_refund() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE entry customer_collections%ROWTYPE; purchase orders%ROWTYPE; actor users%ROWTYPE;
      returned_usd numeric; returned_paid numeric; rate numeric; expected_paid numeric;
    BEGIN
      SELECT * INTO entry FROM customer_collections WHERE id=NEW.collection_id;
      IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='P0095', MESSAGE='Refund requires its original collection'; END IF;
      SELECT * INTO purchase FROM orders WHERE id=entry.order_id FOR UPDATE;
      SELECT * INTO actor FROM users WHERE id=NEW.requested_by FOR SHARE;
      IF NOT FOUND OR actor.is_active IS DISTINCT FROM true OR actor.role IS NULL OR actor.role::text NOT IN ('SUPERADMIN','GERENTE','OPERADOR')
        OR (actor.role::text='OPERADOR' AND entry.declared_by IS DISTINCT FROM NEW.requested_by)
        OR purchase.status IS NULL OR purchase.status::text NOT IN ('CANCELADO','FALLIDO')
        OR NOT EXISTS(SELECT 1 FROM customer_collection_reviews WHERE collection_id=entry.id AND decision='VERIFICADO') THEN
        RAISE EXCEPTION USING ERRCODE='P0095', MESSAGE='Refund requires a cancelled or failed verified collection and active authorized staff';
      END IF;
      IF EXISTS(SELECT 1 FROM customer_refunds WHERE collection_id=entry.id AND customer_refund_status(id) NOT IN ('RECHAZADA','DEVUELTA')) THEN
        RAISE EXCEPTION USING ERRCODE='P0095', MESSAGE='Resolve the active refund before allocating another';
      END IF;
      SELECT coalesce(sum(amount_usd),0),coalesce(sum(return_amount),0) INTO returned_usd,returned_paid
        FROM customer_refunds WHERE collection_id=entry.id AND customer_refund_status(id)='DEVUELTA';
      IF NEW.prior_refunded_usd IS DISTINCT FROM returned_usd OR NEW.prior_refunded_paid IS DISTINCT FROM returned_paid
        OR NEW.amount_usd > entry.amount_usd-returned_usd OR NEW.return_currency IS DISTINCT FROM entry.paid_currency THEN
        RAISE EXCEPTION USING ERRCODE='P0095', MESSAGE='Refund exceeds its original verified collection or changes its currency';
      END IF;
      IF entry.paid_currency='USD' THEN rate:=1;
      ELSE SELECT r.ves_per_usd INTO rate FROM order_currency_quotes q JOIN bcv_rates r ON r.id=q.rate_id WHERE q.id=entry.quote_id; END IF;
      expected_paid:=round((returned_usd+NEW.amount_usd)*rate,2)-returned_paid;
      IF expected_paid IS NULL OR expected_paid<=0 OR NEW.return_amount IS DISTINCT FROM expected_paid
        OR NEW.return_amount>entry.paid_amount-returned_paid THEN
        RAISE EXCEPTION USING ERRCODE='P0095', MESSAGE='Refund must preserve cumulative original conversion and paid cents';
      END IF;
      IF (NEW.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Caracas')::date IS DISTINCT FROM (clock_timestamp() AT TIME ZONE 'America/Caracas')::date THEN
        RAISE EXCEPTION USING ERRCODE='P0095', MESSAGE='Refund request requires its actual operating day';
      END IF;
      RETURN NEW;
    END; $$"""
    )
    op.execute(
        r"""CREATE FUNCTION validate_customer_refund_event() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE request customer_refunds%ROWTYPE; entry customer_collections%ROWTYPE; purchase orders%ROWTYPE;
      actor users%ROWTYPE; latest customer_refund_events%ROWTYPE; execution customer_refund_events%ROWTYPE;
      state text; allowed boolean:=false; executing boolean; no_execution boolean; evidence boolean;
    BEGIN
      SELECT * INTO request FROM customer_refunds WHERE id=NEW.refund_id;
      IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='P0095', MESSAGE='Refund request not found'; END IF;
      SELECT * INTO entry FROM customer_collections WHERE id=request.collection_id;
      SELECT * INTO purchase FROM orders WHERE id=entry.order_id FOR UPDATE;
      executing:=NEW.kind='DECLARAR_EJECUCION';
      IF executing THEN
        PERFORM pg_advisory_xact_lock(hashtext('refund:reference:'||NEW.source_key||chr(31)||NEW.reference_key)::bigint);
      END IF;
      SELECT * INTO actor FROM users WHERE id=NEW.actor_id FOR SHARE;
      IF NOT FOUND OR actor.is_active IS DISTINCT FROM true OR actor.role IS NULL OR actor.role::text NOT IN ('SUPERADMIN','GERENTE') THEN
        RAISE EXCEPTION USING ERRCODE='P0095', MESSAGE='Refund event requires an active supervisor';
      END IF;
      SELECT * INTO latest FROM customer_refund_events WHERE refund_id=request.id ORDER BY revision DESC LIMIT 1;
      state:=customer_refund_status(request.id);
      IF NEW.revision IS DISTINCT FROM coalesce(latest.revision,0)+1 OR NEW.created_at<coalesce(latest.created_at,request.created_at) THEN
        RAISE EXCEPTION USING ERRCODE='P0095', MESSAGE='Refund event revision or timestamp is stale';
      END IF;
      allowed:=(state='SOLICITADA' AND NEW.kind IN ('APROBAR','RECHAZAR'))
        OR (state='APROBADA' AND NEW.kind IN ('DECLARAR_EJECUCION','ANULAR_APROBACION'))
        OR (state='EJECUCION_DECLARADA' AND NEW.kind IN ('VERIFICAR_DEVOLUCION','OBSERVAR_EJECUCION'))
        OR (state='OBSERVADA' AND NEW.kind IN ('VERIFICAR_DEVOLUCION','CONFIRMAR_NO_EJECUTADA'));
      IF NOT allowed THEN RAISE EXCEPTION USING ERRCODE='P0095', MESSAGE='Refund event does not follow the preserved state'; END IF;
      IF NEW.kind IN ('APROBAR','RECHAZAR','ANULAR_APROBACION') AND NEW.actor_id=request.requested_by THEN
        RAISE EXCEPTION USING ERRCODE='P0095', MESSAGE='Another supervisor must authorize or release the request';
      END IF;
      SELECT * INTO execution FROM customer_refund_events WHERE refund_id=request.id AND kind='DECLARAR_EJECUCION' ORDER BY revision DESC LIMIT 1;
      IF NEW.kind IN ('VERIFICAR_DEVOLUCION','OBSERVAR_EJECUCION','CONFIRMAR_NO_EJECUTADA') AND NEW.actor_id=execution.actor_id THEN
        RAISE EXCEPTION USING ERRCODE='P0095', MESSAGE='Another supervisor must reconcile the declared execution';
      END IF;
      no_execution:=NEW.kind IN ('CONFIRMAR_NO_EJECUTADA','ANULAR_APROBACION');
      evidence:=NEW.kind IN ('VERIFICAR_DEVOLUCION','CONFIRMAR_NO_EJECUTADA','ANULAR_APROBACION');
      IF NEW.confirmed_no_execution IS DISTINCT FROM no_execution OR NEW.verified_evidence IS DISTINCT FROM evidence OR NEW.confirmed_execution IS DISTINCT FROM executing THEN
        RAISE EXCEPTION USING ERRCODE='P0095', MESSAGE='Refund evidence and explicit confirmations must match the action';
      END IF;
      IF NEW.kind IN ('APROBAR','DECLARAR_EJECUCION') AND (purchase.status IS NULL OR purchase.status::text NOT IN ('CANCELADO','FALLIDO')) THEN
        RAISE EXCEPTION USING ERRCODE='P0095', MESSAGE='Approved refund requires a cancelled or failed order';
      END IF;
      IF executing THEN
        IF NEW.method IS NULL OR NEW.method NOT IN ('EFECTIVO','TRANSFERENCIA','PAGO_MOVIL')
          OR NEW.source_key IS NULL OR NEW.reference_key IS NULL
          OR NEW.source_key !~ '^[A-Z0-9][A-Z0-9 ._/#:\-]*$' OR NEW.reference_key !~ '^[A-Z0-9][A-Z0-9 ._/#:\-]*$'
          OR NEW.source_key IS DISTINCT FROM regexp_replace(btrim(NEW.source_key),' +',' ','g')
          OR NEW.reference_key IS DISTINCT FROM regexp_replace(btrim(NEW.reference_key),' +',' ','g')
          OR NEW.paid_amount IS DISTINCT FROM request.return_amount OR NEW.paid_currency IS DISTINCT FROM request.return_currency
          OR (NEW.method='PAGO_MOVIL' AND NEW.paid_currency IS DISTINCT FROM 'VES')
          OR NEW.executed_on IS DISTINCT FROM (clock_timestamp() AT TIME ZONE 'America/Caracas')::date
          OR (NEW.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Caracas')::date IS DISTINCT FROM NEW.executed_on THEN
          RAISE EXCEPTION USING ERRCODE='P0095', MESSAGE='Declared refund must preserve the approved amount, currency, real reference and operating day';
        END IF;
        IF EXISTS(SELECT 1 FROM customer_refund_events WHERE kind='DECLARAR_EJECUCION' AND source_key=NEW.source_key AND reference_key=NEW.reference_key) THEN
          RAISE EXCEPTION USING ERRCODE='P0095', MESSAGE='Refund execution reference already used';
        END IF;
      ELSIF NEW.method IS NOT NULL OR NEW.source_key IS NOT NULL OR NEW.reference_key IS NOT NULL OR NEW.paid_amount IS NOT NULL OR NEW.paid_currency IS NOT NULL OR NEW.executed_on IS NOT NULL THEN
        RAISE EXCEPTION USING ERRCODE='P0095', MESSAGE='Only an execution declaration may contain payout data';
      END IF;
      RETURN NEW;
    END; $$"""
    )
    op.execute(
        """CREATE FUNCTION guard_customer_refund_order_status() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.status IS NULL OR NEW.status::text NOT IN ('CANCELADO','FALLIDO') THEN
        IF EXISTS(SELECT 1 FROM customer_refunds r JOIN customer_collections c ON c.id=r.collection_id
          WHERE c.order_id=NEW.id AND customer_refund_status(r.id)<>'RECHAZADA') THEN
          RAISE EXCEPTION USING ERRCODE='P0095', MESSAGE='An order with active or verified refunds cannot reopen';
        END IF;
      END IF;
      RETURN NEW;
    END; $$"""
    )
    op.execute(
        "CREATE TRIGGER guard_customer_refund_order_status BEFORE UPDATE OF status ON orders FOR EACH ROW EXECUTE FUNCTION guard_customer_refund_order_status()"
    )
    for table, validator in [
        ("customer_refunds", "validate_customer_refund"),
        ("customer_refund_events", "validate_customer_refund_event"),
    ]:
        op.execute(
            f"CREATE TRIGGER validate_{table} BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION {validator}()"
        )
        op.execute(
            f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION currency_history_immutable()"
        )
        op.execute(
            f"CREATE TRIGGER immutable_truncate_{table} BEFORE TRUNCATE ON {table} EXECUTE FUNCTION currency_history_immutable()"
        )


def downgrade():
    op.execute(
        "LOCK TABLE orders,customer_refunds,customer_refund_events IN ACCESS EXCLUSIVE MODE NOWAIT"
    )
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM customer_refunds) OR EXISTS(SELECT 1 FROM customer_refund_events)"
            )
        )
        .scalar()
    ):
        raise RuntimeError(
            "Downgrade refused: preserve customer refunds and reconciliation events first"
        )
    op.execute("DROP TRIGGER guard_customer_refund_order_status ON orders")
    op.drop_table("customer_refund_events")
    op.drop_table("customer_refunds")
    for function, signature in [
        ("guard_customer_refund_order_status", ""),
        ("validate_customer_refund_event", ""),
        ("validate_customer_refund", ""),
        ("customer_refund_status", "uuid"),
    ]:
        op.execute(f"DROP FUNCTION {function}({signature})")
