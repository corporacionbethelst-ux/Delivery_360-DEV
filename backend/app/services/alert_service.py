"""Operational legacy inbox alerts and bounded, durable pre-deadline SLA warnings."""

from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.exceptions import NotFoundError, ValidationError
from app.models.notification import (
    Notification,
    NotificationType,
    NotificationPriority,
    Alert,
)
from app.models.user import User, UserRole
from app.models.rider import Rider
from app.services.notification_values import notification_text, notification_recipients
from app.services.sla_monitor import lock_sla_deliveries


class AlertService:
    async def _recipients(
        self, db: AsyncSession, values: list[UUID | str] | None
    ) -> list[UUID]:
        if values is None:
            ids = list(
                (
                    await db.scalars(
                        select(User.id)
                        .where(
                            User.is_active.is_(True),
                            User.role.in_((UserRole.SUPERADMIN, UserRole.GERENTE)),
                        )
                        .order_by(User.id)
                        .limit(201)
                    )
                ).all()
            )
            if len(ids) > 200:
                raise ValidationError("Demasiados destinatarios; particione el lote")
            return ids
        ids = notification_recipients(values)
        available = set(
            (
                await db.scalars(
                    select(User.id).where(User.id.in_(ids), User.is_active.is_(True))
                )
            ).all()
        )
        if set(ids) != available:
            raise NotFoundError("Uno o más destinatarios no están disponibles")
        return ids

    @staticmethod
    def _severity(value: str) -> str:
        value = notification_text(value, "Severidad", 20).lower()
        value = {
            "baja": "low",
            "normal": "medium",
            "media": "medium",
            "alta": "high",
            "critica": "critical",
            "crítica": "critical",
        }.get(value, value)
        if value not in ("low", "medium", "high", "critical"):
            raise ValidationError("Severidad inválida")
        return value

    @staticmethod
    def _notifications(
        ids: list[UUID],
        alert_type: str,
        severity: str,
        title: str,
        message: str,
        related_id: str | None,
        related_type: str | None,
        *,
        extra: dict[str, str] | None = None,
    ) -> list[Notification]:
        data = {"alert_type": alert_type, "severity": severity, **(extra or {})}
        if related_type in ("order", "rider") and related_id is not None:
            data["related_" + related_type + "_id"] = related_id
        priority = {
            "low": NotificationPriority.BAJA,
            "medium": NotificationPriority.NORMAL,
            "high": NotificationPriority.ALTA,
            "critical": NotificationPriority.CRITICA,
        }[severity]
        return [
            Notification(
                user_id=uid,
                notification_type=NotificationType.ALERTA_OPERACIONAL,
                priority=priority,
                title=title,
                message=message,
                data=dict(data),
                related_id=related_id,
                related_type=related_type,
                channels="in_app",
                is_sent=False,
            )
            for uid in ids
        ]

    async def create_alert(
        self,
        db: AsyncSession,
        alert_type: str,
        severity: str,
        title: str,
        message: str,
        related_entity_id: object = None,
        related_entity_type: str | None = None,
        recipient_user_ids: list[UUID | str] | None = None,
    ) -> Notification:
        kind = notification_text(alert_type, "Tipo de alerta", 50)
        severity = self._severity(severity)
        title = notification_text(title, "Título", 255)
        message = notification_text(message, "Mensaje", 4000)
        related_id = None
        if related_entity_id is not None:
            if isinstance(related_entity_id, bool) or not isinstance(
                related_entity_id, (str, int, UUID)
            ):
                raise ValidationError("Referencia de alerta inválida")
            related_id = notification_text(str(related_entity_id), "Referencia", 100)
        related_type = (
            notification_text(related_entity_type, "Tipo de referencia", 50).lower()
            if related_entity_type is not None
            else None
        )
        if recipient_user_ids is not None:
            notification_recipients(recipient_user_ids)  # validate before database I/O
        try:
            ids = await self._recipients(db, recipient_user_ids)
            if not ids:
                raise NotFoundError("No hay destinatarios activos para la alerta")
            notifications = self._notifications(
                ids, kind, severity, title, message, related_id, related_type
            )
            db.add_all(notifications)
            await db.flush()
            await db.commit()
            return notifications[0]
        except BaseException:
            await db.rollback()
            raise

    async def check_sla_alerts(
        self,
        db: AsyncSession,
        threshold_minutes: int = 5,
        *,
        now: datetime | None = None,
        delivery_id: UUID | None = None,
        batch_size: int = 100,
    ) -> list[Notification]:
        now = now if now is not None else datetime.utcnow()
        try:
            deliveries = await lock_sla_deliveries(
                db,
                now,
                warning_minutes=threshold_minutes,
                delivery_id=delivery_id,
                batch_size=batch_size,
            )
            managers = await self._recipients(db, None)
            notifications: list[Notification] = []
            for delivery in deliveries:
                owner = await db.scalar(
                    select(User.id)
                    .join(Rider, Rider.user_id == User.id)
                    .where(Rider.id == delivery.rider_id, User.is_active.is_(True))
                )
                recipients = sorted(
                    set(managers) | ({owner} if owner is not None else set())
                )
                alert_id = uuid4()
                db.add(
                    Alert(
                        id=alert_id,
                        alert_type="SLA_WARNING",
                        severity="HIGH",
                        title="Entrega próxima a vencer SLA",
                        description="La entrega activa está dentro del intervalo de aviso previo.",
                        delivery_id=delivery.id,
                        order_id=delivery.order_id,
                        rider_id=delivery.rider_id,
                        status="OPEN",
                    )
                )
                if settings.NOTIFICATIONS_ENABLED:
                    from app.models.notification import (
                        NotificationPreference,
                        NotificationChannel,
                    )

                    muted = set(
                        (
                            await db.scalars(
                                select(NotificationPreference.user_id).where(
                                    NotificationPreference.user_id.in_(recipients),
                                    NotificationPreference.event_code == "sla_warning",
                                    NotificationPreference.channel
                                    == NotificationChannel.IN_APP,
                                    NotificationPreference.enabled.is_(False),
                                )
                            )
                        ).all()
                    )
                    rows = self._notifications(
                        [uid for uid in recipients if uid not in muted],
                        "sla_warning",
                        "high",
                        "Entrega próxima a vencer SLA",
                        f"La entrega {delivery.id} vence dentro de los próximos {threshold_minutes} minutos",
                        str(delivery.id),
                        "delivery",
                        extra={
                            "operational_alert_id": str(alert_id),
                            "related_order_id": str(delivery.order_id),
                            "related_rider_id": str(delivery.rider_id),
                        },
                    )
                    notifications.extend(rows)
            db.add_all(notifications)
            await db.flush()
            await db.commit()
            return notifications
        except BaseException:
            await db.rollback()
            raise


alert_service = AlertService()
