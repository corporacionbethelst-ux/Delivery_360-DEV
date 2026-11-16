"""Exact registered records preserve units, missing snapshots and one read cut."""

import asyncio
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4, UUID
import pytest
from sqlalchemy import event, text
from app.core.security import create_access_token
from app.models.financial import Financial, PaymentStatus, TransactionType
from tests.test_financial_reports_exact_postgresql import (
    reports_db,
    quote_db,
    currency_db,
    ledger,
)  # noqa: F401

BASE = "/api/v1/financial/transactions/exact"


def get(f, params=None, id=None, role="GERENTE", status=200):
    response = f[0].get(
        BASE + ("/" + str(id) if id is not None else "/page"),
        params=params or {},
        headers=(
            {"Authorization": "Bearer " + create_access_token(f[2][role])}
            if role
            else {}
        ),
    )
    assert response.status_code == status, response.text
    return response.json()


@pytest.mark.asyncio
async def test_exact_strings_original_signs_and_registered_snapshots(reports_db):
    f = reports_db
    id = await ledger(
        f,
        "-0.10",
        TransactionType.RETIRO,
        balance_before=Decimal("99999999.99"),
        balance_after=None,
    )
    async with f[1]() as db:
        await db.execute(
            text("UPDATE financials SET balance_after=NULL WHERE id=:id"), {"id": id}
        )
        await db.commit()
    v = get(f, id=id)
    r = v["items"][0]
    assert (
        r["amount"] == "-0.10"
        and r["balance_before"] == "99999999.99"
        and r["balance_after"] is None
    )
    assert (
        r["currency"] == r["currency_recorded"] == "USD"
        and not r["currency_review"]
        and r["money_review"] == []
    )
    assert r["type"] == r["transaction_type"] == "RETIRO" and r["processed_at"] is None
    assert (
        not v["available_balance_included"]
        and not v["bank_verified"]
        and not v["wallet_cents_included"]
        and not v["customer_cashbook_included"]
    )
    assert (
        v["balance_basis"] == "registered_snapshots_not_available_balance"
        and v["snapshot_basis"] == "single_statement_visibility"
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "currency,expected,review",
    [
        (None, None, False),
        ("VES", "VES", False),
        ("COP", "COP", False),
        ("usd", None, True),
        ("", None, True),
    ],
)
async def test_currency_is_never_assumed_or_converted(
    reports_db, currency, expected, review
):
    f = reports_db
    id = await ledger(f, "0.20")
    async with f[1]() as db:
        await db.execute(
            text("UPDATE financials SET currency_code=:currency WHERE id=:id"),
            {"currency": currency, "id": id},
        )
        await db.commit()
    r = get(f, id=id)["items"][0]
    assert (
        r["currency"] == expected
        and r["currency_recorded"] == currency
        and r["currency_review"] == review
        and r["amount"] == "0.20"
    )


@pytest.mark.asyncio
async def test_bad_money_remains_visible_and_missing_values_are_not_zero(reports_db):
    f = reports_db
    bad = await ledger(f, "NaN", balance_before=Decimal("NaN"))
    healthy = await ledger(f, "0.00")
    async with f[1]() as db:
        await db.execute(
            text(
                "UPDATE financials SET balance_after=NULL,created_at=NULL,updated_at=NULL,status=NULL WHERE id=:id"
            ),
            {"id": bad},
        )
        await db.commit()
    v = get(f)
    assert len(v["items"]) == 2
    r = next(r for r in v["items"] if r["id"] == str(bad))
    assert (
        r["amount"] is None
        and r["balance_before"] is None
        and r["balance_after"] is None
    )
    assert r["money_review"] == [
        {"field": "amount", "reason": "IMPORTE_NO_VALIDO"},
        {"field": "balance_before", "reason": "IMPORTE_NO_VALIDO"},
    ]
    assert r["created_at"] is None and r["updated_at"] is None and r["status"] is None
    assert next(r for r in v["items"] if r["id"] == str(healthy))["amount"] == "0.00"
    # The original non-finite value is retained in PostgreSQL.
    async with f[1]() as db:
        assert (
            await db.scalar(
                text("SELECT amount::text FROM financials WHERE id=:id"), {"id": bad}
            )
            == "NaN"
        )


