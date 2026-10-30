"""Real HTTP + PostgreSQL contracts for delivery/order/ledger atomicity."""

import asyncio
import os
import json
from concurrent.futures import Future
from pathlib import Path
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update, delete, text, MetaData
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool
from app.main import app
from app.core.database import Base, get_db
from app.core.rate_limiter import RateLimiter
from app.core.security import create_access_token
from app.core.exceptions import DuplicateTransactionError, ValidationError
from app.middleware import rate_limit_middleware
from app.models.delivery import Delivery, DeliveryStatus, ProofType
from app.models.financial import (
    Financial,
    PaymentStatus,
    TransactionType,
    RiderWallet,
    FinancialTransaction,
)
from app.models.order import Order, OrderStatus
from app.models.platform_setting import PlatformSetting
from app.models.rider import Rider, RiderStatus
from app.models.user import User, UserRole
from app.services.delivery_ledger import (
    calculated_bonus,
    bonus_component,
    validate_bonus_receipt,
)


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        "bad",
        "NaN",
        "Infinity",
        "-Infinity",
        "-0.01",
        "100000000",
        object(),
    ],
)
def test_bonus_components_cannot_be_negative_nonfinite_or_unrepresentable(value):
    with pytest.raises(ValidationError):
        bonus_component(value)


def test_reward_calculation_rounds_once_after_multipliers():
    base = bonus_component("2.505")
    assert base == Decimal("2.505")
    assert calculated_bonus(base * bonus_component("1.5")) == Decimal("3.76")
    assert calculated_bonus(0) == Decimal("0.00")


