"""Exact report semantics, complete export, currency exclusions and consistent reads."""

from datetime import datetime, timezone, date
from decimal import Decimal
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
import asyncio, hashlib, json
import pytest
from sqlalchemy import MetaData, select, text, event
from app.models.financial import Financial, TransactionType, PaymentStatus
from app.models.payout import Payout, PayoutStatus
from app.models.rider import Rider
from app.models.order import Order
from app.core.security import create_access_token
from app.services import financial_reports_exact as service, order_pricing
from tests.test_order_currency_quote_postgresql import (
    quote_db,
    currency_db,
)  # noqa: F401

STAMP = datetime(2026, 11, 14, 16)


@pytest.fixture
async def reports_db(quote_db):
    f = quote_db
    metadata = MetaData()
    tables = {Financial.__table__, Payout.__table__}
    while True:
        more = tables | {
            fk.column.table for table in tables for fk in table.foreign_keys
        }
        if more == tables:
            break
        tables = more
    for table in tables:
        table.to_metadata(metadata)
    async with f[3].begin() as db:
        await db.run_sync(metadata.create_all)
    async with f[1]() as db:
        rider = await db.scalar(select(Rider.id))
        f[2]["rider"] = rider
        await db.execute(
            text("UPDATE orders SET created_at=:stamp, ordered_at=:stamp"),
            {"stamp": STAMP},
        )
        await db.commit()
    yield f


def get(f, params=None, role="GERENTE", status=200):
    response = f[0].get(
        "/api/v1/financial/reports/exact",
        params=params or {"date_from": "2026-11-14", "date_to": "2026-11-14"},
        headers=(
            {"Authorization": "Bearer " + create_access_token(f[2][role])}
            if role
            else {}
        ),
    )
    assert response.status_code == status, response.text
    return response.json()


async def seed(f, model, **values):
    async with f[1]() as db:
        row = model(id=uuid4(), rider_id=f[2]["rider"], currency_code="USD", **values)
        db.add(row)
        await db.commit()
        return row.id


async def ledger(
    f,
    amount,
    kind=TransactionType.PAGO_ENTREGA,
    status=PaymentStatus.PROCESADO,
    **extra,
):
    return await seed(
        f,
        Financial,
        amount=Decimal(amount),
        transaction_type=kind,
        status=status,
        created_at=STAMP,
        **extra,
    )


async def payout(f, amount, status=PayoutStatus.PENDIENTE, **extra):
    return await seed(
        f, Payout, amount=Decimal(amount), status=status, requested_at=STAMP, **extra
    )


