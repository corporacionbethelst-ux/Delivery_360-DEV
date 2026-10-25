"""Inventory preconditions checked against rows protected by PostgreSQL locks."""

import asyncio
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import raiseload
from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from tests.test_document_uploads_postgresql import pg_documents  # noqa: F401
from tests.test_fleet_assignment_postgresql import pg_fleet, assign  # noqa: F401
from app.api.v1 import vehicles as api
from app.core.vehicle_revision import vehicle_edit_revision
from app.models.vehicle import Vehicle
from app.services.fleet_assignment import lock_vehicles


async def token(sessions, vehicle_id):
    async with sessions() as db:
        return vehicle_edit_revision(
            await db.scalar(
                select(Vehicle).options(raiseload("*")).where(Vehicle.id == vehicle_id)
            )
        )


async def edit(sessions, vehicle_id, expected, notes):
    async with sessions() as db:
        return await api.update_vehicle(
            str(vehicle_id),
            api.VehicleUpdate(notes=notes),
            db,
            SimpleNamespace(),
            if_match=expected,
        )


@pytest.mark.asyncio
async def test_two_editors_with_same_tag_only_one_can_commit(pg_fleet):
    sessions, _, vehicles = pg_fleet
    expected = await token(sessions, vehicles[0])
    results = await asyncio.gather(
        *(edit(sessions, vehicles[0], expected, note) for note in ["FIRST", "SECOND"]),
        return_exceptions=True,
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    error = next(result for result in results if isinstance(result, Exception))
    assert isinstance(error, HTTPException) and error.status_code == 409
    async with sessions() as db:
        assert await db.scalar(
            select(Vehicle.notes).where(Vehicle.id == vehicles[0])
        ) in ("FIRST", "SECOND")


@pytest.mark.asyncio
async def test_waiting_editor_observes_new_note_under_lock(pg_fleet):
    sessions, _, vehicles = pg_fleet
    expected = await token(sessions, vehicles[0])
    async with sessions() as editor:
        vehicle = (await lock_vehicles(editor, {vehicles[0]}))[vehicles[0]]
        task = asyncio.create_task(edit(sessions, vehicles[0], expected, "STALE"))
        await asyncio.sleep(0.1)
        assert not task.done()
        vehicle.notes = "NEWER"
        await editor.commit()
    with pytest.raises(HTTPException) as error:
        await asyncio.wait_for(task, 10)
    assert error.value.status_code == 409
    async with sessions() as db:
        assert (
            await db.scalar(select(Vehicle.notes).where(Vehicle.id == vehicles[0]))
            == "NEWER"
        )


@pytest.mark.asyncio
async def test_edit_and_delete_cannot_both_accept_old_tag(pg_fleet):
    sessions, _, vehicles = pg_fleet
    expected = await token(sessions, vehicles[0])

    async def delete():
        async with sessions() as db:
            return await api.delete_vehicle(
                str(vehicles[0]), db, SimpleNamespace(), if_match=expected
            )

    results = await asyncio.gather(
        edit(sessions, vehicles[0], expected, "NEW"), delete(), return_exceptions=True
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    error = next(result for result in results if isinstance(result, Exception))
    assert isinstance(error, HTTPException) and error.status_code in (404, 409)
    async with sessions() as db:
        note = await db.scalar(select(Vehicle.notes).where(Vehicle.id == vehicles[0]))
        assert note in (None, "NEW")


@pytest.mark.asyncio
async def test_owner_change_invalidates_even_cosmetic_editor(pg_fleet):
    sessions, riders, vehicles = pg_fleet
    expected = await token(sessions, vehicles[0])
    await assign(sessions, riders[0], vehicles[0])
    with pytest.raises(HTTPException) as error:
        await edit(sessions, vehicles[0], expected, "STALE")
    assert error.value.status_code == 409
    async with sessions() as db:
        assert (
            await db.scalar(select(Vehicle.notes).where(Vehicle.id == vehicles[0]))
            is None
        )
