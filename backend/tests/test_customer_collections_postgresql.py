"""Real SQL customer book, independent decisions, replay and price protection."""

import asyncio
from concurrent.futures import Future
from datetime import timedelta
from decimal import Decimal
import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text, func
from sqlalchemy.exc import DBAPIError

from app.core.security import create_access_token
from app.models.customer_collection import CustomerCollection, CustomerCollectionReview
from app.models.audit_log import AuditLog
from app.models.order import Order
from app.services import bcv_currency as currency
from tests.test_order_currency_quote_postgresql import (
    quote_db,
    currency_db,
    rate,
    command as quote_command,
    call as quote_call,
    path as quote_path,
)  # noqa: F401


def module():
    spec = importlib.util.spec_from_file_location(
        "collections94",
        Path(__file__).parents[1] / "alembic/versions/20261114_customer_collections.py",
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


async def migrate(engine, direction):
    def apply(conn):
        with Operations.context(MigrationContext.configure(conn)):
            getattr(module(), direction)()

    async with engine.begin() as conn:
        await conn.run_sync(apply)


@pytest.fixture
async def collection_db(quote_db):
    engine = quote_db[3]
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "ALTER TABLE orders DROP COLUMN collection_revision, DROP COLUMN collection_locked"
            )
        )
    await migrate(engine, "upgrade")
    yield quote_db


def call(fixture, method, path, body=None, role="OPERADOR", status=200):
    client, _, ids, _ = fixture
    response = client.request(
        method,
        "/api/v1/customer-collections" + path,
        headers={"Authorization": "Bearer " + create_access_token(ids[role])},
        json=body,
    )
    assert response.status_code == status, response.text
    return response.json()


def path(fixture):
    return "/orders/" + str(fixture[2]["order"])


def declaration(fixture, **extra):
    return dict(
        request_key=str(uuid4()),
        expected_pricing_revision=1,
        expected_collection_revision=0,
        amount_usd="0.20",
        paid_amount="0.20",
        paid_currency="USD",
        method="EFECTIVO",
        source_key="CAJA PRINCIPAL",
        reference_key="RECIBO-" + uuid4().hex.upper(),
        received_on=currency.current_day().isoformat(),
        confirmed_received=True,
        **extra,
    )


def decision(revision=1, **extra):
    result = dict(
        request_key=str(uuid4()),
        expected_collection_revision=revision,
        decision="VERIFICADO",
        note="Comprobado contra el recibo físico",
        verified_evidence=True,
        acknowledge_refund_due=False,
    )
    result.update(extra)
    return result


def review(fixture, row, body=None, **kw):
    return call(
        fixture,
        "POST",
        "/" + row["id"] + "/review",
        body or decision(),
        role=kw.pop("role", "GERENTE"),
        status=kw.pop("status", 201),
    )


@pytest.mark.asyncio
async def test_partial_usd_pending_then_independent_review_and_replay(collection_db):
    f = collection_db
    body = declaration(f)
    first = call(f, "POST", path(f), body, status=201)
    assert first["status"] == "PENDIENTE" and first["bank_verified"] is False
    ctx = call(f, "GET", path(f))
    assert ctx["collection_revision"] == 1 and ctx["price_locked"]
    assert (
        ctx["summary"]["pending_usd"],
        ctx["summary"]["verified_usd"],
        ctx["summary"]["due_usd"],
        ctx["summary"]["available_to_declare_usd"],
    ) == ("0.20", "0.00", "0.50", "0.30")
    assert call(f, "POST", path(f), body, status=201) == first
    review_body = decision()
    confirmed = review(f, first, review_body)
    assert confirmed["status"] == "VERIFICADO_MANUALMENTE"
    assert review(f, first, review_body) == confirmed
    assert call(f, "POST", path(f), body, status=201) == confirmed
    ctx = call(f, "GET", path(f))
    assert ctx["collection_revision"] == 2 and ctx["summary"]["state"] == "PARCIAL"
    assert (
        ctx["summary"]["pending_usd"],
        ctx["summary"]["verified_usd"],
        ctx["summary"]["due_usd"],
    ) == ("0.00", "0.20", "0.30")
    async with f[1]() as db:
        assert await db.scalar(select(func.count(CustomerCollection.id))) == 1
        assert await db.scalar(select(func.count(CustomerCollectionReview.id))) == 1
        assert (
            await db.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.resource_type.in_(
                        ["CUSTOMER_COLLECTION", "CUSTOMER_COLLECTION_REVIEW"]
                    )
                )
            )
            == 2
        )
        assert await db.scalar(select(Order.payment_status)) == "pendiente"


