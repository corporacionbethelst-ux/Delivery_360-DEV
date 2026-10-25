"""Profile and fleet preconditions protect a mixed command atomically."""

import pytest
from sqlalchemy import select, update
from tests.test_fleet_assignment import fleet  # noqa: F401
from tests.test_document_uploads import submissions  # noqa: F401
from tests.test_private_documents import documents  # noqa: F401
from app.models.user import User, UserRole
from app.models.rider import Rider
from app.models.vehicle import Vehicle
from app.models.audit_log import AuditLog


async def observed(client, ctx):
    response = await client.get(f"/api/v1/riders/{ctx['rider_id']}")
    assert response.status_code == 200, response.text
    return response.json()


async def edit(client, ctx, own, payload):
    return await client.request(
        "PUT" if own else "PATCH",
        "/api/v1/riders/me" if own else f"/api/v1/riders/{ctx['rider_id']}",
        json=payload,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("own", [True, False])
@pytest.mark.parametrize(
    "revision,status", [(None, 409), ("bad", 422), ("0" * 64, 409)]
)
async def test_missing_malformed_stale_profile_revision_writes_nothing(
    fleet, own, revision, status
):
    client, db, ctx, _, _ = fleet
    old = await observed(client, ctx)
    response = await edit(
        client,
        ctx,
        own,
        {"phone": "+584121111111", "expected_profile_revision": revision},
    )
    assert response.status_code == status, response.text
    current = await observed(client, ctx)
    assert current["profile_revision"] == old["profile_revision"]
    assert current["phone"] == old["phone"]
    assert (await db.scalars(select(AuditLog))).all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("own", [True, False])
async def test_later_editor_cannot_overwrite_personal_data_or_tier(fleet, own):
    client, db, ctx, _, _ = fleet
    old = await observed(client, ctx)
    first = await edit(
        client,
        ctx,
        own,
        {
            "phone": "+584121111111",
            "expected_profile_revision": old["profile_revision"],
        },
    )
    assert first.status_code == 200, first.text
    assert first.json()["profile_revision"] != old["profile_revision"]
    second = await edit(
        client,
        ctx,
        own,
        {
            "phone": "+584122222222",
            "tier": "ORO",
            "expected_profile_revision": old["profile_revision"],
        },
    )
    assert second.status_code == 409, second.text
    current = await observed(client, ctx)
    assert current["phone"] == "+584121111111" and current["tier"] == old["tier"]
    assert current["assignment_revision"] == old["assignment_revision"]


@pytest.mark.asyncio
async def test_stale_personal_revision_rolls_back_company_claim_and_audit(fleet):
    client, db, ctx, first, _ = fleet
    vid = first.id
    vehicle = (await client.get(f"/api/v1/vehicles/{vid}")).json()
    old = await observed(client, ctx)
    good = await edit(
        client,
        ctx,
        False,
        {"first_name": "Updated", "expected_profile_revision": old["profile_revision"]},
    )
    assert good.status_code == 200, good.text
    response = await edit(
        client,
        ctx,
        False,
        {
            "phone": "+584121111111",
            "vehicle_ownership_type": "EMPRESA",
            "assigned_vehicle_id": str(vid),
            "expected_vehicle_revision": vehicle["revision"],
            "expected_assignment_revision": old["assignment_revision"],
            "expected_profile_revision": old["profile_revision"],
        },
    )
    assert response.status_code == 409, response.text
    assert await db.scalar(select(Vehicle.rider_id).where(Vehicle.id == vid)) is None
    assert (await db.scalars(select(AuditLog))).all() == []
    current = await observed(client, ctx)
    assert current["first_name"] == "Updated" and current["phone"] == old["phone"]
    assert current["assignment_revision"] == old["assignment_revision"]


@pytest.mark.asyncio
async def test_fleet_and_telemetry_changes_do_not_stale_personal_revision(fleet):
    client, db, ctx, _, _ = fleet
    old = await observed(client, ctx)
    await db.execute(
        update(Rider)
        .where(Rider.id == ctx["rider_id"])
        .values(vehicle_plate="Changed", is_online=False, total_points=123)
    )
    await db.commit()
    response = await edit(
        client,
        ctx,
        False,
        {
            "phone": "+584121111111",
            "expected_profile_revision": old["profile_revision"],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["vehicle_plate"] == "Changed"


@pytest.mark.asyncio
async def test_self_cannot_set_tier_even_with_current_revision(fleet):
    client, _, ctx, _, _ = fleet
    old = await observed(client, ctx)
    ctx["current"][0].role = UserRole.REPARTIDOR
    response = await edit(
        client,
        ctx,
        True,
        {"tier": "ORO", "expected_profile_revision": old["profile_revision"]},
    )
    assert response.status_code == 403
