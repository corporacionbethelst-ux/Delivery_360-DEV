"""Modelos fiscales Fase 10 — Facturación electrónica, split payments y reconciliación.

Diseño:
- Valores monetarios SIEMPRE en centavos (BigInteger) para precisión contable.
- Enums de estado en ESPAÑOL puro (regla heredada Fase 7), con valores explícitos.
- NO se tocan enums legacy (TransactionType/PaymentStatus/PayoutStatus).
- Trazabilidad: cada factura guarda snapshot JSON del cálculo y respuesta del proveedor.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    Enum as SQLEnum,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import UUID
import enum

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

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    invoice_type: Any = Column(
        SQLEnum(InvoiceType, values_callable=lambda e: [m.value for m in e], create_type=False),
        nullable=False, default=InvoiceType.VENTA,
    )

    # Numeración oficial (resolución autorizada)
    resolution_number = Column(Integer, nullable=False)
    sequence_number = Column(Integer, nullable=False)
    unique_identifier = Column(String(100), nullable=True, index=True)  # CUFE / UUID CFDI

    # Fechas oficiales
    issue_date = Column(Date, nullable=False, index=True, default=utc_now_naive)
    issue_time = Column(Time, nullable=False, default=datetime.min.time)
    cancellation_date = Column(DateTime, nullable=True)

    # Datos tributarios
    provider_type: Any = Column(
        SQLEnum(CountryTaxRegime, values_callable=lambda e: [m.value for m in e], create_type=False),
        nullable=False,
    )
    currency_code = Column(String(3), nullable=False, default="COP")
    exchange_rate = Column(Numeric(10, 4), nullable=False, default=1)

    # Valores monetarios en CENTAVOS (enteros exactos)
    subtotal_cents = Column(BigInteger, nullable=False)
    tax_total_cents = Column(BigInteger, nullable=False, default=0)
    retention_total_cents = Column(BigInteger, nullable=False, default=0)
    discount_total_cents = Column(BigInteger, nullable=False, default=0)
    grand_total_cents = Column(BigInteger, nullable=False)

    # Estado del proceso
    status: Any = Column(
        SQLEnum(InvoiceStatus, values_callable=lambda e: [m.value for m in e], create_type=False),
        nullable=False, default=InvoiceStatus.PENDIENTE, index=True,
    )
    error_message = Column(Text, nullable=True)

    # Contenido técnico
    signed_xml_content = Column(Text, nullable=True)
    pdf_url = Column(Text, nullable=True)
    qr_code_url = Column(Text, nullable=True)

    # Vinculaciones (notas crédito/débito referencian factura original)
    reference_invoice_id = Column(
        UUID(as_uuid=True), ForeignKey("electronic_invoices.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Metadata extendida (snapshot inmutable del cálculo)
    customer_info_json = Column(Text, nullable=False, default="{}")
    tax_breakdown_json = Column(Text, nullable=True)

    created_at = Column(DateTime, default=utc_now_naive, nullable=False)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False)

    __table_args__ = (
        UniqueConstraint("provider_type", "resolution_number", "sequence_number",
                         name="uq_invoice_resolution_sequence"),
    )


class InvoiceResolution(Base):
    """Rango de numeración autorizado por la autoridad fiscal (DIAN resolucion / SAT folios)."""
    __tablename__ = "invoice_resolutions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prefix = Column(String(10), nullable=False)
    start_range = Column(Integer, nullable=False)
    end_range = Column(Integer, nullable=False)
    current_counter = Column(Integer, nullable=False, default=0)
    valid_from = Column(Date, nullable=False)
    valid_until = Column(Date, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)

    # Seguridad: SOLO rutas/identificadores, nunca material de clave en claro.
    private_key_path = Column(Text, nullable=True)
    certificate_path = Column(Text, nullable=True)
    password_encrypted = Column(Text, nullable=True)

    country_code: Any = Column(
        SQLEnum(CountryTaxRegime, values_callable=lambda e: [m.value for m in e], create_type=False),
        nullable=False, default=CountryTaxRegime.COLOMBIA,
    )

    created_at = Column(DateTime, default=utc_now_naive, nullable=False)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False)

    __table_args__ = (
        UniqueConstraint("prefix", "start_range", "end_range",
                         name="uq_resolution_prefix_range"),
    )


class PaymentDistributionSnapshot(Base):
    """Split de ingresos por orden: plataforma / rider (+ restaurante futuro)."""
    __tablename__ = "payment_distribution_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    gross_amount_cents = Column(BigInteger, nullable=False)
    platform_share_cents = Column(BigInteger, nullable=False)
    restaurant_share_cents = Column(BigInteger, nullable=False, default=0)
    rider_share_cents = Column(BigInteger, nullable=False)
    applied_rule_json = Column(Text, nullable=False, default="{}")
    tax_allocation_json = Column(Text, nullable=True)
    settled_at = Column(DateTime, default=utc_now_naive, nullable=False)

    __table_args__ = (
        UniqueConstraint("order_id", name="uq_distribution_order"),
    )


class FiscalConfiguration(Base):
    """Regla fiscal configurable por país (y opcionalmente por zona)."""
    __tablename__ = "fiscal_configurations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    country_code: Any = Column(
        SQLEnum(CountryTaxRegime, values_callable=lambda e: [m.value for m in e], create_type=False),
        nullable=False,
    )
    zone_id = Column(UUID(as_uuid=True), ForeignKey("zones.id", ondelete="CASCADE"), nullable=True)
    tax_code = Column(String(20), nullable=False)
    tax_name = Column(String(100), nullable=False)
    rate = Column(Numeric(5, 4), nullable=False)  # 0.1900 = 19%
    applicability_condition = Column(Text, nullable=True)  # 'always' | 'conditional' | expr simple
    taxable_base_type = Column(String(20), nullable=False, default="gross")
    included_in_price = Column(Boolean, nullable=False, default=False)
    priority = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, default=utc_now_naive, nullable=False)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False)

    __table_args__ = (
        UniqueConstraint("country_code", "tax_code", "zone_id",
                         name="uq_fiscal_country_tax_zone"),
    )


class BankReconciliationRecord(Base):
    """Línea de extracto bancario relacionada con transacciones internas."""
    __tablename__ = "bank_reconciliation_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    statement_date = Column(Date, nullable=False, index=True)
    bank_reference = Column(String(100), nullable=True, index=True)
    internal_transaction_id = Column(
        UUID(as_uuid=True), ForeignKey("financial_transactions.id", ondelete="SET NULL"),
        nullable=True,
    )
    statement_amount_cents = Column(BigInteger, nullable=False)
    matched_amount_cents = Column(BigInteger, nullable=True)
    variance_cents = Column(BigInteger, nullable=False, default=0)
    match_confidence_score = Column(Numeric(3, 2), nullable=True)  # 0.00–1.00
    status: Any = Column(
        SQLEnum(ReconciliationStatus, values_callable=lambda e: [m.value for m in e], create_type=False),
        nullable=False, default=ReconciliationStatus.SIN_RELACIONAR, index=True,
    )
    resolved_manually = Column(Boolean, nullable=False, default=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now_naive, nullable=False)
