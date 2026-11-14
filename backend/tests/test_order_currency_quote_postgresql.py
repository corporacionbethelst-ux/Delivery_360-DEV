"""Real immutable order quotations, SQL guards, replay and transaction races."""

import asyncio
from concurrent.futures import Future
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import importlib.util
from pathlib import Path
from uuid import uuid4, UUID

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import DBAPIError

from app.core.security import create_access_token
from app.models.order import Order, OrderStatus
from app.models.delivery import Delivery
from app.models.order_currency_quote import OrderCurrencyQuote
from app.models.currency import BcvRate
from app.models.user import User, UserRole
from app.models.audit_log import AuditLog
from app.services import bcv_currency as currency, order_pricing
from tests.test_bcv_currency_postgresql import currency_db  # noqa: F401
from tests.test_order_pricing_exact import install as install_exact
from tests.test_assignment_concurrency_postgresql import wait_for_blocker


def revision_module():
    spec = importlib.util.spec_from_file_location(
        "order_quotes93",
        Path(__file__).parents[1] / "alembic/versions/20261114_order_bcv_quotes.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def migration(engine, direction):
    def operation(conn):
        with Operations.context(MigrationContext.configure(conn)):
            getattr(revision_module(), direction)()

    async with engine.begin() as connection:
        await connection.run_sync(operation)


def call(fixture, method, path, body=None, role="SUPERADMIN", status=200):
    client, _, ids, _ = fixture
    response = client.request(
        method,
        "/api/v1/currency" + path,
        headers={"Authorization": "Bearer " + create_access_token(ids[role])},
        json=body,
    )
    assert response.status_code == status, response.text
    return response.json()


def rate(fixture, previous=None, value="1.50000000"):
    day = currency.current_day().isoformat()
    return call(
        fixture,
        "POST",
        "/rates",
        {
            "request_key": str(uuid4()),
            "previous_rate_id": previous,
            "valid_on": day,
            "reference_date": day,
            "ves_per_usd": value,
            "note": "Synthetic reference for order quote tests",
            "confirmed_bcv": True,
        },
        status=201,
    )


@pytest.fixture
async def quote_db(currency_db, monkeypatch):
    client, sessions, ids, engine = currency_db
    # Use the actual Caracas day so the SQL clock guard stays portable.
    monkeypatch.setattr(currency, "utc_now", lambda: datetime.now(timezone.utc))
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda conn: Order.__table__.create(conn, checkfirst=True)
        )
        await connection.run_sync(
            lambda conn: Delivery.__table__.create(conn, checkfirst=True)
        )
    await install_exact(engine)
    await migration(engine, "upgrade")
    async with sessions() as db:
        order = Order(
            customer_name="Synthetic",
            customer_phone="123",
            pickup_address="A",
            delivery_address="B",
            status=OrderStatus.PENDIENTE,
            currency_code="USD",
            external_id="ORDER93",
        )
        order_pricing.apply(
            order,
            order_pricing.calculate(
                [{"product_name": "Decimal", "quantity": "3", "unit_price": "0.10"}],
                delivery_fee="0.20",
            ),
        )
        db.add(order)
        await db.commit()
        ids["order"] = order.id
    yield currency_db


def command(fixture, rate_id, revision=1, key=None):
    return {
        "request_key": key or str(uuid4()),
        "rate_id": rate_id,
        "expected_pricing_revision": revision,
    }


def path(fixture):
    return "/orders/" + str(fixture[2]["order"]) + "/quotes"


@pytest.mark.asyncio
async def test_exact_receipt_replay_preserves_original_price_rate_and_zero(
    quote_db, monkeypatch
):
    fixture = quote_db
    reference = rate(fixture)
    body = command(fixture, reference["id"])
    first = call(fixture, "POST", path(fixture), body, status=201)
    assert (first["amount_usd"], first["amount_ves"], first["pricing"]["revision"]) == (
        "0.50",
        "0.75",
        1,
    )
    assert (
        first["request_key"] == body["request_key"]
        and first["pricing"]["items"][0]["subtotal"] == "0.30"
    )
    assert first["quotation_only"] and first["payment_confirmed"] is False
    rate(fixture, reference["id"], "2.00000000")
    client, sessions, ids, _ = fixture
    response = client.patch(
        "/api/v1/orders/" + str(ids["order"]),
        headers={"Authorization": "Bearer " + create_access_token(ids["SUPERADMIN"])},
        json={"delivery_fee": "0.30", "expected_pricing_revision": 1},
    )
    assert response.status_code == 200, response.text
    assert call(fixture, "GET", "/order-quotes/" + first["id"]) == first
    assert call(fixture, "POST", path(fixture), body, status=201) == first
    day = currency.current_day()
    monkeypatch.setattr(currency, "current_day", lambda: day + timedelta(days=1))
    assert call(fixture, "POST", path(fixture), body, status=201) == first
    context = call(fixture, "GET", path(fixture))
    assert context["pricing"]["revision"] == 2 and context["current_rate"] is None
    assert context["receipts"] == [first]
    call(
        fixture, "POST", path(fixture), command(fixture, reference["id"], 2), status=409
    )
    async with sessions() as db:
        assert await db.scalar(select(func.count(OrderCurrencyQuote.id))) == 1
        assert (
            await db.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.resource_type == "ORDER_USD_VES_QUOTE"
                )
            )
            == 1
        )


