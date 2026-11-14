"""Bind an immutable quotation to the server's exact order price, never to a client amount."""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.json_types import json_value
from app.models.audit_log import AuditLog, ActionType
from app.models.currency import BcvRate
from app.models.order import Order, OrderStatus
from app.models.order_currency_quote import OrderCurrencyQuote
from app.models.user import User, UserRole
from app.services import bcv_currency as currency, order_pricing


async def order_row(db: AsyncSession, identity: UUID, *, lock=False) -> Order:
    query = (
        select(Order)
        .where(Order.id == identity)
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update(read=lock == "read")
    row = await db.scalar(query)
    if row is None:
        raise HTTPException(404, "Orden no encontrada")
    return row


async def receipt_view(db: AsyncSession, row: OrderCurrencyQuote) -> dict:
    rate = await db.get(BcvRate, row.rate_id)
    if rate is None:
        raise HTTPException(409, "La referencia del comprobante requiere revisión")
    return {
        "id": str(row.id),
        "request_key": str(row.request_key),
        "order_id": str(row.order_id),
        "order_external_id": row.order_external_id,
        "pricing": row.pricing_snapshot,
        "amount_usd": format(row.amount_usd, ".2f"),
        "amount_ves": format(row.amount_ves, ".2f"),
        "rate": currency.rate_view(rate),
        "created_at": row.created_at.isoformat() + "Z",
        "created_by": str(row.created_by),
        "country": "VE",
        "base_currency": "USD",
        "quote_currency": "VES",
        "scope": "order_quotation_only",
        "quotation_only": True,
        "payment_confirmed": False,
    }


async def context_view(db: AsyncSession, actor: User, identity: UUID) -> dict:
    order = await order_row(db, identity, lock="read")
    if order.status is None:
        raise HTTPException(409, "El estado de la orden requiere revisión")
    day = currency.current_day()
    rate = await currency.latest_for(db, day)
    query = select(OrderCurrencyQuote).where(OrderCurrencyQuote.order_id == identity)
    if actor.role == UserRole.OPERADOR:
        query = query.where(OrderCurrencyQuote.created_by == actor.id)
    rows = list(
        (
            await db.scalars(
                query.order_by(
                    OrderCurrencyQuote.created_at.desc(), OrderCurrencyQuote.id.desc()
                ).limit(11)
            )
        ).all()
    )
    return {
        "order_id": str(order.id),
        "order_external_id": order.external_id,
        "currency": order.currency_code,
        "status": order.status.value,
        "pricing": order_pricing.view(order),
        "today": day.isoformat(),
        "current_rate": currency.rate_view(rate) if rate else None,
        "receipts": [await receipt_view(db, row) for row in rows[:10]],
        "has_more": len(rows) > 10,
        "scope": "order_quotation_only",
    }


async def create(db: AsyncSession, actor: User, identity: UUID, body) -> dict:
    # Capture credentials before any wait can refresh identity-map objects.
    actor_id, version = actor.id, actor.token_version
    await currency.advisory(db, "bcv:order-quote:" + str(body.request_key))
    prior = await db.scalar(
        select(OrderCurrencyQuote).where(
            OrderCurrencyQuote.request_key == body.request_key
        )
    )
    if prior is not None:
        if (
            prior.created_by,
            prior.order_id,
            prior.rate_id,
            prior.pricing_revision,
        ) != (actor_id, identity, body.rate_id, body.expected_pricing_revision):
            raise HTTPException(
                409, "La clave identifica otro comprobante de cotización"
            )
        await currency.actor_lock(
            db, actor, currency.QUOTE_ROLES, expected_version=version
        )
        return await receipt_view(db, prior)
    order = await order_row(db, identity, lock=True)
    if order.currency_code != "USD" or order.pricing_version != 1:
        raise HTTPException(
            409, "Confirma primero un precio exacto en USD para esta orden"
        )
    if order.status is None or order.status in (
        OrderStatus.CANCELADO,
        OrderStatus.FALLIDO,
    ):
        raise HTTPException(
            409, "La orden cancelada o fallida no admite una nueva cotización"
        )
    if order.pricing_revision != body.expected_pricing_revision:
        raise HTTPException(
            412, "El precio de la orden cambió; recarga antes de cotizar"
        )
    pack = order_pricing.view(order)
    assert pack is not None
    usd = order_pricing.amount(order, "total")
    await currency.actor_lock(db, actor, currency.QUOTE_ROLES, expected_version=version)
    day = currency.current_day()
    await currency.advisory(db, "bcv:day:" + day.isoformat())
    if currency.current_day() != day:
        raise HTTPException(409, "Cambió el día de operación; recarga")
    rate = await currency.latest_for(db, day)
    if rate is None:
        raise HTTPException(409, "Falta una referencia BCV registrada para hoy")
    if rate.id != body.rate_id:
        raise HTTPException(412, "La tasa BCV cambió; recarga antes de cotizar")
    row = OrderCurrencyQuote(
        request_key=body.request_key,
        order_id=order.id,
        order_external_id=order.external_id,
        pricing_revision=pack["revision"],
        pricing_snapshot=json_value(pack),
        rate_id=rate.id,
        amount_usd=usd,
        amount_ves=currency.converted_amount(usd, rate.ves_per_usd),
        created_by=actor_id,
        created_at=currency.utc_now().replace(tzinfo=None),
    )
    db.add(row)
    await db.flush()
    result = await receipt_view(db, row)
    db.add(
        AuditLog(
            user_id=actor_id,
            user_email=actor.email,
            user_role=actor.role.value if actor.role else None,
            action_type=ActionType.CREATE,
            resource_type="ORDER_USD_VES_QUOTE",
            resource_id=str(row.id),
            description="Cotización de orden conservada; no confirma cobro",
            new_values=result,
            success=True,
        )
    )
    await db.flush()
    if currency.current_day() != day:
        raise HTTPException(409, "Cambió el día de operación; recarga")
    await db.commit()
    return result
