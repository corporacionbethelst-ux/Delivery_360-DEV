"""Real PostgreSQL assignment competition and vehicle mutation serialization."""

import asyncio
import pytest
from fastapi import HTTPException
from sqlalchemy import select, text, update
from sqlalchemy.orm import load_only, raiseload
from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from tests.test_document_uploads_postgresql import pg_documents  # noqa: F401
from app.models.rider import Rider, RiderStatus
from app.core.fleet_revision import assignment_revision
from app.models.vehicle import Vehicle
from app.services.fleet_assignment import (
    prepare_vehicle_update,
    invalidate_vehicle_documents,
    lock_vehicles,
    ensure_vehicle_unassigned,
)
from app.services.document_review import lock_rider


@pytest.fixture
async def pg_fleet(pg_documents):
    sessions, riders, _, _ = pg_documents
    async with sessions() as db:
        connection = await db.connection()
        await connection.run_sync(
            lambda conn: Rider.__table__.c.vehicle_type.type.create(
                conn, checkfirst=True
            )
        )
        await connection.run_sync(
            lambda conn: Vehicle.__table__.create(conn, checkfirst=True)
        )
        await connection.run_sync(
            lambda conn: Rider.__table__.c.vehicle_ownership_type.type.create(
                conn, checkfirst=True
            )
        )
        await db.execute(
            text(
                "ALTER TABLE riders ADD COLUMN vehicle_type vehicletype DEFAULT 'MOTO', ADD COLUMN vehicle_plate VARCHAR(20), ADD COLUMN vehicle_model VARCHAR(100), ADD COLUMN vehicle_ownership_type vehicleownershiptype DEFAULT 'PROPIO', ADD COLUMN assigned_vehicle_id UUID REFERENCES vehicles(id)"
            )
        )
        vehicles = [
            Vehicle(
                plate=f"FLEET-{n}",
                type="MOTO",
                status="ACTIVO",
                model="Test",
                color="Black",
                year=2025,
            )
            for n in range(2)
        ]
        db.add_all(vehicles)
        await db.commit()
        ids = [v.id for v in vehicles]
    return sessions, riders, ids


