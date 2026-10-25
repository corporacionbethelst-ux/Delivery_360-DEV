"""Conditional inventory editing/deletion, including notes and explicit clears."""

from datetime import date
import pytest
from sqlalchemy import select, update
from tests.test_fleet_assignment import fleet  # noqa: F401
from tests.test_document_uploads import submissions  # noqa: F401
from tests.test_private_documents import documents  # noqa: F401
from app.core.vehicle_revision import vehicle_revision, vehicle_edit_revision
from app.models.user import UserRole
from app.models.vehicle import Vehicle


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
@pytest.mark.parametrize(
    "header,status",
    [
        (None, 409),
        ("0" * 64, 409),
        ("bad", 422),
        ("*", 422),
        ('W/"' + "a" * 64 + '"', 422),
    ],
)
async def test_invalid_preconditions_have_no_effect(fleet, method, header, status):
    client, db, _, vehicle, _ = fleet
    vehicle_id = vehicle.id
    response = await client.request(
        method,
        f"/api/v1/vehicles/{vehicle_id}",
        headers={"If-Match": header} if header is not None else {},
        **({"json": {"notes": "UNSAFE", "color": "Red"}} if method == "PATCH" else {}),
    )
    assert response.status_code == status, response.text
    assert (
        await db.execute(
            select(Vehicle.notes, Vehicle.color).where(Vehicle.id == vehicle_id)
        )
    ).one() == (None, "Black")


@pytest.mark.asyncio
async def test_notes_invalidate_edit_revision_without_invalidating_candidate(fleet):
    client, db, _, vehicle, _ = fleet
    vehicle_id = vehicle.id
    source, candidate = vehicle_edit_revision(vehicle), vehicle_revision(vehicle)
    await db.execute(
        update(Vehicle).where(Vehicle.id == vehicle_id).values(notes="NEWER NOTES")
    )
    await db.commit()
    response = await client.patch(
        f"/api/v1/vehicles/{vehicle_id}",
        json={"notes": "OLDER NOTES", "color": "Red"},
        headers={"If-Match": source},
    )
    assert response.status_code == 409
    response = await client.delete(
        f"/api/v1/vehicles/{vehicle_id}", headers={"If-Match": source}
    )
    assert response.status_code == 409
    current = await client.get(f"/api/v1/vehicles/{vehicle_id}")
    assert current.json()["revision"] == candidate
    assert current.json()["edit_revision"] != source
    assert (
        current.json()["notes"] == "NEWER NOTES" and current.json()["color"] == "Black"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("quoted", [False, True])
async def test_edit_tag_is_exposed_and_valid_for_update_and_delete(fleet, quoted):
    client, db, _, vehicle, _ = fleet
    vehicle_id = vehicle.id
    response = await client.get(f"/api/v1/vehicles/{vehicle_id}")
    tag = response.json()["edit_revision"]
    assert response.headers["etag"] == f'"{tag}"'
    assert response.headers["cache-control"] == "private, no-store"
    header = f'"{tag}"' if quoted else tag
    updated = await client.patch(
        f"/api/v1/vehicles/{vehicle_id}",
        json={"notes": "Reviewed"},
        headers={"If-Match": header},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["edit_revision"] != tag
    assert (
        await client.delete(
            f"/api/v1/vehicles/{vehicle_id}", headers={"If-Match": header}
        )
    ).status_code == 409
    deleted = await client.delete(
        f"/api/v1/vehicles/{vehicle_id}",
        headers={"If-Match": updated.json()["edit_revision"]},
    )
    assert deleted.status_code == 200
    assert await db.scalar(select(Vehicle.id).where(Vehicle.id == vehicle_id)) is None


@pytest.mark.asyncio
async def test_notes_and_insurance_can_be_cleared_explicitly(fleet):
    client, db, _, vehicle, _ = fleet
    vehicle.notes = "Old note"
    vehicle.insurance_expiry = date(2027, 1, 1)
    await db.commit()
    token = vehicle_edit_revision(vehicle)
    response = await client.patch(
        f"/api/v1/vehicles/{vehicle.id}",
        json={"notes": None, "insurance_expiry": None},
        headers={"If-Match": token},
    )
    assert response.status_code == 200, response.text
    assert (
        response.json()["notes"] is None and response.json()["insurance_expiry"] is None
    )


@pytest.mark.asyncio
async def test_second_editor_cannot_overwrite_first_using_same_tag(fleet):
    client, _, _, vehicle, _ = fleet
    vehicle_id = vehicle.id
    token = vehicle_edit_revision(vehicle)
    first = await client.patch(
        f"/api/v1/vehicles/{vehicle_id}",
        json={"notes": "FIRST"},
        headers={"If-Match": token},
    )
    assert first.status_code == 200
    second = await client.patch(
        f"/api/v1/vehicles/{vehicle_id}",
        json={"notes": "SECOND"},
        headers={"If-Match": token},
    )
    assert second.status_code == 409
    assert (await client.get(f"/api/v1/vehicles/{vehicle_id}")).json()[
        "notes"
    ] == "FIRST"


@pytest.mark.asyncio
async def test_candidate_tag_is_not_an_inventory_precondition(fleet):
    client, _, _, vehicle, _ = fleet
    response = await client.patch(
        f"/api/v1/vehicles/{vehicle.id}",
        json={"notes": "UNSAFE"},
        headers={"If-Match": vehicle_revision(vehicle)},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role", [UserRole.OPERADOR, UserRole.REPARTIDOR, UserRole.CLIENTE, UserRole.AUDITOR]
)
async def test_preconditions_do_not_grant_write_authority(fleet, role):
    client, _, ctx, vehicle, _ = fleet
    ctx["current"][0].role = role
    for method in ("PATCH", "DELETE"):
        response = await client.request(
            method,
            f"/api/v1/vehicles/{vehicle.id}",
            headers={"If-Match": vehicle_edit_revision(vehicle)},
            **({"json": {"notes": "UNSAFE"}} if method == "PATCH" else {}),
        )
        assert response.status_code == 403
