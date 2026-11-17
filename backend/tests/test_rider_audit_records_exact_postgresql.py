"""Exact operational table records: own source units, bounded pages and SQL cuts."""

import asyncio, hashlib, json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4
import pytest
from sqlalchemy import select, text, event
from app.models.order import Order, OrderStatus
from app.models.delivery import Delivery, DeliveryStatus
from app.models.financial import Financial
from app.core.security import create_access_token
from tests.test_financial_reports_exact_postgresql import (
    reports_db,
    quote_db,
    currency_db,
    ledger,
)  # noqa: F401

PATH = "/api/v1/riders/audit/records/exact"
STAMP = datetime(2026, 11, 16, 12)


@pytest.fixture
async def records_db(reports_db):
    f = reports_db
    async with f[1]() as db:
        await db.execute(
            text("UPDATE orders SET assigned_rider_id=:rider WHERE id=:id"),
            dict(rider=f[2]["rider"], id=f[2]["order"]),
        )
        await db.commit()
    return f


def get(f, kind="orders", offset=0, limit=51, role="GERENTE", status=200, **extra):
    params = dict(rider_id=str(f[2]["rider"]), kind=kind, offset=offset, limit=limit)
    params.update(extra)
    r = f[0].get(
        PATH,
        params=params,
        headers=(
            {"Authorization": "Bearer " + create_access_token(f[2][role])}
            if role
            else {}
        ),
    )
    assert r.status_code == status, r.text
    return r.json()


async def order(f, **extra):
    v = dict(
        id=uuid4(),
        assigned_rider_id=f[2]["rider"],
        customer_name="Synthetic",
        customer_phone="1",
        pickup_address="A",
        delivery_address="B",
        status=OrderStatus.ASIGNADO,
        currency_code="USD",
        created_at=STAMP,
    )
    v.update(extra)
    async with f[1]() as db:
        row = Order(**v)
        db.add(row)
        await db.commit()
        return row.id


async def delivery(f, oid=None, **extra):
    oid = oid or await order(f)
    v = dict(
        id=uuid4(),
        order_id=oid,
        rider_id=f[2]["rider"],
        status=DeliveryStatus.COMPLETADA,
        locked_bonus_amount=Decimal("0.10"),
        created_at=STAMP,
    )
    v.update(extra)
    async with f[1]() as db:
        row = Delivery(**v)
        db.add(row)
        await db.commit()
        return row.id


@pytest.mark.asyncio
async def test_exact_order_price_never_uses_legacy_float_and_hash(records_db):
    f = records_db
    v = get(f)
    r = v["items"][0]
    assert (
        r["amount"] == "0.50"
        and r["price_review"] is None
        and r["pricing_revision"] == 1
    )
    assert r["currency"] == "USD" and v["viewer_user_id"] == str(f[2]["GERENTE"])
    assert (
        v["amount_basis"] == "exact_order_price_not_rider_earnings"
        and not v["bank_verified"]
        and not v["available_balance_included"]
    )
    digest = v.pop("content_sha256")
    assert (
        digest
        == hashlib.sha256(
            json.dumps(
                v, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest()
    )
    oid = await order(f, total=999999.99, subtotal=999999.99)
    row = next(r for r in get(f)["items"] if r["id"] == str(oid))
    assert row["amount"] is None and row["price_review"] == "PRECIO_HISTORICO_NO_EXACTO"


@pytest.mark.asyncio
@pytest.mark.parametrize("unit", [None, "VES", "COP", "usd", ""])
async def test_original_units_never_relabel_unknown_historical_orders(records_db, unit):
    f = records_db
    oid = await order(f, currency_code=unit, total=10)
    row = next(r for r in get(f)["items"] if r["id"] == str(oid))
    assert row["currency_recorded"] == unit and row["currency"] == (
        unit if unit in ("VES", "COP") else None
    )
    assert row["amount"] is None and row["price_review"] == "PRECIO_HISTORICO_NO_EXACTO"


@pytest.mark.asyncio
async def test_bonus_is_decimal_but_not_denomination_of_order_or_linked_ledger(
    records_db,
):
    f = records_db
    did = await delivery(f, f[2]["order"])
    await ledger(f, "0.10", source_type="delivery", source_id=str(did))
    v = get(f, "deliveries")
    r = v["items"][0]
    assert (
        r["locked_bonus_amount"] == "0.10"
        and r["currency"] is None
        and r["currency_recorded"] is None
    )
    assert r["currency_basis"] == "not_recorded_on_delivery" and not r["money_review"]
    assert r["fallback"] is False and not v["fallback"]
    assert v["amount_basis"] == "locked_delivery_bonus_not_ledger"


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", [None, "0.00", "-0.01", "NaN"])
async def test_missing_zero_and_invalid_locked_bonuses_do_not_hide_other_rows(
    records_db, amount
):
    f = records_db
    bad = await delivery(
        f, locked_bonus_amount=None if amount is None else Decimal(amount)
    )
    healthy = await delivery(f)
    rows = get(f, "deliveries")["items"]
    assert len(rows) == 2
    badrow = next(r for r in rows if r["id"] == str(bad))
    assert badrow["locked_bonus_amount"] == ("0.00" if amount == "0.00" else None)
    assert bool(badrow["money_review"]) == (amount in ("-0.01", "NaN"))
    assert (
        next(r for r in rows if r["id"] == str(healthy))["locked_bonus_amount"]
        == "0.10"
    )


@pytest.mark.asyncio
async def test_real_pagination_is_separate_from_bounded_order_support(records_db):
    f = records_db
    await order(f)
    for _ in range(52):
        await delivery(f)
    for _ in range(51):
        await order(f)
    first = get(f, "deliveries")
    assert (
        len(first["items"]) == 51
        and len(first["fallback"]) == 50
        and first["fallback_has_more"]
    )
    assert all(
        r["fallback"] and r["locked_bonus_amount"] is None for r in first["fallback"]
    )
    assert not {r["order_id"] for r in first["fallback"]} & {
        r["order_id"] for r in first["items"]
    }
    second = get(f, "deliveries", offset=50)
    assert (
        len(second["items"]) == 2
        and second["fallback"] == []
        and not second["fallback_has_more"]
    )
    assert first["items"][50]["id"] == second["items"][0]["id"]


@pytest.mark.asyncio
async def test_tied_and_null_dates_have_stable_identity_order(records_db):
    f = records_db
    for i in (1, 2):
        await order(f, id=UUID(int=i), created_at=STAMP)
    async with f[1]() as db:
        await db.execute(
            text("UPDATE orders SET created_at=NULL WHERE id=:id"),
            {"id": f[2]["order"]},
        )
        await db.commit()
    rows = get(f)["items"]
    assert [r["id"] for r in rows[:2]] == [str(UUID(int=2)), str(UUID(int=1))] and rows[
        -1
    ]["created_at"] is None


@pytest.mark.asyncio
async def test_foreign_rider_records_are_excluded_and_missing_profile_is_404(
    records_db,
):
    f = records_db
    async with f[1]() as db:
        await db.execute(
            text("UPDATE orders SET assigned_rider_id=NULL WHERE id=:id"),
            {"id": f[2]["order"]},
        )
        await db.commit()
    assert not get(f)["items"]
    get(f, rider_id=str(uuid4()), status=404)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role,status",
    [
        (None, 401),
        ("GERENTE", 200),
        ("SUPERADMIN", 200),
        ("OPERADOR", 403),
        ("REPARTIDOR", 403),
        ("AUDITOR", 403),
        ("CLIENTE", 403),
    ],
)
async def test_roles(records_db, role, status):
    get(records_db, role=role, status=status)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"kind": "transactions"},
        {"limit": 52},
        {"offset": -1},
        {"rider_id": "other"},
        {"currency": "USD"},
    ],
)
async def test_invalid_queries_do_not_broaden_scope(records_db, params):
    get(records_db, status=422, **params)


