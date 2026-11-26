"""Assignment receipts and external work share the assignment transaction."""

import hashlib
import json
import re
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.delivery import Delivery
from app.models.notification import (
    NotificationChannel as Channel,
    NotificationLog,
    NotificationTemplate,
    OmnichannelStatus as Status,
    utc_now_naive,
)
from app.models.order import Order
from app.models.user import User
from app.services.omnichannel_service import (
    OmnichannelNotificationService,
    render_template,
)

CODE = "nuevo_pedido_asignado"


async def enqueue_assignment_notice(
    db: AsyncSession,
    order: Order,
    delivery: Delivery,
    user: User,
    event_id: UUID,
    source: str,
) -> None:
    """Caller holds order/recipient locks and owns commit, rollback and replay."""
    now = utc_now_naive()
    title = "Pedido asignado"
    body = f"Se te asignó la orden #{order.external_id or str(order.id)[:8]}. Consulta su estado actual antes de iniciar el recorrido."
    context = {
        "entity_id": str(event_id),
        "assignment_event_id": str(event_id),
        "order_id": str(order.id),
        "delivery_id": str(delivery.id),
        "delivery_code": str(delivery.id)[:8].upper(),
        "rider_id": str(delivery.rider_id),
        "order_code": order.external_id or str(order.id)[:8],
        "source": source,
        "customer_name": order.customer_name,
        "pickup_address": order.pickup_address,
        "delivery_address": order.delivery_address,
    }
    plans: list[tuple[Channel, str, str, Status, str | None]] = [
        (Channel.IN_APP, title, body, Status.ENVIADO, None)
    ]
    if settings.NOTIFICATIONS_ENABLED and user.is_active:
        template = await db.scalar(
            select(NotificationTemplate)
            .where(
                NotificationTemplate.code == CODE,
                NotificationTemplate.is_active.is_(True),
            )
            .execution_options(populate_existing=True)
        )
        if template is not None:
            channels = await OmnichannelNotificationService(
                db, redis_client=False
            ).resolve_channels(user, template, CODE, channels=[template.channel])
            # Assignment is not a monetary receipt. Old templates must not turn
            # absent/unlabelled order totals into a rider's earnings.
            unsafe = bool(
                set(
                    re.findall(
                        r"\{\{\s*(\w+)\s*\}\}",
                        (template.body_template or "") + (template.subject or ""),
                    )
                )
                - context.keys()
            )
            for channel in dict.fromkeys(channels):
                if channel == Channel.IN_APP:
                    continue
                rendered_body = render_template(template.body_template, context)
                rendered_title = (
                    render_template(template.subject, context)
                    if template.subject
                    else title
                )
                unsafe = (
                    unsafe
                    or not rendered_body.strip()
                    or any(
                        marker in rendered_body + rendered_title
                        for marker in ("{{", "}}")
                    )
                )
                plans.append(
                    (
                        channel,
                        (
                            title
                            if unsafe or not template.subject
                            else render_template(template.subject, context)[:255]
                        ),
                        (
                            body
                            if unsafe
                            else render_template(template.body_template, context)
                        ),
                        Status.FALLIDO if unsafe else Status.PENDIENTE,
                        (
                            "Plantilla requiere revisión: variables no disponibles; no se envió"
                            if unsafe
                            else None
                        ),
                    )
                )
    for channel, subject, text, status, error in plans:
        notice_id = uuid4()
        db.add(
            NotificationLog(
                id=notice_id,
                user_id=user.id,
                delivery_id=delivery.id,
                template_code=CODE,
                channel=channel,
                status=status,
                title=subject,
                body=text,
                payload_json=json.dumps(
                    (
                        context
                        if channel == Channel.IN_APP
                        else {
                            **context,
                            "event": CODE,
                            "dispatch": {"version": 1, "state": "queued"},
                        }
                    ),
                    sort_keys=True,
                    ensure_ascii=False,
                ),
                dedupe_key=hashlib.sha256(
                    f"assignment:{event_id}:{channel.value}".encode()
                ).hexdigest(),
                created_at=now,
                sent_at=now if channel == Channel.IN_APP else None,
                next_retry_at=now if status == Status.PENDIENTE else None,
                error_message=error,
            )
        )
        if channel == Channel.IN_APP:
            from app.services.assignment_realtime import queue_assignment_nudge

            queue_assignment_nudge(db, notice_id)


async def recipient_still_valid(
    db: AsyncSession, log: NotificationLog, user: User, payload: dict[str, Any]
) -> bool:
    """Reject stale assignment events, including a rider reassigned away and back."""
    from app.models.audit_log import AuditLog, ActionType
    from app.models.order import OrderStatus
    from app.models.delivery import DeliveryStatus
    from app.models.rider import Rider
    from app.models.user import UserRole

    if user.role != UserRole.REPARTIDOR:
        return False
    assignment = await db.scalar(
        select(Delivery.id)
        .join(Order, Order.id == Delivery.order_id)
        .join(Rider, Rider.id == Delivery.rider_id)
        .where(
            Delivery.id == log.delivery_id,
            Order.id == UUID(payload["order_id"]),
            Delivery.rider_id == UUID(payload["rider_id"]),
            Rider.user_id == log.user_id,
            Order.assigned_rider_id == Delivery.rider_id,
            Order.status.in_(
                (OrderStatus.ASIGNADO, OrderStatus.RECOLECTADO, OrderStatus.EN_RUTA)
            ),
            Delivery.status.not_in(
                (
                    DeliveryStatus.COMPLETADA,
                    DeliveryStatus.FALLIDA,
                    DeliveryStatus.CANCELADA,
                )
            ),
        )
    )
    if assignment is None:
        return False
    latest = await db.scalar(
        select(AuditLog.id)
        .where(
            AuditLog.resource_type == "ORDER",
            AuditLog.resource_id == payload["order_id"],
            AuditLog.action_type.in_((ActionType.ASSIGN, ActionType.REASSIGN)),
            AuditLog.success.is_(True),
        )
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(1)
    )
    return str(latest) == payload["assignment_event_id"]
