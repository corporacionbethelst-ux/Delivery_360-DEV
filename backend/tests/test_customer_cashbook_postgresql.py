"""Verified customer cash flow, original currencies, bounded export and MVCC."""

from datetime import datetime, date, timezone
from pathlib import Path
import importlib.util
import json
import hashlib
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from app.core.security import create_access_token
from app.services import customer_cashbook as service
from tests.test_customer_refunds_postgresql import (
    refund_db,
    collection_db,
    quote_db,
    currency_db,
    paid,
    request,
    call as refund_call,
    path as refund_path,
    act,
    event,
    execute,
    settle,
)  # noqa: F401
from tests.test_customer_collections_postgresql import (
    declaration,
    call as collection_call,
    path as collection_path,
    review as collection_review,
    rate,
    quote_call,
)  # noqa: F401


async def migrate(engine, direction):
    spec = importlib.util.spec_from_file_location(
        "cashbook96",
        Path(__file__).parents[1]
        / "alembic/versions/20261115_customer_cashbook_indexes.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def apply(conn):
        with Operations.context(MigrationContext.configure(conn)):
            getattr(module, direction)()

    async with engine.begin() as conn:
        await conn.run_sync(apply)


@pytest.fixture
async def cashbook_db(refund_db):
    # quote_db uses the real day for PostgreSQL guards. Keep that same calendar
    # for the report; a frozen November 14 window loses later real fixtures.
    await migrate(refund_db[3], "upgrade")
    yield refund_db


def report(f, params=None, role="GERENTE", status=200):
    headers = (
        {"Authorization": "Bearer " + create_access_token(f[2][role])} if role else {}
    )
    response = f[0].get(
        "/api/v1/customer-cashbook/report", params=params or {}, headers=headers
    )
    assert response.status_code == status, response.text
    return response.json()


def test_caracas_calendar_and_half_open_bounds():
    now = datetime(2026, 11, 15, 2, tzinfo=timezone.utc)
    first, last, start, end = service.civil_window(None, None, now)
    assert (first, last) == (date(2026, 11, 8), date(2026, 11, 14))
    assert start == datetime(2026, 11, 8, 4) and end == datetime(2026, 11, 15, 4)
    service.civil_window(date(2026, 10, 15), date(2026, 11, 14), now)
    for a, b in [
        (date(2026, 10, 14), date(2026, 11, 14)),
        (date(2026, 11, 15), None),
        (date(2026, 11, 14), date(2026, 11, 13)),
    ]:
        with pytest.raises(Exception) as err:
            service.civil_window(a, b, now)
        assert err.value.status_code == 422


@pytest.mark.asyncio
async def test_empty_read_only_report_complete_and_hashed(cashbook_db):
    f = cashbook_db
    value = report(f, role="AUDITOR")
    assert value["summary"] == dict(
        collection_count=0,
        refund_count=0,
        entry_count=0,
        collection_usd="0.00",
        refund_usd="0.00",
        net_usd="0.00",
    )
    assert (
        len(value["daily"]) == 7
        and len(value["currencies"]) == 2
        and len(value["methods"]) == 5
    )
    assert (
        value["rows"] == [] and value["export_complete"] and not value["bank_verified"]
    )
    digest = value.pop("content_sha256")
    assert (
        digest
        == hashlib.sha256(
            json.dumps(
                value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest()
    )
    async with f[1]() as db:
        assert await db.scalar(text("SELECT count(*) FROM customer_refund_events")) == 0
        assert (
            await db.scalar(text("SELECT count(*) FROM customer_collection_reviews"))
            == 0
        )


@pytest.mark.asyncio
async def test_only_verifications_are_recognized_and_original_rate_preserved(
    cashbook_db,
):
    f = cashbook_db
    original = await paid(f, ves=True)
    initial = report(f)
    assert initial["summary"]["collection_usd"] == "0.50"
    assert initial["currencies"][1]["collection_original"] == "0.75"
    r = refund_call(f, "POST", refund_path(f), request(original), status=201)
    act(f, r, event())
    act(f, r, execute(r), role="SUPERADMIN")
    assert report(f)["summary"]["refund_count"] == 0
    act(f, r, event("VERIFICAR_DEVOLUCION", 2))
    current = quote_call(f, "GET", "/context")["current_rate"]
    rate(f, current["id"], "99.00000000")
    value = report(f)
    assert value["summary"]["net_usd"] == "0.30"
    assert value["currencies"][1]["net_original"] == "0.45"
    row = value["rows"][0]
    assert row["kind"] == "DEVOLUCION" and row["amount_original"] == "0.30"
    assert row["bcv_rate"] == "1.50000000" and row["verified_by"] != row["declared_by"]
    assert row["refund_id"] == r["id"] and row["collection_id"] == original["id"]
    assert sum(day["entry_count"] for day in value["daily"]) == 2


@pytest.mark.asyncio
async def test_cumulative_partial_refunds_close_exact_original_cents(cashbook_db):
    f = cashbook_db
    original = await paid(f, ves=True)
    for revision, (usd, physical) in enumerate(
        [("0.01", "0.02"), ("0.01", "0.01"), ("0.48", "0.72")]
    ):
        r = refund_call(
            f, "POST", refund_path(f), request(original, usd, revision * 4), status=201
        )
        assert r["return_amount"] == physical
        settle(f, r)
    value = report(f)
    assert value["summary"]["net_usd"] == "0.00"
    assert value["currencies"][1]["net_original"] == "0.00"
    assert value["summary"]["refund_count"] == 3
    assert sorted(
        r["amount_original"] for r in value["rows"] if r["kind"] == "DEVOLUCION"
    ) == ["0.01", "0.02", "0.72"]


@pytest.mark.asyncio
async def test_observed_execution_retry_has_one_final_outflow(cashbook_db):
    f = cashbook_db
    original = await paid(f)
    r = refund_call(f, "POST", refund_path(f), request(original), status=201)
    act(f, r, event())
    first = execute(r)
    act(f, r, first, role="SUPERADMIN")
    act(f, r, event("OBSERVAR_EJECUCION", 2))
    act(f, r, event("CONFIRMAR_NO_EJECUTADA", 3))
    second = execute(r, 4)
    act(f, r, second, role="SUPERADMIN")
    act(f, r, event("VERIFICAR_DEVOLUCION", 5))
    value = report(f)
    refunds = [r for r in value["rows"] if r["kind"] == "DEVOLUCION"]
    assert len(refunds) == 1 and refunds[0]["reference_key"] == second["reference_key"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role,status",
    [
        ("SUPERADMIN", 200),
        ("GERENTE", 200),
        ("AUDITOR", 200),
        ("OPERADOR", 403),
        ("CLIENTE", 403),
        ("REPARTIDOR", 403),
        (None, 401),
    ],
)
async def test_report_roles(cashbook_db, role, status):
    report(cashbook_db, role=role, status=status)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"unknown": "x"},
        [("currency", "USD"), ("currency", "VES")],
        {"date_from": "2026-2-01"},
        {"date_to": "2099-01-01"},
        {"date_from": "2026-01-01", "date_to": "2026-03-01"},
        {"method": "CARD"},
        {"currency": "EUR"},
        {"source_key": "\n"},
    ],
)
async def test_reject_ambiguous_or_invalid_filters(cashbook_db, params):
    report(cashbook_db, params, status=422)


