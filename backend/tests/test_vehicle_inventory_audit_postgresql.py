"""Atomic inventory history using native PostgreSQL commits and failures."""

import asyncio
import pytest
from fastapi import HTTPException
from sqlalchemy import select, text, func
from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from tests.test_document_uploads_postgresql import pg_documents  # noqa: F401
from tests.test_fleet_assignment_postgresql import pg_fleet  # noqa: F401
from tests.test_vehicle_inventory_postgresql import (
    inventory_fleet,
    actor,
    token,
    edit,
)  # noqa: F401
from app.api.v1 import vehicles as api
from app.models.audit_log import AuditLog, ActionType
from app.models.vehicle import Vehicle
from app.services.fleet_assignment import lock_vehicles
from app.services.vehicle_inventory_audit import (
    inventory_snapshot,
    record_inventory_change,
)


@pytest.mark.asyncio
async def test_history_is_durable_after_commit_and_vehicle_deletion(inventory_fleet):
    sessions, _, vehicles = inventory_fleet
    expected = await token(sessions, vehicles[0])
    updated = await edit(sessions, vehicles[0], expected, "PG note")
    async with sessions() as db:
        event = await db.scalar(select(AuditLog))
        assert event.action_type == ActionType.UPDATE
        assert event.old_values["edit_revision"] == expected
        assert event.new_values["state"]["notes"] == "PG note"
        assert event.new_values["state"]["edit_revision"] == updated["edit_revision"]
        await api.delete_vehicle(
            str(vehicles[0]), db, await actor(db), if_match=updated["edit_revision"]
        )
    async with sessions() as db:
        assert (
            await db.scalar(select(Vehicle.id).where(Vehicle.id == vehicles[0])) is None
        )
        events = list(
            (await db.scalars(select(AuditLog).order_by(AuditLog.created_at))).all()
        )
        assert len(events) == 2 and events[-1].action_type == ActionType.DELETE
        assert events[-1].old_values["notes"] == "PG note"
        assert events[-1].new_values["state"] is None


@pytest.mark.asyncio
async def test_real_event_constraint_failure_restores_deleted_vehicle(inventory_fleet):
    sessions, _, vehicles = inventory_fleet
    expected = await token(sessions, vehicles[0])
    async with sessions() as db:
        await db.execute(
            text(
                "ALTER TABLE audit_logs ADD CONSTRAINT reject_inventory_event CHECK (resource_type <> 'Vehicle')"
            )
        )
        await db.commit()
    async with sessions() as db:
        with pytest.raises(HTTPException) as error:
            await api.delete_vehicle(
                str(vehicles[0]), db, await actor(db), if_match=expected
            )
        assert error.value.status_code == 503
    async with sessions() as db:
        assert (
            await db.scalar(select(Vehicle.id).where(Vehicle.id == vehicles[0]))
            == vehicles[0]
        )
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 0
    assert await token(sessions, vehicles[0]) == expected


@pytest.mark.asyncio
async def test_outer_rollback_after_audit_flush_removes_both_changes(inventory_fleet):
    sessions, _, vehicles = inventory_fleet
    expected = await token(sessions, vehicles[0])
    async with sessions() as db:
        vehicle = (await lock_vehicles(db, {vehicles[0]}))[vehicles[0]]
        before = inventory_snapshot(vehicle)
        vehicle.notes = "Transient"
        event_id = await record_inventory_change(
            db,
            await actor(db),
            vehicle_id=vehicle.id,
            before=before,
            after=inventory_snapshot(vehicle),
        )
        assert event_id is not None
        assert await db.scalar(select(AuditLog.id)) == event_id
        await db.rollback()
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 0
        assert (
            await db.scalar(select(Vehicle.notes).where(Vehicle.id == vehicles[0]))
            is None
        )
    assert await token(sessions, vehicles[0]) == expected


@pytest.mark.asyncio
async def test_same_precondition_competition_records_only_winner(inventory_fleet):
    sessions, _, vehicles = inventory_fleet
    expected = await token(sessions, vehicles[0])
    results = await asyncio.gather(
        *(edit(sessions, vehicles[0], expected, note) for note in ["A", "B"]),
        return_exceptions=True,
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    failure = next(result for result in results if isinstance(result, Exception))
    assert isinstance(failure, HTTPException) and failure.status_code == 409
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 1
        event = await db.scalar(select(AuditLog))
        assert event.new_values["state"]["notes"] == await db.scalar(
            select(Vehicle.notes).where(Vehicle.id == vehicles[0])
        )
