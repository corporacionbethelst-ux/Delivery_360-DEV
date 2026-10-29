"""Modelos fiscales Fase 10 — Facturación electrónica, split payments y reconciliación.

Diseño:
- Valores monetarios SIEMPRE en centavos (BigInteger) para precisión contable.
- Enums de estado en ESPAÑOL puro (regla heredada Fase 7), con valores explícitos.
- NO se tocan enums legacy (TransactionType/PaymentStatus/PayoutStatus).
- Trazabilidad: cada factura guarda snapshot JSON del cálculo y respuesta del proveedor.
"""

import uuid
from datetime import date, time, datetime, timezone
from decimal import Decimal
from sqlalchemy.orm import Mapped, mapped_column

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    Index,
    CheckConstraint,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    Enum as SQLEnum,
    ForeignKey,
    false,
)
from sqlalchemy.dialects.postgresql import UUID, ENUM as PGEnum
import enum


def _pg_enum(python_enum, name):
    """FIX CRÍTICO FASE 10 (3ra auditoría): SQLAlchemy 2.0.x adapta
    sa.Enum(..., create_type=False) a postgresql.ENUM vía dialect_impl() y
    PIERDE el flag create_type (queda True). Resultado: op.create_table /
    metadata.create_all re-emiten CREATE TYPE <name> sobre tipos que ya
    fueron creados por la migración con _create_enum_tolerant(), causando
    asyncpg DuplicateObjectError: type "countrytaxregime" already exists.

    Solución: construir SIEMPRE el tipo con postgresql.ENUM nativo del
    dialecto + create_type=False, que sí respeta el flag (verificado:
    dialect_impl(ENUM(create_type=False)) conserva create_type=False)."""
    return PGEnum(
        python_enum,
        values_callable=lambda e: [m.value for m in e],
        name=name,
        create_type=False,
    )


from app.core.database import Base