async def assign(sessions, rider_id, vehicle_id):
    async with sessions() as db:
        rider = await db.scalar(
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
        payload = {
            "vehicle_ownership_type": "EMPRESA",
            "assigned_vehicle_id": vehicle_id,
        }
        changed = await prepare_vehicle_update(
            db, rider, payload, assignment_revision(rider)
        )
        for key, value in payload.items():
            setattr(rider, key, value)
        await db.flush()
        if changed:
            await invalidate_vehicle_documents(db, rider_id)
        await db.commit()
        return rider.id


@pytest.mark.asyncio
async def test_two_riders_compete_for_one_vehicle_without_double_assignment(pg_fleet):
    sessions, riders, vehicles = pg_fleet
    results = await asyncio.gather(
        *(assign(sessions, rider_id, vehicles[0]) for rider_id in riders),
        return_exceptions=True,
    )
    assert sum(not isinstance(result, Exception) for result in results) == 1
    errors = [r for r in results if isinstance(r, Exception)]
    assert (
        len(errors) == 1
        and isinstance(errors[0], HTTPException)
        and errors[0].status_code == 409
    )
    async with sessions() as db:
        rows = (
            await db.execute(
                select(Rider.id, Rider.user_id).where(
                    Rider.assigned_vehicle_id == vehicles[0]
                )
            )
        ).all()
        assert len(rows) == 1
        assert (
            await db.scalar(select(Vehicle.rider_id).where(Vehicle.id == vehicles[0]))
            == rows[0].user_id
        )


@pytest.mark.asyncio
async def test_reassignment_releases_previous_vehicle_in_same_transaction(pg_fleet):
    sessions, riders, vehicles = pg_fleet
    await assign(sessions, riders[0], vehicles[0])
    await assign(sessions, riders[0], vehicles[1])
    await assign(sessions, riders[1], vehicles[0])
    async with sessions() as db:
        assert (
            await db.scalar(
                select(Rider.assigned_vehicle_id).where(Rider.id == riders[0])
            )
            == vehicles[1]
        )
        assert (
            await db.scalar(
                select(Rider.assigned_vehicle_id).where(Rider.id == riders[1])
            )
            == vehicles[0]
        )


@pytest.mark.asyncio
async def test_vehicle_delete_and_assignment_cannot_leave_dangling_links(pg_fleet):
    sessions, riders, vehicles = pg_fleet

    async def delete():
        async with sessions() as db:
            vehicle = (await lock_vehicles(db, {vehicles[0]}))[vehicles[0]]
            await ensure_vehicle_unassigned(db, vehicle)
            await db.delete(vehicle)
            await db.commit()

    results = await asyncio.gather(
        assign(sessions, riders[0], vehicles[0]), delete(), return_exceptions=True
    )
    assert sum(not isinstance(r, Exception) for r in results) == 1
    assert all(
        not isinstance(r, Exception)
        or isinstance(r, HTTPException)
        and r.status_code in (404, 409)
        for r in results
    )
    async with sessions() as db:
        pointer = await db.scalar(
            select(Rider.assigned_vehicle_id).where(Rider.id == riders[0])
        )
        exists = await db.scalar(select(Vehicle.id).where(Vehicle.id == vehicles[0]))
        assert (pointer is None and exists is None) or pointer == exists == vehicles[0]


@pytest.mark.asyncio
async def test_suspension_racing_assignment_is_preserved(pg_fleet):
    sessions, riders, vehicles = pg_fleet

    async def suspend():
        async with sessions() as db:
            await lock_rider(db, riders[0])
            await db.execute(
                update(Rider)
                .where(Rider.id == riders[0])
                .values(status=RiderStatus.SUSPENDIDO, is_online=False)
            )
            await db.commit()

    results = await asyncio.gather(
        assign(sessions, riders[0], vehicles[0]), suspend(), return_exceptions=True
    )
    assert all(not isinstance(r, Exception) for r in results), results
    async with sessions() as db:
        assert (
            await db.execute(
                select(Rider.status, Rider.is_online).where(Rider.id == riders[0])
            )
        ).one() == (RiderStatus.SUSPENDIDO, False)


@pytest.mark.asyncio
async def test_assignment_waiting_on_vehicle_observes_maintenance(pg_fleet):
    sessions, riders, vehicles = pg_fleet
    async with sessions() as admin:
        vehicle = (await lock_vehicles(admin, {vehicles[0]}))[vehicles[0]]
        task = asyncio.create_task(assign(sessions, riders[0], vehicles[0]))
        await asyncio.sleep(0.1)
        assert not task.done()
        vehicle.status = "MANTENIMIENTO"
        await admin.commit()
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
async def test_two_stale_assignments_for_same_rider_do_not_leave_two_owned_vehicles(
    pg_fleet,
):
    sessions, riders, vehicles = pg_fleet
    async with sessions() as admin:
        await lock_rider(admin, riders[0])
        tasks = [
            asyncio.create_task(assign(sessions, riders[0], vehicle_id))
            for vehicle_id in vehicles
        ]
        await asyncio.sleep(0.2)
        assert all(not task.done() for task in tasks)
        await admin.commit()
    results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 10)
    assert sum(not isinstance(result, Exception) for result in results) == 1, results
    error = next(result for result in results if isinstance(result, Exception))
    assert isinstance(error, HTTPException) and error.status_code == 409
    async with sessions() as db:
        user_id = await db.scalar(select(Rider.user_id).where(Rider.id == riders[0]))
        owned = list(
            (
                await db.scalars(select(Vehicle.id).where(Vehicle.rider_id == user_id))
            ).all()
        )
        assert len(owned) == 1
        assert (
            await db.scalar(
                select(Rider.assigned_vehicle_id).where(Rider.id == riders[0])
            )
            == owned[0]
        )
