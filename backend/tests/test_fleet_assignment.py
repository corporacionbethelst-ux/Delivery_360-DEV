from app.core.vehicle_revision import vehicle_revision

"""Assignment contracts and administrative invalidation using real SQL rows."""

from datetime import datetime
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sqlalchemy import select, update
from tests.test_document_uploads import submissions  # noqa: F401
from tests.test_private_documents import documents  # noqa: F401
from app.models.rider import Rider, RiderStatus
from app.models.rider_document import RiderDocument, DocumentStatus
from app.models.vehicle import Vehicle
from app.models.user import UserRole
from tests.fleet_audit_fixtures import create_sqlite_audit_table
from app.api.v1 import vehicles as vehicles_api
from app.services.fleet_assignment import lock_vehicles, ensure_vehicle_unassigned


@pytest.fixture
async def fleet(submissions):
    client, db, ctx = submissions
    await create_sqlite_audit_table(db)
    connection = await db.connection()
    await connection.run_sync(
        lambda conn: conn.connection.dbapi_connection.create_function(
            "AsEWKB", 1, lambda value: None
        )
    )
    ctx["current"][0].role = UserRole.GERENTE
    first = Vehicle(
        plate="FLEET-1",
        type="MOTO",
        model="Company 1",
        color="Black",
        year=2025,
        status="ACTIVO",
    )
    second = Vehicle(
        plate="FLEET-2",
        type="AUTO",
        model="Company 2",
        color="White",
        year=2025,
        status="ACTIVO",
    )
    db.add_all([first, second])
    await db.execute(
        update(RiderDocument).values(
            status=DocumentStatus.APROBADO, updated_at=datetime.utcnow()
        )
    )
    await db.commit()
    return client, db, ctx, first, second


async def change(client, ctx, **payload):
    if "expected_assignment_revision" not in payload:
        current = await client.get(f"/api/v1/riders/{ctx['rider_id']}")
        assert current.status_code == 200, current.text
        payload["expected_assignment_revision"] = current.json()["assignment_revision"]
    if "expected_vehicle_revision" not in payload:
        current = await client.get(f"/api/v1/riders/{ctx['rider_id']}")
        target = payload.get("assigned_vehicle_id") or current.json().get(
            "assigned_vehicle_id"
        )
        ownership = payload.get(
            "vehicle_ownership_type", current.json().get("vehicle_ownership_type")
        )
        if target and ownership == "EMPRESA":
            candidate = await client.get(f"/api/v1/vehicles/{target}")
            if candidate.status_code == 200:
                payload["expected_vehicle_revision"] = candidate.json()["revision"]
    return await client.patch(f"/api/v1/riders/{ctx['rider_id']}", json=payload)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        RiderStatus.ACTIVO,
        RiderStatus.OCUPADO,
        RiderStatus.SUSPENDIDO,
        RiderStatus.INACTIVO,
    ],
)
async def test_admin_vehicle_change_invalidates_and_preserves_closures(fleet, status):
    client, db, ctx, _, _ = fleet
    await db.execute(
        update(Rider)
        .where(Rider.id == ctx["rider_id"])
        .values(status=status, is_online=True)
    )
    await db.commit()
    response = await change(client, ctx, vehicle_plate="OWN-NEW")
    assert response.status_code == 200, response.text
    expected = (
        RiderStatus.PENDIENTE
        if status in (RiderStatus.ACTIVO, RiderStatus.OCUPADO)
        else status
    )
    assert response.json()["status"] == expected.value
    assert response.json()["is_online"] is False
    assert await db.scalar(select(RiderDocument.status)) == DocumentStatus.RECHAZADO