@pytest.mark.asyncio
async def test_zero_half_up_and_no_client_amount_override(quote_db):
    fixture = quote_db
    reference = rate(fixture)
    client, _, ids, _ = fixture

    def reprice(amount, expected):
        response = client.patch(
            "/api/v1/orders/" + str(ids["order"]),
            headers={
                "Authorization": "Bearer " + create_access_token(ids["SUPERADMIN"])
            },
            json={
                "items": [],
                "subtotal": amount,
                "delivery_fee": "0.00",
                "expected_pricing_revision": expected,
            },
        )
        assert response.status_code == 200, response.text

    reprice("0.01", 1)
    first = call(
        fixture, "POST", path(fixture), command(fixture, reference["id"], 2), status=201
    )
    assert first["amount_ves"] == "0.02"
    reprice("0.00", 2)
    zero = call(
        fixture, "POST", path(fixture), command(fixture, reference["id"], 3), status=201
    )
    assert zero["amount_usd"] == zero["amount_ves"] == "0.00"
    for change in [
        {"amount_usd": "100"},
        {"order_id": str(uuid4())},
        {"expected_pricing_revision": True},
        {"expected_pricing_revision": "3"},
        {"rate_id": "bad"},
    ]:
        call(
            fixture,
            "POST",
            path(fixture),
            {**command(fixture, reference["id"], 3), **change},
            status=422,
        )


@pytest.mark.asyncio
async def test_price_or_rate_conflict_and_history_require_explicit_review(quote_db):
    fixture = quote_db
    reference = rate(fixture)
    call(
        fixture,
        "POST",
        path(fixture),
        command(fixture, reference["id"], 99),
        status=412,
    )
    rate(fixture, reference["id"], "2")
    call(fixture, "POST", path(fixture), command(fixture, reference["id"]), status=412)
    _, sessions, ids, _ = fixture
    async with sessions() as db:
        old = Order(
            customer_name="Old",
            customer_phone="123",
            pickup_address="A",
            delivery_address="B",
            currency_code=None,
            subtotal=0.30000000000000004,
        )
        db.add(old)
        await db.commit()
        old_id = old.id
    call(
        fixture,
        "POST",
        "/orders/" + str(old_id) + "/quotes",
        command(fixture, reference["id"]),
        status=409,
    )
    async with sessions() as db:
        row = await db.get(Order, old_id)
        assert (
            row.currency_code is None
            and row.pricing_version is None
            and row.subtotal == 0.30000000000000004
        )
        assert await db.scalar(select(func.count(OrderCurrencyQuote.id))) == 0
        await db.execute(
            update(Order)
            .where(Order.id == ids["order"])
            .values(status=OrderStatus.CANCELADO)
        )
        await db.commit()
    call(fixture, "POST", path(fixture), command(fixture, reference["id"]), status=409)


@pytest.mark.asyncio
async def test_roles_ownership_context_and_idempotency_conflicts(quote_db):
    fixture = quote_db
    reference = rate(fixture)
    body = command(fixture, reference["id"])
    first = call(fixture, "POST", path(fixture), body, role="OPERADOR", status=201)
    call(fixture, "GET", "/order-quotes/" + first["id"], role="OTHER", status=403)
    assert call(fixture, "GET", path(fixture), role="OTHER")["receipts"] == []
    assert call(fixture, "GET", path(fixture), role="AUDITOR")["receipts"] == [first]
    for role in ["AUDITOR", "CLIENTE", "REPARTIDOR"]:
        call(
            fixture,
            "POST",
            path(fixture),
            command(fixture, reference["id"]),
            role=role,
            status=403,
        )
    for role in ["CLIENTE", "REPARTIDOR"]:
        call(fixture, "GET", path(fixture), role=role, status=403)
    call(fixture, "POST", path(fixture), body, role="SUPERADMIN", status=409)
    call(
        fixture,
        "POST",
        path(fixture),
        {**body, "expected_pricing_revision": 2},
        role="OPERADOR",
        status=409,
    )


