"""Two-person authorization and confirmation; never initiate a bank transaction."""

from decimal import Decimal
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import select, func, case
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.customer_refund import CustomerRefund, CustomerRefundEvent
from app.models.customer_collection import CustomerCollection, CustomerCollectionReview
from app.models.order import Order
from app.models.order_currency_quote import OrderCurrencyQuote
from app.models.currency import BcvRate
from app.models.user import User, UserRole
from app.services import bcv_currency as currency
from app.services.customer_collections import (
    money,
    audit,
    receipt as collection_receipt,
    TERMINAL,
    DECLARE_ROLES,
    REVIEW_ROLES,
)
from app.services.order_currency_quote import order_row

STATES = {
    "APROBAR": "APROBADA",
    "RECHAZAR": "RECHAZADA",
    "DECLARAR_EJECUCION": "EJECUCION_DECLARADA",
    "VERIFICAR_DEVOLUCION": "DEVUELTA",
    "OBSERVAR_EJECUCION": "OBSERVADA",
    "CONFIRMAR_NO_EJECUTADA": "APROBADA",
    "ANULAR_APROBACION": "RECHAZADA",
}
ALLOWED = {
    "SOLICITADA": {"APROBAR", "RECHAZAR"},
    "APROBADA": {"DECLARAR_EJECUCION", "ANULAR_APROBACION"},
    "EJECUCION_DECLARADA": {"VERIFICAR_DEVOLUCION", "OBSERVAR_EJECUCION"},
    "OBSERVADA": {"VERIFICAR_DEVOLUCION", "CONFIRMAR_NO_EJECUTADA"},
    "DEVUELTA": set(),
    "RECHAZADA": set(),
}
EXECUTION_FIELDS = (
    "method",
    "source_key",
    "reference_key",
    "paid_amount",
    "paid_currency",
    "executed_on",
)


async def current_event(db, refund_id):
    return await db.scalar(
        select(CustomerRefundEvent)
        .where(CustomerRefundEvent.refund_id == refund_id)
        .order_by(CustomerRefundEvent.revision.desc())
        .limit(1)
    )


async def latest_execution(db, refund_id):
    return await db.scalar(
        select(CustomerRefundEvent)
        .where(
            CustomerRefundEvent.refund_id == refund_id,
            CustomerRefundEvent.kind == "DECLARAR_EJECUCION",
        )
        .order_by(CustomerRefundEvent.revision.desc())
        .limit(1)
    )


def status(last):
    return STATES[last.kind] if last else "SOLICITADA"


async def book_revision(db, order_id):
    refunds = (
        select(CustomerRefund.id)
        .join(CustomerCollection, CustomerCollection.id == CustomerRefund.collection_id)
        .where(CustomerCollection.order_id == order_id)
    )
    requests = await db.scalar(select(func.count()).select_from(refunds.subquery()))
    events = await db.scalar(
        select(func.count(CustomerRefundEvent.id)).where(
            CustomerRefundEvent.refund_id.in_(refunds)
        )
    )
    return int(requests or 0) + int(events or 0)


async def rollup(db, collection_id):
    r = CustomerRefund
    s = func.customer_refund_status(r.id)
    row = (
        await db.execute(
            select(
                func.coalesce(
                    func.sum(case((s == "DEVUELTA", r.amount_usd), else_=0)), 0
                ),
                func.coalesce(
                    func.sum(case((s == "DEVUELTA", r.return_amount), else_=0)), 0
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (s.not_in(["DEVUELTA", "RECHAZADA"]), r.amount_usd), else_=0
                        )
                    ),
                    0,
                ),
                func.count(case((s.not_in(["DEVUELTA", "RECHAZADA"]), r.id))),
            ).where(r.collection_id == collection_id)
        )
    ).one()
    return dict(
        returned_usd=Decimal(row[0]),
        returned_paid=Decimal(row[1]),
        reserved_usd=Decimal(row[2]),
        active_count=int(row[3]),
    )


async def rate_for(db, collection):
    if collection.paid_currency == "USD":
        return Decimal("1")
    quote = await db.get(OrderCurrencyQuote, collection.quote_id)
    rate = await db.get(BcvRate, quote.rate_id) if quote else None
    if rate is None:
        raise HTTPException(409, "La referencia del cobro requiere revisión")
    return rate.ves_per_usd


async def allocation(db, collection, amount, totals):
    # A single unresolved request per collection preserves an immutable prefix.
    # Differences of cumulative conversion settle the original paid cents exactly.
    return (
        currency.converted_amount(
            totals["returned_usd"] + amount, await rate_for(db, collection)
        )
        - totals["returned_paid"]
    )