@pytest.mark.asyncio
async def test_assignment_replacement_and_release_keep_both_links_consistent(fleet):
    client, db, ctx, first, second = fleet
    response = await change(
        client, ctx, vehicle_ownership_type="EMPRESA", assigned_vehicle_id=str(first.id)
    )
    assert response.status_code == 200, response.text
    assert response.json()["vehicle_plate"] == "FLEET-1"
    assert response.json()["vehicle_model"] == "Company 1"
    assert (
        await db.scalar(select(Vehicle.rider_id).where(Vehicle.id == first.id))
        == ctx["current"][0].id
    )
    response = await change(client, ctx, assigned_vehicle_id=str(second.id))
    assert response.status_code == 200, response.text
    assert response.json()["vehicle_plate"] == "FLEET-2"
    assert (
        await db.scalar(select(Vehicle.rider_id).where(Vehicle.id == first.id)) is None
    )
    response = await change(client, ctx, vehicle_ownership_type="PROPIO")
    assert response.status_code == 200, response.text
    assert response.json()["assigned_vehicle_id"] is None
    assert (
        await db.scalar(select(Vehicle.rider_id).where(Vehicle.id == second.id)) is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["missing", "inactive", "owned", "referenced"])
async def test_unavailable_assignment_has_no_partial_links(fleet, kind):
    client, db, ctx, first, _ = fleet
    target = first.id
    if kind == "missing":
        target = uuid4()
    elif kind == "inactive":
        first.status = "MANTENIMIENTO"
    elif kind == "owned":
        first.rider_id = await db.scalar(
            select(Rider.user_id).where(Rider.id != ctx["rider_id"])
        )
    else:
        await db.execute(
            update(Rider)
            .where(Rider.id != ctx["rider_id"])
            .values(assigned_vehicle_id=first.id)
        )
    await db.commit()
    response = await change(
        client, ctx, vehicle_ownership_type="EMPRESA", assigned_vehicle_id=str(target)
    )
    assert response.status_code == (404 if kind == "missing" else 409), response.text
    assert (
        await db.scalar(
            select(Rider.assigned_vehicle_id).where(Rider.id == ctx["rider_id"])
        )
        is None
    )
    assert await db.scalar(select(RiderDocument.status)) == DocumentStatus.APROBADO


@pytest.mark.asyncio
async def test_noop_keeps_approval_but_real_model_change_invalidates(fleet):
    client, db, ctx, first, _ = fleet
    assert (
        await change(
            client,
            ctx,
            vehicle_ownership_type="EMPRESA",
            assigned_vehicle_id=str(first.id),
        )
    ).status_code == 200
    await db.execute(
        update(RiderDocument).values(
            status=DocumentStatus.APROBADO, updated_at=datetime.utcnow()
        )
    )
    await db.commit()
    response = await change(client, ctx, assigned_vehicle_id=str(first.id))
    assert response.status_code == 200
    assert await db.scalar(select(RiderDocument.status)) == DocumentStatus.APROBADO
    response = await change(client, ctx, vehicle_model="Different vehicle")
    assert response.status_code == 409
    assert await db.scalar(select(RiderDocument.status)) == DocumentStatus.APROBADO


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("plate", "NEW"),
        ("status", "BAJA"),
        ("type", "AUTO"),
        ("model", "Changed"),
        ("insurance_expiry", None),
    ],
)
async def test_assigned_vehicle_critical_edits_are_rejected(fleet, field, value):
    client, db, ctx, first, _ = fleet
    first.insurance_expiry = datetime(2027, 1, 1).date()
    await db.commit()
    assert (
        await change(
            client,
            ctx,
            vehicle_ownership_type="EMPRESA",
            assigned_vehicle_id=str(first.id),
        )
    ).status_code == 200
    with pytest.raises(HTTPException) as error:
        await vehicles_api.update_vehicle(
            str(first.id),
            vehicles_api.VehicleUpdate(**{field: value}),
            db,
            ctx["current"][0],
        )
    assert error.value.status_code == 409
    await db.rollback()


@pytest.mark.asyncio
async def test_delete_checks_profile_reference_even_when_owner_is_missing(fleet):
    _, db, ctx, first, _ = fleet
    await db.execute(
        update(Rider)
        .where(Rider.id == ctx["rider_id"])
        .values(assigned_vehicle_id=first.id)
    )
    await db.commit()
    with pytest.raises(HTTPException) as error:
        await vehicles_api.delete_vehicle(str(first.id), db, ctx["current"][0])
    assert error.value.status_code == 409
    await db.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("ownership", ["UNKNOWN", ""])