@pytest.mark.asyncio
async def test_concurrent_identical_requests_create_one_receipt_and_audit(quote_db):
    fixture = quote_db
    reference = rate(fixture)
    body = command(fixture, reference["id"])
    results = await asyncio.gather(
        *(
            asyncio.to_thread(call, fixture, "POST", path(fixture), body, status=201)
            for _ in range(2)
        )
    )
    assert results[0] == results[1]
    async with fixture[1]() as db:
        assert await db.scalar(select(func.count(OrderCurrencyQuote.id))) == 1
        assert (
            await db.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.resource_type == "ORDER_USD_VES_QUOTE"
                )
            )
            == 1
        )


@pytest.mark.asyncio
async def test_sql_enforces_snapshot_conversion_and_immutable_history(quote_db):
    fixture = quote_db
    reference = rate(fixture)
    first = call(
        fixture, "POST", path(fixture), command(fixture, reference["id"]), status=201
    )
    engine = fixture[3]
    columns = [
        "id",
        "request_key",
        "order_id",
        "order_external_id",
        "pricing_revision",
        "pricing_snapshot",
        "rate_id",
        "amount_usd",
        "amount_ves",
        "created_by",
        "created_at",
    ]
    for change in [
        {"amount_usd": "0.51"},
        {"amount_ves": "0.74"},
        {"order_external_id": "'wrong'"},
        {"pricing_revision": "2"},
        {"created_at": "created_at - interval '2 days'"},
        {
            "pricing_snapshot": "jsonb_set(pricing_snapshot::jsonb,'{total}','\"0.51\"')::json"
        },
    ]:
        expressions = {
            **{column: column for column in columns},
            "id": ":id",
            "request_key": ":key",
            **change,
        }
        with pytest.raises(DBAPIError):
            async with engine.begin() as db:
                await db.execute(
                    text(
                        "INSERT INTO order_currency_quotes ("
                        + ",".join(columns)
                        + ") SELECT "
                        + ",".join(expressions[column] for column in columns)
                        + " FROM order_currency_quotes WHERE id=:source"
                    ),
                    {"id": uuid4(), "key": uuid4(), "source": UUID(first["id"])},
                )
    for statement in [
        "UPDATE order_currency_quotes SET amount_usd=0",
        "DELETE FROM order_currency_quotes",
        "TRUNCATE order_currency_quotes",
    ]:
        with pytest.raises(DBAPIError):
            async with engine.begin() as db:
                await db.execute(text(statement))
    with pytest.raises(RuntimeError, match="preserve order"):
        await migration(engine, "downgrade")
    assert call(fixture, "GET", "/order-quotes/" + first["id"]) == first


@pytest.mark.asyncio
async def test_audit_failure_rolls_back_receipt_and_empty_downgrade_is_safe(quote_db):
    fixture = quote_db
    reference = rate(fixture)
    async with fixture[3].begin() as db:
        await db.execute(
            text(
                "ALTER TABLE audit_logs ADD CONSTRAINT reject_order_quote_audit CHECK(resource_type <> 'ORDER_USD_VES_QUOTE')"
            )
        )
    call(fixture, "POST", path(fixture), command(fixture, reference["id"]), status=500)
    async with fixture[1]() as db:
        assert await db.scalar(select(func.count(OrderCurrencyQuote.id))) == 0
    await migration(fixture[3], "downgrade")
    async with fixture[3].connect() as db:
        assert (
            await db.execute(
                text("SELECT to_regclass(current_schema()||'.order_currency_quotes')")
            )
        ).scalar() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("change,status", [("token", 401), ("role", 403)])
