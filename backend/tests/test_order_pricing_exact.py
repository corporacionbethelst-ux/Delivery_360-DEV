"""Exact money, prospective storage and real PostgreSQL enforcement."""

import asyncio
import importlib
from copy import deepcopy
from decimal import Decimal

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from concurrent.futures import Future

from app.core.exceptions import AppException
from app.core.security import create_access_token
from app.models.order import Order
from app.models.user import User, UserRole
from app.services import order_pricing as pricing
from tests.test_delivery_financial_postgresql import payment_db  # noqa: F401
from tests.test_assignment_concurrency_postgresql import wait_for_blocker


def test_exact_arithmetic_half_up_zero_and_no_input_mutation():
    items = [{"quantity": "3", "unit_price": "0.10", "product_name": "A"}]
    original = deepcopy(items)
    price = pricing.calculate(items, delivery_fee="0.20", total="0.50")
    assert price.view(1)["total"] == "0.50"
    assert price.items[0]["subtotal"] == "0.30"
    assert items == original
    half = pricing.calculate([{"quantity": "0.5", "unit_price": "0.01"}])
    assert half.subtotal == Decimal("0.01")
    assert pricing.calculate([], subtotal="0", total="0").total == 0
    assert pricing.calculate([{"subtotal": "2.55"}]).items == [
        {"quantity": None, "unit_price": None, "subtotal": "2.55"}
    ]


@pytest.mark.parametrize(
    "value",
    [
        True,
        None,
        -1,
        "NaN",
        "Infinity",
        "1e2",
        "0.001",
        "100000000",
        "-0",
        "",
        {},
        0.30000000000000004,
    ],
)
def test_malformed_money_never_becomes_a_price(value):
    with pytest.raises(AppException):
        pricing.decimal_value(value)


@pytest.mark.parametrize(
    "body",
    [
        {"items": [{"quantity": 0, "unit_price": 1}]},
        {"items": [{"quantity": "1000000", "unit_price": 1}]},
        {"items": [{"quantity": "0.0001", "unit_price": 1}]},
        {"items": [{"quantity": 2, "unit_price": 1, "subtotal": 0}]},
        {"items": [{"subtotal": 1}], "subtotal": 0},
        {"items": [], "subtotal": 1, "total": 0},
        {"items": [], "subtotal": 1, "declared_value": 0},
        {"items": [], "subtotal": "99999999.99", "delivery_fee": "0.01"},
        {"items": [{"subtotal": 0}] * 201},
        {"items": [{"subtotal": 0, "metadata": object()}]},
    ],
)
def test_inconsistent_or_unbounded_prices_rejected(body):
    with pytest.raises(AppException):
        pricing.calculate(**body)


def revision_module():
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "exact_prices",
        Path(__file__).parents[1] / "alembic/versions/20261114_order_exact_prices.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def install(engine):
    migration = revision_module()
    async with engine.begin() as conn:
        for column in migration.COLUMNS:
            await conn.execute(text(f'ALTER TABLE orders DROP COLUMN "{column}"'))

        def upgrade(sync):
            with Operations.context(MigrationContext.configure(sync)):
                migration.upgrade()

        await conn.run_sync(upgrade)


def auth(ids):
    return {"Authorization": "Bearer " + create_access_token(ids["staff"])}


def create(client, ids, **extra):
    return client.post(
        "/api/v1/orders",
        headers=auth(ids),
        json={
            "customer_name": "Exact",
            "customer_phone": "123",
            "pickup_address": "A",
            "delivery_address": "B",
            "delivery_contact": "Contact",
            "items": [
                {"product_name": "Decimal", "quantity": "3", "unit_price": "0.10"}
            ],
            "delivery_fee": "0.20",
            "currency": "USD",
            **extra,
        },
    )


@pytest.mark.asyncio
async def test_migration_preserves_old_float_rows_and_null_exact_fields(payment_db):
    _, sessions, ids = payment_db
    engine = sessions.kw["bind"]
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE orders SET subtotal=0.30000000000000004, total=0.30000000000000004 WHERE id=:id"
            ),
            {"id": ids["order"]},
        )
        before = (
            await conn.execute(
                text(
                    "SELECT to_jsonb(o) - ARRAY['pricing_version','pricing_revision','subtotal_exact','delivery_fee_exact','total_exact','items_exact'] FROM orders o"
                )
            )
        ).scalar_one()
    await install(engine)
    async with engine.connect() as conn:
        after = (
            await conn.execute(
                text(
                    "SELECT to_jsonb(o) - ARRAY['pricing_version','pricing_revision','subtotal_exact','delivery_fee_exact','total_exact','items_exact'] FROM orders o"
                )
            )
        ).scalar_one()
        assert before == after
        assert (
            await conn.execute(
                text("SELECT pricing_version, subtotal_exact, items_exact FROM orders")
            )
        ).one() == (None, None, None)


