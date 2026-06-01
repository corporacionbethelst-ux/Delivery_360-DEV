"""Financial models for rider payments and transactions."""

import uuid
from datetime import datetime, timezone
from typing import Any  # <--- IMPORTACIÓN AGREGADA
from sqlalchemy import Column, String, Float, DateTime, ForeignKey, Enum as SQLEnum, Numeric, Text, text
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import enum

from app.core.database import Base

def utc_now_naive():
    """Devuelve la hora actual en UTC sin zona horaria (naive) para compatibilidad con PostgreSQL."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

class TransactionType(str, enum.Enum):
    """Transaction types."""
    PAGO_ENTREGA = "PAGO_ENTREGA"
    BONO = "BONO"
    DESCUENTO = "DESCUENTO"
    AJUSTE = "AJUSTE"
    RETIRO = "RETIRO"


class PaymentStatus(str, enum.Enum):
    """Payment status."""
    PENDIENTE = "PENDIENTE"
    PROCESADO = "PROCESADO"
    PAGADO = "PAGADO"
    RECHAZADO = "RECHAZADO"

class Financial(Base):
    """Financial transaction record for riders."""
    
    __tablename__ = "financials"
    
    id = Column(
        UUID(as_uuid=True), 
        primary_key=True, 
        index=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()")  # <-- Clave para que PG genere el ID
    )
    rider_id = Column(UUID(as_uuid=True), ForeignKey("riders.id"), nullable=False, index=True)
    shift_id = Column(UUID(as_uuid=True), ForeignKey("shifts.id"), nullable=True, index=True)
    
    # Transaction Details
    transaction_type: Any = Column(SQLEnum(TransactionType), nullable=False)
    amount = Column(Numeric(10, 2), nullable=False, default=0.0)
    balance_after = Column(Numeric(10, 2), default=0.0)
    
    # Status
    status: Any = Column(SQLEnum(PaymentStatus), default=PaymentStatus.PENDIENTE)
    
    # Description
    description = Column(Text)
    reference_id = Column(String(100))
    
    # Timestamps
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)
    
    # Relationships (Unidireccionales para evitar errores de configuración)
    rider = relationship("Rider")
    shift = relationship("Shift")
    
    def __repr__(self):
        return f"<Financial(id={self.id}, rider={self.rider_id}, amount={self.amount})>"