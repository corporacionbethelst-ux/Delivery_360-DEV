"""Delivery model."""
import uuid
from datetime import datetime, timezone  # CORREGIDO
from typing import Any
from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, Enum as SQLEnum, Text, text, Boolean, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import enum
from app.core.database import Base

def utc_now_naive():
    """Devuelve la hora actual en UTC sin zona horaria (naive) para compatibilidad con PostgreSQL."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

class DeliveryStatus(str, enum.Enum):
    PENDIENTE = "PENDIENTE"
    INICIADA = "INICIADA"
    EN_PICKUP = "EN_PICKUP"
    EN_ROUTE = "EN_ROUTE"
    EN_DESTINO = "EN_DESTINO"
    COMPLETADA = "COMPLETADA"
    FALLIDA = "FALLIDA"

class ProofType(str, enum.Enum):
    FOTO = "FOTO"
    FIRMA = "FIRMA"
    OTP = "OTP"
    NINGUNO = "NINGUNO"

class DeliveryFailureCause(str, enum.Enum):
    """
    Causas estandarizadas para entregas fallidas.
    Determina automáticamente si el repartidor recibe bono por intento fallido.
    """
    # === CAUSAS EXTERNAS (BONIFICABLES - 1500 COP) ===
    CLIENTE_NO_ESTA = "CLIENTE_NO_ESTA"
    CLIENTE_NO_CONTESTA = "CLIENTE_NO_CONTESTA"
    DIRECCION_INCORRECTA = "DIRECCION_INCORRECTA"
    DIRECCION_NO_EXISTE = "DIRECCION_NO_EXISTE"
    COMERCIO_CERRADO = "COMERCIO_CERRADO"
    CLIENTE_RECHAZA = "CLIENTE_RECHAZA"
    ZONA_INSEGURA = "ZONA_INSEGURA"
    FUERZA_MAYOR = "FUERZA_MAYOR"
    EDIFICIO_RESTRINGIDO = "EDIFICIO_RESTRINGIDO"
    
    # === CAUSAS DEL REPARTIDOR (NO BONIFICABLES) ===
    REPARTIDOR_NO_QUIERE_ENTREGAR = "REPARTIDOR_NO_QUIERE_ENTREGAR"
    REPARTIDOR_LLEGO_TARDE = "REPARTIDOR_LLEGO_TARDE"
    REPARTIDOR_ERROR_PROPIO = "REPARTIDOR_ERROR_PROPIO"
    REPARTIDOR_VEHICULO_FALLA = "REPARTIDOR_VEHICULO_FALLA"
    REPARTIDOR_SIN_BATERIA = "REPARTIDOR_SIN_BATERIA"
    OTRO_REPARTIDOR = "OTRO_REPARTIDOR"
    
    @property
    def is_bonificable(self) -> bool:
        """Determina si esta causa da derecho al bono por intento fallido."""
        return check_is_bonificable(self)


def get_bonificable_causes() -> list[str]:
    """Retorna lista de valores de causas bonificables."""
    return [
        "CLIENTE_NO_ESTA",
        "CLIENTE_NO_CONTESTA",
        "DIRECCION_INCORRECTA",
        "DIRECCION_NO_EXISTE",
        "COMERCIO_CERRADO",
        "CLIENTE_RECHAZA",
        "ZONA_INSEGURA",
        "FUERZA_MAYOR",
        "EDIFICIO_RESTRINGIDO",
    ]


def check_is_bonificable(cause: "DeliveryFailureCause") -> bool:
    """
    Función helper para verificar si una causa es bonificable.
    
    Args:
        cause: Instancia de DeliveryFailureCause
        
    Returns:
        True si la causa da derecho al bono por intento fallido
    """
    if isinstance(cause, DeliveryFailureCause):
        return cause.value in get_bonificable_causes()
    return False

class Delivery(Base):
    __tablename__ = "deliveries"
    __table_args__ = {'extend_existing': True}
    
    id = Column(
        UUID(as_uuid=True), 
        primary_key=True, 
        index=True,
        default=uuid.uuid4
    )
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    rider_id = Column(UUID(as_uuid=True), ForeignKey("riders.id", ondelete="SET NULL"), nullable=False, index=True)
    
    status: Any = Column(SQLEnum(DeliveryStatus), default=DeliveryStatus.PENDIENTE)
    
    # CORREGIDO
    started_at = Column(DateTime)
    arrived_pickup_at = Column(DateTime)
    left_pickup_at = Column(DateTime)
    arrived_delivery_at = Column(DateTime)
    completed_at = Column(DateTime)
    
    current_latitude = Column(Float)
    current_longitude = Column(Float)
    last_location_update = Column(DateTime)
    
    route_data = Column(JSON)
    distance_total = Column(Float)
    distance_pickup = Column(Float)
    distance_delivery = Column(Float)
    
    proof_type: Any = Column(SQLEnum(ProofType))
    proof_photo_url = Column(String(500))
    proof_signature = Column(Text)
    proof_otp = Column(String(10))
    proof_notes = Column(Text)
    customer_name_received = Column(String(255))
    
    has_issues = Column(Boolean, default=False)
    failure_cause: Any = Column(SQLEnum(DeliveryFailureCause), nullable=True)  # Nuevo campo ENUM estandarizado
    issue_type = Column(String(50))  # Se mantiene para compatibilidad pero se depreca
    issue_description = Column(Text)
    issue_resolved = Column(Boolean, default=False)
    issue_analysis_result = Column(Text)  # Resultado del análisis de causa (externa/interna)
    
    time_to_pickup = Column(Integer)
    time_at_pickup = Column(Integer)
    time_to_delivery = Column(Integer)
    total_time = Column(Integer)
    
    sla_expected_minutes = Column(Integer)
    sla_actual_minutes = Column(Integer)
    sla_compliant = Column(Boolean)
    
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)
    
    order = relationship("Order", back_populates="delivery")
    rider = relationship("Rider", back_populates="deliveries", foreign_keys=[rider_id])
    route = relationship("Route", back_populates="delivery", uselist=False, primaryjoin="Delivery.id == foreign(Route.delivery_id)", foreign_keys="[Route.delivery_id]")

    def __repr__(self):
        return f"<Delivery(id={self.id}, order={self.order_id}, status={self.status})>"