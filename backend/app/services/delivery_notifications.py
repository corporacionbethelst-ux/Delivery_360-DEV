"""Operational completion receipt, committed with delivery and ledger state."""

import hashlib
import json
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    recipient = await db.scalar(
        select(Rider.user_id).where(Rider.id == delivery.rider_id)
    )
    if recipient is None:
        raise HTTPException(
            409, "El destinatario del comprobante de entrega requiere revisión"
        )
    key = hashlib.sha256(f"order:{order.id}:{CODE}:IN_APP".encode()).hexdigest()
    # autoflush=False: a second call in this transaction must see pending rows.
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
            or existing.delivery_id != delivery.id
            or existing.channel != NotificationChannel.IN_APP
            or existing.template_code != CODE
            or existing.payout_id is not None
        ):
            raise HTTPException(
                409, "El comprobante de entrega existente requiere revisión"
            )
        return existing.id
    if delivery in db.new:
        await db.flush([delivery])
    notice_id = uuid4()
    now = utc_now_naive()
    db.add(
        NotificationLog(
            id=notice_id,
            user_id=recipient,
            delivery_id=delivery.id,
            template_code=CODE,
            channel=NotificationChannel.IN_APP,
            status=OmnichannelStatus.ENVIADO,
            dedupe_key=key,
            title="Entrega registrada",
            body=f"Se registró la entrega de la orden #{order.external_id or str(order.id)[:8]}. Consulta su detalle para revisar el cierre.",
            payload_json=json.dumps(
                {
                    "order_id": str(order.id),
                    "delivery_id": str(delivery.id),
                    "event": CODE,
                    "source": source,
                    "completed_at": (
                        delivery.completed_at.isoformat()
                        if delivery.completed_at
                        else None
                    ),
                },
                sort_keys=True,
            ),
            created_at=now,
            sent_at=now,
        )
    )
    queue_inbox_nudge(db, notice_id)
    return notice_id
