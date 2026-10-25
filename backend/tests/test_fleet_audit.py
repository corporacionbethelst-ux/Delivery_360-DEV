from app.core.vehicle_revision import vehicle_revision

"""Committed fleet history, no-op policy and real audit-insert rollback."""

from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, func, text, update
from tests.test_fleet_assignment import fleet, change  # noqa: F401
from tests.test_document_uploads import submissions  # noqa: F401
from tests.test_private_documents import documents  # noqa: F401
from app.api.v1 import riders as api, audit, vehicles
from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.audit_log import AuditLog, ActionType
from app.models.rider import Rider, RiderStatus
from app.models.rider_document import RiderDocument, DocumentStatus
from app.models.user import User, UserRole
from app.models.vehicle import Vehicle


@pytest.fixture
async def history(fleet):
    _, db, ctx, first, second = fleet
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    app.include_router(vehicles.router, prefix="/api/v1")
    app.include_router(audit.router, prefix="/api/v1/audit")

    async def database():
        try:
            yield db
        except Exception:
            await db.rollback()
            raise

    async def identity():
        return ctx["current"][0]

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = identity
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, db, ctx, first, second


async def events(db):
    return list(
        (await db.scalars(select(AuditLog).order_by(AuditLog.created_at))).all()
    )


@pytest.mark.asyncio
async def test_assign_reassign_unassign_records_exact_before_after_and_actor(history):
    client, db, ctx, first, second = history
    target_user = ctx["current"][0].id
    actor = User(
        email="fleet-manager@example.test",
        first_name="Manager",
        last_name="Test",
        hashed_password="unused",
        role=UserRole.GERENTE,
    )
    db.add(actor)
    await db.commit()
    ctx["current"][0] = actor
    assert (
        await change(
            client,
            ctx,
            vehicle_ownership_type="EMPRESA",
            assigned_vehicle_id=str(first.id),
        )
    ).status_code == 200
    assert (
        await change(client, ctx, assigned_vehicle_id=str(second.id))
    ).status_code == 200
    assert (
        await change(
            client, ctx, vehicle_ownership_type="PROPIO", vehicle_plate="OWN-NEW"
        )
    ).status_code == 200
    logs = await events(db)
    assert [entry.action_type for entry in logs] == [
        ActionType.ASSIGN,
        ActionType.REASSIGN,
        ActionType.UPDATE,
    ]
    assert [entry.new_values["operation"] for entry in logs] == [
        "ASSIGN",
        "REASSIGN",
        "UNASSIGN",
    ]
    first_log, switched, released = logs
    assert first_log.user_id == actor.id and first_log.user_email is None
    assert first_log.user_role == "GERENTE"
    assert first_log.resource_type == "Rider" and first_log.resource_id == str(
        ctx["rider_id"]
    )
    assert first_log.old_values["user_id"] == str(target_user)
    assert first_log.old_values["assigned_vehicle_id"] is None
    assert first_log.new_values["assigned_vehicle_id"] == str(first.id)
    assert first_log.new_values["documents_invalidated"] == 1
    assert first_log.new_values["status"] == "PENDIENTE"
    assert first_log.contains_personal_data is True
    assert first_log.new_values["event_family"] == "RIDER_FLEET"
    assert first_log.new_values["schema_version"] == 1
    assert (
        first_log.new_values["occurred_at_utc"]
        == first_log.created_at.isoformat() + "Z"
    )
    assert first_log.new_values["source"] == "rider_patch"
    assert "phone" not in first_log.new_values and "email" not in first_log.new_values
    assert switched.old_values["vehicle_links"][str(first.id)] == str(target_user)
    assert switched.new_values["vehicle_links"][str(first.id)] is None
    assert switched.new_values["vehicle_links"][str(second.id)] == str(target_user)
    assert released.new_values["vehicle_links"][str(second.id)] is None
    response = await client.get(
        "/api/v1/audit",
        params={"resource_type": "Rider", "resource_id": str(ctx["rider_id"])},
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 3
    assert all(
        item["success"] and item["new_values"]["event_family"] == "RIDER_FLEET"
        for item in response.json()["items"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("own", [False, True])
async def test_physical_change_records_source_and_revisions(history, own):
    client, db, ctx, _, _ = history
    old = (await client.get(f"/api/v1/riders/{ctx['rider_id']}")).json()
    response = await client.request(
        "PUT" if own else "PATCH",
        "/api/v1/riders/me" if own else f"/api/v1/riders/{ctx['rider_id']}",
        json={
            "vehicle_plate": "NEW-PHYSICAL",
            "expected_assignment_revision": old["assignment_revision"],
        },
    )
    assert response.status_code == 200, response.text
    (log,) = await events(db)
    assert log.old_values["assignment_revision"] == old["assignment_revision"]
    assert (
        log.new_values["assignment_revision"] == response.json()["assignment_revision"]
    )
    assert log.new_values["vehicle_plate"] == "NEW-PHYSICAL"
    assert log.new_values["operation"] == "VEHICLE_UPDATE"
    assert log.new_values["source"] == ("self_profile" if own else "rider_patch")
    assert "vehicle_plate" in log.new_values["changed_fields"]


@pytest.mark.asyncio
async def test_noop_and_rejected_revision_do_not_create_success_events(history):
    client, db, ctx, first, _ = history
    assert (
        await change(
            client,
            ctx,
            vehicle_ownership_type="EMPRESA",
            assigned_vehicle_id=str(first.id),
        )
    ).status_code == 200
    assert (
        await change(client, ctx, assigned_vehicle_id=str(first.id))
    ).status_code == 200
    response = await change(
        client, ctx, vehicle_plate="STALE", expected_assignment_revision="0" * 64
    )
    assert response.status_code == 409
    assert len(await events(db)) == 1


@pytest.mark.asyncio
async def test_link_only_repair_is_audited_and_invalidates_uncertain_documents(history):
    client, db, ctx, first, _ = history
    assert (
        await change(
            client,
            ctx,
            vehicle_ownership_type="EMPRESA",
            assigned_vehicle_id=str(first.id),
        )
    ).status_code == 200
    await db.execute(
        update(Vehicle).where(Vehicle.id == first.id).values(rider_id=None)
    )
    await db.execute(
        update(RiderDocument).values(
            status=DocumentStatus.APROBADO, updated_at=func.current_timestamp()
        )
    )
    await db.commit()
    response = await change(client, ctx, assigned_vehicle_id=str(first.id))
    assert response.status_code == 200, response.text
    logs = await events(db)
    assert len(logs) == 2
    assert logs[-1].new_values["operation"] == "LINK_REPAIR"
    assert logs[-1].old_values["vehicle_links"][str(first.id)] is None
    assert logs[-1].new_values["vehicle_links"][str(first.id)] == str(
        ctx["current"][0].id
    )
    assert await db.scalar(select(RiderDocument.status)) == DocumentStatus.RECHAZADO


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["assignment", "self", "creation"])
async def test_real_audit_insert_failure_rolls_back_entire_operation(history, kind):
    client, db, ctx, first, _ = history
    vehicle_id = first.id
    old = (await client.get(f"/api/v1/riders/{ctx['rider_id']}")).json()
    await db.execute(
        text(
            "CREATE TRIGGER reject_fleet_audit BEFORE INSERT ON audit_logs BEGIN SELECT RAISE(ABORT, 'audit rejected'); END"
        )
    )
    await db.commit()
    if kind == "creation":
        response = await client.post(
            "/api/v1/riders",
            json={
                "email": "failed-new@example.test",
                "password": "ValidPassword123!",
                "first_name": "New",
                "last_name": "Test",
                "phone": "+584121234567",
                "vehicle_type": "MOTO",
                "vehicle_ownership_type": "EMPRESA",
                "assigned_vehicle_id": str(vehicle_id),
                "expected_vehicle_revision": vehicle_revision(first),
            },
        )
    elif kind == "self":
        response = await client.put(
            "/api/v1/riders/me",
            json={
                "vehicle_plate": "SHOULD-ROLLBACK",
                "expected_assignment_revision": old["assignment_revision"],
            },
        )
    else:
        response = await change(
            client,
            ctx,
            vehicle_ownership_type="EMPRESA",
            assigned_vehicle_id=str(vehicle_id),
            phone="+584129999999",
        )
    assert response.status_code == 503, response.text
    assert "audit rejected" not in response.text
    assert (
        await db.scalar(select(Vehicle.rider_id).where(Vehicle.id == vehicle_id))
        is None
    )
    assert (
        await db.scalar(select(User.id).where(User.email == "failed-new@example.test"))
        is None
    )
    current = (await client.get(f"/api/v1/riders/{ctx['rider_id']}")).json()
    assert current["assignment_revision"] == old["assignment_revision"]
    assert current["phone"] == old["phone"]
    assert current["status"] == old["status"]
    assert await db.scalar(select(RiderDocument.status)) == DocumentStatus.APROBADO
    assert not await events(db)


@pytest.mark.asyncio
async def test_creation_audit_is_committed_with_profile(history):
    client, db, ctx, first, _ = history
    response = await client.post(
        "/api/v1/riders",
        json={
            "email": "created-audit@example.test",
            "password": "ValidPassword123!",
            "first_name": "New",
            "last_name": "Test",
            "phone": "+584121234567",
            "vehicle_type": "MOTO",
            "vehicle_ownership_type": "EMPRESA",
            "assigned_vehicle_id": str(first.id),
            "expected_vehicle_revision": vehicle_revision(first),
        },
    )
    assert response.status_code == 201, response.text
    (log,) = await events(db)
    assert log.old_values is None
    assert log.resource_id == response.json()["id"]
    assert log.action_type == ActionType.CREATE
    assert log.new_values["source"] == "admin_create"
    assert (
        log.new_values["assignment_revision"] == response.json()["assignment_revision"]
    )
    assert log.new_values["documents_invalidated"] == 0


@pytest.mark.asyncio
async def test_unauthorized_assignment_has_no_audit_record(history):
    client, db, ctx, first, _ = history
    ctx["current"][0].role = UserRole.REPARTIDOR
    response = await change(
        client, ctx, vehicle_ownership_type="EMPRESA", assigned_vehicle_id=str(first.id)
    )
    assert response.status_code == 403
    assert not await events(db)