def event_view(row):
    return dict(
        id=str(row.id),
        request_key=str(row.request_key),
        refund_id=str(row.refund_id),
        revision=row.revision,
        kind=row.kind,
        note=row.note,
        verified_evidence=row.verified_evidence,
        confirmed_no_execution=row.confirmed_no_execution,
        confirmed_execution=row.confirmed_execution,
        method=row.method,
        source_key=row.source_key,
        reference_key=row.reference_key,
        paid_amount=money(row.paid_amount) if row.paid_amount is not None else None,
        paid_currency=row.paid_currency,
        executed_on=row.executed_on.isoformat() if row.executed_on else None,
        actor_id=str(row.actor_id),
        created_at=row.created_at.isoformat() + "Z",
    )


async def actions(db, actor, row, last):
    if actor.role not in REVIEW_ROLES:
        return []
    result = set(ALLOWED[status(last)])
    if row.requested_by == actor.id:
        result -= {"APROBAR", "RECHAZAR", "ANULAR_APROBACION"}
    execution = await latest_execution(db, row.id)
    if execution and execution.actor_id == actor.id:
        result -= {
            "VERIFICAR_DEVOLUCION",
            "OBSERVAR_EJECUCION",
            "CONFIRMAR_NO_EJECUTADA",
        }
    return sorted(result)


async def receipt(db, actor, row):
    collection = await db.get(CustomerCollection, row.collection_id)
    last = await current_event(db, row.id)
    rows = list(
        (
            await db.scalars(
                select(CustomerRefundEvent)
                .where(CustomerRefundEvent.refund_id == row.id)
                .order_by(CustomerRefundEvent.revision.desc())
                .limit(51)
            )
        ).all()
    )
    return dict(
        id=str(row.id),
        request_key=str(row.request_key),
        order_id=str(collection.order_id),
        collection_id=str(row.collection_id),
        amount_usd=money(row.amount_usd),
        return_amount=money(row.return_amount),
        return_currency=row.return_currency,
        prior_refunded_usd=money(row.prior_refunded_usd),
        prior_refunded_paid=money(row.prior_refunded_paid),
        reason=row.reason,
        requested_by=str(row.requested_by),
        created_at=row.created_at.isoformat() + "Z",
        revision=last.revision if last else 0,
        state=status(last),
        original_collection=await collection_receipt(db, collection),
        events=[event_view(x) for x in rows[:50]],
        has_more_events=len(rows) > 50,
        allowed_actions=await actions(db, actor, row, last),
        policy="ORIGINAL_RECEIVED",
        rounding="CUMULATIVE_ORIGINAL_BCV",
        scope="manual_customer_refunds",
        bank_verified=False,
    )


async def visible_refund(db, actor, refund_id, *, lock="read"):
    row = await db.get(CustomerRefund, refund_id)
    if row is None:
        raise HTTPException(404, "Solicitud de devolución no encontrada")
    collection = await db.get(CustomerCollection, row.collection_id)
    if (
        actor.role == UserRole.OPERADOR
        and collection.declared_by != actor.id
        and row.requested_by != actor.id
    ):
        raise HTTPException(403, "La devolución pertenece a otra cuenta")
    order = await order_row(db, collection.order_id, lock=lock)
    return row, order


async def get_receipt(db: AsyncSession, actor: User, refund_id: UUID):
    row, _ = await visible_refund(db, actor, refund_id)
    return await receipt(db, actor, row)


async def event_page(db, actor, refund_id, before_revision=None):
    row, _ = await visible_refund(db, actor, refund_id)
    query = select(CustomerRefundEvent).where(CustomerRefundEvent.refund_id == row.id)
    if before_revision is not None:
        query = query.where(CustomerRefundEvent.revision < before_revision)
    rows = list(
        (
            await db.scalars(
                query.order_by(CustomerRefundEvent.revision.desc()).limit(51)
            )
        ).all()
    )
    return dict(
        refund_id=str(row.id),
        events=[event_view(x) for x in rows[:50]],
        has_more=len(rows) > 50,
        next_before_revision=rows[49].revision if len(rows) > 50 else None,
    )