@pytest.fixture
async def payment_db(monkeypatch):
    raw = os.environ.get("TEST_DATABASE_URL")
    if not raw:
        pytest.skip("TEST_DATABASE_URL required for real payment workflow tests")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql" or not (url.database or "").startswith(
        "test_"
    ):
        pytest.fail("Explicit PostgreSQL test_* database required")
    url = url.set(drivername="postgresql+asyncpg")
    schema = "delivery_payment_" + uuid4().hex
    admin = create_async_engine(url, poolclass=NullPool)
    engine = None
    old = app.dependency_overrides.copy()
    client = None
    try:
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(
            url,
            poolclass=NullPool,
            connect_args={"server_settings": {"search_path": schema + ",public"}},
        )
        tables = {
            m.__table__
            for m in [
                Delivery,
                Order,
                Financial,
                RiderWallet,
                FinancialTransaction,
                PlatformSetting,
            ]
        }
        while True:
            expanded = tables | {
                fk.column.table for table in tables for fk in table.foreign_keys
            }
            if expanded == tables:
                break
            tables = expanded
        # Creating cyclic FK tables may change SQLAlchemy constraint DDL rules.
        # Keep those rules on disposable copies, never production ORM metadata.
        ddl_metadata = MetaData()
        for table in tables:
            table.to_metadata(ddl_metadata)
        async with engine.begin() as conn:
            await conn.run_sync(ddl_metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with sessions() as db:
            staff = User(
                email="staff@payment.test",
                hashed_password="unused",
                first_name="Staff",
                last_name="Test",
                role=UserRole.SUPERADMIN,
                is_active=True,
            )
            owner = User(
                email="owner@payment.test",
                hashed_password="unused",
                first_name="Owner",
                last_name="Test",
                role=UserRole.REPARTIDOR,
                is_active=True,
            )
            db.add_all([staff, owner])
            await db.flush()
            rider = Rider(
                user_id=owner.id,
                status=RiderStatus.ACTIVO,
                wallet_balance=Decimal("3.00"),
            )
            db.add(rider)
            await db.flush()
            order = Order(
                customer_name="Customer",
                customer_phone="123",
                pickup_address="A",
                delivery_address="B",
                status=OrderStatus.EN_RUTA,
                assigned_rider_id=rider.id,
                accepted_at=datetime.utcnow() - timedelta(minutes=2),
            )
            db.add(order)
            await db.flush()
            delivery = Delivery(
                order_id=order.id,
                rider_id=rider.id,
                status=DeliveryStatus.EN_ROUTE,
                proof_type=ProofType.NINGUNO,
                started_at=datetime.utcnow() - timedelta(minutes=1),
            )
            db.add_all(
                [
                    delivery,
                    Financial(
                        rider_id=rider.id,
                        amount=100,
                        balance_before=0,
                        balance_after=100,
                        transaction_type=TransactionType.INGRESO,
                        status=PaymentStatus.PROCESADO,
                        created_at=datetime.utcnow() - timedelta(hours=2),
                    ),
                    RiderWallet(rider_id=rider.id, balance_cents=1000),
                    PlatformSetting(key="rider_delivery_bonus", value="2.50"),
                    PlatformSetting(key="rider_failed_attempt_bonus", value="1.00"),
                ]
            )
            await db.commit()
            ids = dict(
                staff=staff.id,
                owner=owner.id,
                rider=rider.id,
                order=order.id,
                delivery=delivery.id,
            )

        async def database():
            async with sessions() as db:
                db.info["workflow_request"] = True
                try:
                    yield db
                    await db.commit()
                except BaseException:
                    await db.rollback()
                    raise

        app.dependency_overrides[get_db] = database
        monkeypatch.setattr(rate_limit_middleware, "rate_limiter", RateLimiter())
        monkeypatch.setattr(
            "app.services.invoicing_engine.issue_invoice_for_order_safe",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            "app.services.split_payment_service.settle_order_safe",
            AsyncMock(return_value=None),
        )
        client = TestClient(app, raise_server_exceptions=False)
        yield client, sessions, ids
    finally:
        if client:
            client.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(old)
        if engine:
            await engine.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()


def request(client, ids, operation, *, actor="staff", **body):
    headers = {"Authorization": "Bearer " + create_access_token(ids[actor])}
    if operation == "order":
        return client.patch(
            f"/api/v1/orders/{ids['order']}/status",
            params={"new_status": "ENTREGADO"},
            headers=headers,
        )
    if operation in ("success", "failure"):
        payload = (
            {"status": "COMPLETADA"}
            if operation == "success"
            else {"status": "FALLIDA", "issue_type": "CLIENTE_NO_ESTA"}
        )
        return client.patch(
            f"/api/v1/deliveries/{ids['delivery']}/status",
            headers=headers,
            json={**payload, **body},
        )
    target = "complete" if operation == "service_success" else "fail"
    payload = {} if target == "complete" else {"failure_cause": "CLIENTE_NO_ESTA"}
    return client.post(
        f"/api/v1/deliveries/{ids['delivery']}/{target}",
        headers=headers,
        json={**payload, **body},
    )


async def saved(sessions, ids):
    async with sessions() as db:
        order = (
            await db.execute(
                select(Order.status, Order.delivered_at, Order.failure_reason).where(
                    Order.id == ids["order"]
                )
            )
        ).one()
        delivery = (
            await db.execute(
                select(
                    Delivery.status,
                    Delivery.completed_at,
                    Delivery.locked_bonus_amount,
                    Delivery.locked_bonus_type,
                ).where(Delivery.id == ids["delivery"])
            )
        ).one()
        entries = (
            await db.execute(
                select(
                    Financial.transaction_type,
                    Financial.amount,
                    Financial.balance_before,
                    Financial.balance_after,
                    Financial.idempotency_key,
                ).order_by(Financial.created_at, Financial.id)
            )
        ).all()
        cache = (
            await db.execute(
                select(Rider.wallet_balance, Rider.version).where(
                    Rider.id == ids["rider"]
                )
            )
        ).one()
        modern = await db.scalar(select(RiderWallet.balance_cents))
        return (
            tuple(order),
            tuple(delivery),
            list(map(tuple, entries)),
            tuple(cache),
            modern,
        )


OPERATIONS = ["order", "success", "failure", "service_success", "service_failure"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", OPERATIONS)
async def test_all_terminal_entrypoints_append_contiguous_ledger_and_preserve_other_balances(
    payment_db, operation
):
    client, sessions, ids = payment_db
    result = request(client, ids, operation)
    assert result.status_code == 200, result.text
    data = await saved(sessions, ids)
    failure = "failure" in operation
    amount = Decimal("1.00") if failure else Decimal("2.50")
    assert data[0][0] == (OrderStatus.FALLIDO if failure else OrderStatus.ENTREGADO)
    assert data[1][0] == (
        DeliveryStatus.FALLIDA if failure else DeliveryStatus.COMPLETADA
    )
    assert len(data[2]) == 2
    assert data[2][-1][1:4] == (amount, Decimal("100"), Decimal("100") + amount)
    assert data[2][-1][4] == ("pago_fallido_" if failure else "pago_entrega_") + str(
        ids["order"]
    )
    assert data[3:] == ((Decimal("3.00"), 0), 1000)
    # A terminal transition cannot pay for a second completion/failure.
    again = request(client, ids, operation)
    assert again.status_code == 400, again.text
    assert await saved(sessions, ids) == data


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", OPERATIONS)
async def test_zero_bonus_closes_the_workflow_without_inventing_zero_movements(
    payment_db, operation
):
    client, sessions, ids = payment_db
    async with sessions() as db:
        await db.execute(update(PlatformSetting).values(value="0"))
        await db.commit()
    response = request(client, ids, operation)
    assert response.status_code == 200, response.text
    data = await saved(sessions, ids)
    assert len(data[2]) == 1 and data[3:] == ((Decimal("3.00"), 0), 1000)
    if operation == "failure":
        assert response.json()["bonus_applied"] is False
        assert response.json()["bonus_amount"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", OPERATIONS)
async def test_invalid_history_reverts_order_delivery_snapshot_and_new_movement(
    payment_db, operation
):
    client, sessions, ids = payment_db
    async with sessions() as db:
        await db.execute(update(Financial).values(balance_before=None))
        await db.commit()
    before = await saved(sessions, ids)
    response = request(client, ids, operation)
    assert response.status_code == 409, response.text
    assert await saved(sessions, ids) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", OPERATIONS)
async def test_failed_final_commit_reverts_the_whole_terminal_unit(
    payment_db, operation, monkeypatch
):
    client, sessions, ids = payment_db
    before = await saved(sessions, ids)
    original = AsyncSession.commit

    async def failed_commit(db):
        if db.info.get("workflow_request"):
            raise RuntimeError("injected workflow commit failure")
        return await original(db)

    monkeypatch.setattr(AsyncSession, "commit", failed_commit)
    response = request(client, ids, operation)
    assert response.status_code == 500, response.text
    assert await saved(sessions, ids) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", OPERATIONS)
async def test_ledger_flush_failure_cannot_leave_a_completed_domain_state(
    payment_db, operation, monkeypatch
):
    client, sessions, ids = payment_db
    before = await saved(sessions, ids)
    original = AsyncSession.flush

    async def failed_flush(db, *args, **kwargs):
        if db.info.get("workflow_request") and any(
            isinstance(item, Financial) for item in db.new
        ):
            raise RuntimeError("injected ledger insert failure")
        return await original(db, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "flush", failed_flush)
    response = request(client, ids, operation)
    assert response.status_code == 500, response.text
    assert await saved(sessions, ids) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operations",
    [
        ("success", "failure"),
        ("service_success", "service_failure"),
        ("order", "service_success"),
        ("order", "success"),
    ],
)
async def test_concurrent_terminal_paths_are_serialized_before_rechecking_state(
    payment_db, operations
):
    client, sessions, ids = payment_db
    responses = await asyncio.wait_for(
        asyncio.gather(
            *(asyncio.to_thread(request, client, ids, name) for name in operations)
        ),
        15,
    )
    assert sorted(r.status_code for r in responses) == [200, 400], [
        r.text for r in responses
    ]
    data = await saved(sessions, ids)
    assert len(data[2]) == 2
    failed = data[1][0] == DeliveryStatus.FALLIDA
    assert data[0][0] == (OrderStatus.FALLIDO if failed else OrderStatus.ENTREGADO)
    assert data[2][-1][0] == (
        TransactionType.PAGO_INTENTO_FALLIDO if failed else TransactionType.PAGO_ENTREGA
    )
    assert data[3:] == ((Decimal("3.00"), 0), 1000)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["order", "success", "failure"])
@pytest.mark.parametrize("collision", ["rider", "type", "status", "reference"])
async def test_existing_bonus_key_cannot_silently_belong_to_another_operation(
    payment_db, operation, collision
):
    client, sessions, ids = payment_db
    failed = operation == "failure"
    kind = (
        TransactionType.PAGO_INTENTO_FALLIDO if failed else TransactionType.PAGO_ENTREGA
    )
    async with sessions() as db:
        row = Financial(
            rider_id=ids["rider"],
            amount=1,
            balance_before=100,
            balance_after=101,
            transaction_type=kind,
            status=PaymentStatus.PROCESADO,
            reference_id=str(ids["order"]),
            idempotency_key=("pago_fallido_" if failed else "pago_entrega_")
            + str(ids["order"]),
        )
        if collision == "rider":
            owner = User(
                email=f"{uuid4()}@other.test",
                hashed_password="unused",
                first_name="Other",
                last_name="Rider",
                role=UserRole.REPARTIDOR,
            )
            db.add(owner)
            await db.flush()
            other = Rider(user_id=owner.id)
            db.add(other)
            await db.flush()
            row.rider_id = other.id
        elif collision == "type":
            row.transaction_type = TransactionType.RETIRO
        elif collision == "status":
            row.status = PaymentStatus.PENDIENTE
        else:
            row.reference_id = str(uuid4())
        db.add(row)
        await db.commit()
    before = await saved(sessions, ids)
    response = request(client, ids, operation)
    assert response.status_code == 409, response.text
    assert await saved(sessions, ids) == before


@pytest.mark.asyncio
async def test_calculated_fractional_reward_and_snapshot_use_the_same_cents(payment_db):
    client, sessions, ids = payment_db
    async with sessions() as db:
        await db.execute(
            update(PlatformSetting)
            .where(PlatformSetting.key == "rider_delivery_bonus")
            .values(value="2.505")
        )
        await db.commit()
    result = request(client, ids, "success")
    assert result.status_code == 200, result.text
    data = await saved(sessions, ids)
    assert data[1][2] == Decimal("2.51")
    assert data[2][-1][1] == Decimal("2.51")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["success", "service_success"])
