"""HTTP plate collisions preserve inventory state and do not record success."""

import pytest
from sqlalchemy import select
from tests.test_vehicle_inventory_audit import (
    inventory_history,
    body,
    rows,
)  # noqa: F401
from tests.test_fleet_assignment import fleet  # noqa: F401
from tests.test_document_uploads import submissions  # noqa: F401
from tests.test_private_documents import documents  # noqa: F401
from app.api.v1 import vehicles as api
from app.core.vehicle_revision import vehicle_edit_revision
from app.models.vehicle import Vehicle


@pytest.mark.asyncio
async def test_create_and_edit_share_canonical_plate(inventory_history):
    client, db, _, _, _ = inventory_history
    created = await client.post("/api/v1/vehicles", json=body(" \tabc-123\r\n"))
    assert created.status_code == 201, created.text
    state = created.json()
    assert state["plate"] == "ABC-123"
    edited = await client.patch(
        f"/api/v1/vehicles/{state['id']}",
        json={"plate": "\vnew-456\f "},
        headers={"If-Match": state["edit_revision"]},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["plate"] == "NEW-456"
    assert [e.new_values["state"]["plate"] for e in await rows(db)] == [
        "ABC-123",
        "NEW-456",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "plate", ["", "   ", "AB 12", "ÁBC-1", "ABC_1", "A" * 21, 123, "\u00a0ABC-1"]
)
async def test_invalid_plate_is_rejected_without_writes(inventory_history, plate):
    client, db, _, vehicle, _ = inventory_history
    vid, expected = vehicle.id, vehicle_edit_revision(vehicle)
    assert (await client.post("/api/v1/vehicles", json=body(plate))).status_code == 422
    assert (
        await client.patch(
            f"/api/v1/vehicles/{vid}",
            json={"plate": plate, "notes": "UNSAFE"},
            headers={"If-Match": expected},
        )
    ).status_code == 422
    assert not await rows(db)
    current = (await client.get(f"/api/v1/vehicles/{vid}")).json()
    assert current["edit_revision"] == expected


@pytest.mark.asyncio
async def test_duplicate_create_and_edit_return_typed_conflict_and_keep_revision(
    inventory_history,
):
    client, db, _, first, second = inventory_history
    vid, expected, old_plate = first.id, vehicle_edit_revision(first), first.plate
    duplicate = second.plate.lower()
    for response in [
        await client.post("/api/v1/vehicles", json=body(duplicate)),
        await client.patch(
            f"/api/v1/vehicles/{vid}",
            json={"plate": duplicate, "notes": "UNSAFE"},
            headers={"If-Match": expected},
        ),
    ]:
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "VEHICLE_PLATE_CONFLICT"
    current = (await client.get(f"/api/v1/vehicles/{vid}")).json()
    assert current["plate"] == old_plate and current["notes"] is None
    assert current["edit_revision"] == expected
    assert not await rows(db)
    corrected = await client.patch(
        f"/api/v1/vehicles/{vid}",
        json={"plate": "FREE-1"},
        headers={"If-Match": expected},
    )
    assert corrected.status_code == 200, corrected.text
    assert len(await rows(db)) == 1


@pytest.mark.asyncio
async def test_multiple_legacy_equivalents_do_not_cause_server_error(inventory_history):
    client, db, _, first, second = inventory_history
    first.plate, second.plate = " \tlegacy-1\n", "LEGACY-1"
    await db.commit()
    response = await client.post("/api/v1/vehicles", json=body("legacy-1"))
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "VEHICLE_PLATE_CONFLICT"
    assert set((await db.scalars(select(Vehicle.plate))).all()) == {
        " \tlegacy-1\n",
        "LEGACY-1",
    }
    assert not await rows(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "update"])
async def test_real_unique_index_fallback_is_typed_and_atomic(
    inventory_history, monkeypatch, operation
):
    client, db, _, first, second = inventory_history
    vid, expected, duplicate = first.id, vehicle_edit_revision(first), second.plate

    async def bypass(*args, **kwargs):
        pass

    monkeypatch.setattr(api, "claim_vehicle_plate", bypass)
    response = (
        await client.post("/api/v1/vehicles", json=body(duplicate))
        if operation == "create"
        else await client.patch(
            f"/api/v1/vehicles/{vid}",
            json={"plate": duplicate, "notes": "UNSAFE"},
            headers={"If-Match": expected},
        )
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "VEHICLE_PLATE_CONFLICT"
    assert not await rows(db)
    assert (await client.get(f"/api/v1/vehicles/{vid}")).json()[
        "edit_revision"
    ] == expected
