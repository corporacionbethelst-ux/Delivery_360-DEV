"""Owner-bound exact earnings and canonical reserved balance without order inference."""

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
import asyncio
import pytest
from sqlalchemy import select, text, event
from app.core.security import create_access_token
from app.models.financial import Financial, TransactionType, PaymentStatus
from app.models.payout import Payout, PayoutStatus
from app.models.rider import Rider
from app.services import rider_earnings_exact as service
from tests.test_financial_reports_exact_postgresql import (
    reports_db,
    quote_db,
    currency_db,
)  # noqa: F401

STAMP = datetime(2026, 11, 14, 16)


async def entry(
    f,
    amount="0.10",
    kind=TransactionType.PAGO_ENTREGA,
    before="0.00",
    after="0.10",
    tick=0,
    **kw,
):
    row = Financial(
        id=uuid4(),
        rider_id=f[2]["rider"],
        currency_code="USD",
        amount=Decimal(amount),
        transaction_type=kind,
        status=PaymentStatus.PROCESADO,
        balance_before=Decimal(before),
        balance_after=Decimal(after),
        created_at=STAMP + timedelta(microseconds=tick),
        **kw,
    )
    async with f[1]() as db:
        db.add(row)
        await db.commit()
    return row.id


async def withdrawal(f, amount="0.10", status=PayoutStatus.PENDIENTE):
    row = Payout(
        id=uuid4(),
        rider_id=f[2]["rider"],
        currency_code="USD",
        amount=Decimal(amount),
        status=status,
        requested_at=STAMP,
    )
    async with f[1]() as db:
        db.add(row)
        await db.commit()
    return row.id


def get(
    f, path="/financial/riders/me/report", role="REPARTIDOR", status=200, params=None
):
    r = f[0].get(
        "/api/v1" + path,
        params=params or {},
        headers=(
            {"Authorization": "Bearer " + create_access_token(f[2][role])}
            if role
            else {}
        ),
    )
    assert r.status_code == status, r.text
    return r.json()


@pytest.mark.asyncio
async def test_order_value_never_becomes_earnings_and_no_evidence_is_zero(reports_db):
    f = reports_db
    v = get(f)
    assert (
        v["lifetime"]["credit_usd"] == "0.00"
        and v["lifetime"]["completed_delivery_count"] == 0
        and v["rows"] == []
    )
    assert (
        v["user_id"] == str(f[2]["REPARTIDOR"])
        and v["rider_id"] == str(f[2]["rider"])
        and not v["order_values_included"]
    )
    b = get(f, "/payouts/balance/exact")
    assert (
        b["available"] == "0.00"
        and b["ledger_integrity"] == "no_evidence"
        and not b["bank_verified"]
    )


@pytest.mark.asyncio
async def test_exact_totals_canonical_direction_and_original_source_rows(reports_db):
    f = reports_db
    await entry(f, "-0.10")
    await entry(f, "0.20", TransactionType.BONO, before="0.10", after="0.30", tick=1)
    await entry(f, "0.07", TransactionType.RETIRO, before="0.30", after="0.23", tick=2)
    await entry(f, "-0.02", TransactionType.AJUSTE, before="0.23", after="0.21", tick=3)
    v = get(f)
    assert v["lifetime"] == dict(
        count=4,
        credit_usd="0.30",
        debit_usd="0.07",
        adjustment_usd="-0.02",
        net_change_usd="0.21",
        completed_delivery_count=1,
    )
    assert (
        all(r["rider_id"] == v["rider_id"] for r in v["rows"])
        and v["rows"][0]["delta_usd"] == "-0.02"
    )
    assert get(f, "/payouts/balance/exact")["available"] == "0.21"


@pytest.mark.asyncio
async def test_reservations_and_posted_debits_are_not_subtracted_twice(reports_db):
    f = reports_db
    await entry(f, "0.30", after="0.30")
    pid = await withdrawal(f)
    pending = get(f, "/payouts/balance/exact")
    assert (
        pending["available"] == "0.20"
        and pending["reserved"] == "0.10"
        and pending["pending"] == "0.10"
    )
    await entry(
        f,
        "0.10",
        TransactionType.RETIRO,
        before="0.30",
        after="0.20",
        tick=1,
        source_type="PAYOUT",
        source_id=str(pid),
    )
    async with f[1]() as db:
        await db.execute(
            text("UPDATE payouts SET status='EN_PROCESO' WHERE id=:id"), {"id": pid}
        )
        await db.commit()
    posted = get(f, "/payouts/balance/exact")
    assert (
        posted["available"] == "0.20"
        and posted["reserved"] == "0.00"
        and posted["processed"] == "0.10"
    )
    await withdrawal(f, "0.05", PayoutStatus.COMPLETADO)
    final = get(f, "/payouts/balance/exact")
    assert final["available"] == "0.15" and final["reserved"] == "0.05"
    legacy = get(f, "/payouts/balance")
    assert all(
        Decimal(str(legacy[k])) == Decimal(final[k])
        for k in (
            "available",
            "pending",
            "processed",
            "reserved",
            "ledger_balance",
            "total_earned",
        )
    )