@pytest.mark.asyncio
async def test_filters_and_refund_only_period_net_can_be_negative(cashbook_db):
    f = cashbook_db
    original = await paid(f)
    r = refund_call(f, "POST", refund_path(f), request(original), status=201)
    settle(f, r)
    value = report(f, {"source_key": " caja devoluciones "})
    assert value["filters"]["source_key"] == "CAJA DEVOLUCIONES"
    assert (
        value["summary"]["net_usd"] == "-0.20"
        and value["summary"]["collection_count"] == 0
    )
    assert report(f, {"currency": "VES"})["rows"] == []
    assert report(f, {"method": "TRANSFERENCIA"})["rows"] == []


@pytest.mark.asyncio
async def test_overflow_refuses_incomplete_export(cashbook_db, monkeypatch):
    f = cashbook_db
    original = await paid(f)
    settle(f, refund_call(f, "POST", refund_path(f), request(original), status=201))
    monkeypatch.setattr(service, "MAX_ROWS", 1)
    assert "reduce" in report(f, status=409)["detail"]


@pytest.mark.asyncio
async def test_index_downgrade_preserves_populated_book(cashbook_db):
    f = cashbook_db
    original = await paid(f)
    settle(f, refund_call(f, "POST", refund_path(f), request(original), status=201))
    before = report(f)
    await migrate(f[3], "downgrade")
    after = report(f)
    assert before["rows"] == after["rows"] and before["summary"] == after["summary"]
    await migrate(f[3], "upgrade")
    assert report(f)["rows"] == before["rows"]


@pytest.mark.asyncio
async def test_one_statement_snapshot_survives_concurrent_verification(cashbook_db):
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy import event as sql_event

    f = cashbook_db
    original = await paid(f)
    r = refund_call(f, "POST", refund_path(f), request(original), status=201)
    act(f, r, event())
    act(f, r, execute(r), role="SUPERADMIN")
    seen = []

    def after_query(conn, cursor, statement, parameters, context, executemany):
        if "bounded_entries" not in statement or seen:
            return
        seen.append(statement)
        # The reader already has its one PostgreSQL snapshot. A separate real
        # request commits a new verification before Python totals are assembled.
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(act, f, r, event("VERIFICAR_DEVOLUCION", 2)).result(timeout=15)

    sql_event.listen(f[3].sync_engine, "after_cursor_execute", after_query)
    try:
        value = report(f)
    finally:
        sql_event.remove(f[3].sync_engine, "after_cursor_execute", after_query)
    assert len(seen) == 1
    assert value["summary"]["net_usd"] == "0.50" and len(value["rows"]) == 1
    next_value = report(f)
    assert next_value["summary"]["net_usd"] == "0.30" and len(next_value["rows"]) == 2
