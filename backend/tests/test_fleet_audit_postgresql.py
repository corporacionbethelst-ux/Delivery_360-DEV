from app.core.vehicle_revision import vehicle_revision

"""Durable fleet/audit coupling with native PostgreSQL transactions."""

import asyncio
import pytest
from fastapi import HTTPException
from sqlalchemy.orm import raiseload
from sqlalchemy import select, text, func
from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from tests.test_document_uploads_postgresql import pg_documents  # noqa: F401
from tests.test_fleet_assignment_postgresql import pg_fleet  # noqa: F401
from tests.test_fleet_form_postgresql import current, snapshot
from app.models.audit_log import AuditLog, ActionType
from app.models.rider import Rider
from app.models.user import User, UserRole
from app.models.vehicle import Vehicle
from app.services.fleet_assignment import (
    prepare_vehicle_update,
    invalidate_vehicle_documents,
)
from app.services.fleet_audit import record_fleet_change


@pytest.fixture
async def audited(pg_fleet):
    sessions, riders, vehicles = pg_fleet
    async with sessions() as db:
        connection = await db.connection()
        await connection.run_sync(
            lambda conn: AuditLog.__table__.create(conn, checkfirst=True)
        )
        actor = User(
            email="pg-fleet-auditor@example.test",
            first_name="Admin",
            last_name="Test",
            role=UserRole.GERENTE,
            hashed_password="unused",
        )
        db.add(actor)
        await db.commit()
        actor_id = actor.id
    return sessions, riders, vehicles, actor_id


async def apply(db, rider_id, vehicle_id, actor_id, token):
    rider = await current(db, rider_id)
    candidate = await db.scalar(
        select(Vehicle).options(raiseload("*")).where(Vehicle.id == vehicle_id)
    )
    payload = {"vehicle_ownership_type": "EMPRESA", "assigned_vehicle_id": vehicle_id}
    before = {}
    changed = await prepare_vehicle_update(
        db,
        rider,
        payload,
        token,
        before_state=before,
        expected_vehicle_revision=vehicle_revision(candidate) if candidate else None,
    )
    for key, value in payload.items():
        setattr(rider, key, value)
    await db.flush()
    if changed:
        count = await invalidate_vehicle_documents(db, rider_id)
        await db.refresh(rider, attribute_names=["status", "is_online"])
        actor = await db.get(User, actor_id)
        return await record_fleet_change(
            db,
            rider,
            actor,
            before=before,
            source="rider_patch",
            documents_invalidated=count,
        )
    return None


@pytest.mark.asyncio
async def test_event_survives_commit_and_matches_committed_links(audited):
    sessions, riders, vehicles, actor_id = audited
    token = await snapshot(sessions, riders[0])
    async with sessions() as db:
        event_id = await apply(db, riders[0], vehicles[0], actor_id, token)
        await db.commit()
    async with sessions() as db:
        event = await db.get(AuditLog, event_id)
        assert event.user_id == actor_id and event.user_role == "GERENTE"
        assert event.action_type == ActionType.ASSIGN
        assert event.old_values["assignment_revision"] == token
        assert event.new_values["documents_invalidated"] == 1
        assert event.new_values["assigned_vehicle_id"] == str(vehicles[0])
        assert event.new_values["is_online"] is False
        assert (
            await db.scalar(
                select(Rider.assigned_vehicle_id).where(Rider.id == riders[0])
            )
            == vehicles[0]
        )


@pytest.mark.asyncio
async def test_real_audit_constraint_failure_rolls_back_business_and_history(audited):
    sessions, riders, vehicles, actor_id = audited
    token = await snapshot(sessions, riders[0])
    async with sessions() as db:
        await db.execute(
            text(
                "ALTER TABLE audit_logs ADD CONSTRAINT reject_fleet_event CHECK (resource_type <> 'Rider')"
            )
        )
        await db.commit()
    async with sessions() as db:
        with pytest.raises(HTTPException) as error:
            await apply(db, riders[0], vehicles[0], actor_id, token)
        assert error.value.status_code == 503
    async with sessions() as db:
        assert (
            await db.scalar(
                select(Rider.assigned_vehicle_id).where(Rider.id == riders[0])
            )
            is None
        )
        assert (
            await db.scalar(select(Vehicle.rider_id).where(Vehicle.id == vehicles[0]))
            is None
        )
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 0
    assert await snapshot(sessions, riders[0]) == token


@pytest.mark.asyncio
async def test_outer_rollback_after_audit_flush_removes_both(audited):
    sessions, riders, vehicles, actor_id = audited
    token = await snapshot(sessions, riders[0])
    async with sessions() as db:
        event_id = await apply(db, riders[0], vehicles[0], actor_id, token)
        assert event_id is not None
        assert await db.scalar(select(AuditLog.id)) == event_id
        await db.rollback()
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 0
        assert (
            await db.scalar(select(Vehicle.rider_id).where(Vehicle.id == vehicles[0]))
            is None
        )
    assert await snapshot(sessions, riders[0]) == token


@pytest.mark.asyncio
async def test_concurrent_same_snapshot_records_only_winning_change(audited):
    sessions, riders, vehicles, actor_id = audited
    token = await snapshot(sessions, riders[0])

    async def write(vehicle_id):
        async with sessions() as db:
            event_id = await apply(db, riders[0], vehicle_id, actor_id, token)
            await db.commit()
            return event_id

    results = await asyncio.gather(
        *(write(vehicle_id) for vehicle_id in vehicles), return_exceptions=True
    )
    assert sum(not isinstance(result, Exception) for result in results) == 1
    failure = next(result for result in results if isinstance(result, Exception))
    assert isinstance(failure, HTTPException) and failure.status_code == 409
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 1
        event = await db.scalar(select(AuditLog))
        assert event.new_values["assigned_vehicle_id"] == str(
            await db.scalar(
                select(Rider.assigned_vehicle_id).where(Rider.id == riders[0])
            )
        )