async def context(db: AsyncSession, actor: User, order_id: UUID):
    order = await order_row(db, order_id, lock="read")
    all_collections = list(
        (
            await db.scalars(
                select(CustomerCollection)
                .join(
                    CustomerCollectionReview,
                    CustomerCollectionReview.collection_id == CustomerCollection.id,
                )
                .where(
                    CustomerCollection.order_id == order_id,
                    CustomerCollectionReview.decision == "VERIFICADO",
                )
                .order_by(CustomerCollection.created_at, CustomerCollection.id)
            )
        ).all()
    )
    gross = returned = reserved = requestable = Decimal("0.00")
    eligible = []
    for collection in all_collections:
        totals = await rollup(db, collection.id)
        gross += collection.amount_usd
        returned += totals["returned_usd"]
        reserved += totals["reserved_usd"]
        remaining = collection.amount_usd - totals["returned_usd"]
        can_request = (
            order.status in TERMINAL and not totals["active_count"] and remaining > 0
        )
        if can_request:
            requestable += remaining
        if actor.role != UserRole.OPERADOR or collection.declared_by == actor.id:
            eligible.append(
                dict(
                    collection=await collection_receipt(db, collection),
                    returned_usd=money(totals["returned_usd"]),
                    returned_paid=money(totals["returned_paid"]),
                    remaining_usd=money(remaining),
                    active_request=totals["active_count"] > 0,
                    can_request=can_request and actor.role in DECLARE_ROLES,
                    rate=format(await rate_for(db, collection), ".8f"),
                )
            )
    query = (
        select(CustomerRefund)
        .join(CustomerCollection, CustomerCollection.id == CustomerRefund.collection_id)
        .where(CustomerCollection.order_id == order_id)
    )
    if actor.role == UserRole.OPERADOR:
        query = query.where(
            (CustomerCollection.declared_by == actor.id)
            | (CustomerRefund.requested_by == actor.id)
        )
    rows = list(
        (
            await db.scalars(
                query.order_by(
                    CustomerRefund.created_at.desc(), CustomerRefund.id.desc()
                ).limit(21)
            )
        ).all()
    )
    return dict(
        order_id=str(order_id),
        order_status=order.status.value if order.status else None,
        today=currency.current_day().isoformat(),
        book_revision=await book_revision(db, order_id),
        summary=dict(
            currency="USD",
            gross_verified_usd=money(gross),
            refunded_usd=money(returned),
            in_progress_usd=money(reserved),
            remaining_usd=money(gross - returned if order.status in TERMINAL else 0),
            requestable_now_usd=money(requestable),
        ),
        collections=eligible,
        refunds=[await receipt(db, actor, row) for row in rows[:20]],
        has_more=len(rows) > 20,
        policy="ORIGINAL_RECEIVED",
        scope="manual_customer_refunds",
        bank_integration_available=False,
    )


async def checked_flush(db):
    try:
        await db.flush()
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == "P0095":
            await db.rollback()
            raise HTTPException(
                409,
                "El estado, la referencia o el importe de la devolución cambiaron; actualiza antes de continuar",
            ) from exc
        raise


async def request_refund(db, actor, order_id, body):
    identity, version = actor.id, actor.token_version
    await currency.advisory(db, "refund:request:" + str(body.request_key))
    prior = await db.scalar(
        select(CustomerRefund).where(CustomerRefund.request_key == body.request_key)
    )
    if prior:
        source = await db.get(CustomerCollection, prior.collection_id)
        if (
            prior.requested_by,
            source.order_id,
            prior.collection_id,
            prior.amount_usd,
            prior.reason,
        ) != (identity, order_id, body.collection_id, body.amount_usd, body.reason):
            raise HTTPException(409, "La clave identifica otra solicitud de devolución")
        await order_row(db, source.order_id, lock="read")
        await currency.actor_lock(db, actor, DECLARE_ROLES, expected_version=version)
        return await receipt(db, actor, prior)
    order = await order_row(db, order_id, lock=True)
    if order.status not in TERMINAL:
        raise HTTPException(
            409,
            "Primero cancela la orden o registra su fallo antes de solicitar una devolución",
        )
    if await book_revision(db, order_id) != body.expected_book_revision:
        raise HTTPException(
            412, "Las devoluciones cambiaron; actualiza antes de solicitar"
        )
    collection = await db.get(CustomerCollection, body.collection_id)
    if collection is None or collection.order_id != order.id:
        raise HTTPException(404, "Cobro de esta orden no encontrado")
    if actor.role == UserRole.OPERADOR and collection.declared_by != identity:
        raise HTTPException(403, "El cobro pertenece a otra cuenta")
    await currency.actor_lock(db, actor, DECLARE_ROLES, expected_version=version)
    verified = await db.scalar(
        select(CustomerCollectionReview).where(
            CustomerCollectionReview.collection_id == collection.id
        )
    )
    if verified is None or verified.decision != "VERIFICADO":
        raise HTTPException(409, "Solo se devuelve un cobro verificado manualmente")
    totals = await rollup(db, collection.id)
    if totals["active_count"]:
        raise HTTPException(
            409, "Resuelve la devolución en curso de este cobro antes de solicitar otra"
        )
    if body.amount_usd > collection.amount_usd - totals["returned_usd"]:
        raise HTTPException(
            409, "El importe supera el saldo del cobro pendiente de devolución"
        )
    paid = await allocation(db, collection, body.amount_usd, totals)
    if paid <= 0:
        raise HTTPException(
            422,
            "El abono es demasiado pequeño para devolver un centavo en la moneda original",
        )
    row = CustomerRefund(
        request_key=body.request_key,
        collection_id=collection.id,
        amount_usd=body.amount_usd,
        return_amount=paid,
        return_currency=collection.paid_currency,
        prior_refunded_usd=totals["returned_usd"],
        prior_refunded_paid=totals["returned_paid"],
        reason=body.reason,
        requested_by=identity,
        created_at=currency.utc_now().replace(tzinfo=None),
    )
    db.add(row)
    await checked_flush(db)
    result = await receipt(db, actor, row)
    audit(
        db,
        actor,
        "CUSTOMER_REFUND_REQUEST",
        row.id,
        "Solicitud de devolución; no confirma salida de dinero",
        result,
    )
    await db.flush()
    await db.commit()
    return result


