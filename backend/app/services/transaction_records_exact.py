"""Decimal registered movements, without deriving balances or converting currencies."""

from datetime import datetime, timezone
from decimal import Decimal, localcontext
import hashlib
import json
import re
from fastapi import HTTPException
from sqlalchemy import select, func, cast, String, true
from app.models.financial import Financial
from app.services.customer_cashbook import utc

MONEY_FIELDS = ("amount", "balance_before", "balance_after")


def normalize_bound(value):
    if value is None:
        return None
    return (
        value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
    )


def row_money(value, field, issues):
    if value is None:
        if field == "amount":
            issues.append({"field": field, "reason": "NO_REGISTRADO"})
        return None
    with localcontext() as context:
        context.prec = 60
        if (
            not isinstance(value, Decimal)
            or not value.is_finite()
            or abs(value) > Decimal("99999999.99")
            or value != value.quantize(Decimal(".01"))
        ):
            issues.append({"field": field, "reason": "IMPORTE_NO_VALIDO"})
            return None
        return format(abs(value) if value == 0 else value, ".2f")


def query(filters, limit, offset):
    selected = select(
        Financial.id,
        Financial.rider_id,
        Financial.amount,
        Financial.balance_before,
        Financial.balance_after,
        Financial.currency_code.label("currency_recorded"),
        cast(Financial.transaction_type, String).label("type"),
        cast(Financial.status, String).label("status"),
        Financial.description,
        Financial.reference_id,
        Financial.source_type,
        Financial.source_id,
        Financial.idempotency_key,
        Financial.created_by_user_id,
        Financial.created_at,
        Financial.updated_at,
    )
    columns = {
        "transaction_id": Financial.id,
        "rider_id": Financial.rider_id,
        "type": cast(Financial.transaction_type, String),
        "status": cast(Financial.status, String),
    }
    for key, column in columns.items():
        if filters[key] is not None:
            selected = selected.where(column == filters[key])
    if filters["date_from"] is not None:
        selected = selected.where(Financial.created_at >= filters["date_from"])
    if filters["date_to"] is not None:
        selected = selected.where(Financial.created_at <= filters["date_to"])
    page = (
        selected.order_by(Financial.created_at.desc().nulls_last(), Financial.id.desc())
        .limit(limit)
        .offset(offset)
        .cte("exact_transaction_records")
    )
    clock = select(
        func.timezone("UTC", func.statement_timestamp()).label("generated_at")
    ).cte("exact_transaction_clock")
    return (
        select(clock, page)
        .select_from(clock.outerjoin(page, true()))
        .order_by(page.c.created_at.desc().nulls_last(), page.c.id.desc())
    )


async def report(db, actor, filters, limit, offset):
    captured = dict(filters)
    for key in ("date_from", "date_to"):
        captured[key] = normalize_bound(captured[key])
    if (
        captured["date_from"]
        and captured["date_to"]
        and captured["date_from"] > captured["date_to"]
    ):
        raise HTTPException(422, "El inicio no puede ser posterior al final")
    rows = (await db.execute(query(captured, limit, offset))).mappings().all()
    generated = rows[0]["generated_at"]
    if not isinstance(generated, datetime):
        raise HTTPException(503, "No se pudo confirmar el corte de lectura")
    items = []
    for raw in rows:
        if raw["id"] is None:
            continue
        item = {
            key: raw[key]
            for key in (
                "type",
                "status",
                "description",
                "reference_id",
                "source_type",
                "source_id",
                "idempotency_key",
                "currency_recorded",
            )
        }
        item.update(
            {
                key: str(raw[key]) if raw[key] is not None else None
                for key in ("id", "rider_id", "created_by_user_id")
            }
        )
        item.update(
            {
                key: utc(raw[key]) if raw[key] is not None else None
                for key in ("created_at", "updated_at")
            }
        )
        item["processed_at"] = None  # This model does not record a process timestamp.
        item["transaction_type"] = item["type"]
        recorded = raw["currency_recorded"]
        item["currency"] = (
            recorded
            if isinstance(recorded, str) and re.fullmatch("[A-Z]{3}", recorded)
            else None
        )
        item["currency_review"] = recorded is not None and item["currency"] is None
        issues = []
        item.update({key: row_money(raw[key], key, issues) for key in MONEY_FIELDS})
        item["money_review"] = issues
        items.append(item)
    if captured["transaction_id"] is not None and not items:
        raise HTTPException(404, "Transacción no encontrada")
    serialized_filters = {
        key: (
            utc(value)
            if isinstance(value, datetime)
            else str(value) if value is not None else None
        )
        for key, value in captured.items()
    }
    result = dict(
        version=1,
        scope="registered_financial_records",
        units_basis="recorded_currency_no_conversion",
        balance_basis="registered_snapshots_not_available_balance",
        snapshot_basis="single_statement_visibility",
        available_balance_included=False,
        bank_verified=False,
        wallet_cents_included=False,
        customer_cashbook_included=False,
        viewer_user_id=str(actor.id),
        viewer_role=actor.role.value,
        generated_at=utc(generated),
        filters=serialized_filters,
        limit=limit,
        offset=offset,
        total=len(items),
        items=items,
    )
    result["content_sha256"] = hashlib.sha256(
        json.dumps(
            result, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    return result
