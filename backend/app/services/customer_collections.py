"""An independent customer USD book with explicit human verification."""

from decimal import Decimal
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import select, func, case
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.json_types import json_value
from app.models.customer_collection import CustomerCollection, CustomerCollectionReview
from app.models.order import Order, OrderStatus
from app.models.order_currency_quote import OrderCurrencyQuote
from app.models.currency import BcvRate
from app.models.user import User, UserRole
from app.models.audit_log import AuditLog, ActionType
from app.services import bcv_currency as currency, order_pricing
from app.services.order_currency_quote import order_row, receipt_view as quote_view

DECLARE_ROLES = {UserRole.SUPERADMIN, UserRole.GERENTE, UserRole.OPERADOR}
REVIEW_ROLES = {UserRole.SUPERADMIN, UserRole.GERENTE}
TERMINAL = {OrderStatus.CANCELADO, OrderStatus.FALLIDO}


def money(value) -> str:
    return format(Decimal(value), ".2f")


async def totals(db: AsyncSession, order_id: UUID) -> dict:
    c, r = CustomerCollection, CustomerCollectionReview
    row = (
        await db.execute(
            select(
                func.coalesce(
                    func.sum(case((r.id.is_(None), c.amount_usd), else_=0)), 0
                ),
                func.coalesce(
                    func.sum(case((r.decision == "VERIFICADO", c.amount_usd), else_=0)),
                    0,
                ),
                func.count(c.id),
                func.count(r.id),
            )
            .select_from(c)
            .outerjoin(r, r.collection_id == c.id)
            .where(c.order_id == order_id)
        )
    ).one()
    return {
        "pending": Decimal(row[0]),
        "verified": Decimal(row[1]),
        "count": int(row[2]),
        "reviews": int(row[3]),
    }


async def review_view(row: CustomerCollectionReview | None):
    if row is None:
        return None
    return {
        "id": str(row.id),
        "request_key": str(row.request_key),
        "collection_id": str(row.collection_id),
        "decision": row.decision,
        "note": row.note,
        "verified_evidence": row.verified_evidence,
        "acknowledge_refund_due": row.acknowledge_refund_due,
        "reviewed_by": str(row.reviewed_by),
        "reviewed_at": row.reviewed_at.isoformat() + "Z",
    }


async def receipt(db: AsyncSession, row: CustomerCollection, review_row=None):
    if review_row is None:
        review_row = await db.scalar(
            select(CustomerCollectionReview).where(
                CustomerCollectionReview.collection_id == row.id
            )
        )
    quote = await db.get(OrderCurrencyQuote, row.quote_id) if row.quote_id else None
    return {
        "id": str(row.id),
        "request_key": str(row.request_key),
        "order_id": str(row.order_id),
        "pricing": row.pricing_snapshot,
        "amount_usd": money(row.amount_usd),
        "paid_amount": money(row.paid_amount),
        "paid_currency": row.paid_currency,
        "method": row.method,
        "source_key": row.source_key,
        "reference_key": row.reference_key,
        "received_on": row.received_on.isoformat(),
        "declared_by": str(row.declared_by),
        "created_at": row.created_at.isoformat() + "Z",
        "quote": await quote_view(db, quote) if quote else None,
        "review": await review_view(review_row),
        "status": (
            (
                "VERIFICADO_MANUALMENTE"
                if review_row.decision == "VERIFICADO"
                else "RECHAZADO"
            )
            if review_row
            else "PENDIENTE"
        ),
        "scope": "manual_customer_collections",
        "bank_verified": False,
    }