@pytest.mark.asyncio
async def test_unknown_currency_is_preserved_and_never_funds_usd(reports_db):
    f = reports_db
    await entry(f, "0.30", after="0.30")
    old = await entry(f, "99.00", tick=1)
    p = await withdrawal(f, "99.00")
    async with f[1]() as db:
        await db.execute(
            text("UPDATE financials SET currency_code=NULL WHERE id=:id"), {"id": old}
        )
        await db.execute(
            text("UPDATE payouts SET currency_code=NULL WHERE id=:id"), {"id": p}
        )
        await db.commit()
    v = get(f)
    assert v["lifetime"]["credit_usd"] == "0.30" and v["excluded_count"] == 1
    assert next(r for r in v["rows"] if r["id"] == str(old))["amount_usd"] is None
    b = get(f, "/payouts/balance/exact")
    assert (
        b["available"] == "0.30"
        and b["unverified_financial_count"] == 1
        and b["unverified_payout_count"] == 1
    )


@pytest.mark.asyncio
async def test_corrupt_chain_cannot_publish_a_spendable_zero_or_balance(reports_db):
    f = reports_db
    await entry(f, after="9.99")
    get(f, "/payouts/balance/exact", status=409)


@pytest.mark.asyncio
async def test_owner_filter_cannot_be_selected_or_replaced(reports_db):
    f = reports_db
    async with f[1]() as db:
        other = Rider(user_id=f[2]["OTHER"])
        db.add(other)
        await db.flush()
        db.add(
            Financial(
                rider_id=other.id,
                currency_code="USD",
                amount=Decimal("99.00"),
                transaction_type=TransactionType.INGRESO,
                status=PaymentStatus.PROCESADO,
                created_at=STAMP,
                balance_before=0,
                balance_after=99,
            )
        )
        await db.commit()
    assert get(f)["rows"] == []
    for path in ("/financial/riders/me/report", "/payouts/balance/exact"):
        get(f, path, params={"rider_id": str(other.id)}, status=422)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["/financial/riders/me/report", "/payouts/balance/exact"]
)
@pytest.mark.parametrize(
    "role,status",
    [
        ("SUPERADMIN", 403),
        ("GERENTE", 403),
        ("OPERADOR", 403),
        ("AUDITOR", 403),
        ("CLIENTE", 403),
        (None, 401),
    ],
)
async def test_private_rider_roles(reports_db, path, role, status):
    get(reports_db, path, role=role, status=status)


@pytest.mark.asyncio
async def test_missing_profile_never_returns_a_fabricated_account(reports_db):
    f = reports_db
    async with f[1]() as db:
        await db.execute(
            text("UPDATE users SET role='REPARTIDOR' WHERE id=:id"),
            {"id": f[2]["OTHER"]},
        )
        await db.commit()
    for path in ("/financial/riders/me/report", "/payouts/balance/exact"):
        get(f, path, role="OTHER", status=403)


@pytest.mark.asyncio
async def test_future_and_undated_rows_visible_but_not_credited(reports_db):
    f = reports_db
    a = await entry(f)
    b = await entry(f, tick=1)
    async with f[1]() as db:
        await db.execute(
            text("UPDATE financials SET created_at=NULL WHERE id=:id"), {"id": a}
        )
        await db.execute(
            text(
                "UPDATE financials SET created_at=timezone('UTC',now()) + interval '1 day' WHERE id=:id"
            ),
            {"id": b},
        )
        await db.commit()
    v = get(f)
    assert v["lifetime"]["count"] == 0 and {
        r["exclusion_reason"] for r in v["rows"]
    } == {"FECHA_NO_REGISTRADA", "FECHA_FUTURA"}
    get(f, "/payouts/balance/exact", status=409)


@pytest.mark.asyncio
async def test_overflow_never_truncates_totals_or_export(reports_db, monkeypatch):
    f = reports_db
    await entry(f)
    await entry(f, tick=1)
    monkeypatch.setattr(service, "MAX_ROWS", 1)
    get(f, status=409)


@pytest.mark.asyncio
async def test_one_snapshot_survives_a_concurrent_backdated_credit(reports_db):
    f = reports_db
    seen = []

    def listener(conn, cursor, statement, params, ctx, many):
        if "owner_earnings_rows" not in statement or seen:
            return
        seen.append(statement)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(lambda: asyncio.run(entry(f))).result(timeout=15)

    event.listen(f[3].sync_engine, "after_cursor_execute", listener)
    try:
        first = get(f)
    finally:
        event.remove(f[3].sync_engine, "after_cursor_execute", listener)
    assert (
        len(seen) == 1
        and first["lifetime"]["credit_usd"] == "0.00"
        and get(f)["lifetime"]["credit_usd"] == "0.10"
    )