@pytest.mark.asyncio
async def test_exact_order_values_are_separate_from_collection_and_ledger(reports_db):
    f = reports_db
    v = get(f)
    assert (
        v["orders"]["total_usd"] == "0.50"
        and v["orders"]["subtotal_usd"] == "0.30"
        and v["orders"]["delivery_fee_usd"] == "0.20"
    )
    assert (
        v["ledger"]["net_change_usd"] == "0.00" and v["payouts"]["amount_usd"] == "0.00"
    )
    assert (
        not v["bank_verified"]
        and not v["customer_cashbook_included"]
        and not v["wallet_cents_included"]
    )
    assert (
        v["snapshot_basis"] == "single_statement_visibility"
        and v["period_start"] == "2026-11-14T04:00:00.000000Z"
    )
    assert v["row_count"] == 1 and v["rows"][0]["key"] == "ORDEN:" + str(f[2]["order"])
    digest = v.pop("content_sha256")
    assert (
        digest
        == hashlib.sha256(
            json.dumps(
                v, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest()
    )


@pytest.mark.asyncio
async def test_canonical_directions_signed_adjustment_and_payouts_never_double_count(
    reports_db,
):
    f = reports_db
    await ledger(f, "-0.10")
    await ledger(f, "0.20", TransactionType.BONO)
    await ledger(f, "-0.07", TransactionType.DESCUENTO)
    await ledger(f, "0.05", TransactionType.RETIRO)
    await ledger(f, "0.01", TransactionType.AJUSTE_MANUAL)
    await ledger(f, "-0.03", TransactionType.AJUSTE)
    for status in PayoutStatus:
        await payout(f, "0.05", status)
    v = get(f)
    assert (
        v["ledger"]["credit_usd"] == "0.30"
        and v["ledger"]["debit_usd"] == "0.13"
        and v["ledger"]["adjustment_usd"] == "-0.03"
        and v["ledger"]["net_change_usd"] == "0.14"
    )
    assert v["payouts"]["amount_usd"] == "0.30" and all(
        r["count"] == 1 for r in v["payouts"]["by_status"]
    )
    assert v["payout_basis"] == "requests_created_in_period_current_status"
    assert v["daily"][0]["ledger"] == {
        k: v["ledger"][k]
        for k in (
            "count",
            "credit_usd",
            "debit_usd",
            "adjustment_usd",
            "net_change_usd",
        )
    }
    assert all(
        isinstance(r["amount_usd"], str) for r in v["rows"] if r["kind"] != "ORDEN"
    )


@pytest.mark.asyncio
async def test_unknown_units_prices_unprocessed_and_other_book_types_excluded(
    reports_db,
):
    f = reports_db
    unknown = await ledger(f, "99.99")
    pending = await ledger(f, "99.99", status=PaymentStatus.PENDIENTE)
    unsupported = await ledger(f, "99.99", TransactionType.DELIVERY_BONUS)
    cash = await payout(f, "99.99")
    async with f[1]() as db:
        await db.execute(
            text("UPDATE financials SET currency_code=NULL WHERE id=:id"),
            {"id": unknown},
        )
        await db.execute(
            text("UPDATE payouts SET currency_code=NULL WHERE id=:id"), {"id": cash}
        )
        # Preserve a genuinely old Float-only order; no copied exact columns.
        old = Order(
            id=uuid4(),
            customer_name="Legacy",
            customer_phone="123",
            pickup_address="A",
            delivery_address="B",
            currency_code="USD",
            subtotal=0.1,
            delivery_fee=0.2,
            total=0.30000000000000004,
            created_at=STAMP,
            ordered_at=STAMP,
        )
        db.add(old)
        await db.commit()
    v = get(f)
    counts = {r["reason"]: r["count"] for r in v["exclusions"]}
    assert (
        counts["MONEDA_NO_VERIFICADA"] == 2
        and counts["PRECIO_NO_EXACTO"] == 1
        and counts["ESTADO_NO_PROCESADO"] == 1
        and counts["TIPO_NO_ADMITIDO"] == 1
    )
    assert (
        v["orders"]["count"] == 1
        and v["ledger"]["count"] == 0
        and v["payouts"]["count"] == 0
        and v["excluded_count"] == 5
    )
    assert all(
        r["amount_usd"] is None and r["total_usd"] is None
        for r in v["rows"]
        if not r["included"]
    )


@pytest.mark.asyncio
async def test_undated_records_are_visible_as_excluded_and_future_outside_window_hidden(
    reports_db,
):
    f = reports_db
    uid = await ledger(f, "0.10")
    async with f[1]() as db:
        await db.execute(
            text("UPDATE financials SET created_at=NULL WHERE id=:id"), {"id": uid}
        )
        await db.commit()
    v = get(f)
    row = next(r for r in v["rows"] if r["id"] == str(uid))
    assert (
        row["occurred_at"] is None and row["exclusion_reason"] == "FECHA_NO_REGISTRADA"
    )
    assert (
        v["ledger"]["count"] == 0 and v["sources"]["MOVIMIENTO"]["excluded_count"] == 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role,status",
    [
        ("SUPERADMIN", 200),
        ("GERENTE", 200),
        ("AUDITOR", 403),
        ("OPERADOR", 403),
        ("CLIENTE", 403),
        ("REPARTIDOR", 403),
        (None, 401),
    ],
)
async def test_roles_preserve_existing_financial_permissions(reports_db, role, status):
    get(reports_db, role=role, status=status)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"bad": "1"},
        [("date_from", "2026-11-14"), ("date_from", "2026-11-14")],
        {"date_to": "2099-01-01"},
        {"date_to": "2026-2-1"},
        {"date_from": "2026-01-01", "date_to": "2026-03-01"},
    ],
)
async def test_invalid_or_ambiguous_ranges_rejected(reports_db, params):
    get(reports_db, params, status=422)


@pytest.mark.asyncio
async def test_overflow_never_returns_truncated_totals_or_csv(reports_db, monkeypatch):
    f = reports_db
    await ledger(f, "0.01")
    monkeypatch.setattr(service, "MAX_ROWS", 1)
    assert "5000" in get(f, status=409)["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize("model,amount", [(Financial, "NaN"), (Payout, "-0.01")])
async def test_invalid_included_numeric_cannot_silently_become_zero(
    reports_db, model, amount
):
    f = reports_db
    if model == Financial:
        await ledger(f, amount)
    else:
        await payout(f, amount)
    get(f, status=409)


@pytest.mark.asyncio
async def test_empty_range_is_complete_and_zero_not_a_connection_failure(reports_db):
    v = get(reports_db, {"date_from": "2026-11-01", "date_to": "2026-11-01"})
    assert (
        v["rows"] == []
        and v["row_count"] == 0
        and v["orders"]["total_usd"] == "0.00"
        and len(v["daily"]) == 1
        and v["export_complete"]
    )


@pytest.mark.asyncio
async def test_one_read_snapshot_not_changed_by_concurrent_insert_and_no_source_writes(
    reports_db,
):
    f = reports_db
    seen = []

    async def write():
        await ledger(f, "0.01")

    def listener(conn, cursor, statement, parameters, context, many):
        if "exact_financial_rows" not in statement or seen:
            return
        seen.append(statement)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(lambda: asyncio.run(write())).result(timeout=15)

    event.listen(f[3].sync_engine, "after_cursor_execute", listener)
    try:
        before = get(f)
    finally:
        event.remove(f[3].sync_engine, "after_cursor_execute", listener)
    after = get(f)
    assert (
        len(seen) == 1
        and before["ledger"]["count"] == 0
        and after["ledger"]["net_change_usd"] == "0.01"
    )
    again = get(f)
    assert (
        after["rows"] == again["rows"]
        and after["orders"] == again["orders"]
        and after["ledger"] == again["ledger"]
    )
