"""Operational delivery receipts, committed with state and ledger changes."""

import hashlib
import json
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.serialization import utc_isoformat
from app.models.delivery import Delivery, DeliveryStatus
from app.models.notification import (
    NotificationChannel,
    NotificationLog,
    OmnichannelStatus,
    utc_now_naive,
)
from app.models.order import Order, OrderStatus
from app.models.rider import Rider
from app.services.assignment_realtime import queue_inbox_nudge

CODE = "entrega_completada"


async def enqueue_completion_notice(
    db: AsyncSession, order: Order | None, delivery: Delivery, *, source: str
) -> UUID | None:
    """Caller holds transition locks and owns commit/rollback. No provider I/O."""
    if order is None or delivery.rider_id is None:
        return None
    if (
        delivery.order_id != order.id
        or order.status != OrderStatus.ENTREGADO
        or delivery.status != DeliveryStatus.COMPLETADA
    ):
        raise HTTPException(
            409, "El comprobante requiere un cierre operativo coherente"
        )
    return await _enqueue_notice(
        db,
        order,
        delivery,
        delivery.rider_id,
        code=CODE,
        title="Entrega registrada",
        source=source,
        body=f"Se registró la entrega de la orden #{order.external_id or str(order.id)[:8]}. Consulta su detalle para revisar el cierre.",
    )


async def enqueue_failure_notice(
    db: AsyncSession, order: Order | None, delivery: Delivery, *, source: str
) -> UUID | None:
    if order is None or delivery.rider_id is None:
        return None
    if (
        delivery.order_id != order.id
        or order.status != OrderStatus.FALLIDO
        or delivery.status != DeliveryStatus.FALLIDA
        or order.assigned_rider_id != delivery.rider_id
    ):
        raise HTTPException(409, "El comprobante requiere un fallo operativo coherente")
    return await _enqueue_notice(
        db,
        order,
        delivery,
        delivery.rider_id,
        code="entrega_fallida",
        title="Intento fallido registrado",
        source=source,
        body=f"Se registró un intento fallido para la orden #{order.external_id or str(order.id)[:8]}. Consulta el detalle de la entrega para revisar el motivo.",
    )


async def enqueue_cancellation_notice(
    db: AsyncSession, order: Order, delivery: Delivery | None
) -> UUID | None:
    if order.status != OrderStatus.CANCELADO or (
        delivery is not None
        and (
            delivery.order_id != order.id
            or delivery.status != DeliveryStatus.CANCELADA
            or delivery.rider_id != order.assigned_rider_id
        )
    ):
        raise HTTPException(409, "El comprobante requiere una cancelación coherente")
    rider_id = delivery.rider_id if delivery is not None else order.assigned_rider_id
    if rider_id is None:
        return None
    return await _enqueue_notice(
        db,
        order,
        delivery,
        rider_id,
        code="orden_cancelada",
        title="Orden cancelada",
        source="order_cancellation",
        body=f"Se canceló la orden #{order.external_id or str(order.id)[:8]}. Consulta su detalle para revisar la cancelación.",
    )


async def _enqueue_notice(
    db: AsyncSession,
    order: Order,
    delivery: Delivery | None,
    rider_id: UUID,
    *,
    code: str,
    title: str,
    body: str,
    source: str,
) -> UUID:
    """Never commits, sends external messages or recreates historical events."""
    recipient = await db.scalar(select(Rider.user_id).where(Rider.id == rider_id))
    if recipient is None:
        raise HTTPException(409, "El destinatario del comprobante requiere revisión")
    delivery_id = delivery.id if delivery is not None else None
    key = hashlib.sha256(f"order:{order.id}:{code}:IN_APP".encode()).hexdigest()
    existing = next(
        (
            row
            for row in db.new
            if isinstance(row, NotificationLog) and row.dedupe_key == key
        ),
        None,
    )
    if existing is None:
        existing = await db.scalar(
            select(NotificationLog).where(NotificationLog.dedupe_key == key)
        )
    if existing is not None:
        if (
            existing.user_id != recipient
            or existing.delivery_id != delivery_id
            or existing.channel != NotificationChannel.IN_APP
            or existing.template_code != code
            or existing.payout_id is not None
        ):
            raise HTTPException(409, "El comprobante existente requiere revisión")
        return existing.id
    if delivery is not None and delivery in db.new:
        await db.flush([delivery])
    notice_id = uuid4()
    now = utc_now_naive()
    payload = {
        "order_id": str(order.id),
        "delivery_id": str(delivery_id) if delivery_id is not None else None,
        "event": code,
        "source": source,
    }
    if code == CODE:
        payload["completed_at"] = (
            delivery.completed_at.isoformat()
            if delivery is not None and delivery.completed_at
            else None
        )
    else:
        payload["recorded_at"] = utc_isoformat(now)
    db.add(
        NotificationLog(
            id=notice_id,
            user_id=recipient,
            delivery_id=delivery_id,
            template_code=code,
            channel=NotificationChannel.IN_APP,
            status=OmnichannelStatus.ENVIADO,
            dedupe_key=key,
            title=title,
            body=body,
            payload_json=json.dumps(payload, sort_keys=True),
            created_at=now,
            sent_at=now,
        )
    )
    queue_inbox_nudge(db, notice_id)
    return notice_id
