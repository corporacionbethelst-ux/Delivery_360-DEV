"""Financial models for rider payments and transactions - Fase 7 Enterprise."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from sqlalchemy import Column, DateTime, Enum as SQLEnum, ForeignKey, Numeric, String, Text, Integer, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import enum
from app.core.database import Base

def utc_now_naive():
    """Devuelve la hora actual en UTC sin zona horaria (naive) para compatibilidad con PostgreSQL."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TransactionType(str, enum.Enum):
    """Transaction types - Ampliado para Fase 7 (Pagos Reales)."""
    # Tipos Críticos Fase 3-6
    PAGO_ENTREGA = "PAGO_ENTREGA"
    PAGO_INTENTO_FALLIDO = "PAGO_INTENTO_FALLIDO"
    BONO_RENDIMIENTO = "BONO_RENDIMIENTO"
    PENALIZACION = "PENALIZACION"
    AJUSTE_MANUAL = "AJUSTE_MANUAL"
    INGRESO = "INGRESO"
    
    # Tipos Estándar
    RETIRO = "RETIRO"
    
    # Legacy (Mantenidos para compatibilidad con datos históricos)
    BONO = "BONO"
    DESCUENTO = "DESCUENTO"
    AJUSTE = "AJUSTE"
    
    # === NUEVOS TIPOS FASE 7: Pagos Reales & Wallet ===
    DELIVERY_BONUS = "DELIVERY_BONUS"           # Bono por entrega completada (nuevo estándar)
    FAILED_ATTEMPT_BONUS = "FAILED_ATTEMPT_BONUS" # Compensación fallo externo
    WITHDRAWAL_REQUEST = "WITHDRAWAL_REQUEST"   # Solicitud de retiro (debito temporal)
    WITHDRAWAL_COMPLETION = "WITHDRAWAL_COMPLETION" # Retiro ejecutado (debito final)
    STRIPE_PAYOUT = "STRIPE_PAYOUT"             # Payout vía Stripe Connect
    STRIPE_INSTANT = "STRIPE_INSTANT"           # Pago instantáneo Stripe
    BANK_TRANSFER = "BANK_TRANSFER"             # Transferencia bancaria directa
    WALLET_ADJUSTMENT = "WALLET_ADJUSTMENT"     # Ajuste de wallet (admin)


class PaymentStatus(str, enum.Enum):
    """Payment status."""
    PENDIENTE = "PENDIENTE"
    PROCESADO = "PROCESADO"
    PAGADO = "PAGADO"
    RECHAZADO = "RECHAZADO"


class TransactionStatus(str, enum.Enum):
    """Estados de transacción para Fase 7."""
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    PROCESSING = "PROCESSING"


class PayoutStatus(str, enum.Enum):
    """Estados de solicitud de retiro (en español para Fase 7 Enterprise)."""
    PENDIENTE = "PENDIENTE"
    APROBADO = "APROBADO"
    EN_PROCESO = "EN_PROCESO"
    COMPLETADO = "COMPLETADO"
    RECHAZADO = "RECHAZADO"
    FALLIDO = "FALLIDO"


