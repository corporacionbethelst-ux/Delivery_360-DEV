"""Order model."""

import uuid
from datetime import datetime, timezone  # CORREGIDO
from app.core.json_types import JsonValue
from sqlalchemy import (
    String,
    Float,
    DateTime,
    ForeignKey,
    Enum as SQLEnum,
    Text,
    text,
    Boolean,
    JSON,
    Integer,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import enum
from app.core.database import Base


def utc_now_naive():
    """Devuelve la hora actual en UTC sin zona horaria (naive) para compatibilidad con PostgreSQL."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class OrderStatus(str, enum.Enum):
    PENDIENTE = "PENDIENTE"
    ASIGNADO = "ASIGNADO"
    EN_RECOLECCION = "EN_RECOLECCION"
    RECOLECTADO = "RECOLECTADO"
    EN_RUTA = "EN_RUTA"
    ENTREGADO = "ENTREGADO"
    FALLIDO = "FALLIDO"
    CANCELADO = "CANCELADO"


class OrderPriority(str, enum.Enum):
    NORMAL = "NORMAL"
    ALTA = "ALTA"
    URGENTE = "URGENTE"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        index=True,
        default=uuid.uuid4,
        nullable=False,
    )
    external_id: Mapped[str | None] = mapped_column(
        String(100), unique=True, index=True, nullable=True
    )
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    customer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    pickup_address: Mapped[str] = mapped_column(Text, nullable=False)
    pickup_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pickup_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    delivery_address: Mapped[str] = mapped_column(Text, nullable=False)
    delivery_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    delivery_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)

    pickup_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    pickup_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    delivery_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    delivery_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    items: Mapped[JsonValue] = mapped_column(JSON, nullable=True)
    subtotal: Mapped[float | None] = mapped_column(Float, default=0.0, nullable=True)
    delivery_fee: Mapped[float | None] = mapped_column(
        Float, default=0.0, nullable=True
    )
    total: Mapped[float | None] = mapped_column(Float, default=0.0, nullable=True)

    payment_method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payment_status: Mapped[str | None] = mapped_column(
        String(20), default="pendiente", nullable=True
    )
    status: Mapped[OrderStatus | None] = mapped_column(
        SQLEnum(OrderStatus), default=OrderStatus.PENDIENTE, nullable=True
    )
    priority: Mapped[OrderPriority | None] = mapped_column(
        SQLEnum(OrderPriority), default=OrderPriority.NORMAL, nullable=True
    )

    assigned_rider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("riders.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    # CORREGIDO: Fechas con timezone
    ordered_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, nullable=False
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    estimated_delivery_time: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    sla_deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    failure_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failure_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_cause_external: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True
    )  # True si la causa fue externa (cliente/comercio), False si fue culpa del rider
    cancelled_by: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(50), default="app", nullable=True)
    integration_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    webhook_sent: Mapped[bool | None] = mapped_column(
        Boolean, default=False, nullable=True
    )

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=utc_now_naive, nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=True
    )

    delivery = relationship("Delivery", back_populates="order", uselist=False)

    assigned_rider = relationship(
        "Rider",
        foreign_keys=[assigned_rider_id],
        backref="assigned_orders",
    )

    def __repr__(self):
        return f"<Order(id={self.id}, external_id={self.external_id}, status={self.status})>"