@pytest.mark.asyncio
async def test_all_registered_statuses_types_and_missing_dates_are_retained(reports_db):
    f = reports_db
    for status in PaymentStatus:
        await ledger(f, "0.10", TransactionType.WALLET_ADJUSTMENT, status)
    v = get(f)
    assert {r["status"] for r in v["items"]} == {s.value for s in PaymentStatus}
    assert all(
        r["type"] == "WALLET_ADJUSTMENT" and r["amount"] == "0.10" for r in v["items"]
    )
    v = get(
        f,
        {
            "type": "WALLET_ADJUSTMENT",
            "status": "RECHAZADO",
            "rider_id": str(f[2]["rider"]),
            "date_from": "2026-11-14T12:00:00-04:00",
            "date_to": "2026-11-14T16:00:00Z",
        },
    )
    assert (
        len(v["items"]) == 1
        and v["filters"]["date_from"]
        == v["filters"]["date_to"]
        == "2026-11-14T16:00:00.000000Z"
    )
    assert get(f, {"date_to": "2026-11-14"})["items"] == []


@pytest.mark.asyncio
async def test_tied_timestamps_have_uuid_order_and_exact_detail(reports_db):
    f = reports_db
    ids = [await ledger(f, "0.10"), await ledger(f, "0.20")]
    expected = sorted(map(str, ids), reverse=True)
    a = get(f, {"limit": 1})
    b = get(f, {"limit": 1, "offset": 1})
    assert [a["items"][0]["id"], b["items"][0]["id"]] == expected
    assert get(f, id=expected[1])["items"][0]["id"] == expected[1]
    empty = get(f, {"offset": 200})
    assert (
        empty["items"] == []
        and empty["total"] == 0
        and empty["generated_at"].endswith("Z")
    )
    get(f, id=uuid4(), status=404)


@pytest.mark.asyncio
async def test_single_statement_does_not_mix_concurrent_changes(reports_db):
    f = reports_db
    id = await ledger(f, "0.10", balance_after=Decimal("1.10"))
    seen = []

    async def write():
        async with f[1]() as db:
            await db.execute(
                text(
                    "UPDATE financials SET amount=0.20,balance_after=1.20 WHERE id=:id"
                ),
                {"id": id},
            )
            await db.commit()

    def listener(conn, cursor, statement, parameters, context, many):
        if "exact_transaction_clock" not in statement or seen:
            return
        seen.append(statement)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(lambda: asyncio.run(write())).result(timeout=15)

    event.listen(f[3].sync_engine, "after_cursor_execute", listener)
    try:
        before = get(f, id=id)["items"][0]
    finally:
        event.remove(f[3].sync_engine, "after_cursor_execute", listener)
    after = get(f, id=id)["items"][0]
    assert (
        len(seen) == 1
        and (before["amount"], before["balance_after"]) == ("0.10", "1.10")
        and (after["amount"], after["balance_after"]) == ("0.20", "1.20")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role,status",
    [
        (None, 401),
        ("GERENTE", 200),
        ("SUPERADMIN", 200),
        ("OPERADOR", 403),
        ("REPARTIDOR", 403),
        ("CLIENTE", 403),
        ("AUDITOR", 403),
    ],
)
async def test_staff_permissions_apply_before_record_lookup(reports_db, role, status):
    f = reports_db
    get(f, role=role, status=status)
    get(f, id=uuid4(), role=role, status=404 if status == 200 else status)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 501},
        {"offset": -1},
        {"offset": 9007199254740992},
        {"rider_id": "bad"},
        {"type": "NOT_A_TYPE"},
        {"status": "APROBADA"},
        {"date_from": "bad"},
        {"date_from": "2026-11-15", "date_to": "2026-11-14"},
    ],
)
async def test_invalid_filters_are_rejected(reports_db, params):
    get(reports_db, params, status=422)


@pytest.mark.asyncio
async def test_new_routes_preserve_numeric_legacy_contract(reports_db):
    f = reports_db
    id = await ledger(f, "0.10")
    response = f[0].get(
        "/api/v1/financial/transactions/" + str(id),
        headers={"Authorization": "Bearer " + create_access_token(f[2]["GERENTE"])},
    )
    assert (
        response.status_code == 200
        and isinstance(response.json()["amount"], float)
        and response.json()["amount"] == 0.1
    )
    assert get(f, id=id)["items"][0]["amount"] == "0.10"
    get(f, id="invalid", status=422)
