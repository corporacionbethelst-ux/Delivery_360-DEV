"""Productivity models."""
import uuid
from datetime import datetime, timezone  # CORREGIDO
from typing import Any
from sqlalchemy import Column, String, Float, DateTime, ForeignKey, Enum as SQLEnum, Integer, text
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import enum
from app.core.database import Base

def utc_now_naive():
    """Devuelve la hora actual en UTC sin zona horaria (naive) para compatibilidad con PostgreSQL."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

class MetricType(str, enum.Enum):
    ENTREGAS_TOTAL = "ENTREGAS_TOTAL"
    TIEMPO_PROMEDIO = "TIEMPO_PROMEDIO"
    CALIFICACION = "CALIFICACION"
    DISTANCIA_TOTAL = "DISTANCIA_TOTAL"
    INGRESOS_TURNO = "INGRESOS_TURNO"

class ProductivityRecord(Base):
    __tablename__ = "productivity_records"
    
    id = Column(
        UUID(as_uuid=True), 
        primary_key=True, 
        index=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()")  # <-- Clave para que PG genere el ID
    )
    rider_id = Column(UUID(as_uuid=True), ForeignKey("riders.id", ondelete="SET NULL"), nullable=False, index=True)
    shift_id = Column(UUID(as_uuid=True), ForeignKey("shifts.id", ondelete="CASCADE"), nullable=True, index=True)
    
    metric_type: Any = Column(SQLEnum(MetricType), nullable=False)
    value = Column(Float, nullable=False)
    unit = Column(String(50))
    
    date = Column(DateTime, nullable=False)
    notes = Column(String(500))
    
    created_at = Column(DateTime, default=utc_now_naive)
    
    rider = relationship("Rider")
    shift = relationship("Shift")

    def __repr__(self):
        return f"<ProductivityRecord(id={self.id}, rider={self.rider_id}, type={self.metric_type})>"