async def test_tier_bonus_uses_decimal_midpoint_rounding_in_both_paths(
    payment_db, operation
):
    from app.models.rider import RiderTier

    client, sessions, ids = payment_db
    async with sessions() as db:
        await db.execute(
            update(PlatformSetting)
            .where(PlatformSetting.key == "rider_delivery_bonus")
            .values(value="5.50")
        )
        await db.execute(
            update(Rider).where(Rider.id == ids["rider"]).values(tier=RiderTier.PLATINO)
        )
        await db.commit()
    result = request(client, ids, operation)
    assert result.status_code == 200, result.text
    data = await saved(sessions, ids)
    # 5.50 * 1.15 = 6.325; binary float previously produced 6.324999999999999.
    assert data[1][2] == Decimal("6.33")
    assert data[2][-1][1:4] == (Decimal("6.33"), Decimal("100"), Decimal("106.33"))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["success", "failure"])
@pytest.mark.parametrize("value", [True, "NaN", "-1", "100000000", "bad"])
async def test_invalid_direct_reward_configuration_is_a_domain_error_with_no_partial_state(
    payment_db, operation, value
):
    client, sessions, ids = payment_db
    async with sessions() as db:
        await db.execute(update(PlatformSetting).values(value=value))
        await db.commit()
    before = await saved(sessions, ids)
    response = request(client, ids, operation)
    assert response.status_code == 400, response.text
    assert await saved(sessions, ids) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["service_success", "service_failure", "success"])