@pytest.mark.asyncio
async def test_real_http_revision_atomicity_and_database_guards(payment_db):
    client, sessions, ids = payment_db
    engine = sessions.kw["bind"]
    await install(engine)
    response = await asyncio.to_thread(create, client, ids)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["pricing"] == {
        "version": 1,
        "currency": "USD",
        "revision": 1,
        "subtotal": "0.30",
        "delivery_fee": "0.20",
        "total": "0.50",
        "items": [
            {
                "product_name": "Decimal",
                "quantity": "3",
                "unit_price": "0.10",
                "subtotal": "0.30",
            }
        ],
    }
    path = "/api/v1/orders/" + data["id"]

    async def patch(body):
        return await asyncio.to_thread(client.patch, path, headers=auth(ids), json=body)

    stale = await patch({"delivery_fee": "0.30", "pickup_address": "LOST"})
    assert stale.status_code == 412
    inconsistent = await patch(
        {"delivery_fee": "0.30", "total": "0.00", "expected_pricing_revision": 1}
    )
    assert inconsistent.status_code == 422
    noop = await patch({"delivery_fee": "0.20", "expected_pricing_revision": 1})
    assert noop.status_code == 200, noop.text
    assert noop.json()["pricing"]["revision"] == 1
    results = await asyncio.gather(
        patch({"delivery_fee": "0.30", "expected_pricing_revision": 1}),
        patch({"delivery_fee": "0.40", "expected_pricing_revision": 1}),
    )
    assert sorted(r.status_code for r in results) == [200, 412]
    async with sessions() as db:
        row = await db.scalar(select(Order).where(Order.id == data["id"]))
        assert row.pricing_revision == 2
        assert row.pickup_address == "A"
        total = row.total_exact
        assert isinstance(total, Decimal)
        assert total in (Decimal("0.60"), Decimal("0.70"))
    operational = await patch({"delivery_reference": "Gate"})
    assert operational.status_code == 200, operational.text
    assert operational.json()["pricing"]["revision"] == 2
    for assignment in [
        "total=100",
        "pricing_version=NULL",
        "pricing_revision=99",
        "total_exact=0",
        "items_exact='[]'",
        "items='[]'",
        'items_exact=\'[{"quantity":"3","unit_price":"0.10","subtotal":"0.31"}]\'',
    ]:
        with pytest.raises(DBAPIError):
            async with engine.begin() as conn:
                await conn.execute(
                    text(f"UPDATE orders SET {assignment} WHERE id=:id"),
                    {"id": data["id"]},
                )
    async with engine.begin() as conn:

        def downgrade(sync):
            with Operations.context(MigrationContext.configure(sync)):
                revision_module().downgrade()

        with pytest.raises(RuntimeError, match="preserve exact"):
            await conn.run_sync(downgrade)


@pytest.mark.asyncio
async def test_new_validation_legacy_explicit_reprice_and_exact_report_subset(
    payment_db,
):
    client, sessions, ids = payment_db
    await install(sessions.kw["bind"])
    for extra in [
        {"total": "0"},
        {"subtotal": "0.00"},
        {"currency": "VES"},
        {"delivery_fee": True},
        {"delivery_fee": "0.001"},
    ]:
        response = await asyncio.to_thread(create, client, ids, **extra)
        assert response.status_code == 422, response.text
    response = await asyncio.to_thread(
        create,
        client,
        ids,
        items=[],
        subtotal="0.00",
        delivery_fee="0.00",
        total="0.00",
    )
    assert response.status_code == 201, response.text
    assert response.json()["pricing"]["total"] == "0.00"
    async with sessions() as db:
        old = await db.get(Order, ids["order"])
        old.currency_code = "USD"
        old.status = "PENDIENTE"
        await db.commit()
    path = f"/api/v1/orders/{ids['order']}"
    response = await asyncio.to_thread(
        client.patch, path, headers=auth(ids), json={"delivery_fee": "1.00"}
    )
    assert response.status_code == 409
    async with sessions() as db:
        report = await pricing.aggregate(db)
    assert report == {
        "scope": "exact_usd_only",
        "currency": "USD",
        "order_count": 1,
        "legacy_order_count": 1,
        "subtotal": "0.00",
        "delivery_fee": "0.00",
        "total": "0.00",
    }
    response = await asyncio.to_thread(
        client.patch,
        path,
        headers=auth(ids),
        json={"items": [{"subtotal": "0.30"}], "delivery_fee": "0.20", "total": "0.50"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["pricing"]["revision"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change,status", [("revoke", 401), ("role", 403)])
async def test_money_edit_rechecks_operator_after_real_database_lock_wait(
    payment_db, monkeypatch, change, status
):
    client, sessions, ids = payment_db
    await install(sessions.kw["bind"])
    created = await asyncio.to_thread(create, client, ids)
    assert created.status_code == 201, created.text
    oid = created.json()["id"]
    waiting = Future()
    original = AsyncSession.execute

    async def observed(db, statement, *args, **kwargs):
        if (
            db.info.get("workflow_request")
            and getattr(statement, "_for_update_arg", None) is not None
            and not waiting.done()
        ):
            waiting.set_result(
                (await original(db, text("SELECT pg_backend_pid()"))).scalar_one()
            )
        return await original(db, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", observed)
    async with asyncio.timeout(20):
        async with sessions() as blocker:
            pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
            await blocker.execute(
                select(Order).where(Order.id == oid).with_for_update()
            )
            pending = asyncio.create_task(
                asyncio.to_thread(
                    client.patch,
                    "/api/v1/orders/" + oid,
                    headers=auth(ids),
                    json={"delivery_fee": "0.30", "expected_pricing_revision": 1},
                )
            )
            try:
                waiter = await asyncio.wait_for(asyncio.wrap_future(waiting), 5)
                await wait_for_blocker(sessions, waiter, pid)
                async with sessions() as writer:
                    actor = await writer.get(User, ids["staff"])
                    if change == "revoke":
                        actor.token_version += 1
                    else:
                        actor.role = UserRole.REPARTIDOR
                    await writer.commit()
            finally:
                await blocker.rollback()
            result = await pending
    assert result.status_code == status, result.text
    async with sessions() as db:
        row = await db.get(Order, oid)
        assert row.total_exact == Decimal("0.50") and row.pricing_revision == 1