async def context(db: AsyncSession, actor: User, order_id: UUID):
    order = await order_row(db, order_id, lock="read")
    pack = order_pricing.view(order)
    amounts = await totals(db, order_id)
    total = order_pricing.amount(order, "total") if pack else None
    pending, verified = amounts["pending"], amounts["verified"]
    terminal = order.status in TERMINAL
    state = (
        "REQUIERE_REVISION"
        if not pack
        else (
            "DEVOLUCION_PENDIENTE"
            if terminal and verified > 0
            else (
                "COMPLETO"
                if total and verified == total
                else (
                    "PARCIAL"
                    if verified > 0
                    else "EN_REVISION" if pending > 0 else "SIN_COBROS"
                )
            )
        )
    )
    summary = {
        "currency": "USD",
        "total_usd": money(total) if total is not None else None,
        "pending_usd": money(pending),
        "verified_usd": money(verified),
        "due_usd": (
            money(0 if terminal else total - verified) if total is not None else None
        ),
        "available_to_declare_usd": (
            money(0 if terminal else total - verified - pending)
            if total is not None
            else None
        ),
        "refund_due_usd": money(verified if terminal else 0),
        "refund_due_scope": "gross_verified_collections",
        "state": state,
        "declaration_count": amounts["count"],
        "review_count": amounts["reviews"],
    }
    query = select(CustomerCollection).where(CustomerCollection.order_id == order_id)
    if actor.role == UserRole.OPERADOR:
        query = query.where(CustomerCollection.declared_by == actor.id)
    rows = list(
        (
            await db.scalars(
                query.order_by(
                    CustomerCollection.created_at.desc(), CustomerCollection.id.desc()
                ).limit(21)
            )
        ).all()
    )
    day = currency.current_day()
    q = (
        select(OrderCurrencyQuote)
        .join(BcvRate, BcvRate.id == OrderCurrencyQuote.rate_id)
        .where(
            OrderCurrencyQuote.order_id == order_id,
            OrderCurrencyQuote.pricing_revision == order.pricing_revision,
            BcvRate.valid_on == day,
        )
    )
    if actor.role == UserRole.OPERADOR:
        q = q.where(OrderCurrencyQuote.created_by == actor.id)
    quotes = (
        list(
            (
                await db.scalars(
                    q.order_by(
                        OrderCurrencyQuote.created_at.desc(),
                        OrderCurrencyQuote.id.desc(),
                    ).limit(10)
                )
            ).all()
        )
        if pack
        else []
    )
    return {
        "order_id": str(order.id),
        "pricing": pack,
        "order_status": order.status.value if order.status else None,
        "currency": order.currency_code,
        "collection_revision": order.collection_revision or 0,
        "price_locked": order.collection_locked is True,
        "today": day.isoformat(),
        "summary": summary,
        "collections": [await receipt(db, row) for row in rows[:20]],
        "has_more": len(rows) > 20,
        "ves_quotes": [await quote_view(db, row) for row in quotes],
        "scope": "manual_customer_collections",
        "bank_integration_available": False,
    }


async def reference_lock(db, source, reference):
    await currency.advisory(db, "collection:reference:" + source + "\x1f" + reference)


async def checked_flush(db):
    try:
        await db.flush()
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == "P0094":
            await db.rollback()
            raise HTTPException(
                409,
                "El estado del cobro, su referencia o el día cambiaron; actualiza antes de continuar",
            ) from exc
        raise


def audit(db, actor, resource, identity, description, data):
    db.add(
        AuditLog(
            user_id=actor.id,
            user_email=actor.email,
            user_role=actor.role.value if actor.role else None,
            action_type=ActionType.CREATE,
            resource_type=resource,
            resource_id=str(identity),
            description=description,
            new_values=data,
            success=True,
        )
    )