def utc_now_naive():
    """Hora UTC naive, patrón consistente con modelos Fase 7/8/9."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ──────────────────────────────────────────────────────────────
# ENUMS
# ──────────────────────────────────────────────────────────────
class CountryTaxRegime(str, enum.Enum):
    """Países soportados por el motor fiscal (valores = ISO-3166 alfa-2)."""

    COLOMBIA = "CO"
    MEXICO = "MX"
    CHILE = "CL"
    PERU = "PE"


class InvoiceType(str, enum.Enum):
    """Tipo de documento tributario. Valores en español (regla Fase 7)."""

    VENTA = "VENTA"
    COMPRA = "COMPRA"
    NOTA_CREDITO = "NOTA_CREDITO"
    NOTA_DEBITO = "NOTA_DEBITO"


class InvoiceStatus(str, enum.Enum):
    """Estado del ciclo de vida de la factura electrónica. Español puro."""

    PENDIENTE = "PENDIENTE"
    ENVIADA = "ENVIADA"
    ACEPTADA = "ACEPTADA"
    RECHAZADA = "RECHAZADA"
    CANCELADA = "CANCELADA"


class ReconciliationStatus(str, enum.Enum):
    """Estado del matching bancario. Español puro."""

    SIN_RELACIONAR = "SIN_RELACIONAR"
    RELACIONADO = "RELACIONADO"
    VARIANCIA = "VARIANCIA"
    RESUELTO_MANUAL = "RESUELTO_MANUAL"


# ──────────────────────────────────────────────────────────────
# TABLAS
# ──────────────────────────────────────────────────────────────
class ElectronicInvoice(Base):
    """Factura electrónica emitida (o intentada) contra una orden."""

    __tablename__ = "electronic_invoices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    invoice_type: Mapped[InvoiceType] = mapped_column(
        _pg_enum(InvoiceType, "invoicetype"),
        nullable=False,
        default=InvoiceType.VENTA,
    )

    resolution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "invoice_resolutions.id",
            ondelete="RESTRICT",
            name="fk_invoice_resolution_identity",
        ),
        nullable=True,
    )
    execution_mode: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="legacy_unverified",
        server_default="legacy_unverified",
    )

    # Numeración oficial (resolución autorizada)
    resolution_number: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    unique_identifier: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )  # CUFE / UUID CFDI

    # Fechas oficiales
    issue_date: Mapped[date] = mapped_column(
        Date, nullable=False, index=True, default=utc_now_naive
    )
    issue_time: Mapped[time] = mapped_column(
        Time, nullable=False, default=datetime.min.time
    )
    cancellation_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Datos tributarios
    provider_type: Mapped[CountryTaxRegime] = mapped_column(
        _pg_enum(CountryTaxRegime, "countrytaxregime"),
        nullable=False,
    )
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="COP")
    exchange_rate: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False, default=1
    )

    # Valores monetarios en CENTAVOS (enteros exactos)
    subtotal_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tax_total_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    retention_total_cents: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    discount_total_cents: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    grand_total_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Estado del proceso
    status: Mapped[InvoiceStatus] = mapped_column(
        _pg_enum(InvoiceStatus, "invoicestatus"),
        nullable=False,
        default=InvoiceStatus.PENDIENTE,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Contenido técnico
    signed_xml_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    qr_code_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Vinculaciones (notas crédito/débito referencian factura original)
    reference_invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("electronic_invoices.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Metadata extendida (snapshot inmutable del cálculo)
    customer_info_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    tax_breakdown_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False
    )

    __table_args__ = (
        Index("idx_invoice_resolution_date", "resolution_id", "issue_date"),
        CheckConstraint(
            "execution_mode IN ('legacy_unverified','sandbox','real')",
            name="ck_invoice_execution_mode",
        ),
        UniqueConstraint(
            "provider_type",
            "resolution_number",
            "sequence_number",
            name="uq_invoice_resolution_sequence",
        ),
    )


class InvoiceResolution(Base):
    """Rango de numeración autorizado por la autoridad fiscal (DIAN resolucion / SAT folios)."""

    __tablename__ = "invoice_resolutions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    prefix: Mapped[str] = mapped_column(String(10), nullable=False)
    start_range: Mapped[int] = mapped_column(Integer, nullable=False)
    end_range: Mapped[int] = mapped_column(Integer, nullable=False)
    current_counter: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_until: Mapped[date] = mapped_column(Date, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    is_sandbox: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    # Seguridad: SOLO rutas/identificadores, nunca material de clave en claro.
    private_key_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    certificate_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    country_code: Mapped[CountryTaxRegime] = mapped_column(
        _pg_enum(CountryTaxRegime, "countrytaxregime"),
        nullable=False,
        default=CountryTaxRegime.COLOMBIA,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "prefix", "start_range", "end_range", name="uq_resolution_prefix_range"
        ),
    )


class PaymentDistributionSnapshot(Base):
    """Split de ingresos por orden: plataforma / rider (+ restaurante futuro)."""

    __tablename__ = "payment_distribution_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    gross_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    platform_share_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    restaurant_share_cents: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    rider_share_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    applied_rule_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    tax_allocation_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    settled_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )

    __table_args__ = (UniqueConstraint("order_id", name="uq_distribution_order"),)


class FiscalConfiguration(Base):
    """Regla fiscal configurable por país (y opcionalmente por zona)."""

    __tablename__ = "fiscal_configurations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    country_code: Mapped[CountryTaxRegime] = mapped_column(
        _pg_enum(CountryTaxRegime, "countrytaxregime"),
        nullable=False,
    )
    zone_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zones.id", ondelete="CASCADE"), nullable=True
    )
    tax_code: Mapped[str] = mapped_column(String(20), nullable=False)
    tax_name: Mapped[str] = mapped_column(String(100), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)  # 0.1900 = 19%
    applicability_condition: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # 'always' | 'conditional' | expr simple
    taxable_base_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="gross"
    )
    included_in_price: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "country_code", "tax_code", "zone_id", name="uq_fiscal_country_tax_zone"
        ),
    )


class BankReconciliationRecord(Base):
    """Línea de extracto bancario relacionada con transacciones internas."""

    __tablename__ = "bank_reconciliation_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    statement_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    bank_reference: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )
    internal_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("financial_transactions.id", ondelete="SET NULL"),
        nullable=True,
    )
    statement_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    matched_amount_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    variance_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    match_confidence_score: Mapped[Decimal | None] = mapped_column(
        Numeric(3, 2), nullable=True
    )  # 0.00–1.00
    status: Mapped[ReconciliationStatus] = mapped_column(
        _pg_enum(ReconciliationStatus, "reconciliationstatus"),
        nullable=False,
        default=ReconciliationStatus.SIN_RELACIONAR,
        index=True,
    )
    resolved_manually: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )
