"""
Fase 10 - Facturación Electrónica & Motor Fiscal: migración de esquemas.

Crea:
    - electronic_invoices            (facturas NC/ND con trazabilidad completa)
    - invoice_resolutions            (rangos autorizados de numeración)
    - payment_distribution_snapshots (split plataforma/rider por orden, snapshot auditable)
    - fiscal_configurations          (reglas IVA/retención/timbre por país y zona opcional)
    - bank_reconciliation_records    (matching extracto bancario vs transacciones internas)

Tipos ENUM PG nuevos, tolerantes a fallos (patrón savepoint Fase 8/9):
    - countrytaxregime      (CO, MX, CL, PE)
    - invoicetype           (VENTA, COMPRA, NOTA_CREDITO, NOTA_DEBITO)   -- español puro
    - invoicestatus         (PENDIENTE, ENVIADA, ACEPTADA, RECHAZADA, CANCELADA)
    - reconciliationstatus  (SIN_RELACIONAR, RELACIONADO, VARIANCIA, RESUELTO_MANUAL)

DECISIONES DOCUMENTADAS:
    - NO se modifican enums legacy (TransactionType/PaymentStatus/PayoutStatus).
    - Montos SIEMPRE en centavos (BIGINT). Restaurantes quedan fuera del split
      real (no existe modelo Vendor); restaurant_share_cents=0 reservado.
    - financial_transactions.wallet_id es NOT NULL; el split de plataforma se
      audita vía payment_distribution_snapshots + AJUSTE_MANUAL cuando aplique,
      sin tocar la tabla legacy.

Seed idempotente (INSERT ... ON CONFLICT DO NOTHING):
    - 1 resolución demo CO + 1 demo MX
    - Reglas fiscales CO (IVA 19%, RET_IVA 1.5%, Timbre Bogotá 1.5% condicional)
      y MX (IVA 16% incluido en precio).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '20260930_fase10'
down_revision: Union[str, None] = '20260915_fase9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_enum_tolerant(name: str, values: list) -> None:
    """CREATE TYPE IF NOT EXISTS via savepoint (patron tolerante Fase 8/9).

    FIX FASE 10: antes el `except Exception` capturaba el error de asyncpg en
    nivel DRIVER y dejaba la transaccion PG abortada; cualquier statement
    posterior fallaba con InFailedSQLTransaction o DuplicateObjectError.
    Ahora se consulta pg_type PRIMERO (no lanza, no aborta) y solo se ejecuta
    CREATE TYPE si el tipo realmente no existe. El savepoint se conserva como
    red de seguridad para reintentos parciales.
    """
    bind = op.get_bind()
    exists = bind.execute(
        sa.text("SELECT 1 FROM pg_type WHERE typname = :n"), {"n": name}
    ).scalar()
    if exists:
        return
    bind.execute(sa.text(f"SAVEPOINT sp_enum_{name}"))
    try:
        value_list = ", ".join(f"'{v}'" for v in values)
        bind.execute(sa.text(f"CREATE TYPE {name} AS ENUM ({value_list})"))
        bind.execute(sa.text(f"RELEASE SAVEPOINT sp_enum_{name}"))
    except Exception:
        # Solo llega aqui si otro usuario creo el tipo entre la consulta y el
        # CREATE (condicion de carrera): rollback al savepoint y continuar.
        bind.execute(sa.text(f"ROLLBACK TO SAVEPOINT sp_enum_{name}"))
        bind.execute(sa.text(f"RELEASE SAVEPOINT sp_enum_{name}"))


# Tipos ENUM nativos de Postgres (creados tolerante a fallos mas abajo;
# aqui solo se referencian como tipo de columna).
# FIX CRITICO FASE 10: usar postgresql.ENUM(...) EXPLICITO con
# create_type=False. Motivo: sa.Enum(..., create_type=False) pierde el flag
# al adaptarse internamente al dialecto postgresql (la clase adaptada queda
# sin el atributo), por lo que op.create_table re-emite CREATE TYPE y revienta
# con DuplicateObjectError ("type countrytaxregime already exists") incluso en
# DB limpia tras el pre-check. postgresql.ENUM es la clase NATIVA del dialecto
# (no se adapta) y respeta create_type=False de forma garantizada.
CTRT = postgresql.ENUM("CO", "MX", "CL", "PE", name="countrytaxregime", create_type=False)
IVT = postgresql.ENUM("VENTA", "COMPRA", "NOTA_CREDITO", "NOTA_DEBITO", name="invoicetype", create_type=False)
IVS = postgresql.ENUM("PENDIENTE", "ENVIADA", "ACEPTADA", "RECHAZADA", "CANCELADA", name="invoicestatus", create_type=False)
RCS = postgresql.ENUM("SIN_RELACIONAR", "RELACIONADO", "VARIANCIA", "RESUELTO_MANUAL", name="reconciliationstatus", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))

    # ------------------------------------------------------------------
    # 1) Tipos ENUM
    # ------------------------------------------------------------------
    _create_enum_tolerant("countrytaxregime", ["CO", "MX", "CL", "PE"])
    _create_enum_tolerant("invoicetype", ["VENTA", "COMPRA", "NOTA_CREDITO", "NOTA_DEBITO"])
    _create_enum_tolerant("invoicestatus", ["PENDIENTE", "ENVIADA", "ACEPTADA", "RECHAZADA", "CANCELADA"])
    _create_enum_tolerant("reconciliationstatus", ["SIN_RELACIONAR", "RELACIONADO", "VARIANCIA", "RESUELTO_MANUAL"])

    # ------------------------------------------------------------------
    # 2) invoice_resolutions
    # ------------------------------------------------------------------
    op.create_table(
        "invoice_resolutions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("prefix", sa.String(10), nullable=False),
        sa.Column("start_range", sa.Integer, nullable=False),
        sa.Column("end_range", sa.Integer, nullable=False),
        sa.Column("current_counter", sa.Integer, nullable=False, server_default="0"),
        sa.Column("valid_from", sa.Date, nullable=False),
        sa.Column("valid_until", sa.Date, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("private_key_path", sa.Text, nullable=True),
        sa.Column("certificate_path", sa.Text, nullable=True),
        sa.Column("password_encrypted", sa.Text, nullable=True),
        sa.Column("country_code", CTRT, nullable=False, server_default="CO"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("prefix", "start_range", "end_range", name="uq_resolution_prefix_range"),
    )

    # ------------------------------------------------------------------
    # 3) electronic_invoices
    # ------------------------------------------------------------------
    op.create_table(
        "electronic_invoices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("invoice_type", IVT, nullable=False, server_default="VENTA"),
        sa.Column("resolution_number", sa.Integer, nullable=False),
        sa.Column("sequence_number", sa.Integer, nullable=False),
        sa.Column("unique_identifier", sa.String(100), nullable=True),
        sa.Column("issue_date", sa.Date, nullable=False),
        sa.Column("issue_time", sa.Time, nullable=False),
        sa.Column("cancellation_date", sa.DateTime, nullable=True),
        sa.Column("provider_type", CTRT, nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=False, server_default="COP"),
        sa.Column("exchange_rate", sa.Numeric(10, 4), nullable=False, server_default="1"),
        sa.Column("subtotal_cents", sa.BigInteger, nullable=False),
        sa.Column("tax_total_cents", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("retention_total_cents", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("discount_total_cents", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("grand_total_cents", sa.BigInteger, nullable=False),
        sa.Column("status", IVS, nullable=False, server_default="PENDIENTE"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("signed_xml_content", sa.Text, nullable=True),
        sa.Column("pdf_url", sa.Text, nullable=True),
        sa.Column("qr_code_url", sa.Text, nullable=True),
        sa.Column("reference_invoice_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("electronic_invoices.id", ondelete="SET NULL"), nullable=True),
        sa.Column("customer_info_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("tax_breakdown_json", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("provider_type", "resolution_number", "sequence_number",
                            name="uq_invoice_resolution_sequence"),
    )
    op.create_index("idx_einvoices_order", "electronic_invoices", ["order_id"])
    op.create_index("idx_einvoices_status", "electronic_invoices", ["status"])
    op.create_index("idx_einvoices_unique_id", "electronic_invoices", ["unique_identifier"])
    op.create_index("idx_einvoices_issue_date", "electronic_invoices",
                    [sa.text("issue_date DESC")])

    # ------------------------------------------------------------------
    # 4) payment_distribution_snapshots
    # ------------------------------------------------------------------
    op.create_table(
        "payment_distribution_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("gross_amount_cents", sa.BigInteger, nullable=False),
        sa.Column("platform_share_cents", sa.BigInteger, nullable=False),
        sa.Column("restaurant_share_cents", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("rider_share_cents", sa.BigInteger, nullable=False),
        sa.Column("applied_rule_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("tax_allocation_json", sa.Text, nullable=True),
        sa.Column("settled_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("order_id", name="uq_distribution_order"),
    )
    op.create_index("idx_distribution_order", "payment_distribution_snapshots", ["order_id"])

    # ------------------------------------------------------------------
    # 5) fiscal_configurations
    # ------------------------------------------------------------------
    op.create_table(
        "fiscal_configurations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("country_code", CTRT, nullable=False),
        sa.Column("zone_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("zones.id", ondelete="CASCADE"), nullable=True),
        sa.Column("tax_code", sa.String(20), nullable=False),
        sa.Column("tax_name", sa.String(100), nullable=False),
        sa.Column("rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("applicability_condition", sa.Text, nullable=True),
        sa.Column("taxable_base_type", sa.String(20), nullable=False, server_default="gross"),
        sa.Column("included_in_price", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("country_code", "tax_code", "zone_id",
                            name="uq_fiscal_country_tax_zone"),
    )

    # ------------------------------------------------------------------
    # 6) bank_reconciliation_records
    # ------------------------------------------------------------------
    op.create_table(
        "bank_reconciliation_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("statement_date", sa.Date, nullable=False),
        sa.Column("bank_reference", sa.String(100), nullable=True),
        sa.Column("internal_transaction_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("financial_transactions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("statement_amount_cents", sa.BigInteger, nullable=False),
        sa.Column("matched_amount_cents", sa.BigInteger, nullable=True),
        sa.Column("variance_cents", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("match_confidence_score", sa.Numeric(3, 2), nullable=True),
        sa.Column("status", RCS, nullable=False,
                  server_default="SIN_RELACIONAR"),
        sa.Column("resolved_manually", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_reconciliation_date", "bank_reconciliation_records",
                    [sa.text("statement_date DESC")])
    op.create_index("idx_reconciliation_bank_ref", "bank_reconciliation_records", ["bank_reference"])
    op.create_index("idx_reconciliation_status", "bank_reconciliation_records", ["status"])

    # ------------------------------------------------------------------
    # 7) Seeds idempotentes (ON CONFLICT DO NOTHING)
    # ------------------------------------------------------------------
    bind.execute(sa.text(
        "INSERT INTO invoice_resolutions "
        "(id, prefix, start_range, end_range, current_counter, valid_from, valid_until, is_active, country_code) "
        "VALUES (gen_random_uuid(), 'FCT-', 1, 100000, 0, '2026-01-01', '2027-12-31', TRUE, 'CO') "
        "ON CONFLICT (prefix, start_range, end_range) DO NOTHING"
    ))
    bind.execute(sa.text(
        "INSERT INTO invoice_resolutions "
        "(id, prefix, start_range, end_range, current_counter, valid_from, valid_until, is_active, country_code) "
        "VALUES (gen_random_uuid(), 'MXA', 1, 100000, 0, '2026-01-01', '2027-12-31', TRUE, 'MX') "
        "ON CONFLICT (prefix, start_range, end_range) DO NOTHING"
    ))

    fiscal_seed = [
        # (country, tax_code, name, rate, applicability, base, included, priority)
        ("CO", "IVA", "Impuesto sobre Ventas", "0.1900", "always", "gross", False, 0),
        ("CO", "RET_IVA", "Retención en la Fuente IVA", "0.0150", "conditional", "gross", False, 1),
        ("CO", "Timbre_Bogota", "Timbre Departamental Bogotá", "0.0150", "conditional", "gross", False, 2),
        ("MX", "IVA", "Impuesto al Valor Agregado", "0.1600", "always", "gross", True, 0),
        ("CL", "IVA", "Impuesto al Valor Agregado", "0.1900", "always", "gross", False, 0),
        ("PE", "IGV", "Impuesto General a las Ventas", "0.1800", "always", "gross", False, 0),
    ]
    for country, code, name, rate, applicability, base, included, prio in fiscal_seed:
        bind.execute(sa.text(
            "INSERT INTO fiscal_configurations "
            "(id, country_code, zone_id, tax_code, tax_name, rate, applicability_condition, "
            " taxable_base_type, included_in_price, priority, is_active) "
            "VALUES (gen_random_uuid(), CAST(:country AS countrytaxregime), NULL, :code, :name, "
            " CAST(:rate AS numeric), :applicability, :base, CAST(:included AS boolean), :prio, TRUE) "
            "ON CONFLICT (country_code, tax_code, zone_id) DO NOTHING"
        ), {"country": country, "code": code, "name": name, "rate": rate,
            "applicability": applicability, "base": base, "included": included, "prio": prio})


def downgrade() -> None:
    op.drop_index("idx_reconciliation_status", table_name="bank_reconciliation_records")
    op.drop_index("idx_reconciliation_bank_ref", table_name="bank_reconciliation_records")
    op.drop_index("idx_reconciliation_date", table_name="bank_reconciliation_records")
    op.drop_table("bank_reconciliation_records")
    op.drop_table("fiscal_configurations")
    op.drop_index("idx_distribution_order", table_name="payment_distribution_snapshots")
    op.drop_table("payment_distribution_snapshots")
    op.drop_index("idx_einvoices_issue_date", table_name="electronic_invoices")
    op.drop_index("idx_einvoices_unique_id", table_name="electronic_invoices")
    op.drop_index("idx_einvoices_status", table_name="electronic_invoices")
    op.drop_index("idx_einvoices_order", table_name="electronic_invoices")
    op.drop_table("electronic_invoices")
    op.drop_table("invoice_resolutions")
    op.execute("DROP TYPE IF EXISTS reconciliationstatus")
    op.execute("DROP TYPE IF EXISTS invoicestatus")
    op.execute("DROP TYPE IF EXISTS invoicetype")
    op.execute("DROP TYPE IF EXISTS countrytaxregime")