@pytest.mark.asyncio
async def test_ves_partial_uses_frozen_daily_quote_after_rate_correction(collection_db):
    f = collection_db
    reference = rate(f)
    q = quote_call(
        f,
        "POST",
        quote_path(f),
        quote_command(f, reference["id"]),
        role="OPERADOR",
        status=201,
    )
    rate(f, reference["id"], "2.00000000")
    body = declaration(f)
    body.update(
        paid_currency="VES", method="PAGO_MOVIL", paid_amount="0.30", quote_id=q["id"]
    )
    row = call(f, "POST", path(f), body, status=201)
    assert row["quote"] == q and row["amount_usd"] == "0.20"
    ctx = call(f, "GET", path(f))
    assert ctx["ves_quotes"] == [q]
    review(f, row)
    body = declaration(f)
    body.update(
        expected_collection_revision=2,
        amount_usd="0.30",
        paid_amount="0.45",
        paid_currency="VES",
        method="TRANSFERENCIA",
        quote_id=q["id"],
    )
    second = call(f, "POST", path(f), body, status=201)
    review(f, second, decision(3))
    ctx = call(f, "GET", path(f))
    assert (
        ctx["summary"]["state"] == "COMPLETO"
        and ctx["summary"]["verified_usd"] == "0.50"
        and ctx["summary"]["due_usd"] == "0.00"
    )


@pytest.mark.asyncio
async def test_reject_releases_capacity_reference_and_price_lock(collection_db):
    f = collection_db
    body = declaration(f)
    first = call(f, "POST", path(f), body, status=201)
    body2 = {**body, "request_key": str(uuid4()), "expected_collection_revision": 1}
    call(f, "POST", path(f), body2, status=409)
    review(
        f,
        first,
        decision(
            decision="RECHAZADO",
            verified_evidence=False,
            note="Referencia no corresponde al ingreso",
        ),
    )
    ctx = call(f, "GET", path(f))
    assert ctx["price_locked"] is False and ctx["collection_revision"] == 2
    assert ctx["summary"]["available_to_declare_usd"] == "0.50"
    body2["expected_collection_revision"] = 2
    assert call(f, "POST", path(f), body2, status=201)["id"] != first["id"]


@pytest.mark.asyncio
async def test_price_freeze_cannot_be_bypassed_but_operational_edits_allowed(
    collection_db,
):
    f = collection_db
    call(f, "POST", path(f), declaration(f), status=201)
    client, _, ids, _ = f
    headers = {"Authorization": "Bearer " + create_access_token(ids["SUPERADMIN"])}
    url = "/api/v1/orders/" + str(ids["order"])
    assert (
        client.patch(
            url,
            headers=headers,
            json={"delivery_fee": "0.30", "expected_pricing_revision": 1},
        ).status_code
        == 409
    )
    assert (
        client.patch(
            url, headers=headers, json={"delivery_address": "New destination"}
        ).status_code
        == 200
    )
    async with f[1]() as db:
        for sql in (
            "UPDATE orders SET collection_locked=false",
            "UPDATE orders SET collection_revision=0",
            "UPDATE orders SET delivery_fee_exact=0.30,total_exact=0.60,delivery_fee=0.30,total=0.60,pricing_revision=2",
        ):
            with pytest.raises(DBAPIError):
                await db.execute(text(sql))
            await db.rollback()


