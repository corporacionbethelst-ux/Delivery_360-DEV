"""Read-only exact order prices and delivery snapshots, each from one SQL cut."""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
import hashlib
import json
from fastapi import HTTPException
from sqlalchemy import select, func, cast, String, true, literal, null, union_all
from app.models.order import Order
from app.models.delivery import Delivery
from app.models.rider import Rider
from app.services import order_pricing
from app.services.customer_cashbook import utc
from app.services.payout_records_exact import currency
from app.services.transaction_records_exact import row_money
from app.core.exceptions import AppException


def order_query(rider_id, limit, offset):
    return (
        select(
            Order.id,
            Order.assigned_rider_id.label("rider_id"),
            Order.external_id,
            Order.customer_name,
            cast(Order.status, String).label("status"),
            Order.created_at,
            Order.updated_at,
            Order.currency_code,
            Order.pricing_version,
            Order.pricing_revision,
            Order.subtotal_exact,
            Order.delivery_fee_exact,
            Order.total_exact,
            Order.items_exact,
        )
        .where(Order.assigned_rider_id == rider_id)
        .order_by(Order.created_at.desc().nulls_last(), Order.id.desc())
        .limit(limit)
        .offset(offset)
    )


def delivery_query(rider_id, limit, offset):
    real = (
        select(
            cast(Delivery.id, String).label("id"),
            Delivery.order_id,
            Delivery.rider_id,
            Order.external_id,
            Order.customer_name,
            cast(Delivery.status, String).label("status"),
            Delivery.created_at,
            Delivery.updated_at,
            Delivery.locked_bonus_amount,
            literal(False).label("fallback"),
        )
        .outerjoin(Order, Delivery.order_id == Order.id)
        .where(Delivery.rider_id == rider_id)
        .order_by(Delivery.created_at.desc().nulls_last(), Delivery.id.desc())
        .limit(limit)
        .offset(offset)
        .cte("audit_real_deliveries")
    )
    if offset:
        return select(real)
    support = (
        select(
            (literal("order-") + cast(Order.id, String)).label("id"),
            Order.id.label("order_id"),
            Order.assigned_rider_id.label("rider_id"),
            Order.external_id,
            Order.customer_name,
            cast(Order.status, String).label("status"),
            Order.created_at,
            Order.updated_at,
            cast(null(), Delivery.locked_bonus_amount.type).label(
                "locked_bonus_amount"
            ),
            literal(True).label("fallback"),
        )
        .where(
            Order.assigned_rider_id == rider_id,
            ~select(Delivery.id).where(Delivery.order_id == Order.id).exists(),
        )
        .order_by(Order.created_at.desc().nulls_last(), Order.id.desc())
        .limit(51)
        .cte("audit_support_orders")
    )
    return union_all(select(real), select(support))


def base_row(raw):
    return dict(
        id=str(raw["id"]),
        rider_id=str(raw["rider_id"]),
        external_id=raw["external_id"],
        customer_name=raw["customer_name"],
        status=raw["status"],
        created_at=utc(raw["created_at"]) if raw["created_at"] is not None else None,
        updated_at=utc(raw["updated_at"]) if raw["updated_at"] is not None else None,
    )


def order_row(raw):
    item = base_row(raw)
    item.update(
        currency(raw),
        amount=None,
        pricing_revision=raw["pricing_revision"],
        price_review=None,
    )
    if raw["pricing_version"] is None:
        item["price_review"] = "PRECIO_HISTORICO_NO_EXACTO"
        return item
    try:
        if (
            raw["pricing_version"] != 1
            or not isinstance(raw["pricing_revision"], int)
            or not 1 <= raw["pricing_revision"] <= order_pricing.MAX_REVISION
            or any(
                not isinstance(raw[k], Decimal) or not raw[k].is_finite()
                for k in ("subtotal_exact", "delivery_fee_exact", "total_exact")
            )
        ):
            raise ValueError("Incomplete exact price")
        price = order_pricing.view(SimpleNamespace(**raw))
        item["amount"] = price["total"]
    except (AppException, ValueError, ArithmeticError, TypeError):
        item["price_review"] = "PRECIO_POR_REVISAR"
    return item


def delivery_row(raw):
    item = base_row(raw)
    fallback = raw["fallback"]
    if fallback:
        item["status"] = (
            {
                "ENTREGADO": "COMPLETADA",
                "FALLIDO": "FALLIDA",
                "RECOLECTADO": "EN_ROUTE",
                "EN_RUTA": "EN_ROUTE",
                "ASIGNADO": "INICIADA",
            }.get(raw["status"], "PENDIENTE")
            if raw["status"] is not None
            else None
        )
    issues = []
    bonus = row_money(raw["locked_bonus_amount"], "locked_bonus_amount", issues)
    if bonus is not None and Decimal(bonus) < 0:
        bonus = None
        issues.append(dict(field="locked_bonus_amount", reason="IMPORTE_NO_VALIDO"))
    # Delivery has no recorded currency column. A price or linked ledger is not its denomination.
    item.update(
        order_id=str(raw["order_id"]),
        fallback=fallback,
        locked_bonus_amount=bonus,
        currency=None,
        currency_recorded=None,
        currency_review=False,
        currency_basis="not_recorded_on_delivery",
        money_review=issues,
    )
    return item


async def report(db, actor, rider_id, kind, limit, offset):
    records = (
        order_query(rider_id, limit, offset)
        if kind == "orders"
        else delivery_query(rider_id, limit, offset)
    ).cte("exact_audit_records")
    clock = select(
        func.timezone("UTC", func.statement_timestamp()).label("generated_at")
    ).cte("audit_records_clock")
    query = (
        select(clock, Rider.id.label("profile_id"), records)
        .select_from(
            clock.outerjoin(Rider, Rider.id == rider_id).outerjoin(records, true())
        )
        .order_by(records.c.created_at.desc().nulls_last(), records.c.id.desc())
    )
    rows = (await db.execute(query)).mappings().all()
    if rows[0]["profile_id"] is None:
        raise HTTPException(404, "Perfil de repartidor no encontrado")
    if not isinstance(rows[0]["generated_at"], datetime):
        raise HTTPException(503, "No se pudo confirmar el corte de auditoría")
    source = [r for r in rows if r["id"] is not None]
    items = [
        order_row(r) if kind == "orders" else delivery_row(r)
        for r in source
        if kind == "orders" or not r["fallback"]
    ]
    fallback = [
        delivery_row(r) for r in source if kind == "deliveries" and r["fallback"]
    ]
    result = dict(
        version=1,
        scope="rider_audit_registered_records",
        kind=kind,
        units_basis="recorded_currency_no_conversion",
        snapshot_basis="single_statement_visibility",
        amount_basis=(
            "exact_order_price_not_rider_earnings"
            if kind == "orders"
            else "locked_delivery_bonus_not_ledger"
        ),
        available_balance_included=False,
        bank_verified=False,
        wallet_cents_included=False,
        viewer_user_id=str(actor.id),
        viewer_role=actor.role.value,
        rider_id=str(rider_id),
        limit=limit,
        offset=offset,
        generated_at=utc(rows[0]["generated_at"]),
        total=len(items),
        items=items,
        fallback=fallback[:50],
        fallback_limit=50,
        fallback_has_more=len(fallback) > 50,
        pagination_basis="offset_live_records_real_deliveries_only",
    )
    result["content_sha256"] = hashlib.sha256(
        json.dumps(
            result, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    return result
