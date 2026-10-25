"""Client-observed fleet snapshots are required before any partial update."""

from datetime import datetime
from decimal import Decimal
import pytest
from sqlalchemy import select, update
from tests.test_fleet_assignment import fleet, change  # noqa: F401
from tests.test_document_uploads import submissions  # noqa: F401
from tests.test_private_documents import documents  # noqa: F401
from app.models.rider import Rider, RiderStatus
from app.models.vehicle import Vehicle
from app.models.user import User
from app.models.rider_document import RiderDocument, DocumentStatus


async def metadata(client, ctx):
    response = await client.get(f"/api/v1/riders/{ctx['rider_id']}")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token,status",
    [(None, 409), ("", 422), ("0" * 64, 409), ("A" * 64, 422), ("bad", 422)],
)
@pytest.mark.parametrize("own", [False, True])
async def test_missing_malformed_or_wrong_fleet_revision_has_no_partial_effect(
    fleet, token, status, own
):
    client, db, ctx, _, _ = fleet
    old_phone = await db.scalar(
        select(User.phone).where(User.id == ctx["current"][0].id)
    )
    url = "/api/v1/riders/me" if own else f"/api/v1/riders/{ctx['rider_id']}"
    response = await client.request(
        "PUT" if own else "PATCH",
        url,
        json={
            "vehicle_plate": "NEW",
            "phone": "+584121234567",
            "expected_assignment_revision": token,
        },
    )
    assert response.status_code == status, response.text
    assert (
        await db.scalar(select(User.phone).where(User.id == ctx["current"][0].id))
        == old_phone
    )
    assert (
        await db.scalar(select(Rider.vehicle_plate).where(Rider.id == ctx["rider_id"]))
        is None
    )
    assert await db.scalar(select(RiderDocument.status)) == DocumentStatus.APROBADO


@pytest.mark.asyncio
@pytest.mark.parametrize("own", [False, True])
async def test_stale_form_cannot_overwrite_later_assignment_or_other_fields(fleet, own):
    client, db, ctx, first, second = fleet
    first_id, second_id = first.id, second.id
    old = await metadata(client, ctx)
    assert (
        await change(
            client,
            ctx,
            vehicle_ownership_type="EMPRESA",
            assigned_vehicle_id=str(first_id),
        )
    ).status_code == 200
    old_phone = await db.scalar(
        select(User.phone).where(User.id == ctx["current"][0].id)
    )
    response = await client.request(
        "PUT" if own else "PATCH",
        "/api/v1/riders/me" if own else f"/api/v1/riders/{ctx['rider_id']}",
        json={
            "vehicle_ownership_type": "EMPRESA",
            "assigned_vehicle_id": str(second_id),
            "expected_assignment_revision": old["assignment_revision"],
            "phone": "+584129999999",
            "tier": "ORO",
        },
    )
    assert response.status_code == 409, response.text
    assert (
        await db.scalar(
            select(Rider.assigned_vehicle_id).where(Rider.id == ctx["rider_id"])
        )
        == first_id
    )
    assert (
        await db.scalar(select(Vehicle.rider_id).where(Vehicle.id == second_id)) is None
    )
    assert (
        await db.scalar(select(User.phone).where(User.id == ctx["current"][0].id))
        == old_phone
    )


@pytest.mark.asyncio
async def test_gps_status_and_financial_updates_do_not_expire_fleet_snapshot(fleet):
    client, db, ctx, _, _ = fleet
    old = await metadata(client, ctx)
    await db.execute(
        update(Rider)
        .where(Rider.id == ctx["rider_id"])
        .values(
            last_lat=10,
            last_lng=-66,
            is_online=True,
            status=RiderStatus.OCUPADO,
            updated_at=datetime.utcnow(),
            version=Rider.version + 1,
            wallet_balance=Decimal("1.00"),
        )
    )
    await db.commit()
    current = await metadata(client, ctx)
    assert current["assignment_revision"] == old["assignment_revision"]
    response = await change(
        client,
        ctx,
        vehicle_plate="NEW",
        expected_assignment_revision=old["assignment_revision"],
    )
    assert response.status_code == 200, response.text
    assert response.json()["assignment_revision"] != old["assignment_revision"]
    assert (
        response.json()["status"] == "PENDIENTE"
        and response.json()["is_online"] is False
    )


@pytest.mark.asyncio
async def test_nonfleet_update_needs_no_revision_and_admin_phone_is_persisted(fleet):
    client, db, ctx, _, _ = fleet
    response = await client.patch(
        f"/api/v1/riders/{ctx['rider_id']}", json={"phone": "+584121234567"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["phone"] == "+584121234567"
    assert (
        await db.scalar(select(User.phone).where(User.id == ctx["current"][0].id))
        == "+584121234567"
    )
    assert await db.scalar(select(RiderDocument.status)) == DocumentStatus.APROBADO


@pytest.mark.asyncio
async def test_state_fingerprint_is_not_a_monotonic_event_counter(fleet):
    client, db, ctx, _, _ = fleet
    original = await metadata(client, ctx)
    await db.execute(
        update(Rider).where(Rider.id == ctx["rider_id"]).values(vehicle_plate="OTHER")
    )
    await db.commit()
    assert (await metadata(client, ctx))["assignment_revision"] != original[
        "assignment_revision"
    ]
    await db.execute(
        update(Rider).where(Rider.id == ctx["rider_id"]).values(vehicle_plate=None)
    )
    await db.commit()
    assert (await metadata(client, ctx))["assignment_revision"] == original[
        "assignment_revision"
    ]
