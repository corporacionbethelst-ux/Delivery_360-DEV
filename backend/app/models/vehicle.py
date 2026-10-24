# app/models/vehicle.py
from sqlalchemy import (
    String,
    Integer,
    Date,
    Text,
    ForeignKey,
    DateTime,
    Enum as SQLEnum,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import date, datetime, timezone
import uuid

# Importar los enums compartidos
from app.models.enums import VehicleType, VehicleStatus

# Importar Base desde database para mantener consistencia con el resto de modelos
from app.core.database import Base


def utc_now_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )

    # Definición correcta de Enums en SQL: pasar los valores (.value) como argumentos
    type: Mapped[str] = mapped_column(
        SQLEnum(*[e.value for e in VehicleType], name="vehicletype", create_type=True),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        SQLEnum(
            *[e.value for e in VehicleStatus], name="vehiclestatus", create_type=True
        ),
        nullable=False,
        default="ACTIVO",
    )

    plate: Mapped[str] = mapped_column(
        String(20), unique=True, index=True, nullable=False
    )
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    color: Mapped[str] = mapped_column(String(50), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)

    insurance_expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Clave foránea hacia Users (no hacia Riders directamente, ya que el vehículo lo posee la persona/usuario)
    rider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )

    # Relación: Un vehículo pertenece a un Usuario (que puede ser repartidor)
    # ✅ CORRECCIÓN: Eliminar back_populates para evitar circularidad.
    # La relación es unidireccional desde Vehicle hacia User.
    # Usamos lazy='selectin' para carga asíncrona correcta en FastAPI
    rider = relationship("User", foreign_keys=[rider_id], lazy="selectin")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utc_now_naive, nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False),
        default=utc_now_naive,
        onupdate=utc_now_naive,
        nullable=True,
    )

    # Índice compuesto útil para búsquedas
    __table_args__ = (Index("ix_vehicles_status_plate", "status", "plate"),)