async def declare(db: AsyncSession, actor: User, order_id: UUID, body):
    identity, version = actor.id, actor.token_version
    await currency.advisory(db, "collection:request:" + str(body.request_key))
    prior = await db.scalar(
        select(CustomerCollection).where(
            CustomerCollection.request_key == body.request_key
        )
    )
    expected = (
        identity,
        order_id,
        body.expected_pricing_revision,
        body.amount_usd,
        body.paid_amount,
        body.paid_currency,
        body.method,
        body.source_key,
        body.reference_key,
        body.received_on,
        body.quote_id,
    )
    if prior:
        if (
            prior.declared_by,
            prior.order_id,
            prior.pricing_revision,
            prior.amount_usd,
            prior.paid_amount,
            prior.paid_currency,
            prior.method,
            prior.source_key,
            prior.reference_key,
            prior.received_on,
            prior.quote_id,
        ) != expected:
            raise HTTPException(409, "La clave identifica otro cobro declarado")
        await currency.actor_lock(db, actor, DECLARE_ROLES, expected_version=version)
        return await receipt(db, prior)
    order = await order_row(db, order_id, lock=True)
    if order.currency_code != "USD" or order.pricing_version != 1:
        raise HTTPException(
            409, "Revisa primero el precio exacto y la moneda de la orden"
        )
    if order.status is None or order.status in TERMINAL:
        raise HTTPException(
            409, "La orden cancelada o fallida no admite nuevos cobros declarados"
        )
    if (
        order.pricing_revision != body.expected_pricing_revision
        or (order.collection_revision or 0) != body.expected_collection_revision
    ):
        raise HTTPException(
            412,
            "El precio o los cobros de la orden cambiaron; actualiza antes de declarar",
        )
    await reference_lock(db, body.source_key, body.reference_key)
    await currency.actor_lock(db, actor, DECLARE_ROLES, expected_version=version)
    duplicate = await db.scalar(
        select(CustomerCollection.id)
        .outerjoin(
            CustomerCollectionReview,
            CustomerCollectionReview.collection_id == CustomerCollection.id,
        )
        .where(
            CustomerCollection.source_key == body.source_key,
            CustomerCollection.reference_key == body.reference_key,
            CustomerCollectionReview.decision.is_distinct_from("RECHAZADO"),
        )
        .limit(1)
    )
    if duplicate:
        raise HTTPException(
            409, "Esa referencia ya identifica un cobro pendiente o verificado"
        )
    day = currency.current_day()
    if body.received_on != day:
        raise HTTPException(
            409,
            "Declara cobros recibidos hoy en Caracas; los anteriores requieren revisión específica",
        )
    pack = order_pricing.view(order)
    usd = order_pricing.amount(order, "total")
    amounts = await totals(db, order_id)
    if body.amount_usd > usd - amounts["pending"] - amounts["verified"]:
        raise HTTPException(
            409,
            "El abono supera el importe disponible, incluidos los cobros en revisión",
        )
    if body.paid_currency == "USD":
        if body.paid_amount != body.amount_usd:
            raise HTTPException(
                422, "El importe recibido USD debe coincidir con el abono USD"
            )
    else:
        quote = await db.get(OrderCurrencyQuote, body.quote_id)
        if (
            quote is None
            or quote.order_id != order.id
            or quote.pricing_revision != order.pricing_revision
        ):
            raise HTTPException(
                412, "La cotización no corresponde al precio actual de esta orden"
            )
        if actor.role == UserRole.OPERADOR and quote.created_by != identity:
            raise HTTPException(403, "La cotización pertenece a otra cuenta")
        rate = await db.get(BcvRate, quote.rate_id)
        if rate is None or rate.valid_on != day:
            raise HTTPException(
                409, "La cotización VES debe corresponder al día del cobro declarado"
            )
        if body.paid_amount != currency.converted_amount(
            body.amount_usd, rate.ves_per_usd
        ):
            raise HTTPException(
                422,
                "El importe recibido VES no coincide con el abono y su referencia BCV conservada",
            )
    row = CustomerCollection(
        request_key=body.request_key,
        order_id=order.id,
        quote_id=body.quote_id,
        pricing_revision=order.pricing_revision,
        pricing_snapshot=json_value(pack),
        amount_usd=body.amount_usd,
        paid_amount=body.paid_amount,
        paid_currency=body.paid_currency,
        method=body.method,
        source_key=body.source_key,
        reference_key=body.reference_key,
        received_on=body.received_on,
        declared_by=identity,
        created_at=currency.utc_now().replace(tzinfo=None),
    )
    db.add(row)
    await checked_flush(db)
    result = await receipt(db, row)
    audit(
        db,
        actor,
        "CUSTOMER_COLLECTION",
        row.id,
        "Cobro declarado, pendiente de verificación independiente",
        result,
    )
    await db.flush()
    if currency.current_day() != day:
        raise HTTPException(409, "Cambió el día de operación; actualiza")
    await db.commit()
    return result


