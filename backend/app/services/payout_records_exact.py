"""Registered decimal payouts and complete event history; never available funds."""

from datetime import datetime
from decimal import Decimal
import hashlib
import json
import re
from fastapi import HTTPException
from sqlalchemy import select, func, cast, String, true, and_, or_
from app.models.payout import Payout, PayoutStatusHistory
from app.services.payout_cursor import encode_cursor, decode_cursor
from app.services.transaction_records_exact import row_money
from app.services.customer_cashbook import utc

HISTORY_LIMIT = 1000


def selected(stmt):
    columns = [
        getattr(Payout, key)
        for key in (
            "id",
            "rider_id",
            "amount",
            "balance_before",
            "balance_after",
            "currency_code",
            "bank_account_last4",
            "reference_code",
            "rejection_reason",
            "idempotency_key",
            "requested_by_user_id",
            "processed_by_user_id",
            "requested_at",
            "processed_at",
            "updated_at",
        )
    ]
    return stmt.with_only_columns(
        *columns,
        cast(Payout.status, String).label("status"),
        cast(Payout.method, String).label("method"),
        maintain_column_froms=True,
    )


def currency(raw):
    recorded = raw["currency_code"]
    value = (
        recorded
        if isinstance(recorded, str) and re.fullmatch("[A-Z]{3}", recorded)
        else None
    )
    return dict(
        currency_recorded=recorded,
        currency=value,
        currency_review=recorded is not None and value is None,
    )


def payout_row(raw):
    item = {
        key: raw[key]
        for key in (
            "status",
            "method",
            "reference_code",
            "rejection_reason",
            "idempotency_key",
        )
    }
    item.update(
        {
            key: str(raw[key]) if raw[key] is not None else None
            for key in (
                "id",
                "rider_id",
                "requested_by_user_id",
                "processed_by_user_id",
            )
        }
    )
    item.update(
        {
            key: utc(raw[key]) if raw[key] is not None else None
            for key in ("requested_at", "processed_at", "updated_at")
        }
    )
    issues = []
    item.update(
        {
            key: row_money(raw[key], key, issues)
            for key in ("amount", "balance_before", "balance_after")
        }
    )
    if item["amount"] is not None and Decimal(item["amount"]) <= 0:
        item["amount"] = None
        issues.append(dict(field="amount", reason="IMPORTE_NO_VALIDO"))
    bank = raw["bank_account_last4"]
    item.update(
        currency(raw),
        total_amount=item["amount"],
        created_at=item["requested_at"],
        payment_method=item["method"],
        money_review=issues,
        bank_account_last4=(
            bank if isinstance(bank, str) and re.fullmatch(r"\d{4}", bank) else None
        ),
        bank_destination_review=bank is not None
        and (not isinstance(bank, str) or not re.fullmatch(r"\d{4}", bank)),
        orders_count=None,
        period=None,
        period_start=None,
        period_end=None,
    )
    item["bank_destination_review"] = bool(item["bank_destination_review"])
    return item


def history_row(raw):
    issues = []
    value = dict(
        id=str(raw["h_id"]),
        payout_id=str(raw["h_payout_id"]),
        old_status=raw["h_old_status"],
        new_status=raw["h_new_status"],
        reason=raw["h_reason"],
        changed_by_user_id=(
            str(raw["h_changed_by_user_id"]) if raw["h_changed_by_user_id"] else None
        ),
        created_at=utc(raw["h_created_at"]) if raw["h_created_at"] else None,
    )
    value.update(currency({"currency_code": raw["h_currency_code"]}))
    value.update(
        {
            key: row_money(raw["h_" + key], key, issues)
            for key in ("balance_before", "balance_after")
        }
    )
    value["money_review"] = issues
    return value