@pytest.mark.asyncio
async def test_independent_roles_privacy_and_freshness(collection_db):
    f = collection_db
    for role in ("AUDITOR", "CLIENTE", "REPARTIDOR"):
        call(f, "POST", path(f), declaration(f), role=role, status=403)
    own = call(f, "POST", path(f), declaration(f), role="GERENTE", status=201)
    review(f, own, role="GERENTE", status=403)
    review(f, own, role="OPERADOR", status=403)
    review(f, own, decision(2), role="SUPERADMIN", status=412)
    ctx = call(f, "GET", path(f), role="OPERADOR")
    assert ctx["collections"] == [] and ctx["summary"]["pending_usd"] == "0.20"
    assert len(call(f, "GET", path(f), role="AUDITOR")["collections"]) == 1
    review(f, own, role="SUPERADMIN")
    body = declaration(f)
    call(f, "POST", path(f), body, status=412)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation,status",
    [
        ({"paid_amount": "0.21"}, 422),
        ({"paid_amount": True}, 422),
        ({"paid_amount": "NaN"}, 422),
        ({"amount_usd": "0.001"}, 422),
        ({"method": "PAGO_MOVIL"}, 422),
        ({"paid_currency": "VES"}, 422),
        ({"confirmed_received": 1}, 422),
        ({"source_key": "CAJA\nEXTRA"}, 422),
        ({"received_on": "2000-01-01"}, 409),
        ({"amount_usd": "0.51", "paid_amount": "0.51"}, 409),
        ({"expected_pricing_revision": 2}, 412),
        ({"unknown": True}, 422),
    ],
)
async def test_invalid_declared_money_and_identity(collection_db, mutation, status):
    body = declaration(collection_db)
    body.update(mutation)
    call(collection_db, "POST", path(collection_db), body, status=status)
    assert call(collection_db, "GET", path(collection_db))["collection_revision"] == 0


@pytest.mark.asyncio
async def test_cancellation_surfaces_refund_liability_without_rider_mutation(
    collection_db,
):
    f = collection_db
    body = declaration(f)
    row = call(f, "POST", path(f), body, status=201)
    async with f[1]() as db:
        await db.execute(text("UPDATE orders SET status='CANCELADO'"))
        await db.commit()
    review(f, row, status=409)
    review(f, row, decision(acknowledge_refund_due=True))
    ctx = call(f, "GET", path(f))
    assert (
        ctx["summary"]["refund_due_usd"] == "0.20"
        and ctx["summary"]["due_usd"] == "0.00"
        and ctx["summary"]["state"] == "DEVOLUCION_PENDIENTE"
    )
    assert (
        call(f, "POST", path(f), body, status=201)["status"] == "VERIFICADO_MANUALMENTE"
    )
    body["request_key"] = str(uuid4())
    call(f, "POST", path(f), body, status=409)


@pytest.mark.asyncio
async def test_immutable_history_and_populated_downgrade_refused(collection_db):
    f = collection_db
    row = call(f, "POST", path(f), declaration(f), status=201)
    review(f, row)
    async with f[1]() as db:
        for table in ("customer_collections", "customer_collection_reviews"):
            for sql in (
                f"UPDATE {table} SET request_key=request_key",
                f"DELETE FROM {table}",
                f"TRUNCATE {table} CASCADE",
            ):
                with pytest.raises(DBAPIError):
                    await db.execute(text(sql))
                await db.rollback()
    with pytest.raises(RuntimeError, match="preserve customer"):
        await migrate(f[3], "downgrade")
    assert call(f, "GET", path(f))["summary"]["verified_usd"] == "0.20"


@pytest.mark.asyncio
async def test_empty_downgrade_no_backfill_and_upgrade_again(collection_db):
    f = collection_db
    async with f[1]() as db:
        row = (
            await db.execute(select(Order.collection_revision, Order.collection_locked))
        ).one()
        assert row == (None, None)
    await migrate(f[3], "downgrade")
    await migrate(f[3], "upgrade")
    assert call(f, "GET", path(f))["collection_revision"] == 0


@pytest.mark.asyncio
async def test_audit_failure_rolls_back_declaration_and_order_counters(collection_db):
    f = collection_db
    async with f[3].begin() as conn:
        await conn.execute(
            text(
                "ALTER TABLE audit_logs ADD CONSTRAINT reject94 CHECK (resource_type <> 'CUSTOMER_COLLECTION')"
            )
        )
    call(f, "POST", path(f), declaration(f), status=500)
    ctx = call(f, "GET", path(f))
    assert (
        ctx["collection_revision"] == 0
        and ctx["price_locked"] is False
        and ctx["collections"] == []
    )


