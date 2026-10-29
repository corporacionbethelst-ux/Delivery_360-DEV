"""Notification and Alert models."""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from sqlalchemy import (
    Column,
    String,
    Boolean,
    DateTime,
    Enum as SQLEnum,
    Text,
    ForeignKey,
    Index,
    Integer,
)


def _pg_enum(python_enum, name):
    """FIX CRÍTICO FASE 10 (3ra auditoría): sa.Enum(..., create_type=False)
    pierde el flag al adaptarse a postgresql.ENUM en SQLAlchemy 2.0.x y los
    create_all/residuals re-emiten CREATE TYPE -> DuplicateObjectError.
    Usar postgresql.ENUM nativo del dialecto con create_type=False."""
    from sqlalchemy.dialects.postgresql import ENUM as PGEnum

    return PGEnum(
        python_enum,
        values_callable=lambda e: [m.value for m in e],
        name=name,
        create_type=False,
    )


from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
import enum
import sqlalchemy as sa

from app.core.database import Base


def utc_now_naive():
    """Devuelve la hora actual en UTC sin zona horaria (naive)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class NotificationType(str, enum.Enum):
    """Tipos de notificaciones soportadas por Delivery360."""

    ALERTA_OPERACIONAL = "ALERTA_OPERACIONAL"
    ASIGNACION_PEDIDO = "ASIGNACION_PEDIDO"
    ENTREGA_COMPLETADA = "ENTREGA_COMPLETADA"
    ESTADO_ENTREGA = "ESTADO_ENTREGA"
    RECORDATORIO = "RECORDATORIO"
    LOGRO = "LOGRO"
    SISTEMA = "SISTEMA"
    URGENTE = "URGENTE"
    RETIRO_SOLICITADO = "RETIRO_SOLICITADO"
    RETIRO_APROBADO = "RETIRO_APROBADO"
    RETIRO_RECHAZADO = "RETIRO_RECHAZADO"
    SLA_WARNING = "SLA_WARNING"
    PAGO_RECIBIDO = "PAGO_RECIBIDO"


class NotificationPriority(str, enum.Enum):
    BAJA = "BAJA"
    NORMAL = "NORMAL"
    ALTA = "ALTA"
    CRITICA = "CRITICA"


class NotificationStatus(str, enum.Enum):
    """Estado de notificación (convención Fase 7: nombres en ESPAÑOL).

    Valores explícitos conservados en inglés por compatibilidad hacia atrás
    con la columna `notifications.status` existente (enum PG histórico) y con
    los llamadores previos (NotificationStatus.PENDING/.SENT/.FAILED).
    Se añaden alias equivalentes en español para código nuevo de Fase 9.
    """

    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    READ = "READ"
    # Alias en español (misma identidad de miembro → mismo valor PG)
    PENDIENTE = PENDING
    ENVIADO = SENT
    FALLIDO = FAILED
    LEIDO = READ


class Notification(Base):
    """Tabla de notificaciones para usuarios y riders."""

    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, default=uuid.uuid4)

    # Destinatarios (puede ser usuario, rider o ambos)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    rider_id = Column(UUID(as_uuid=True), ForeignKey("riders.id"), index=True)

    # Contenido
    notification_type: Any = Column(SQLEnum(NotificationType), nullable=False)
    priority: Any = Column(
        SQLEnum(NotificationPriority), default=NotificationPriority.NORMAL
    )

    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    data = Column(sa.JSON)  # Datos extra para la UI

    # Canales de envío
    channels = Column(String(100))  # Ej: "email,push,sms"
    sent_channels = Column(String(100))

    # Estado
    is_read = Column(Boolean, default=False)
    read_at = Column(DateTime)
    is_sent = Column(Boolean, default=False)
    sent_at = Column(DateTime)
    failed_channels = Column(String(100))
    error_message = Column(Text)

    # Acción asociada
    action_url = Column(String(500))
    action_type = Column(String(50))

    # Relación genérica a otros recursos
    related_type = Column(String(50))
    related_id = Column(String(100))

    # Programación
    scheduled_for = Column(DateTime)
    expires_at = Column(DateTime)

    created_at = Column(DateTime, default=utc_now_naive, index=True)

    # Relaciones
    user = relationship("User", back_populates="notifications")
    rider = relationship("Rider", back_populates="notifications")

    __table_args__ = (
        Index("idx_notifications_user_date", "user_id", "created_at"),
        Index("idx_notifications_rider_date", "rider_id", "created_at"),
    )

    def __repr__(self):
        return f"<Notification(id={self.id}, type={self.notification_type})>"


class Alert(Base):
    """Tabla de alertas operativas del sistema."""

    __tablename__ = "alerts"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        index=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    )

    alert_type = Column(String(50), nullable=False)
    severity = Column(String(20))  # LOW, MEDIUM, HIGH, CRITICAL
    title = Column(String(255), nullable=False)
    description = Column(Text)

    # Entidades relacionadas
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), index=True)
    delivery_id = Column(UUID(as_uuid=True), ForeignKey("deliveries.id"), index=True)
    rider_id = Column(UUID(as_uuid=True), ForeignKey("riders.id"), index=True)

    # Estado de resolución
    status = Column(String(20), default="OPEN")  # OPEN, ACKNOWLEDGED, RESOLVED

    acknowledged_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    acknowledged_at = Column(DateTime)

    resolved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    resolved_at = Column(DateTime)
    resolution_notes = Column(Text)

    auto_resolve_at = Column(DateTime)
    auto_resolved = Column(Boolean, default=False)

    created_at = Column(DateTime, default=utc_now_naive, index=True)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)

    # Relaciones
    order = relationship("Order")
    delivery = relationship("Delivery")
    rider = relationship("Rider")
    user_ack = relationship("User", foreign_keys=[acknowledged_by])
    user_res = relationship("User", foreign_keys=[resolved_by])

    def __repr__(self):
        return f"<Alert(id={self.id}, type={self.alert_type}, status={self.status})>"


# ═══════════════════════════════════════════════════════════════════
# FASE 9 — Notificaciones & Comunicación Omnicanal
# Tablas nuevas (notification_templates, notification_logs,
# user_device_tokens, notification_preferences). La tabla legacy
# `notifications` NO se modifica (decision documentada en migración
# 20260915_fase9).
# ═══════════════════════════════════════════════════════════════════


class NotificationChannel(str, enum.Enum):
    """Canales de entrega omnicanal (Fase 9)."""

    PUSH = "PUSH"
    SMS = "SMS"
    EMAIL = "EMAIL"
    IN_APP = "IN_APP"


class OmnichannelStatus(str, enum.Enum):
    """Estados del log omnicanal — convención Fase 7: nombres EN ESPAÑOL.

    Nombre de clase distinto a NotificationStatus (legacy) para no romper
    importaciones existentes; valores alfanuméricos limpios para PG.
    """

    PENDIENTE = "PENDIENTE"
    ENVIADO = "ENVIADO"
    ENTREGADO = "ENTREGADO"
    FALLIDO = "FALLIDO"
    LEIDO = "LEIDO"


class NotificationTemplate(Base):
    """Plantilla renderizable de notificación (código estable + canal base)."""

    __tablename__ = "notification_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )  # ej 'payout_aprobado'
    channel: Mapped[NotificationChannel] = mapped_column(
        _pg_enum(NotificationChannel, "notificationchannel"), nullable=False
    )
    subject: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )  # null para push/sms
    body_template: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # sintaxis {{variable}}
    language: Mapped[str] = mapped_column(String(5), nullable=False, default="es")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive, onupdate=utc_now_naive
    )

    def __repr__(self):
        return f"<NotificationTemplate(code={self.code}, channel={self.channel})>"


class NotificationLog(Base):
    """Bitácora omnicanal de envíos con reintentos y dedupe."""

    __tablename__ = "notification_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    template_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    delivery_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("deliveries.id"), nullable=True
    )
    payout_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payouts.id"), nullable=True
    )
    channel: Mapped[NotificationChannel] = mapped_column(
        _pg_enum(NotificationChannel, "notificationchannel"), nullable=False
    )
    status: Mapped[OmnichannelStatus] = mapped_column(
        _pg_enum(OmnichannelStatus, "notificationstatus_fase9"),
        nullable=False,
        default=OmnichannelStatus.PENDIENTE,
    )
    payload_json: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # datos renderizados
    provider_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(
        String(120), unique=True, nullable=True
    )  # evita reenvío <5min
    title: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # para campana IN_APP
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive, index=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_notiflogs_user_created", "user_id", sa.text("created_at DESC")),
        Index("idx_notiflogs_status_retry", "status", "next_retry_at"),
    )

    def __repr__(self):
        return f"<NotificationLog(id={self.id}, template={self.template_code}, status={self.status})>"


class UserDeviceToken(Base):
    """Tokens FCM/APNs por usuario con auto-desactivación por fallos."""

    __tablename__ = "user_device_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    device_token: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    platform: Mapped[str] = mapped_column(
        String(10), nullable=False, default="web"
    )  # 'android'|'ios'|'web'
    failure_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )  # auto-disable tras 3
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive
    )

    def __repr__(self):
        return f"<UserDeviceToken(user={self.user_id}, platform={self.platform})>"


class NotificationPreference(Base):
    """Preferencia granular evento×canal por usuario."""

    __tablename__ = "notification_preferences"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    event_code: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # ej 'payout_aprobado'
    channel: Mapped[NotificationChannel] = mapped_column(
        _pg_enum(NotificationChannel, "notificationchannel"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive, onupdate=utc_now_naive
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "user_id", "event_code", "channel", name="uq_notifpref_user_event_channel"
        ),
    )

    def __repr__(self):
        return f"<NotificationPreference(user={self.user_id}, {self.event_code}/{self.channel}={self.enabled})>"