def envelope(
    actor,
    generated,
    filters,
    target,
    limit,
    cursor,
    items,
    next_cursor=None,
    history=None,
):
    if not isinstance(generated, datetime):
        raise HTTPException(503, "No se pudo confirmar el corte de retiros")
    result = dict(
        version=1,
        scope="registered_payout_records",
        units_basis="recorded_currency_no_conversion",
        balance_basis="registered_snapshots_not_available_balance",
        snapshot_basis="single_statement_visibility",
        pagination_basis="signed_position_live_records",
        available_balance_included=False,
        bank_verified=False,
        wallet_cents_included=False,
        viewer_user_id=str(actor.id),
        viewer_role=actor.role.value,
        effective_rider_id=str(target) if target is not None else None,
        generated_at=utc(generated),
        filters=filters,
        limit=limit,
        cursor=cursor,
        next_cursor=next_cursor,
        total=len(items),
        items=items,
        history=history if history is not None else [],
        history_included=history is not None,
        history_complete=history is not None,
        history_limit=HISTORY_LIMIT if history is not None else None,
    )
    result["content_sha256"] = hashlib.sha256(
        json.dumps(
            result, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    return result


async def page(
    db, actor, stmt, target, requested_rider, status, limit, cursor, audience=None
):
    scope = [
        str(actor.id),
        actor.role.value,
        str(target) if target is not None else None,
        status,
        limit,
    ]
    if status is not None:
        stmt = stmt.where(cast(Payout.status, String) == status)
    if cursor is not None:
        at, id = decode_cursor(cursor, scope)
        stmt = stmt.where(
            and_(Payout.requested_at.is_(None), Payout.id < id)
            if at is None
            else or_(
                Payout.requested_at < at,
                and_(Payout.requested_at == at, Payout.id < id),
                Payout.requested_at.is_(None),
            )
        )
    records = (
        selected(stmt)
        .order_by(Payout.requested_at.desc().nulls_last(), Payout.id.desc())
        .limit(limit + 1)
        .cte("exact_payout_page")
    )
    clock = select(
        func.timezone("UTC", func.statement_timestamp()).label("generated_at")
    ).cte("exact_payout_clock")
    rows = (
        (
            await db.execute(
                select(clock, records)
                .select_from(clock.outerjoin(records, true()))
                .order_by(
                    records.c.requested_at.desc().nulls_last(), records.c.id.desc()
                )
            )
        )
        .mappings()
        .all()
    )
    actual = [r for r in rows if r["id"] is not None]
    visible = actual[:limit]
    next_cursor = None
    if len(actual) > limit:
        last = visible[-1]
        next_cursor = encode_cursor(scope, last["requested_at"], last["id"])
    return envelope(
        actor,
        rows[0]["generated_at"],
        dict(
            rider_id=str(requested_rider) if requested_rider else None,
            status=status,
            payout_id=None,
            audience=audience,
        ),
        target,
        limit,
        cursor,
        [payout_row(r) for r in visible],
        next_cursor,
    )


async def detail(db, actor, stmt, target, payout_id, audience=None):
    parent = (
        selected(stmt.where(Payout.id == payout_id)).limit(1).cte("exact_payout_parent")
    )
    columns = [c.label("h_" + c.key) for c in PayoutStatusHistory.__table__.columns]
    events = (
        select(*columns)
        .join(parent, PayoutStatusHistory.payout_id == parent.c.id)
        .order_by(
            PayoutStatusHistory.created_at.asc().nulls_last(),
            PayoutStatusHistory.id.asc(),
        )
        .limit(HISTORY_LIMIT + 1)
        .cte("exact_payout_events")
    )
    clock = select(
        func.timezone("UTC", func.statement_timestamp()).label("generated_at")
    ).cte("exact_payout_clock")
    query = (
        select(clock, parent, events)
        .select_from(
            clock.outerjoin(parent, true()).outerjoin(
                events, parent.c.id == events.c.h_payout_id
            )
        )
        .order_by(events.c.h_created_at.asc().nulls_last(), events.c.h_id.asc())
    )
    rows = (await db.execute(query)).mappings().all()
    if rows[0]["id"] is None:
        raise HTTPException(404, "Retiro no encontrado en el ámbito autorizado")
    events = [history_row(r) for r in rows if r["h_id"] is not None]
    if len(events) > HISTORY_LIMIT:
        raise HTTPException(
            409,
            "El historial excede el límite de lectura completa; no se publica un historial parcial",
        )
    return envelope(
        actor,
        rows[0]["generated_at"],
        dict(rider_id=None, status=None, payout_id=str(payout_id), audience=audience),
        target,
        1,
        None,
        [payout_row(rows[0])],
        history=events,
    )
