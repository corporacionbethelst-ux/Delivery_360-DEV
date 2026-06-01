"""Payout model for rider withdrawal requests."""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from sqlalchemy import Column, String, Float, DateTime, ForeignKey, Enum as SQLEnum, Numeric, Text, text
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import enum

from app.core.database import Base

def utc_now_naive():
    """Devuelve la hora actual en UTC sin zona horaria (naive)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

class PayoutStatus(str, enum.Enum):
    PENDIENTE = "PENDIENTE"
    PROCESADO = "PROCESADO"
    RECHAZADO = "RECHAZADO"
    CANCELADO = "CANCELADO"

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
        index=True, 
        server_default=text("gen_random_uuid()")
    )

    rider_id = Column(UUID(as_uuid=True), ForeignKey("riders.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Datos del retiro
    amount = Column(Numeric(10, 2), nullable=False)
    status: Any = Column(SQLEnum(PayoutStatus), default=PayoutStatus.PENDIENTE)
    method: Any = Column(SQLEnum(PayoutMethod), default=PayoutMethod.TRANSFERENCIA)
    
    # Información bancaria (opcional, podría venir de una tabla separada)
    bank_account_last4 = Column(String(10), nullable=True)
    reference_code = Column(String(50), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    
    # Fechas
    requested_at = Column(DateTime, default=utc_now_naive)
    processed_at = Column(DateTime, nullable=True)
    
    # Relación
    rider = relationship("Rider", back_populates="payouts")

    def __repr__(self):
        return f"<Payout(id={self.id}, rider={self.rider_id}, amount={self.amount}, status={self.status})>"