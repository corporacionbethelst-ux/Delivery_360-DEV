"""Rider model for delivery personnel management."""

import uuid
from datetime import datetime, timezone
from typing import Union, TypeAlias
from decimal import Decimal
from sqlalchemy import (
    Column,
    String,
    Float,
    DateTime,
    ForeignKey,
    Enum as SQLEnum,
    Boolean,
    JSON,
    Integer,
    Text,
    text,
    Numeric,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from geoalchemy2 import Geometry
import enum

from app.core.database import Base
from app.models.payout import Payout
from app.models.financial import Financial
from app.models.notification import Notification
from app.models.rider_document import RiderDocument
from app.models.enums import VehicleOwnershipType


def utc_now_naive():
    """Devuelve la hora actual en UTC sin zona horaria (naive)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RiderStatus(str, enum.Enum):
    PENDIENTE = "PENDIENTE"
    ACTIVO = "ACTIVO"
    INACTIVO = "INACTIVO"
    OCUPADO = "OCUPADO"
    SUSPENDIDO = "SUSPENDIDO"


class RiderTier(str, enum.Enum):
    """Niveles de repartidor para sistema de gamificación con bonificaciones."""

    BRONCE = "BRONCE"  # Sin bonificación extra (0%)
    PLATA = "PLATA"  # Bonificación 5%
    ORO = "ORO"  # Bonificación 10%
    PLATINO = "PLATINO"  # Bonificación 15%


class VehicleType(str, enum.Enum):
    MOTO = "MOTO"
    BICICLETA = "BICICLETA"
    PATINETA = "PATINETA"
    AUTO = "AUTO"
    FURGONETA = "FURGONETA"


JsonValue: TypeAlias = Union[
    None, bool, int, float, str, list["JsonValue"], dict[str, "JsonValue"]
]


class Rider(Base):
    __tablename__ = "riders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )

    vehicle_type: Mapped[VehicleType | None] = mapped_column(
        SQLEnum(VehicleType), default=VehicleType.MOTO, nullable=True
    )
    vehicle_plate: Mapped[str | None] = mapped_column(String(20), nullable=True)
    vehicle_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    operating_zone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    zone_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("zones.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    cpf: Mapped[str | None] = mapped_column(String(14), nullable=True)
    cnh: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Tipo de propiedad del vehículo (PROPIO o EMPRESA)
    vehicle_ownership_type: Mapped[str | None] = mapped_column(
        SQLEnum(
            *[e.value for e in VehicleOwnershipType],
            name="vehicleownershiptype",
            create_type=True,
        ),
        default=VehicleOwnershipType.PROPIO.value,
        nullable=True,
    )

    # ID del vehículo de empresa asignado (solo si vehicle_ownership_type es EMPRESA)
    assigned_vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vehicles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    status: Mapped[RiderStatus | None] = mapped_column(
        SQLEnum(RiderStatus), default=RiderStatus.PENDIENTE, nullable=True
    )
    tier: Mapped[RiderTier] = mapped_column(
        SQLEnum(RiderTier, name="rider_tier", create_type=False),
        default=RiderTier.BRONCE,
        nullable=False,
    )
    is_online: Mapped[bool | None] = mapped_column(
        Boolean, default=False, nullable=True
    )
    last_location = Column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=True), nullable=True
    )

    current_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    last_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_location_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    level: Mapped[int | None] = mapped_column(Integer, default=1, nullable=True)
    total_points: Mapped[int | None] = mapped_column(Integer, default=0, nullable=True)
    badges: Mapped[JsonValue] = mapped_column(JSON, default=list, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    documents_metadata: Mapped[JsonValue] = mapped_column(JSON, nullable=True)

    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=utc_now_naive, nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=True
    )

    wallet_balance: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), default=0.0, nullable=True
    )
    pending_balance: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), default=0.0, nullable=True
    )

    # Campo de versión para bloqueo optimista (concurrencia financiera)
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # RELACIONES
    user = relationship("User", back_populates="rider_profile")
    zone = relationship("Zone", back_populates="riders", foreign_keys=[zone_id])
    deliveries = relationship(
        "Delivery", back_populates="rider", foreign_keys="Delivery.rider_id"
    )
    documents = relationship(
        "RiderDocument", back_populates="rider", cascade="all, delete-orphan"
    )
    transactions = relationship(
        "Financial",
        back_populates="rider",
        cascade="all, delete-orphan",
        foreign_keys="Financial.rider_id",
    )
    payouts = relationship(
        "Payout", back_populates="rider", cascade="all, delete-orphan"
    )
    notifications = relationship("Notification", back_populates="rider")

    # Relación con vehículo de empresa asignado
    # Usamos lazy='selectin' para carga asíncrona correcta en FastAPI
    assigned_vehicle = relationship(
        "Vehicle", foreign_keys=[assigned_vehicle_id], lazy="selectin"
    )

    # ELIMINADA LA RELACIÓN DIRECTA CON VEHICLE PARA EVITAR CONFLICTOS CIRCULARES
    # La asignación se maneja ahora vía User.vehicles

    active_order = relationship(
        "Order", foreign_keys=[current_order_id], uselist=False, viewonly=True
    )

    # Alias relacional de compatibilidad para código legacy que aún lee financial_transactions.
    financial_transactions = relationship(
        "Financial",
        foreign_keys="Financial.rider_id",
        viewonly=True,
        overlaps="rider,transactions",
    )

    # Relación con Wallet (Fase 7)
    wallet = relationship(
        "RiderWallet",
        uselist=False,
        back_populates="rider",
        cascade="all, delete-orphan",
    )

    # Relación inversa para productivity_metrics (sin back_populates para evitar conflicto, overlaps para silenciar warning)
    productivity_metrics = relationship(
        "ProductivityRecord",
        foreign_keys="ProductivityRecord.rider_id",
        overlaps="rider",
    )

    def __repr__(self):
        return f"<Rider(id={self.id}, status={self.status})>"