async def add_event(db, actor, refund_id, body):
    identity, version = actor.id, actor.token_version
    await currency.advisory(db, "refund:event:" + str(body.request_key))
    prior = await db.scalar(
        select(CustomerRefundEvent).where(
            CustomerRefundEvent.request_key == body.request_key
        )
    )
    intent = (
        identity,
        refund_id,
        body.kind,
        body.note,
        body.verified_evidence,
        body.confirmed_no_execution,
        body.confirmed_execution,
        *(getattr(body, key) for key in EXECUTION_FIELDS),
    )
    if prior:
        stored = (
            prior.actor_id,
            prior.refund_id,
            prior.kind,
            prior.note,
            prior.verified_evidence,
            prior.confirmed_no_execution,
            prior.confirmed_execution,
            *(getattr(prior, key) for key in EXECUTION_FIELDS),
        )
        if stored != intent:
            raise HTTPException(409, "La clave identifica otra acción de devolución")
        row, _ = await visible_refund(db, actor, refund_id)
        await currency.actor_lock(db, actor, REVIEW_ROLES, expected_version=version)
        if row is None:
            raise HTTPException(404, "Solicitud no encontrada")
        return dict(
            refund=await receipt(db, actor, row), applied_event=event_view(prior)
        )
    row, order = await visible_refund(db, actor, refund_id, lock=True)
    if body.kind == "DECLARAR_EJECUCION":
        await currency.advisory(
            db, "refund:reference:" + body.source_key + "\x1f" + body.reference_key
        )
    await currency.actor_lock(db, actor, REVIEW_ROLES, expected_version=version)
    last = await current_event(db, row.id)
    if body.expected_revision != (last.revision if last else 0):
        raise HTTPException(412, "La devolución cambió; actualiza antes de decidir")
    if body.kind not in await actions(db, actor, row, last):
        raise HTTPException(
            409 if body.kind not in ALLOWED[status(last)] else 403,
            "La acción no corresponde al estado actual o requiere otro responsable",
        )
    if body.kind in ("APROBAR", "DECLARAR_EJECUCION") and order.status not in TERMINAL:
        raise HTTPException(409, "La orden debe permanecer cancelada o fallida")
    if body.kind == "DECLARAR_EJECUCION":
        if body.executed_on != currency.current_day():
            raise HTTPException(
                409, "Registra una salida de dinero efectuada hoy en Caracas"
            )
        if (body.paid_amount, body.paid_currency) != (
            row.return_amount,
            row.return_currency,
        ):
            raise HTTPException(
                422,
                "El importe y la moneda devueltos deben coincidir con la solicitud aprobada",
            )
        if await db.scalar(
            select(CustomerRefundEvent.id).where(
                CustomerRefundEvent.source_key == body.source_key,
                CustomerRefundEvent.reference_key == body.reference_key,
            )
        ):
            raise HTTPException(
                409, "La referencia ya identifica una declaración de devolución"
            )
    event = CustomerRefundEvent(
        request_key=body.request_key,
        refund_id=row.id,
        revision=body.expected_revision + 1,
        kind=body.kind,
        note=body.note,
        verified_evidence=body.verified_evidence,
        confirmed_no_execution=body.confirmed_no_execution,
        confirmed_execution=body.confirmed_execution,
        **{key: getattr(body, key) for key in EXECUTION_FIELDS},
        actor_id=identity,
        created_at=currency.utc_now().replace(tzinfo=None),
    )
    db.add(event)
    await checked_flush(db)
    result = dict(refund=await receipt(db, actor, row), applied_event=event_view(event))
    audit(
        db,
        actor,
        "CUSTOMER_REFUND_EVENT",
        event.id,
        "Acción manual de devolución; sin integración bancaria",
        result,
    )
    await db.flush()
    await db.commit()
    return result