class RiderWallet(Base):
    """Billetera virtual del rider - Fase 7.
    
    Balance almacenado en centavos (enteros) para evitar errores de punto flotante.
    Ejemplo: $125.50 USD -> 12550 centavos.
    """
    __tablename__ = "rider_wallets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rider_id = Column(UUID(as_uuid=True), ForeignKey("riders.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    
    # Balance en centavos
    balance_cents = Column(Integer, default=0, nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    
    # Metadata
    is_active = Column(Boolean, default=True, nullable=False)
    last_transaction_at = Column(DateTime, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)

    # Relationships
    rider = relationship("Rider", back_populates="wallet")
    transactions = relationship("FinancialTransaction", back_populates="wallet", cascade="all, delete-orphan", foreign_keys="FinancialTransaction.wallet_id")
    payout_requests = relationship("PayoutRequest", back_populates="wallet", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<RiderWallet(rider_id={self.rider_id}, balance=${self.balance_cents/100})>"

    @property
    def balance_decimal(self) -> Decimal:
        """Convierte centavos a Decimal para visualización/cálculos."""
        from decimal import Decimal
        return Decimal(self.balance_cents) / 100
    
    @staticmethod
    def from_decimal(amount: Decimal) -> int:
        """Convierte Decimal a centavos (enteros)."""
        return int(amount * 100)


class FinancialTransaction(Base):
    """Historial inmutable de cada movimiento financiero - Fase 7."""
    __tablename__ = "financial_transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    wallet_id = Column(UUID(as_uuid=True), ForeignKey("rider_wallets.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Tipo y monto (en centavos)
    transaction_type: Any = Column(SQLEnum(TransactionType), nullable=False)
    amount_cents = Column(Integer, nullable=False)  # Positivo=ingreso, Negativo=egreso
    
    # Metadata contextual
    description = Column(Text, nullable=True)
    reference_id = Column(String(255), nullable=True)  # ID de entrega, payout, etc.
    metadata_json = Column(Text, nullable=True)  # JSON extra
    
    # Estados
    status: Any = Column(SQLEnum(TransactionStatus), default=TransactionStatus.PENDING, nullable=False)
    
    # Snapshot del balance después de esta transacción (auditoría)
    balance_after_cents = Column(Integer, nullable=False)

    # Auditoría
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    idempotency_key = Column(String(100), unique=True, index=True, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=utc_now_naive, index=True)

    # Relationships
    wallet = relationship("RiderWallet", back_populates="transactions")
    creator = relationship("User", foreign_keys=[created_by_user_id])

    def __repr__(self):
        return f"<FinancialTransaction(type={self.transaction_type}, amount=${self.amount_cents/100}, status={self.status})>"


class PayoutRequest(Base):
    """Solicitudes de retiro de fondos hacia cuenta bancaria - Fase 7."""
    __tablename__ = "payout_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    wallet_id = Column(UUID(as_uuid=True), ForeignKey("rider_wallets.id", ondelete="CASCADE"), nullable=False, index=True)
    rider_id = Column(UUID(as_uuid=True), ForeignKey("riders.id", ondelete="CASCADE"), nullable=False, index=True)

    # Monto solicitado en centavos
    amount_cents = Column(Integer, nullable=False)
    currency = Column(String(3), default="USD", nullable=False)

    # Datos bancarios (en producción usar tokenización Stripe)
    bank_account_last4 = Column(String(4), nullable=True)
    bank_name = Column(String(100), nullable=True)
    account_holder_name = Column(String(255), nullable=True)
    
    # ID externo de pasarela (Stripe Transfer ID, etc.)
    provider_payout_id = Column(String(255), nullable=True)
    provider_response_json = Column(Text, nullable=True)

    # Estados
    status: Any = Column(SQLEnum(PayoutStatus), default=PayoutStatus.PENDING, nullable=False, index=True)
    rejection_reason = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=utc_now_naive)
    approved_at = Column(DateTime, nullable=True)
    processed_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    failed_at = Column(DateTime, nullable=True)

    # Relationships
    wallet = relationship("RiderWallet", back_populates="payout_requests")
    rider = relationship("Rider", foreign_keys=[rider_id])

    def __repr__(self):
        return f"<PayoutRequest(rider_id={self.rider_id}, amount=${self.amount_cents/100}, status={self.status})>"


# === LEGACY: Mantener compatibilidad con modelo anterior ===
class Financial(Base):
    """Financial transaction record for riders (legacy name, alias of FinancialTransaction)."""
    
    __tablename__ = "financials"
    
    id = Column(
        UUID(as_uuid=True), 
        primary_key=True, 
        index=True,
        default=uuid.uuid4
    )
    rider_id = Column(UUID(as_uuid=True), ForeignKey("riders.id"), nullable=False, index=True)
    shift_id = Column(UUID(as_uuid=True), ForeignKey("shifts.id"), nullable=True, index=True)
    
    # Transaction Details
    transaction_type: Any = Column(SQLEnum(TransactionType), nullable=False)
    amount = Column(Numeric(10, 2), nullable=False, default=0.0)
    balance_before = Column(Numeric(10, 2), default=0.0)
    balance_after = Column(Numeric(10, 2), default=0.0)
    
    # Status
    status: Any = Column(SQLEnum(PaymentStatus), default=PaymentStatus.PENDIENTE)
    
    # Description
    description = Column(Text)
    reference_id = Column(String(100))
    source_type = Column(String(50), index=True)
    source_id = Column(String(100), index=True)
    idempotency_key = Column(String(100), unique=True, index=True)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    
    # Timestamps
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)
    
    # Relationships
    rider = relationship("Rider", back_populates="transactions")
    shift = relationship("Shift")
    
    def __repr__(self):
        return f"<Financial(id={self.id}, rider={self.rider_id}, amount={self.amount})>"

# Alias de compatibilidad
FinancialTransactionLegacy = Financial