async def test_credentials_rechecked_after_actual_order_lock_wait(
    quote_db, monkeypatch, change, status
):
    fixture = quote_db
    reference = rate(fixture)
    client, sessions, ids, _ = fixture
    waiting = Future()
    original = AsyncSession.scalar

    async def observed(db, statement, *args, **kwargs):
        if (
            db.info.get("currency_request")
            and getattr(statement, "_for_update_arg", None) is not None
            and not waiting.done()
        ):
            waiting.set_result(await original(db, text("SELECT pg_backend_pid()")))
        return await original(db, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "scalar", observed)
    async with asyncio.timeout(20):
        async with sessions() as blocker:
            pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
            await blocker.execute(
                select(Order).where(Order.id == ids["order"]).with_for_update()
            )
            pending = asyncio.create_task(
                asyncio.to_thread(
                    call,
                    fixture,
                    "POST",
                    path(fixture),
                    command(fixture, reference["id"]),
                    status=status,
                )
            )
            try:
                waiter = await asyncio.wait_for(asyncio.wrap_future(waiting), 5)
                await wait_for_blocker(sessions, waiter, pid)
                async with sessions() as writer:
                    actor = await writer.get(User, ids["SUPERADMIN"])
                    if change == "token":
                        actor.token_version += 1
                    else:
                        actor.role = UserRole.REPARTIDOR
                    await writer.commit()
            finally:
                await blocker.rollback()
            await pending
    async with sessions() as db:
        assert await db.scalar(select(func.count(OrderCurrencyQuote.id))) == 0


@pytest.mark.asyncio
async def test_day_change_after_flush_rolls_back_both_receipt_and_audit(
    quote_db, monkeypatch
):
    fixture = quote_db
    reference = rate(fixture)
    today = currency.current_day()
    days = iter([today, today, today + timedelta(days=1)])
    monkeypatch.setattr(currency, "current_day", lambda: next(days))
    call(fixture, "POST", path(fixture), command(fixture, reference["id"]), status=409)
    async with fixture[1]() as db:
        assert await db.scalar(select(func.count(OrderCurrencyQuote.id))) == 0
        assert (
            await db.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.resource_type == "ORDER_USD_VES_QUOTE"
                )
            )
            == 0
        )


@pytest.mark.asyncio
async def test_rate_correction_during_day_lock_wait_cannot_save_a_stale_quote(
    quote_db, monkeypatch
):
    fixture = quote_db
    reference = rate(fixture)
    _, sessions, ids, _ = fixture
    day = currency.current_day()
    waiting = Future()
    original = currency.advisory

    async def observed(db, key):
        if (
            db.info.get("currency_request")
            and key == "bcv:day:" + day.isoformat()
            and not waiting.done()
        ):
            waiting.set_result(await db.scalar(text("SELECT pg_backend_pid()")))
        return await original(db, key)

    monkeypatch.setattr(currency, "advisory", observed)
    async with asyncio.timeout(20):
        async with sessions() as blocker:
            pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
            await original(blocker, "bcv:day:" + day.isoformat())
            pending = asyncio.create_task(
                asyncio.to_thread(
                    call,
                    fixture,
                    "POST",
                    path(fixture),
                    command(fixture, reference["id"]),
                    status=412,
                )
            )
            try:
                waiter = await asyncio.wait_for(asyncio.wrap_future(waiting), 5)
                await wait_for_blocker(sessions, waiter, pid)
                blocker.add(
                    BcvRate(
                        request_key=uuid4(),
                        previous_rate_id=UUID(reference["id"]),
                        valid_on=day,
                        reference_date=day,
                        revision=2,
                        ves_per_usd=Decimal("2.0"),
                        note="Synthetic correction during actual lock wait",
                        recorded_by=ids["SUPERADMIN"],
                        recorded_at=currency.utc_now().replace(tzinfo=None),
                    )
                )
                await blocker.commit()
            finally:
                await blocker.rollback()
            await pending
    async with sessions() as db:
        assert await db.scalar(select(func.count(OrderCurrencyQuote.id))) == 0


@pytest.mark.asyncio
async def test_context_bounds_history_and_preserves_older_recovery_links(quote_db):
    fixture = quote_db
    reference = rate(fixture)
    first = call(
        fixture,
        "POST",
        path(fixture),
        command(fixture, reference["id"]),
        role="OPERADOR",
        status=201,
    )
    for _ in range(11):
        call(
            fixture,
            "POST",
            path(fixture),
            command(fixture, reference["id"]),
            status=201,
        )
    context = call(fixture, "GET", path(fixture))
    assert len(context["receipts"]) == 10 and context["has_more"] is True
    assert first["id"] not in {row["id"] for row in context["receipts"]}
    assert call(fixture, "GET", "/order-quotes/" + first["id"]) == first
    own = call(fixture, "GET", path(fixture), role="OPERADOR")
    assert own["receipts"] == [first] and own["has_more"] is False
