"""
Delivery360 - Fase 8: Mapas & Tracking
Modelos de datos para tracking en tiempo real y snapshots de rutas optimizadas.

Tablas:
    - rider_live_locations : historial de posiciones GPS (retención configurable, default 7 días)
    - delivery_route_snapshots : resultados del optimizador VRP con TTL de caché
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Float, DateTime, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


def utc_now_naive():
    """Hora actual UTC naive (compatibilidad con columnas TIMESTAMP WITHOUT TIME ZONE del proyecto)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RiderLiveLocation(Base):
    """Posición GPS reportada por un repartidor (flujo de alta frecuencia)."""

    __tablename__ = "rider_live_locations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    rider_id = Column(
        UUID(as_uuid=True),
        ForeignKey("riders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    accuracy_meters = Column(Float, nullable=True)      # Precisión GPS reportada por el dispositivo
    speed_kmh = Column(Float, nullable=True)            # Velocidad instantánea normalizada a km/h
    heading_degrees = Column(Float, nullable=True)      # Dirección de brújula (0-360)
    recorded_at = Column(DateTime, default=utc_now_naive, nullable=False, index=True)
    created_at = Column(DateTime, default=utc_now_naive, nullable=False)

    # Índices compuestos para las consultas calientes de la Fase 8:
    #   1) última posición por rider (dashboard / live fallback REST)
    #   2) barrido temporal para el job de retención/limpieza
    __table_args__ = (
        Index("idx_rider_locations_recent", "rider_id", text("recorded_at DESC")),
        Index("idx_rider_locations_recorded", "recorded_at"),
    )

    rider = relationship("Rider")

    def __repr__(self):
        return f"<RiderLiveLocation(rider={self.rider_id}, lat={self.latitude}, lng={self.longitude})>"


class DeliveryRouteSnapshot(Base):
    """Resultado persistido de una optimización de ruta (VRP) con expiración para invalidar caché."""

    __tablename__ = "delivery_route_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    delivery_id = Column(
        UUID(as_uuid=True),
        ForeignKey("deliveries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    optimized_sequence_json = Column(String, nullable=False)  # JSON array de waypoints calculados
    original_distance_km = Column(Float, nullable=False)
    optimized_distance_km = Column(Float, nullable=False)
    savings_percentage = Column(Float, nullable=False, default=0.0)
    calculated_at = Column(DateTime, default=utc_now_naive, nullable=False)
    expires_at = Column(DateTime, nullable=True, index=True)  # TTL: job periódico elimina snapshots vencidos

    __table_args__ = (
        Index("idx_route_snapshots_delivery", "delivery_id"),
        Index("idx_route_snapshots_expires", "expires_at"),
    )

    delivery = relationship("Delivery")

    def __repr__(self):
        return (
            f"<DeliveryRouteSnapshot(delivery={self.delivery_id}, "
            f"savings={self.savings_percentage:.1f}%)>"
        )
