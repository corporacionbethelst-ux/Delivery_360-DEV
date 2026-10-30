"""Integration model for external system connections."""

import uuid
from datetime import datetime, timezone
from app.core.json_types import JsonValue
from sqlalchemy import (
    String,
    Boolean,
    DateTime,
    Enum as SQLEnum,
    Integer,
    Text,
    text,
    ForeignKey,
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


class IntegrationType(str, enum.Enum):
    ERP = "ERP"
    POS = "POS"
    PAYMENT = "PAYMENT"
    MAPS = "MAPS"
    SMS = "SMS"
    EMAIL = "EMAIL"


class IntegrationStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    ERROR = "ERROR"


class WebhookEventType(str, enum.Enum):
    ORDER_CREATED = "ORDER_CREATED"
    ORDER_UPDATED = "ORDER_UPDATED"
    DELIVERY_COMPLETED = "DELIVERY_COMPLETED"
    RIDER_ASSIGNED = "RIDER_ASSIGNED"
    PAYMENT_RECEIVED = "PAYMENT_RECEIVED"
    ALERT_TRIGGERED = "ALERT_TRIGGERED"


class Integration(Base):
    """External system integration configuration."""

    __tablename__ = "integrations"

    # ID como UUID
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        index=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    integration_type: Mapped[IntegrationType] = mapped_column(
        SQLEnum(IntegrationType), nullable=False
    )
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Connection
    api_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    api_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    auth_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    credentials: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Status
    status: Mapped[IntegrationStatus | None] = mapped_column(
        SQLEnum(IntegrationStatus), default=IntegrationStatus.INACTIVE, nullable=True
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int | None] = mapped_column(
        Integer, default=0, nullable=True
    )

    # Config
    config: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    webhook_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Sync
    sync_enabled: Mapped[bool | None] = mapped_column(
        Boolean, default=False, nullable=True
    )
    sync_frequency_minutes: Mapped[int | None] = mapped_column(
        Integer, default=60, nullable=True
    )
    sync_last_run: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sync_next_run: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Timestamps - CORREGIDOS PARA USAR TIMEZONE AWARE
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=utc_now_naive, nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=True
    )

    # created_by como UUID para coincidir con User.id
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True, nullable=True
    )

    # Relationships
    creator = relationship("User")
    webhook_events = relationship(
        "WebhookEvent", back_populates="integration", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Integration(id={self.id}, name={self.name}, type={self.integration_type})>"


class WebhookEvent(Base):
    """Registro de eventos de webhook enviados a integraciones externas."""

    __tablename__ = "webhook_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        index=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
        nullable=False,
    )

    integration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integrations.id"), nullable=False, index=True
    )
    event_type: Mapped[WebhookEventType] = mapped_column(
        SQLEnum(WebhookEventType), nullable=False
    )

    payload: Mapped[JsonValue] = mapped_column(sa.JSON, nullable=True)
    headers: Mapped[JsonValue] = mapped_column(sa.JSON, nullable=True)

    success: Mapped[bool | None] = mapped_column(Boolean, default=False, nullable=True)
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=utc_now_naive, nullable=True
    )
    retry_count: Mapped[int | None] = mapped_column(Integer, default=0, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=utc_now_naive, nullable=True
    )

    # Relationships
    integration = relationship("Integration", back_populates="webhook_events")

    __table_args__ = (
        Index("idx_webhook_events_integration_date", "integration_id", "triggered_at"),
        Index("idx_webhook_events_type", "event_type"),
    )

    def __repr__(self):
        return f"<WebhookEvent(id={self.id}, type={self.event_type}, success={self.success})>"