@pytest.mark.asyncio
async def test_records_and_support_share_one_sql_visibility(records_db):
    f = records_db
    oid = await order(f)
    writer = ThreadPoolExecutor(max_workers=1)
    future = []

    def insert_on_snapshot(conn, cursor, statement, parameters, context, executemany):
        if "audit_records_clock" not in statement or future:
            return
        # The concurrent delivery insertion must never produce both a real and fallback row.
        future.append(writer.submit(lambda: asyncio.run(delivery(f, oid))))
        future[0].result(timeout=15)

    event.listen(f[3].sync_engine, "before_cursor_execute", insert_on_snapshot)
    try:
        v = get(f, "deliveries")
    finally:
        event.remove(f[3].sync_engine, "before_cursor_execute", insert_on_snapshot)
        writer.shutdown()
    assert any(r["order_id"] == str(oid) for r in v["items"])
    assert all(r["order_id"] != str(oid) for r in v["fallback"])


@pytest.mark.asyncio
async def test_nullable_record_state_and_clock_on_empty_pages(records_db):
    f = records_db
    did = await delivery(f, locked_bonus_amount=None)
    async with f[1]() as db:
        await db.execute(
            text("UPDATE deliveries SET status=NULL WHERE id=:id"), {"id": did}
        )
        await db.commit()
    assert get(f, "deliveries")["items"][0]["status"] is None
    v = get(f, offset=9999)
    assert v["items"] == [] and v["total"] == 0 and v["generated_at"].endswith("Z")


@pytest.mark.parametrize(
    "change",
    [
        {"subtotal_exact": None},
        {"total_exact": Decimal("NaN")},
        {"pricing_revision": 0},
        {"pricing_version": 2},
        {"currency_code": "VES"},
        {"total_exact": Decimal("0.31")},
        {"items_exact": [{"quantity": "2", "unit_price": "0.10", "subtotal": "0.30"}]},
    ],
)
def test_inconsistent_registered_price_is_reviewed_without_converting_legacy_values(
    change,
):
    from app.services.rider_audit_records_exact import order_row

    values = dict(
        id=uuid4(),
        rider_id=uuid4(),
        external_id=None,
        customer_name="Synthetic",
        status="ASIGNADO",
        created_at=None,
        updated_at=None,
        currency_code="USD",
        pricing_version=1,
        pricing_revision=1,
        subtotal_exact=Decimal("0.30"),
        delivery_fee_exact=Decimal("0.00"),
        total_exact=Decimal("0.30"),
        items_exact=[],
    )
    values.update(change)
    row = order_row(values)
    assert row["amount"] is None and row["price_review"] == "PRECIO_POR_REVISAR"
