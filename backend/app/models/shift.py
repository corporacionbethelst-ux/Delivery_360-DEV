"""Shift model."""

import uuid
from datetime import datetime, timezone, time  # CORREGIDO
from sqlalchemy import (
    String,
    DateTime,
    ForeignKey,
    Enum as SQLEnum,
    Float,
    Time,
    Integer,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import enum
from app.core.database import Base


def utc_now_naive():
    """Devuelve la hora actual en UTC sin zona horaria para columnas TIMESTAMP WITHOUT TIME ZONE."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ShiftStatus(str, enum.Enum):
    PROGRAMADO = "PROGRAMADO"
    EN_CURSO = "EN_CURSO"
    COMPLETADO = "COMPLETADO"
    CANCELADO = "CANCELADO"
    INCOMPLETO = "INCOMPLETO"


class Shift(Base):
    __tablename__ = "shifts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )
    rider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("riders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    shift_date: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)

    check_in_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    check_out_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    status: Mapped[ShiftStatus | None] = mapped_column(
        SQLEnum(ShiftStatus), default=ShiftStatus.PROGRAMADO, nullable=True
    )

    check_in_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    check_in_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    check_out_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    check_out_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    total_deliveries: Mapped[int | None] = mapped_column(
        Integer, default=0, nullable=True
    )
    completed_deliveries: Mapped[int | None] = mapped_column(
        Integer, default=0, nullable=True
    )
    total_earnings: Mapped[float | None] = mapped_column(
        Float, default=0.0, nullable=True
    )

    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=utc_now_naive, nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=True
    )

    rider = relationship("Rider")
    check_ins = relationship(
        "CheckInOut", back_populates="shift", cascade="all, delete-orphan"
    )
    productivity_records = relationship("ProductivityRecord")

    def __repr__(self):
        return f"<Shift(id={self.id}, rider={self.rider_id}, date={self.shift_date})>"


class CheckInOut(Base):
    __tablename__ = "check_in_out"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )
    rider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("riders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    shift_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shifts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    check_type: Mapped[str] = mapped_column(String(10), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=utc_now_naive, nullable=True
    )

    rider = relationship("Rider")
    shift = relationship("Shift", back_populates="check_ins")

    def __repr__(self):
        return (
            f"<CheckInOut(id={self.id}, rider={self.rider_id}, type={self.check_type})>"
        )
