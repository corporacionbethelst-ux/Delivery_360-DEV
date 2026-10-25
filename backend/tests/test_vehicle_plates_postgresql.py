"""Native PostgreSQL concurrent plate claims and uniqueness fallback."""

import asyncio
import pytest
from fastapi import HTTPException
from sqlalchemy import select, func, text
from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from tests.test_document_uploads_postgresql import pg_documents  # noqa: F401
from tests.test_fleet_assignment_postgresql import pg_fleet  # noqa: F401
from tests.test_vehicle_inventory_postgresql import (
    inventory_fleet,
    actor,
    token,
)  # noqa: F401
from tests.test_vehicle_inventory_audit import body
from app.api.v1 import vehicles as api
from app.models.vehicle import Vehicle
from app.models.audit_log import AuditLog
from app.services.vehicle_plates import claim_vehicle_plate


async def create(sessions, plate):
    async with sessions() as db:
        return await api.create_vehicle(
            api.VehicleCreate(**body(plate)), db, await actor(db)
        )


async def rename(sessions, vid, revision, plate):
    async with sessions() as db:
        return await api.update_vehicle(
            str(vid),
            api.VehicleUpdate(plate=plate, notes="Winner"),
            db,
            await actor(db),
            if_match=revision,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operations", ["create-create", "rename-rename", "create-rename"]
)
async def test_only_one_concurrent_claim_commits_with_one_audit(
    inventory_fleet, operations
):
    sessions, _, vehicles = inventory_fleet
    revisions = [await token(sessions, vid) for vid in vehicles]
    left = (
        create(sessions, " race-1 ")
        if operations.startswith("create")
        else rename(sessions, vehicles[0], revisions[0], " race-1 ")
    )
    right = (
        create(sessions, "\trace-1\n")
        if operations.endswith("create")
        else rename(sessions, vehicles[1], revisions[1], "\trace-1\n")
    )
    results = await asyncio.wait_for(
        asyncio.gather(left, right, return_exceptions=True), 15
    )
    assert sum(isinstance(result, dict) for result in results) == 1, results
    error = next(result for result in results if isinstance(result, Exception))
    assert isinstance(error, HTTPException) and error.status_code == 409
    assert error.detail["code"] == "VEHICLE_PLATE_CONFLICT"
    async with sessions() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Vehicle)
                .where(Vehicle.plate == "RACE-1")
            )
            == 1
        )
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 1
        for vid, revision in zip(vehicles, revisions):
            current = await db.get(Vehicle, vid)
            if current.plate != "RACE-1":
                assert current.notes is None
                assert await token(sessions, vid) == revision


@pytest.mark.asyncio
async def test_waiting_claim_reads_committed_plate_and_rollback_releases_lock(
    inventory_fleet,
):
    sessions, _, _ = inventory_fleet
    async with sessions() as holder:
        await claim_vehicle_plate(holder, " HOLD-1 ")
        task = asyncio.create_task(create(sessions, "\thold-1\n"))
        await asyncio.sleep(0.1)
        assert not task.done()
        holder.add(
            Vehicle(
                plate="HOLD-1",
                type="MOTO",
                model="Held",
                color="Black",
                year=2025,
                status="ACTIVO",
            )
        )
        await holder.commit()
    with pytest.raises(HTTPException) as error:
        await asyncio.wait_for(task, 10)
    assert error.value.detail["code"] == "VEHICLE_PLATE_CONFLICT"
    async with sessions() as holder:
        await claim_vehicle_plate(holder, "ROLLBACK-1")
        task = asyncio.create_task(create(sessions, "rollback-1"))
        await asyncio.sleep(0.1)
        assert not task.done()
        await holder.rollback()
    assert (await asyncio.wait_for(task, 10))["plate"] == "ROLLBACK-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "update"])
async def test_native_unique_index_failure_is_conflict_not_audit_unavailable(
    inventory_fleet, monkeypatch, operation
):
    sessions, _, vehicles = inventory_fleet
    revision = await token(sessions, vehicles[0])
    async with sessions() as db:
        duplicate = await db.scalar(
            select(Vehicle.plate).where(Vehicle.id == vehicles[1])
        )

    async def bypass(*args, **kwargs):
        pass

    monkeypatch.setattr(api, "claim_vehicle_plate", bypass)
    with pytest.raises(HTTPException) as error:
        if operation == "create":
            await create(sessions, duplicate)
        else:
            await rename(sessions, vehicles[0], revision, duplicate)
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "VEHICLE_PLATE_CONFLICT"
    assert await token(sessions, vehicles[0]) == revision
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 0


@pytest.mark.asyncio
async def test_other_unique_constraint_is_not_mislabeled_as_plate_conflict(
    inventory_fleet,
):
    sessions, _, vehicles = inventory_fleet
    async with sessions() as db:
        await db.execute(
            text("CREATE UNIQUE INDEX test_unique_model ON vehicles(model, plate)")
        )
        # A different uniqueness rule on notes fails before the audit write.
        await db.execute(
            text("CREATE UNIQUE INDEX test_unique_notes ON vehicles(notes)")
        )
        await db.execute(
            text("UPDATE vehicles SET notes='Occupied' WHERE id=:id"),
            {"id": vehicles[1]},
        )
        await db.commit()
    from sqlalchemy.exc import IntegrityError

    revision = await token(sessions, vehicles[0])
    async with sessions() as db:
        with pytest.raises(IntegrityError):
            await api.update_vehicle(
                str(vehicles[0]),
                api.VehicleUpdate(notes="Occupied"),
                db,
                await actor(db),
                if_match=revision,
            )
        await db.rollback()
    assert await token(sessions, vehicles[0]) == revision
