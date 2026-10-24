"""Preserve PostgreSQL DDL and real persisted scalar/nullable contracts."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import defer, selectinload

from app.models.payout import Payout
from app.models.rider import Rider, RiderTier
from app.models.vehicle import Vehicle
from app.api.v1.orders import _serialize_order_rider
from app.api.v1.riders import _rider_to_dict
from app.api.v1.payouts import _serialize_payout
from tests.orm_contract import detailed_mapping_contract

TABLES = (
    "payouts",
    "payout_status_history",
    "riders",
    "vehicles",
    "orders",
    "deliveries",
)


def test_typed_mappings_preserve_postgresql_contract():
    expected = json.loads(
        (
            Path(__file__).parent / "fixtures/orm_financial_dispatch_contract.json"
        ).read_text()
    )
    assert detailed_mapping_contract(TABLES) == expected


@pytest.mark.asyncio
async def test_nullable_historical_rider_serializes_without_fabricated_values(
    db_session, test_user
):
    rider = Rider(
        user_id=test_user.id,
        wallet_balance=Decimal("12.34"),
        badges=[{"name": "first", "earned": True}],
    )
    db_session.add(rider)
    await db_session.commit()
    rider_id = rider.id
    await db_session.execute(
        update(Rider)
        .where(Rider.id == rider_id)
        .values(status=None, vehicle_type=None, created_at=None)
    )
    await db_session.commit()
    db_session.expire_all()
    rider = await db_session.scalar(
        select(Rider)
        .where(Rider.id == rider_id)
        .options(
            defer(Rider.last_location),
            selectinload(Rider.user),
            selectinload(Rider.assigned_vehicle),
        )
    )
    assert isinstance(rider.id, UUID)
    assert rider.wallet_balance == Decimal("12.34")
    assert rider.tier == RiderTier.BRONCE
    assert rider.vehicle_ownership_type == "PROPIO"
    assert rider.badges == [{"name": "first", "earned": True}]
    profile = _rider_to_dict(rider)
    assigned = _serialize_order_rider(rider)
    assert profile["status"] is None and profile["vehicle_type"] is None
    assert profile["created_at"] is None
    assert assigned["status"] is None and assigned["vehicle_type"] is None


@pytest.mark.asyncio
async def test_fleet_string_enums_and_date_roundtrip(db_session, test_user):
    vehicle = Vehicle(
        type="MOTO",
        status="ACTIVO",
        plate="TEST-ORM",
        model="Test",
        color="Blue",
        year=2026,
        rider_id=test_user.id,
        insurance_expiry=date(2027, 1, 31),
    )
    db_session.add(vehicle)
    await db_session.commit()
    vehicle_id = vehicle.id
    db_session.expire_all()
    result = await db_session.scalar(select(Vehicle).where(Vehicle.id == vehicle_id))
    assert isinstance(result.id, UUID)
    assert type(result.type) is str
    assert type(result.status) is str
    assert result.type == "MOTO" and result.status == "ACTIVO"
    assert result.insurance_expiry == date(2027, 1, 31)


@pytest.mark.asyncio
async def test_historical_payout_null_dates_remain_null(
    test_engine, db_session, test_user
):
    async with test_engine.begin() as connection:
        await connection.run_sync(lambda conn: Payout.__table__.create(conn))
    rider = Rider(user_id=test_user.id)
    db_session.add(rider)
    await db_session.flush()
    payout = Payout(rider_id=rider.id, amount=Decimal("12.34"))
    db_session.add(payout)
    await db_session.commit()
    payout_id = payout.id
    await db_session.execute(
        update(Payout)
        .where(Payout.id == payout_id)
        .values(status=None, method=None, requested_at=None, updated_at=None)
    )
    await db_session.commit()
    db_session.expire_all()
    payout = await db_session.scalar(select(Payout).where(Payout.id == payout_id))
    response = _serialize_payout(payout)
    assert response["amount"] == 12.34
    assert response["status"] is None
    assert response["method"] is None
    assert response["created_at"] is None and response["updated_at"] is None
