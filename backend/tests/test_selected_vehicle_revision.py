"""A chosen candidate must still match the record the client observed."""

from datetime import date
import pytest
from sqlalchemy import select, update, func
from tests.test_fleet_assignment import fleet  # noqa: F401
from tests.test_document_uploads import submissions  # noqa: F401
from tests.test_private_documents import documents  # noqa: F401
from app.core.vehicle_revision import vehicle_revision
from app.models.rider import Rider
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.audit_log import AuditLog
from app.models.rider_document import RiderDocument, DocumentStatus


async def command(client, ctx, vehicle, token, kind):
    if kind == "creation":
        return await client.post(
            "/api/v1/riders",
            json={
                "email": "candidate-new@example.test",
                "password": "ValidPassword123!",
                "first_name": "New",
                "last_name": "Rider",
                "phone": "+584121234567",
                "vehicle_type": "MOTO",
                "vehicle_ownership_type": "EMPRESA",
                "assigned_vehicle_id": str(vehicle),
                "expected_vehicle_revision": token,
            },
        )
    profile = (await client.get(f"/api/v1/riders/{ctx['rider_id']}")).json()
    return await client.request(
        "PUT" if kind == "self" else "PATCH",
        "/api/v1/riders/me" if kind == "self" else f"/api/v1/riders/{ctx['rider_id']}",
        json={
            "vehicle_ownership_type": "EMPRESA",
            "assigned_vehicle_id": str(vehicle),
            "expected_assignment_revision": profile["assignment_revision"],
            "expected_vehicle_revision": token,
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["creation", "patch", "self"])
@pytest.mark.parametrize(
    "token,status", [(None, 409), ("0" * 64, 409), ("invalid", 422)]
)
async def test_missing_stale_or_malformed_candidate_never_changes_business(
    fleet, kind, token, status
):
    client, db, ctx, vehicle, _ = fleet
    vehicle_id = vehicle.id
    response = await command(client, ctx, vehicle_id, token, kind)
    assert response.status_code == status, response.text
    assert (
        await db.scalar(select(Vehicle.rider_id).where(Vehicle.id == vehicle_id))
        is None
    )
    assert (
        await db.scalar(
            select(Rider.assigned_vehicle_id).where(Rider.id == ctx["rider_id"])
        )
        is None
    )
    assert (
        await db.scalar(
            select(User.id).where(User.email == "candidate-new@example.test")
        )
        is None
    )
    assert await db.scalar(select(RiderDocument.status)) == DocumentStatus.APROBADO
    assert await db.scalar(select(func.count()).select_from(AuditLog)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("plate", "CHANGED"),
        ("model", "Different"),
        ("type", "AUTO"),
        ("year", 2024),
        ("color", "Blue"),
        ("insurance_expiry", date(2027, 1, 1)),
        ("status", "MANTENIMIENTO"),
    ],
)
async def test_earlier_selection_cannot_claim_changed_candidate(fleet, field, value):
    client, db, ctx, vehicle, _ = fleet
    vehicle_id = vehicle.id
    token = vehicle_revision(vehicle)
    await db.execute(
        update(Vehicle).where(Vehicle.id == vehicle_id).values(**{field: value})
    )
    await db.commit()
    response = await command(client, ctx, vehicle_id, token, "patch")
    assert response.status_code == 409, response.text
    assert (
        await db.scalar(
            select(Rider.assigned_vehicle_id).where(Rider.id == ctx["rider_id"])
        )
        is None
    )
    assert await db.scalar(select(func.count()).select_from(AuditLog)) == 0


@pytest.mark.asyncio
async def test_selected_revision_is_exposed_in_catalog_and_committed_audit(fleet):
    client, db, ctx, vehicle, _ = fleet
    available = (await client.get("/api/v1/vehicles/available")).json()
    shown = next(item for item in available if item["id"] == str(vehicle.id))
    assert shown["revision"] == vehicle_revision(vehicle)
    response = await command(client, ctx, vehicle.id, shown["revision"], "patch")
    assert response.status_code == 200, response.text
    assert (
        response.json()["assigned_vehicle"]["revision"] != shown["revision"]
    )  # ownership changes its state
    event = await db.scalar(select(AuditLog))
    assert event.new_values["selected_vehicle_revision"] == shown["revision"]
    current = response.json()["assigned_vehicle"]["revision"]
    noop = await command(client, ctx, vehicle.id, current, "patch")
    assert noop.status_code == 200
    assert await db.scalar(select(func.count()).select_from(AuditLog)) == 1


@pytest.mark.asyncio
async def test_notes_and_timestamp_do_not_change_candidate_revision(fleet):
    client, db, ctx, vehicle, _ = fleet
    token = vehicle_revision(vehicle)
    vehicle.notes = "Internal administrative note"
    await db.commit()
    assert vehicle_revision(vehicle) == token
    response = await command(client, ctx, vehicle.id, token, "creation")
    assert response.status_code == 201, response.text
