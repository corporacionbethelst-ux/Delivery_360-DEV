"""Bounded SLA selection with the same parent-first locks as delivery mutations."""

from datetime import datetime, timedelta
from uuid import UUID
from sqlalchemy import exists, select, cast, String, or_, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.delivery import Delivery, DeliveryStatus
from app.models.order import Order
from app.models.notification import Alert

ACTIVE_SLA_STATES = (
    DeliveryStatus.INICIADA,
    DeliveryStatus.EN_PICKUP,
    DeliveryStatus.EN_ROUTE,
    DeliveryStatus.EN_DESTINO,
)


async def lock_sla_deliveries(
    db: AsyncSession,
    now: datetime,
    *,
    batch_size: int = 100,
    delivery_id: UUID | None = None,
    warning_minutes: int | None = None,
) -> list[Delivery]:
    """Skip busy orders before touching children; recheck eligibility after locks.

    The caller owns commit/rollback, including the durable alert receipt. A batch
    locks parents in UUID order, then their deliveries. No pending cancellation
    can acquire an order lock while this monitor holds only its child lock.
    """
    if not isinstance(now, datetime) or now.tzinfo is not None:
        raise ValueError("Expected UTC naive clock")
    if type(batch_size) is not int or not 1 <= batch_size <= 100:
        raise ValueError("Invalid batch size")
    if delivery_id is not None and not isinstance(delivery_id, UUID):
        raise ValueError("Invalid delivery ID")
    if warning_minutes is not None and (
        type(warning_minutes) is not int or not 1 <= warning_minutes <= 60
    ):
        raise ValueError("Invalid SLA warning window")
    kind = "SLA_BREACH" if warning_minutes is None else "SLA_WARNING"
    deadline = Delivery.started_at + Delivery.sla_expected_minutes * text(
        "INTERVAL '1 minute'"
    )
    previous = exists(
        select(Alert.id).where(
            Alert.delivery_id == Delivery.id, Alert.alert_type == kind
        )
    )
    conditions = [
        Delivery.status.in_(ACTIVE_SLA_STATES),
        Delivery.started_at.is_not(None),
        Delivery.sla_expected_minutes > 0,
        or_(Order.status.is_(None), cast(Order.status, String) != "CANCELADO"),
        ~previous,
    ]
    if warning_minutes is None:
        conditions.append(deadline < now)
    else:
        conditions.extend(
            (deadline > now, deadline <= now + timedelta(minutes=warning_minutes))
        )
    if delivery_id is not None:
        conditions.append(Delivery.id == delivery_id)
    candidates = (
        await db.execute(
            select(Order.id.label("order_id"), Delivery.id.label("delivery_id"))
            .join(Delivery, Delivery.order_id == Order.id)
            .where(*conditions)
            .order_by(Order.id, Delivery.id)
            .limit(batch_size)
            .with_for_update(of=Order, skip_locked=True)
        )
    ).all()
    deliveries = []
    for candidate in candidates:
        delivery = await db.scalar(
            select(Delivery)
            .join(Order, Order.id == Delivery.order_id)
            .where(
                Delivery.id == candidate.delivery_id,
                Delivery.order_id == candidate.order_id,
                *conditions,
            )
            .with_for_update(of=Delivery, skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if delivery is not None:
            deliveries.append(delivery)
    return deliveries