@pytest.mark.parametrize(
    "change,code", [("role", 403), ("inactive", 401), ("assignment", 403)]
)
async def test_account_and_ownership_are_rechecked_after_the_initial_handler_read(
    payment_db, operation, change, code, monkeypatch
):
    from app.services.delivery_ledger import lock_delivery_transition

    client, sessions, ids = payment_db
    entered, release = Future(), Future()

    async def paused(*args, **kwargs):
        if not entered.done():
            entered.set_result(None)
        await asyncio.wrap_future(release)
        return await lock_delivery_transition(*args, **kwargs)

    monkeypatch.setattr(
        "app.services.delivery_service.lock_delivery_transition", paused
    )
    monkeypatch.setattr("app.api.v1.deliveries.lock_delivery_transition", paused)
    async with asyncio.timeout(15):
        pending = asyncio.create_task(
            asyncio.to_thread(request, client, ids, operation, actor="owner")
        )
        try:
            await asyncio.wait_for(asyncio.wrap_future(entered), 5)
            async with sessions() as db:
                if change == "role":
                    await db.execute(
                        update(User)
                        .where(User.id == ids["owner"])
                        .values(role=UserRole.CLIENTE)
                    )
                elif change == "inactive":
                    await db.execute(
                        update(User)
                        .where(User.id == ids["owner"])
                        .values(is_active=False)
                    )
                else:
                    owner = User(
                        email="reassigned@payment.test",
                        hashed_password="unused",
                        first_name="New",
                        last_name="Owner",
                        role=UserRole.REPARTIDOR,
                    )
                    db.add(owner)
                    await db.flush()
                    rider = Rider(user_id=owner.id)
                    db.add(rider)
                    await db.flush()
                    await db.execute(
                        update(Delivery)
                        .where(Delivery.id == ids["delivery"])
                        .values(rider_id=rider.id)
                    )
                    await db.execute(
                        update(Order)
                        .where(Order.id == ids["order"])
                        .values(assigned_rider_id=rider.id)
                    )
                await db.commit()
            before = await saved(sessions, ids)
        finally:
            if not release.done():
                release.set_result(None)
        response = await asyncio.wait_for(pending, 10)
        assert response.status_code == code, response.text
        assert await saved(sessions, ids) == before


