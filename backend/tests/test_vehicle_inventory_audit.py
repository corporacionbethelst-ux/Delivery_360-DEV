"""Inventory history and rollback, including state surviving physical deletion."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, func, text
from tests.test_fleet_assignment import fleet  # noqa: F401
from tests.test_document_uploads import submissions  # noqa: F401
from tests.test_private_documents import documents  # noqa: F401
from app.api.v1 import vehicles as api, audit
from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.core.vehicle_revision import vehicle_edit_revision
from app.models.audit_log import AuditLog, ActionType
from app.models.vehicle import Vehicle
from app.models.user import UserRole


@pytest.fixture
async def inventory_history(fleet):
    _, db, ctx, first, second = fleet
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
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


async def rows(db):
    return list(
        (await db.scalars(select(AuditLog).order_by(AuditLog.created_at))).all()
    )


def body(plate="NEW-1"):
    return {
        "plate": plate,
        "type": "MOTO",
        "model": "Inventory model",
        "color": "Black",
        "year": 2025,
        "notes": "Initial note",
        "insurance_expiry": "2027-01-01",
    }


@pytest.mark.asyncio
async def test_full_inventory_history_survives_delete_and_is_readable(
    inventory_history,
):
    client, db, ctx, _, _ = inventory_history
    created = await client.post("/api/v1/vehicles", json=body())
    assert created.status_code == 201, created.text
    state = created.json()
    vehicle_id = state["id"]
    edited = await client.patch(
        f"/api/v1/vehicles/{vehicle_id}",
        json={"notes": "Updated"},
        headers={"If-Match": state["edit_revision"]},
    )
    assert edited.status_code == 200, edited.text
    down = await client.patch(
        f"/api/v1/vehicles/{vehicle_id}",
        json={"status": "BAJA"},
        headers={"If-Match": edited.json()["edit_revision"]},
    )
    assert down.status_code == 200, down.text
    deleted = await client.delete(
        f"/api/v1/vehicles/{vehicle_id}",
        headers={"If-Match": down.json()["edit_revision"]},
    )
    assert deleted.status_code == 200, deleted.text
    events = await rows(db)
    assert [e.new_values["operation"] for e in events] == [
        "CREATE",
        "UPDATE",
        "DEACTIVATE",
        "DELETE",
    ]
    assert [e.action_type for e in events] == [
        ActionType.CREATE,
        ActionType.UPDATE,
        ActionType.STATUS_CHANGE,
        ActionType.DELETE,
    ]
    assert all(
        e.resource_type == "Vehicle" and e.resource_id == vehicle_id for e in events
    )
    assert all(
        e.user_id == ctx["current"][0].id
        and e.user_role == "GERENTE"
        and e.user_email is None
        for e in events
    )
    assert all(e.contains_personal_data and e.success for e in events)
    assert all(
        e.new_values["occurred_at_utc"] == e.created_at.isoformat() + "Z"
        for e in events
    )
    assert events[0].old_values is None
    assert events[0].new_values["state"]["notes"] == "Initial note"
    assert events[1].old_values["edit_revision"] == state["edit_revision"]
    assert events[1].new_values["changed_fields"] == ["notes"]
    assert events[-1].old_values["created_at"] == state["created_at"] + "Z"
    assert events[-1].old_values["updated_at"] is not None
    assert events[-1].old_values["status"] == "BAJA"
    assert events[-1].old_values["notes"] == "Updated"
    assert events[-1].new_values["state"] is None
    response = await client.get(
        "/api/v1/audit", params={"resource_type": "Vehicle", "resource_id": vehicle_id}
    )
    assert response.status_code == 200 and response.json()["total"] == 4
    assert (await client.get(f"/api/v1/vehicles/{vehicle_id}")).status_code == 404


@pytest.mark.asyncio
async def test_other_status_change_is_distinguished_from_deactivation(
    inventory_history,
):
    client, db, _, vehicle, _ = inventory_history
    response = await client.patch(
        f"/api/v1/vehicles/{vehicle.id}",
        json={"status": "MANTENIMIENTO"},
        headers={"If-Match": vehicle_edit_revision(vehicle)},
    )
    assert response.status_code == 200, response.text
    (event,) = await rows(db)
    assert event.new_values["operation"] == "STATUS_CHANGE"
    assert event.new_values["changed_fields"] == ["status"]


@pytest.mark.asyncio
async def test_noop_and_conflict_do_not_add_success_events(inventory_history):
    client, db, _, vehicle, _ = inventory_history
    vehicle_id = vehicle.id
    expected = vehicle_edit_revision(vehicle)
    assert (
        await client.patch(
            f"/api/v1/vehicles/{vehicle_id}",
            json={"notes": None},
            headers={"If-Match": expected},
        )
    ).status_code == 200
    assert not await rows(db)
    assert (
        await client.patch(
            f"/api/v1/vehicles/{vehicle_id}",
            json={"notes": "New"},
            headers={"If-Match": expected},
        )
    ).status_code == 200
    assert (
        await client.delete(
            f"/api/v1/vehicles/{vehicle_id}", headers={"If-Match": expected}
        )
    ).status_code == 409
    assert len(await rows(db)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "update", "deactivate", "delete"])
async def test_real_event_insert_failure_rolls_back_inventory(
    inventory_history, operation
):
    client, db, _, vehicle, _ = inventory_history
    vehicle_id = vehicle.id
    expected = vehicle_edit_revision(vehicle)
    await db.execute(
        text(
            "CREATE TRIGGER reject_inventory_audit BEFORE INSERT ON audit_logs BEGIN SELECT RAISE(ABORT,'inventory audit unavailable'); END"
        )
    )
    await db.commit()
    if operation == "create":
        response = await client.post("/api/v1/vehicles", json=body("FAILED-1"))
    elif operation == "delete":
        response = await client.delete(
            f"/api/v1/vehicles/{vehicle_id}", headers={"If-Match": expected}
        )
    else:
        response = await client.patch(
            f"/api/v1/vehicles/{vehicle_id}",
            json=(
                {"status": "BAJA"} if operation == "deactivate" else {"notes": "UNSAFE"}
            ),
            headers={"If-Match": expected},
        )
    assert response.status_code == 503, response.text
    assert "inventory audit unavailable" not in response.text
    assert (
        await db.scalar(select(Vehicle.id).where(Vehicle.plate == "FAILED-1")) is None
    )
    current = (await client.get(f"/api/v1/vehicles/{vehicle_id}")).json()
    assert (
        current["edit_revision"] == expected
        and current["status"] == "ACTIVO"
        and current["notes"] is None
    )
    assert not await rows(db)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role", [UserRole.OPERADOR, UserRole.REPARTIDOR, UserRole.CLIENTE, UserRole.AUDITOR]
)
async def test_unauthorized_writes_never_create_inventory_events(
    inventory_history, role
):
    client, db, ctx, vehicle, _ = inventory_history
    vehicle_id = vehicle.id
    expected = vehicle_edit_revision(vehicle)
    ctx["current"][0].role = role
    assert (await client.post("/api/v1/vehicles", json=body())).status_code == 403
    assert (
        await client.patch(
            f"/api/v1/vehicles/{vehicle_id}",
            json={"notes": "UNSAFE"},
            headers={"If-Match": expected},
        )
    ).status_code == 403
    assert (
        await client.delete(
            f"/api/v1/vehicles/{vehicle_id}", headers={"If-Match": expected}
        )
    ).status_code == 403
    assert await db.scalar(select(func.count()).select_from(AuditLog)) == 0