async def review(db: AsyncSession, actor: User, collection_id: UUID, body):
    identity, version = actor.id, actor.token_version
    await currency.advisory(db, "collection:review:" + str(body.request_key))
    prior = await db.scalar(
        select(CustomerCollectionReview).where(
            CustomerCollectionReview.request_key == body.request_key
        )
    )
    expected = (
        identity,
        collection_id,
        body.decision,
        body.note,
        body.verified_evidence,
        body.acknowledge_refund_due,
    )
    if prior:
        if (
            prior.reviewed_by,
            prior.collection_id,
            prior.decision,
            prior.note,
            prior.verified_evidence,
            prior.acknowledge_refund_due,
        ) != expected:
            raise HTTPException(409, "La clave identifica otra revisión de cobro")
        await currency.actor_lock(db, actor, REVIEW_ROLES, expected_version=version)
        row = await db.get(CustomerCollection, collection_id)
        if row is None:
            raise HTTPException(404, "Cobro declarado no encontrado")
        return await receipt(db, row, prior)
    row = await db.get(CustomerCollection, collection_id)
    if row is None:
        raise HTTPException(404, "Cobro declarado no encontrado")
    order = await order_row(db, row.order_id, lock=True)
    if (order.collection_revision or 0) != body.expected_collection_revision:
        raise HTTPException(
            412, "Los cobros o revisiones cambiaron; actualiza antes de decidir"
        )
    await reference_lock(db, row.source_key, row.reference_key)
    await currency.actor_lock(db, actor, REVIEW_ROLES, expected_version=version)
    if row.declared_by == identity:
        raise HTTPException(
            403, "La verificación o rechazo debe realizarlo otro responsable"
        )
    if await db.scalar(
        select(CustomerCollectionReview.id).where(
            CustomerCollectionReview.collection_id == row.id
        )
    ):
        raise HTTPException(409, "Ese cobro ya tiene una decisión conservada")
    if (
        body.decision == "VERIFICADO"
        and order.status in TERMINAL
        and not body.acknowledge_refund_due
    ):
        raise HTTPException(
            409,
            "La orden está cancelada o fallida; reconoce expresamente que el importe quedará pendiente de devolución",
        )
    result_row = CustomerCollectionReview(
        request_key=body.request_key,
        collection_id=row.id,
        decision=body.decision,
        note=body.note,
        verified_evidence=body.verified_evidence,
        acknowledge_refund_due=body.acknowledge_refund_due,
        reviewed_by=identity,
        reviewed_at=currency.utc_now().replace(tzinfo=None),
    )
    db.add(result_row)
    await checked_flush(db)
    result = await receipt(db, row, result_row)
    audit(
        db,
        actor,
        "CUSTOMER_COLLECTION_REVIEW",
        result_row.id,
        "Revisión manual independiente de cobro; sin integración bancaria",
        result,
    )
    await db.flush()
    await db.commit()
    return result


async def get_receipt(db: AsyncSession, actor: User, collection_id: UUID):
    row = await db.get(CustomerCollection, collection_id)
    if row is None:
        raise HTTPException(404, "Cobro declarado no encontrado")
    if actor.role == UserRole.OPERADOR and row.declared_by != actor.id:
        raise HTTPException(403, "El cobro pertenece a otra cuenta")
    return await receipt(db, row)
