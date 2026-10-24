"""Regressions for persisted order fields and malformed monetary inputs."""

import math

import pytest
from fastapi import HTTPException

from app.api.v1.orders import _calculate_order_amounts
from app.core.json_types import json_value
from app.models.order import Order, OrderStatus, OrderPriority
from app.schemas.order import OrderCreate, OrderUpdate
from app.services.order_service import OrderService


def test_order_amounts_preserve_zero_total_fallback():
    assert _calculate_order_amounts(
        [{"quantity": 2, "unit_price": 3.5}], None, 2, 0
    ) == (7, 2, 9)


@pytest.mark.parametrize(
    "items",
    [
        {},
        [None],
        [{"quantity": -1, "unit_price": 2, "subtotal": 5}],
        [{"quantity": 1e308, "unit_price": 1e308}],
        [{"subtotal": 1e308}, {"subtotal": 1e308}],
        [{"subtotal": math.nan}],
        [{"unit_price": True}],
    ],
)
def test_invalid_items_cannot_produce_persisted_totals(items):
    with pytest.raises(HTTPException) as error:
        _calculate_order_amounts(items, None, 0, None)
    assert error.value.status_code == 422


def test_order_total_addition_rejects_overflow():
    with pytest.raises(HTTPException):
        _calculate_order_amounts([], 1e308, 1e308, 0)


@pytest.mark.parametrize("value", [{1: "invalid"}, {"price": math.inf}, [object()]])
def test_json_rejects_values_database_cannot_represent(value):
    with pytest.raises(ValueError):
        json_value(value)


@pytest.mark.asyncio
async def test_service_create_and_update_persist_real_coordinate_fields(
    test_engine, db_session
):
    async with test_engine.begin() as connection:
        await connection.run_sync(Order.__table__.create)
    service = OrderService()
    created = await service.create_order(
        db_session,
        OrderCreate(
            customer_name="Cliente",
            customer_phone="123",
            pickup_address="Origen",
            delivery_address="Destino",
            pickup_latitude=10.5,
            delivery_longitude=-66.9,
            items=[{"quantity": 2, "unit_price": 3.5}],
            subtotal=7,
            delivery_fee=2,
            total=9,
            status="ENTREGADO",
        ),
        created_by=1,
    )
    assert created.status == OrderStatus.PENDIENTE
    assert created.pickup_latitude == 10.5
    assert created.delivery_longitude == -66.9
    assert created.items == [{"quantity": 2, "unit_price": 3.5}]
    updated = await service.update_order(
        db_session,
        created.id,
        OrderUpdate(pickup_latitude=11.5, delivery_longitude=-67.1, priority="ALTA"),
        updated_by=1,
    )
    await db_session.refresh(updated)
    assert updated.pickup_latitude == 11.5
    assert updated.delivery_longitude == -67.1
    assert updated.priority == OrderPriority.ALTA


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["NaN", "Infinity", -1, "invalid", 10**400])
async def test_invalid_bonus_configuration_returns_warning_without_snapshot(value):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock
    from uuid import uuid4
    from app.models.delivery import LockedBonusType
    from app.services.delivery_service import DeliveryService

    result = MagicMock()
    result.fetchall.return_value = [
        SimpleNamespace(key="rider_delivery_bonus", value=value)
    ]
    session = AsyncMock()
    session.execute.return_value = result
    amount, warning = await DeliveryService()._get_bonus_config_and_snapshot(
        session, LockedBonusType.SUCCESS, uuid4(), uuid4()
    )
    assert amount == 0 and warning
    session.execute.assert_awaited_once()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_delivery_snapshot_roundtrip_preserves_decimal_and_caller_transaction(
    test_engine, db_session, test_user
):
    from decimal import Decimal
    from uuid import uuid4
    from unittest.mock import AsyncMock
    from sqlalchemy import select
    from app.models.delivery import Delivery, LockedBonusType
    from app.models.rider import Rider
    from app.services.delivery_service import DeliveryService

    async with test_engine.begin() as connection:
        await connection.run_sync(Order.__table__.create)
        await connection.run_sync(Delivery.__table__.create)
    rider = Rider(user_id=test_user.id)
    order = Order(
        customer_name="Cliente",
        customer_phone="123",
        pickup_address="A",
        delivery_address="B",
    )
    db_session.add_all([rider, order])
    await db_session.flush()
    delivery = Delivery(id=uuid4(), order_id=order.id, rider_id=rider.id)
    db_session.add(delivery)
    transaction_spy = AsyncMock()
    await DeliveryService()._create_financial_snapshot(
        transaction_spy, delivery, LockedBonusType.SUCCESS, 12.345
    )
    transaction_spy.commit.assert_not_awaited()
    assert delivery.locked_bonus_amount == Decimal("12.35")
    await db_session.commit()
    delivery_id = delivery.id
    db_session.expire_all()
    persisted = await db_session.scalar(
        select(Delivery).where(Delivery.id == delivery_id)
    )
    assert persisted.locked_bonus_amount == Decimal("12.35")
    assert persisted.locked_bonus_type == LockedBonusType.SUCCESS
