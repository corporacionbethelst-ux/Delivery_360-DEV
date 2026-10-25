from app.core.vehicle_revision import vehicle_revision

"""Observed fleet snapshots checked after acquiring real parent locks."""

import asyncio
import pytest
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import load_only, raiseload
from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from tests.test_document_uploads_postgresql import pg_documents  # noqa: F401
from tests.test_fleet_assignment_postgresql import pg_fleet, assign  # noqa: F401
from app.core.fleet_revision import assignment_revision
from app.models.rider import Rider
from app.models.vehicle import Vehicle
from app.services.document_review import lock_rider
from app.services.fleet_assignment import (
    prepare_vehicle_update,
    invalidate_vehicle_documents,
)


async def current(db, rider_id):
    return await db.scalar(
        select(Rider)
        .options(
            raiseload("*"),
            load_only(
                Rider.id,
                Rider.user_id,
                Rider.assigned_vehicle_id,
                Rider.vehicle_ownership_type,
                Rider.vehicle_type,
                Rider.vehicle_plate,
                Rider.vehicle_model,
            ),
        )
        .where(Rider.id == rider_id)
    )


async def snapshot(sessions, rider_id):
    async with sessions() as db:
        return assignment_revision(await current(db, rider_id))


async def write(sessions, rider_id, vehicle_id, token):
    async with sessions() as db:
        rider = await current(db, rider_id)
        candidate = await db.scalar(
            select(Vehicle).options(raiseload("*")).where(Vehicle.id == vehicle_id)
        )
        payload = {
            "vehicle_ownership_type": "EMPRESA",
            "assigned_vehicle_id": vehicle_id,
        }
        changed = await prepare_vehicle_update(
            db,
            rider,
            payload,
            token,
            expected_vehicle_revision=(
                vehicle_revision(candidate) if candidate else None
            ),
        )
        for key, value in payload.items():
            setattr(rider, key, value)
        await db.flush()
        if changed:
            await invalidate_vehicle_documents(db, rider_id)
        await db.commit()
        return rider.id


@pytest.mark.asyncio
async def test_old_form_cannot_replace_assignment_after_new_request_starts(pg_fleet):
    sessions, riders, vehicles = pg_fleet
    token = await snapshot(sessions, riders[0])
    await assign(sessions, riders[0], vehicles[0])
    with pytest.raises(HTTPException) as error:
        await write(sessions, riders[0], vehicles[1], token)
    assert error.value.status_code == 409
    async with sessions() as db:
        assert (
            await db.scalar(
                select(Rider.assigned_vehicle_id).where(Rider.id == riders[0])
            )
            == vehicles[0]
        )
        assert (
            await db.scalar(select(Vehicle.rider_id).where(Vehicle.id == vehicles[1]))
            is None
        )


@pytest.mark.asyncio
async def test_two_managers_with_one_snapshot_cannot_both_assign(pg_fleet):
    sessions, riders, vehicles = pg_fleet
    token = await snapshot(sessions, riders[0])
    results = await asyncio.gather(
        *(write(sessions, riders[0], vehicle_id, token) for vehicle_id in vehicles),
        return_exceptions=True,
    )
    assert sum(not isinstance(result, Exception) for result in results) == 1
    error = next(result for result in results if isinstance(result, Exception))
    assert isinstance(error, HTTPException) and error.status_code == 409


@pytest.mark.asyncio
async def test_revision_is_checked_against_state_after_waiting_for_parent(pg_fleet):
    sessions, riders, vehicles = pg_fleet
    token = await snapshot(sessions, riders[0])
    async with sessions() as editor:
        await lock_rider(editor, riders[0])
        task = asyncio.create_task(write(sessions, riders[0], vehicles[0], token))
        await asyncio.sleep(0.1)
        assert not task.done()
        await editor.execute(
            update(Rider)
            .where(Rider.id == riders[0])
            .values(vehicle_plate="NEWER-STATE")
        )
        await editor.commit()
    with pytest.raises(HTTPException) as error:
        await asyncio.wait_for(task, 10)
    assert error.value.status_code == 409
    async with sessions() as db:
        assert (
            await db.scalar(select(Rider.vehicle_plate).where(Rider.id == riders[0]))
            == "NEWER-STATE"
        )
        assert (
            await db.scalar(select(Vehicle.rider_id).where(Vehicle.id == vehicles[0]))
            is None
        )
