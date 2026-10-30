"""Persist legacy inbox records. External delivery belongs to the omnichannel service.

`channels` records a request, never proof of provider acceptance. This adapter
neither sends nor marks an unimplemented transport as successfully sent.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import NotFoundError, ValidationError
from app.models.notification import Notification, NotificationType
from app.models.rider import Rider
from app.models.user import User
from app.services.notification_values import (
    notification_uuid,
    notification_text,
    notification_payload,
)


class NotificationService:
    """Compatibility inbox API; commit=False keeps the caller's unit of work."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_notification(
        self,
        user_id: UUID | str,
        notification_type: NotificationType | str,
        title: str,
        message: str,
        data: dict[str, Any] | None = None,
        channel: str = "push",
        *,
        commit: bool = True,
    ) -> Notification:
        uid = notification_uuid(user_id, "Destinatario")
        try:
            kind = NotificationType(notification_type)
        except (ValueError, TypeError) as exc:
            raise ValidationError("Tipo de notificación inválido") from exc
        title = notification_text(title, "Título", 255)
        message = notification_text(message, "Mensaje", 4000)
        payload = notification_payload(data)
        if not isinstance(channel, str) or channel.strip().lower() not in (
            "in_app",
            "push",
            "email",
            "sms",
        ):
            raise ValidationError("Canal de notificación inválido")
        if type(commit) is not bool:
            raise ValidationError("Opción transaccional inválida")
        try:
            recipient = await self.db.scalar(
                select(User.id).where(User.id == uid, User.is_active.is_(True))
            )
            if recipient is None:
                raise NotFoundError("Destinatario no disponible")
            notification = Notification(
                user_id=uid,
                notification_type=kind,
                title=title,
                message=message,
                channels=channel.strip().lower(),
                data=payload,
                is_sent=False,
            )
            self.db.add(notification)
            await self.db.flush()
            if commit:
                await self.db.commit()
            return notification
        except BaseException:
            if commit:
                await self.db.rollback()
            raise

    async def _rider_user(self, rider_id: UUID | str) -> UUID:
        rid = notification_uuid(rider_id, "Repartidor")
        uid = await self.db.scalar(
            select(Rider.user_id)
            .join(User, User.id == Rider.user_id)
            .where(Rider.id == rid, User.is_active.is_(True))
        )
        if uid is None:
            raise NotFoundError("Destinatario del repartidor no disponible")
        return uid

    async def notify_order_assigned(self, rider_id: UUID | str, order_id: UUID | str):
        oid = notification_uuid(order_id, "Orden")
        return await self.create_notification(
            user_id=await self._rider_user(rider_id),
            notification_type=NotificationType.ASIGNACION_PEDIDO,
            title="Nuevo Pedido Asignado",
            message=f"Se te ha asignado el pedido #{oid}",
            data={"order_id": str(oid)},
            channel="push",
        )

    async def notify_sla_warning(
        self, rider_id: UUID | str, delivery_id: UUID | str, minutes_remaining: int
    ):
        did = notification_uuid(delivery_id, "Entrega")
        if type(minutes_remaining) is not int or not 0 <= minutes_remaining <= 1440:
            raise ValidationError("Minutos restantes inválidos")
        return await self.create_notification(
            user_id=await self._rider_user(rider_id),
            notification_type=NotificationType.SLA_WARNING,
            title="⚠️ Riesgo de SLA",
            message=f"Te quedan {minutes_remaining} minutos para completar la entrega #{did}",
            data={"delivery_id": str(did)},
            channel="push",
        )

    async def notify_payment_received(self, rider_id: UUID | str, amount: float):
        try:
            if isinstance(amount, bool):
                raise InvalidOperation
            value = Decimal(str(amount))
            if (
                not value.is_finite()
                or value <= 0
                or value > Decimal("99999999.99")
                or value != value.quantize(Decimal("0.01"))
            ):
                raise InvalidOperation
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValidationError("Importe de aviso de pago inválido") from exc
        return await self.create_notification(
            user_id=await self._rider_user(rider_id),
            notification_type=NotificationType.PAGO_RECIBIDO,
            title="💰 Pago Recibido",
            message=f"Se registró un pago por {value:.2f}",
            data={"amount": str(value)},
            channel="push",
        )

    async def get_user_notifications(
        self, user_id: UUID | str, limit: int = 50, unread_only: bool = False
    ) -> list[Notification]:
        uid = notification_uuid(user_id, "Destinatario")
        if (
            type(limit) is not int
            or not 1 <= limit <= 200
            or type(unread_only) is not bool
        ):
            raise ValidationError("Filtro de notificaciones inválido")
        query = select(Notification).where(Notification.user_id == uid)
        if unread_only:
            query = query.where(Notification.is_read.is_(False))
        return list(
            (
                await self.db.scalars(
                    query.order_by(
                        Notification.created_at.desc(), Notification.id
                    ).limit(limit)
                )
            ).all()
        )

    async def mark_as_read(self, notification_id: UUID | str, user_id: UUID | str):
        nid = notification_uuid(notification_id, "Notificación")
        uid = notification_uuid(user_id, "Destinatario")
        try:
            notification = await self.db.scalar(
                select(Notification)
                .where(Notification.id == nid, Notification.user_id == uid)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if notification is None:
                raise NotFoundError("Notificación no encontrada")
            notification.is_read = True
            if notification.read_at is None:
                notification.read_at = datetime.utcnow()
            await self.db.commit()
        except BaseException:
            await self.db.rollback()
            raise