@pytest.mark.asyncio
async def test_concurrent_declarations_review_and_replay_serialize(collection_db):
    f = collection_db
    client, _, ids, _ = f

    def post(body):
        return client.post(
            "/api/v1/customer-collections" + path(f),
            headers={"Authorization": "Bearer " + create_access_token(ids["OPERADOR"])},
            json=body,
        )

    first, second = await asyncio.gather(
        asyncio.to_thread(post, declaration(f)), asyncio.to_thread(post, declaration(f))
    )
    assert sorted([first.status_code, second.status_code]) == [201, 412]
    row = first.json() if first.status_code == 201 else second.json()

    def decide(body):
        return client.post(
            "/api/v1/customer-collections/" + row["id"] + "/review",
            headers={"Authorization": "Bearer " + create_access_token(ids["GERENTE"])},
            json=body,
        )

    body = decision()
    outcomes = await asyncio.gather(
        asyncio.to_thread(decide, body), asyncio.to_thread(decide, body)
    )
    assert [r.status_code for r in outcomes] == [201, 201] and outcomes[
        0
    ].json() == outcomes[1].json()
    assert call(f, "GET", path(f))["collection_revision"] == 2


@pytest.mark.asyncio
async def test_reference_namespace_is_shared_across_orders_and_methods(collection_db):
    from app.services import order_pricing

    f = collection_db
    body = declaration(f)
    async with f[1]() as db:
        other = Order(
            customer_name="Other",
            customer_phone="123",
            pickup_address="A",
            delivery_address="B",
            currency_code="USD",
        )
        order_pricing.apply(other, order_pricing.calculate([], subtotal="0.50"))
        db.add(other)
        await db.commit()
        other_id = other.id
    call(f, "POST", path(f), body, status=201)
    body.update(request_key=str(uuid4()), method="TRANSFERENCIA")
    call(f, "POST", "/orders/" + str(other_id), body, status=409)
    assert call(f, "GET", "/orders/" + str(other_id))["collection_revision"] == 0


@pytest.mark.asyncio
async def test_raw_sql_cannot_forge_snapshot_credit_reference_or_self_review(
    collection_db,
):
    from copy import deepcopy

    f = collection_db
    row = call(f, "POST", path(f), declaration(f), role="SUPERADMIN", status=201)
    async with f[1]() as db:
        original = await db.get(CustomerCollection, row["id"])
        values = {
            c.name: getattr(original, c.name)
            for c in CustomerCollection.__table__.columns
        }
        for changes in (
            {"pricing_snapshot": {}},
            {"paid_amount": Decimal("0.21")},
            {"source_key": "lowercase"},
            {"amount_usd": Decimal("0.40"), "paid_amount": Decimal("0.40")},
            {"declared_by": f[2]["CLIENTE"]},
        ):
            variant = {
                **deepcopy(values),
                "id": uuid4(),
                "request_key": uuid4(),
                "reference_key": "NEW-" + uuid4().hex.upper(),
                **changes,
            }
            db.add(CustomerCollection(**variant))
            with pytest.raises(DBAPIError):
                await db.flush()
            await db.rollback()
        db.add(
            CustomerCollectionReview(
                request_key=uuid4(),
                collection_id=values["id"],
                decision="VERIFICADO",
                note="Invalid self verification attempt",
                verified_evidence=True,
                acknowledge_refund_due=False,
                reviewed_by=f[2]["SUPERADMIN"],
                reviewed_at=currency.utc_now().replace(tzinfo=None),
            )
        )
        with pytest.raises(DBAPIError):
            await db.flush()
        await db.rollback()
    call(f, "GET", "/" + row["id"], role="OTHER", status=403)
    assert call(f, "GET", "/" + row["id"], role="AUDITOR") == row
    assert call(f, "GET", path(f))["collection_revision"] == 1
