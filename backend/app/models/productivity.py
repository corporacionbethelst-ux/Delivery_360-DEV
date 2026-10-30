"""Productivity models."""

import uuid
from datetime import datetime, timezone  # CORREGIDO
from sqlalchemy import (
    String,
    Float,
    DateTime,
    ForeignKey,
    Enum as SQLEnum,
    Integer,
    text,
    Boolean,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import enum
import sqlalchemy as sa
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


class ProductivityMetrics(Base):
    """Tabla de métricas de productividad consolidadas por rider y período."""

    __tablename__ = "productivity_metrics"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        index=True,
        default=uuid.uuid4,
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
        ForeignKey("shifts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Métricas principales
    total_deliveries: Mapped[int | None] = mapped_column(
        Integer, default=0, nullable=True
    )
    on_time_deliveries: Mapped[int | None] = mapped_column(
        Integer, default=0, nullable=True
    )
    late_deliveries: Mapped[int | None] = mapped_column(
        Integer, default=0, nullable=True
    )

    avg_delivery_time_minutes: Mapped[float | None] = mapped_column(
        Float, default=0.0, nullable=True
    )
    total_distance_km: Mapped[float | None] = mapped_column(
        Float, default=0.0, nullable=True
    )
    total_earnings: Mapped[float | None] = mapped_column(
        Float, default=0.0, nullable=True
    )

    customer_rating_avg: Mapped[float | None] = mapped_column(
        Float, default=0.0, nullable=True
    )
    customer_rating_count: Mapped[int | None] = mapped_column(
        Integer, default=0, nullable=True
    )

    sla_compliance_rate: Mapped[float | None] = mapped_column(
        Float, default=100.0, nullable=True
    )  # Porcentaje

    # Período
    period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=utc_now_naive, nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=True
    )

    # Relaciones - Sin back_populates para evitar conflictos con Rider
    rider = relationship("Rider", foreign_keys=[rider_id])
    shift = relationship("Shift")

    __table_args__ = (
        Index(
            "idx_productivity_metrics_rider_period",
            "rider_id",
            "period_start",
            "period_end",
        ),
    )

    def __repr__(self):
        return f"<ProductivityMetrics(id={self.id}, rider={self.rider_id}, deliveries={self.total_deliveries})>"


class SLARecord(Base):
    """Registro de cumplimiento de SLA por entrega."""

    __tablename__ = "sla_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        index=True,
        default=uuid.uuid4,
        nullable=False,
    )

    rider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("riders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    delivery_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("deliveries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # SLA targets
    promised_delivery_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_delivery_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Resultado
    sla_met: Mapped[bool | None] = mapped_column(Boolean, default=True, nullable=True)
    delay_minutes: Mapped[int | None] = mapped_column(Integer, default=0, nullable=True)

    # Timestamps
    promised_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=utc_now_naive, nullable=True
    )

    # Relaciones
    rider = relationship("Rider")
    delivery = relationship("Delivery")
    order = relationship("Order")

    __table_args__ = (
        Index("idx_sla_records_rider_date", "rider_id", "created_at"),
        Index("idx_sla_records_met", "sla_met"),
    )

    def __repr__(self):
        return f"<SLARecord(id={self.id}, delivery={self.delivery_id}, sla_met={self.sla_met})>"


class ProductivityRecord(Base):
    __tablename__ = "productivity_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        index=True,
        default=uuid.uuid4,
        nullable=False,
    )
    rider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("riders.id", ondelete="SET NULL"),
        nullable=False,
        index=True,
    )
    shift_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shifts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    metric_type: Mapped[MetricType] = mapped_column(SQLEnum(MetricType), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)

    date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=utc_now_naive, nullable=True
    )

    rider = relationship("Rider")
    shift = relationship("Shift", back_populates="productivity_records")

    def __repr__(self):
        return f"<ProductivityRecord(id={self.id}, rider={self.rider_id}, type={self.metric_type})>"
