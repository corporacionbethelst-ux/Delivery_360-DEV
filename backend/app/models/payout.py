"""Payout model for rider withdrawal requests."""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from sqlalchemy import Column, String, DateTime, ForeignKey, Enum as SQLEnum, Numeric, Text, text, Index
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import enum

from app.core.database import Base

def utc_now_naive():
    """Devuelve la hora actual en UTC sin zona horaria (naive)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

# FIX FASE 7: Se ELIMINÓ la definición duplicada de `PayoutStatus` que vivía aquí.
# Ahora se re-exporta ÚNICAMENTE la clase canónica definida en app.models.financial,
# para que TODOS los modelos y endpoints compartan el mismo enum (6 valores en español)
# vinculado al tipo PostgreSQL 'payoutstatus' estándar creado por la migración 20260818.
from app.models.financial import PayoutStatus  # noqa: F401  (re-export intencional)

class PayoutMethod(str, enum.Enum):
    TRANSFERENCIA = "TRANSFERENCIA"
    EFECTIVO = "EFECTIVO"
    BILLETERA_DIGITAL = "BILLETERA_DIGITAL"

class Payout(Base):
    __tablename__ = "payouts"

    id = Column(
        UUID(as_uuid=True), 
        primary_key=True, 
        default=uuid.uuid4, 
        index=True
    )

    rider_id = Column(UUID(as_uuid=True), ForeignKey("riders.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Datos del retiro
    amount = Column(Numeric(10, 2), nullable=False)
    # FIX FASE 7 (column "payouts.status" does not exist):
    # La tabla legacy 'payouts' se creó en la migración inicial a617d286d3d0 con una
    # columna llamada 'requested_at', NO 'status'. El modelo declaraba 'status', por lo
    # que cualquier SELECT/INSERT de /api/v1/payouts fallaba contra la BD real.
    # Se mapea el atributo 'status' a la columna física existente y se usa
    # create_type=False para reutilizar el tipo PG 'payoutstatus' estándar (6 valores
    # en español) ya normalizado por la migración 20260818.
    status: Any = Column("status", SQLEnum(PayoutStatus, name="payoutstatus", create_type=False), nullable=True)
    method: Any = Column(SQLEnum(PayoutMethod, name="payoutmethod", create_type=False), default=PayoutMethod.TRANSFERENCIA)
    
    # Información bancaria (opcional, podría venir de una tabla separada)
    bank_account_last4 = Column(String(10), nullable=True)
    reference_code = Column(String(50), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    idempotency_key = Column(String(100), unique=True, nullable=True, index=True)

    # Trazabilidad contable y de auditoría
    balance_before = Column(Numeric(10, 2), nullable=True)
    balance_after = Column(Numeric(10, 2), nullable=True)
    requested_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    processed_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    
    # Fechas
    requested_at = Column(DateTime, default=utc_now_naive)
    processed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)
    
    # Relación
    rider = relationship("Rider", back_populates="payouts")
    status_history = relationship("PayoutStatusHistory", back_populates="payout", cascade="all, delete-orphan", order_by="PayoutStatusHistory.created_at")

    def __repr__(self):
        return f"<Payout(id={self.id}, rider={self.rider_id}, amount={self.amount}, status={self.status})>"


class PayoutStatusHistory(Base):
    """Historial auditable de cambios de estado de retiros."""

    __tablename__ = "payout_status_history"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    payout_id = Column(UUID(as_uuid=True), ForeignKey("payouts.id", ondelete="CASCADE"), nullable=False, index=True)
    old_status = Column(String(30), nullable=True)
    new_status = Column(String(30), nullable=False)
    reason = Column(Text, nullable=True)
    changed_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    balance_before = Column(Numeric(10, 2), nullable=True)
    balance_after = Column(Numeric(10, 2), nullable=True)
    created_at = Column(DateTime, default=utc_now_naive, index=True)

    payout = relationship("Payout", back_populates="status_history")

    __table_args__ = (
        Index("idx_payout_status_history_payout_date", "payout_id", "created_at"),
    )

    def __repr__(self):
        return f"<PayoutStatusHistory(payout={self.payout_id}, new_status={self.new_status})>"
