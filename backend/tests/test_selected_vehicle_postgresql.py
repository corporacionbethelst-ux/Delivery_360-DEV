"""Candidate fingerprints checked while the vehicle row is locked."""

import asyncio
import pytest
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import raiseload
from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from tests.test_document_uploads_postgresql import pg_documents  # noqa: F401
from tests.test_fleet_assignment_postgresql import pg_fleet  # noqa: F401
from tests.test_fleet_form_postgresql import current, snapshot
from app.core.vehicle_revision import vehicle_revision
from app.models.rider import Rider
from app.models.vehicle import Vehicle
from app.services.fleet_assignment import (
    lock_vehicles,
    prepare_vehicle_update,
    invalidate_vehicle_documents,
)


async def candidate(sessions, vehicle_id):
    async with sessions() as db:
        vehicle = await db.scalar(
            select(Vehicle).options(raiseload("*")).where(Vehicle.id == vehicle_id)
        )
        return vehicle_revision(vehicle)


async def assign(sessions, rider_id, vehicle_id, source_revision, selected_revision):
    async with sessions() as db:
        rider = await current(db, rider_id)
        data = {"vehicle_ownership_type": "EMPRESA", "assigned_vehicle_id": vehicle_id}
        changed = await prepare_vehicle_update(
            db,
            rider,
            data,
            source_revision,
            expected_vehicle_revision=selected_revision,
        )
        for key, value in data.items():
            setattr(rider, key, value)
        await db.flush()
        if changed:
            await invalidate_vehicle_documents(db, rider_id)
        await db.commit()
        return rider.id


@pytest.mark.asyncio
async def test_changed_candidate_is_rejected_even_with_fresh_source_revision(pg_fleet):
    sessions, riders, vehicles = pg_fleet
    selected = await candidate(sessions, vehicles[0])
    async with sessions() as db:
        await db.execute(
            update(Vehicle)
            .where(Vehicle.id == vehicles[0])
            .values(model="Different model")
        )
        await db.commit()
    source = await snapshot(sessions, riders[0])
    with pytest.raises(HTTPException) as error:
        await assign(sessions, riders[0], vehicles[0], source, selected)
    assert error.value.status_code == 409 and "ficha" in error.value.detail
    async with sessions() as db:
        assert (
            await db.scalar(select(Vehicle.rider_id).where(Vehicle.id == vehicles[0]))
            is None
        )


@pytest.mark.asyncio
async def test_candidate_changed_while_request_waits_for_vehicle_lock(pg_fleet):
    sessions, riders, vehicles = pg_fleet
    selected, source = await candidate(sessions, vehicles[0]), await snapshot(
        sessions, riders[0]
    )
    async with sessions() as editor:
        vehicle = (await lock_vehicles(editor, {vehicles[0]}))[vehicles[0]]
        task = asyncio.create_task(
            assign(sessions, riders[0], vehicles[0], source, selected)
        )
        await asyncio.sleep(0.1)
        assert not task.done()
        vehicle.plate = "NEWER-PLATE"
        await editor.commit()
    with pytest.raises(HTTPException) as error:
        await asyncio.wait_for(task, 10)
    assert error.value.status_code == 409
    async with sessions() as db:
        assert (
            await db.scalar(
                select(Rider.assigned_vehicle_id).where(Rider.id == riders[0])
            )
            is None
        )


@pytest.mark.asyncio
async def test_one_of_two_riders_can_claim_a_selected_free_snapshot(pg_fleet):
    sessions, riders, vehicles = pg_fleet
    selected = await candidate(sessions, vehicles[0])
    sources = [await snapshot(sessions, rider_id) for rider_id in riders]
    results = await asyncio.gather(
        *(
            assign(sessions, rid, vehicles[0], token, selected)
            for rid, token in zip(riders, sources)
        ),
        return_exceptions=True,
    )
    assert sum(not isinstance(result, Exception) for result in results) == 1
    error = next(result for result in results if isinstance(result, Exception))
    assert isinstance(error, HTTPException) and error.status_code == 409
    async with sessions() as db:
        assert (
            len(
                (
                    await db.scalars(
                        select(Rider.id).where(Rider.assigned_vehicle_id == vehicles[0])
                    )
                ).all()
            )
            == 1
        )