async def test_invalid_ownership_rejected_without_invalidation(fleet, ownership):
    client, db, ctx, _, _ = fleet
    response = await change(client, ctx, vehicle_ownership_type=ownership)
    assert response.status_code == 422
    assert await db.scalar(select(RiderDocument.status)) == DocumentStatus.APROBADO


@pytest.mark.asyncio
async def test_assigned_vehicle_cosmetic_update_preserves_links_and_documents(fleet):
    client, db, ctx, first, _ = fleet
    assert (
        await change(
            client,
            ctx,
            vehicle_ownership_type="EMPRESA",
            assigned_vehicle_id=str(first.id),
        )
    ).status_code == 200
    await db.execute(
        update(RiderDocument).values(
            status=DocumentStatus.APROBADO, updated_at=datetime.utcnow()
        )
    )
    await db.commit()
    result = await vehicles_api.update_vehicle(
        str(first.id),
        vehicles_api.VehicleUpdate(color="Blue", notes="Reviewed"),
        db,
        ctx["current"][0],
    )
    assert result["rider_id"] == str(ctx["current"][0].id)
    assert result["rider_profile_id"] == str(ctx["rider_id"])
    assert result["color"] == "Blue"
    assert await db.scalar(select(RiderDocument.status)) == DocumentStatus.APROBADO


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["plate", "type", "model", "color", "year", "status"])
async def test_required_vehicle_fields_cannot_be_null(fleet, field):
    _, db, ctx, first, _ = fleet
    with pytest.raises(HTTPException) as error:
        await vehicles_api.update_vehicle(
            str(first.id),
            vehicles_api.VehicleUpdate(**{field: None}),
            db,
            ctx["current"][0],
        )
    assert error.value.status_code == 422
    await db.rollback()


@pytest.mark.asyncio
async def test_unassigned_vehicle_can_be_edited_then_deleted(fleet):
    _, db, ctx, first, _ = fleet
    vehicle_id = first.id
    result = await vehicles_api.update_vehicle(
        str(vehicle_id),
        vehicles_api.VehicleUpdate(plate=" new-plate ", status="MANTENIMIENTO"),
        db,
        ctx["current"][0],
    )
    assert result["plate"] == "NEW-PLATE"
    assert result["status"] == "MANTENIMIENTO"
    await vehicles_api.delete_vehicle(str(vehicle_id), db, ctx["current"][0])
    assert await db.scalar(select(Vehicle.id).where(Vehicle.id == vehicle_id)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("available", [True, False])
async def test_company_rider_creation_uses_locked_vehicle_and_rolls_back_rejection(
    fleet, available
):
    from app.models.user import User

    client, db, ctx, first, _ = fleet
    vehicle_id = first.id
    if not available:
        first.status = "MANTENIMIENTO"
        await db.commit()
    response = await client.post(
        "/api/v1/riders",
        json={
            "email": "new-fleet@example.test",
            "password": "ValidPassword123!",
            "first_name": "New",
            "last_name": "Rider",
            "phone": "+584121234567",
            "vehicle_type": "AUTO",
            "vehicle_plate": "UNTRUSTED",
            "vehicle_ownership_type": "EMPRESA",
            "assigned_vehicle_id": str(vehicle_id),
            "expected_vehicle_revision": vehicle_revision(first),
        },
    )
    assert response.status_code == (201 if available else 409), response.text
    user_id = await db.scalar(
        select(User.id).where(User.email == "new-fleet@example.test")
    )
    if available:
        assert user_id is not None
        assert response.json()["vehicle_type"] == "MOTO"
        assert response.json()["vehicle_plate"] == "FLEET-1"
        assert (
            await db.scalar(select(Vehicle.rider_id).where(Vehicle.id == vehicle_id))
            == user_id
        )
    else:
        assert user_id is None
        assert (
            await db.scalar(select(Vehicle.rider_id).where(Vehicle.id == vehicle_id))
            is None
        )
