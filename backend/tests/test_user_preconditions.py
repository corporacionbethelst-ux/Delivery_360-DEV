"""Real HTTP user metadata revisions and cross-route profile protection."""

from datetime import datetime
import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.orm import raiseload
from tests.test_fleet_assignment import fleet  # noqa: F401
from tests.test_document_uploads import submissions  # noqa: F401
from tests.test_private_documents import documents  # noqa: F401
from app.api.v1 import users, riders
from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.user import User, UserRole
from app.models.rider import Rider


@pytest.fixture
async def accounts(fleet):
    _, db, ctx, _, _ = fleet
    actor_id = ctx["current"][0].id
    target_id = await db.scalar(
        select(Rider.user_id).where(Rider.id != ctx["rider_id"])
    )
    actor = await db.get(User, actor_id)
    actor.role = UserRole.GERENTE
    await db.commit()
    app = FastAPI()
    app.include_router(users.router, prefix="/api/v1/users")
    app.include_router(riders.router, prefix="/api/v1")

    async def database():
        try:
            yield db
        except Exception:
            await db.rollback()
            raise

    async def identity():
        return await db.scalar(
            select(User)
            .options(raiseload("*"))
            .where(User.id == actor_id)
            .execution_options(populate_existing=True)
        )

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = identity
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, db, actor_id, target_id, ctx["rider_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path", [("PATCH", "target"), ("PATCH", "me"), ("PUT", "me")]
)
@pytest.mark.parametrize(
    "revision,status", [(None, 409), ("bad", 422), ("0" * 64, 409)]
)
async def test_user_writes_reject_missing_invalid_and_stale_revisions(
    accounts, method, path, revision, status
):
    client, _, _, target, _ = accounts
    url = "/api/v1/users/me" if path == "me" else f"/api/v1/users/{target}"
    original = (await client.get(url)).json()
    response = await client.request(
        method, url, json={"phone": "+584121111111", "expected_user_revision": revision}
    )
    assert response.status_code == status, response.text
    current = (await client.get(url)).json()
    assert (
        current["user_revision"] == original["user_revision"]
        and current["phone"] == original["phone"]
    )


@pytest.mark.asyncio
async def test_user_edit_invalidates_old_rider_profile_without_partial_effect(accounts):
    client, _, _, _, rid = accounts
    profile = (await client.get(f"/api/v1/riders/{rid}")).json()
    user = (await client.get("/api/v1/users/me")).json()
    response = await client.patch(
        "/api/v1/users/me",
        json={
            "first_name": "Via user",
            "expected_user_revision": user["user_revision"],
        },
    )
    assert response.status_code == 200, response.text
    response = await client.put(
        "/api/v1/riders/me",
        json={
            "first_name": "Stale",
            "expected_profile_revision": profile["profile_revision"],
        },
    )
    assert response.status_code == 409, response.text
    assert (await client.get("/api/v1/users/me")).json()["first_name"] == "Via user"


@pytest.mark.asyncio
async def test_rider_edit_invalidates_old_user_revision(accounts):
    client, _, _, _, rid = accounts
    profile = (await client.get(f"/api/v1/riders/{rid}")).json()
    user = (await client.get("/api/v1/users/me")).json()
    response = await client.put(
        "/api/v1/riders/me",
        json={
            "first_name": "Via rider",
            "expected_profile_revision": profile["profile_revision"],
        },
    )
    assert response.status_code == 200, response.text
    response = await client.patch(
        "/api/v1/users/me",
        json={"first_name": "Stale", "expected_user_revision": user["user_revision"]},
    )
    assert response.status_code == 409, response.text
    assert (await client.get("/api/v1/users/me")).json()["first_name"] == "Via rider"


@pytest.mark.asyncio
async def test_authentication_counters_do_not_invalidate_user_metadata(accounts):
    client, db, actor, _, _ = accounts
    user = (await client.get("/api/v1/users/me")).json()
    row = await db.get(User, actor)
    row.last_login = datetime(2026, 10, 25)
    row.failed_login_attempts = "2"
    row.hashed_password = "test-only-reset"
    await db.commit()
    response = await client.patch(
        "/api/v1/users/me",
        json={
            "phone": "+584121111111",
            "expected_user_revision": user["user_revision"],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["user_revision"] != user["user_revision"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "revision,status",
    [
        (None, 409),
        ("", 422),
        ("*", 422),
        ('W/"' + "a" * 64 + '"', 422),
        ("0" * 64, 409),
    ],
)
async def test_delete_requires_valid_observed_revision(accounts, revision, status):
    client, db, _, target, _ = accounts
    response = await client.delete(
        f"/api/v1/users/{target}",
        headers={"If-Match": revision} if revision is not None else {},
    )
    assert response.status_code == status, response.text
    assert (await db.get(User, target)).is_active is True


@pytest.mark.asyncio
async def test_conditional_deactivation_is_soft_and_cannot_use_old_snapshot(accounts):
    client, db, _, target, _ = accounts
    url = f"/api/v1/users/{target}"
    original = (await client.get(url)).json()
    changed = await client.patch(
        url,
        json={
            "phone": "+584121111111",
            "expected_user_revision": original["user_revision"],
        },
    )
    assert changed.status_code == 200, changed.text
    assert (
        await client.delete(url, headers={"If-Match": original["user_revision"]})
    ).status_code == 409
    deleted = await client.delete(
        url, headers={"If-Match": '"' + changed.json()["user_revision"] + '"'}
    )
    assert deleted.status_code == 204, deleted.text
    assert (await db.get(User, target)).is_active is False


@pytest.mark.asyncio
async def test_fresh_role_is_checked_before_metadata_precondition(accounts):
    client, db, _, target, _ = accounts
    url = f"/api/v1/users/{target}"
    observed = (await client.get(url)).json()
    row = await db.get(User, target)
    row.role = UserRole.SUPERADMIN
    await db.commit()
    response = await client.patch(
        url,
        json={
            "phone": "+584121111111",
            "expected_user_revision": observed["user_revision"],
        },
    )
    assert response.status_code == 403, response.text
    assert (await client.get(url)).json()["phone"] == observed["phone"]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"is_active": False}, {"role": "OPERADOR"}])
async def test_self_lockout_protections_remain(accounts, payload):
    client, _, actor, _, _ = accounts
    user = (await client.get("/api/v1/users/me")).json()
    response = await client.patch(
        f"/api/v1/users/{actor}",
        json={**payload, "expected_user_revision": user["user_revision"]},
    )
    assert response.status_code == 400, response.text
