"""Route model."""

import uuid
from datetime import datetime, timezone  # CORREGIDO
from sqlalchemy import (
    String,
    Float,
    DateTime,
    ForeignKey,
    Enum as SQLEnum,
    Text,
    Boolean,
    JSON,
    Integer,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.json_types import JsonValue
from sqlalchemy.dialects.postgresql import UUID
import enum
from app.core.database import Base


def utc_now_naive():
    """Devuelve la hora actual en UTC sin zona horaria (naive) para compatibilidad con PostgreSQL."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RouteStatus(str, enum.Enum):
    PLANIFICADA = "PLANIFICADA"
    EN_PROGRESO = "EN_PROGRESO"
    COMPLETADA = "COMPLETADA"
    CANCELADA = "CANCELADA"


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )

    delivery_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("deliveries.id"),
        unique=True,
        index=True,
        nullable=True,
    )

    status: Mapped[RouteStatus | None] = mapped_column(
        SQLEnum(RouteStatus), default=RouteStatus.PLANIFICADA, nullable=True
    )
    planned_route: Mapped[JsonValue] = mapped_column(JSON, nullable=True)
    actual_route: Mapped[JsonValue] = mapped_column(JSON, nullable=True)

    pickup_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    pickup_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    delivery_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    delivery_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    planned_distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    planned_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    has_deviation: Mapped[bool | None] = mapped_column(
        Boolean, default=False, nullable=True
    )
    deviation_distance_km: Mapped[float | None] = mapped_column(
        Float, default=0.0, nullable=True
    )
    deviation_time_minutes: Mapped[int | None] = mapped_column(
        Integer, default=0, nullable=True
    )
    deviation_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    traffic_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    weather_condition: Mapped[str | None] = mapped_column(String(50), nullable=True)
    efficiency_score: Mapped[float | None] = mapped_column(
        Float, default=0.0, nullable=True
    )

    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=utc_now_naive, nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=True
    )

    delivery = relationship(
        "Delivery",
        back_populates="route",
        primaryjoin="Route.delivery_id == Delivery.id",
        foreign_keys="[Route.delivery_id]",
    )
    points = relationship("RoutePoint", back_populates="route")
    deviations = relationship("RouteDeviation", back_populates="route")

    def __repr__(self):
        return f"<Route(id={self.id}, delivery={self.delivery_id})>"


class RoutePoint(Base):
    __tablename__ = "route_points"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )
    route_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("routes.id"), index=True, nullable=True
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    altitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    heading: Mapped[float | None] = mapped_column(Float, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    battery_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_charging: Mapped[bool | None] = mapped_column(
        Boolean, default=False, nullable=True
    )
    network_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source: Mapped[str | None] = mapped_column(String(50), default="gps", nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=utc_now_naive, nullable=True
    )
    route = relationship("Route", back_populates="points")

    def __repr__(self):
        return f"<RoutePoint(route={self.route_id})>"


class RouteDeviation(Base):
    __tablename__ = "route_deviations"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )
    route_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("routes.id"), index=True, nullable=True
    )
    deviation_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    severity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expected_location: Mapped[JsonValue] = mapped_column(JSON, nullable=True)
    actual_location: Mapped[JsonValue] = mapped_column(JSON, nullable=True)
    distance_from_route_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_lost_minutes: Mapped[int | None] = mapped_column(
        Integer, default=0, nullable=True
    )
    status: Mapped[str | None] = mapped_column(
        String(20), default="abierto", nullable=True
    )
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )  # Asegúrate que sea UUID si users.id es UUID
    alert_sent: Mapped[bool | None] = mapped_column(
        Boolean, default=False, nullable=True
    )
    alert_channels: Mapped[JsonValue] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=utc_now_naive, nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=True
    )
    route = relationship("Route", back_populates="deviations")

    def __repr__(self):
        return f"<RouteDeviation(route={self.route_id})>"