@pytest.mark.asyncio
async def test_workflow_ddl_fixture_keeps_production_mapping_contract_unchanged(
    payment_db,
):
    from tests.orm_contract import detailed_mapping_contract, cancellation_contract

    expected = json.loads(
        (
            Path(__file__).parent / "fixtures/orm_financial_dispatch_contract.json"
        ).read_text()
    )
    assert detailed_mapping_contract(tuple(expected)) == cancellation_contract(expected)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", OPERATIONS)
async def test_inconsistent_active_workflow_cannot_pay_opposite_terminal_bonuses(
    payment_db, operation
):
    client, sessions, ids = payment_db
    target_failure = "failure" in operation
    async with sessions() as db:
        db.add(
            Financial(
                rider_id=ids["rider"],
                amount=1,
                balance_before=100,
                balance_after=101,
                transaction_type=(
                    TransactionType.PAGO_ENTREGA
                    if target_failure
                    else TransactionType.PAGO_INTENTO_FALLIDO
                ),
                status=PaymentStatus.PROCESADO,
                reference_id=str(ids["order"]),
                idempotency_key=("pago_entrega_" if target_failure else "pago_fallido_")
                + str(ids["order"]),
            )
        )
        await db.commit()
    before = await saved(sessions, ids)
    response = request(client, ids, operation)
    assert response.status_code == 409, response.text
    assert await saved(sessions, ids) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [DeliveryStatus.COMPLETADA, DeliveryStatus.FALLIDA])
async def test_order_completion_does_not_override_a_conflicting_terminal_delivery(
    payment_db, status
):
    client, sessions, ids = payment_db
    async with sessions() as db:
        await db.execute(
            update(Delivery).where(Delivery.id == ids["delivery"]).values(status=status)
        )
        await db.commit()
    before = await saved(sessions, ids)
    response = request(client, ids, "order")
    assert response.status_code == 409, response.text
    assert await saved(sessions, ids) == before
