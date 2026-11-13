"""Settings revisions, authorization and atomic audit writes at the HTTP boundary."""

import pytest
from types import SimpleNamespace
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.api.v1 import settings
from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.core.exception_handlers import register_exception_handlers
from app.models.audit_log import AuditLog
from app.models.platform_setting import PlatformSetting
from app.models.user import User, UserRole
from tests.fleet_audit_fixtures import create_sqlite_audit_table


@pytest.fixture
async def settings_client(db_session):
    await create_sqlite_audit_table(db_session)
    connection = await db_session.connection()
    column = PlatformSetting.__table__.c.created_at
    previous = column.server_default
    try:
        column.server_default = None
        await connection.run_sync(PlatformSetting.__table__.create)
    finally:
        column.server_default = previous
    actor = User(
        email="settings-admin@example.test",
        hashed_password="unused-synthetic-password",
        first_name="Settings",
        last_name="Administrator",
        role=UserRole.SUPERADMIN,
    )
    db_session.add(actor)
    await db_session.commit()
    actor = SimpleNamespace(id=actor.id, role=actor.role, email=actor.email)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(settings.router, prefix="/api/v1")

    async def database():
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise

    async def identity():
        return actor

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = identity
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, db_session, actor


async def read(client):
    response = await client.get("/api/v1/settings")
    assert response.status_code == 200
    return response.json()


def match(snapshot):
    return {"If-Match": '"' + snapshot["revision"] + '"'}


async def test_reads_initialize_once_and_revision_is_stable(settings_client):
    client, db, _ = settings_client
    first = await read(client)
    assert first == await read(client)
    assert len(first["revision"]) == 67
    assert first["delivery_fee_base"] is None
    assert first["rider_delivery_bonus"] is None
    assert first["maintenance_mode"] is False
    assert first["active_zones"] == []
    assert await db.scalar(select(func.count()).select_from(PlatformSetting)) == 8
    assert await db.scalar(select(func.count()).select_from(AuditLog)) == 0


@pytest.mark.parametrize("method", ["patch", "put"])
@pytest.mark.parametrize("path", ["/api/v1/settings", "/api/v1/settings/"])
async def test_every_write_alias_requires_a_revision_before_mutating(
    settings_client, method, path
):
    client, db, _ = settings_client
    response = await client.request(method, path, json={"delivery_fee_base": 4})
    assert response.status_code == 428
    assert await db.scalar(select(func.count()).select_from(PlatformSetting)) == 0
    assert await db.scalar(select(func.count()).select_from(AuditLog)) == 0


@pytest.mark.parametrize(
    "revision", ["*", 'W/"s1-' + "a" * 64 + '"', "old", '"old"', '"a","b"']
)
async def test_weak_wildcard_or_malformed_revisions_do_not_write(
    settings_client, revision
):
    client, db, _ = settings_client
    response = await client.patch(
        "/api/v1/settings",
        json={"delivery_fee_base": 4},
        headers={"If-Match": revision},
    )
    assert response.status_code == 400
    assert await db.scalar(select(func.count()).select_from(PlatformSetting)) == 0


@pytest.mark.parametrize("method", ["patch", "put"])
async def test_minimal_write_preserves_other_values_and_records_exact_audit(
    settings_client, method
):
    client, db, actor = settings_client
    before = await read(client)
    patch = {
        "delivery_fee_base": 0,
        "rider_delivery_bonus": 2.50001,
        "maintenance_mode": False,
        "active_zones": [" Centro, Norte ", "Sur"],
    }
    response = await client.request(
        method, "/api/v1/settings", json=patch, headers=match(before)
    )
    assert response.status_code == 200
    after = response.json()
    assert after["revision"] != before["revision"]
    assert after["delivery_fee_base"] == 0
    assert after["rider_delivery_bonus"] == 2.50001
    assert after["maintenance_mode"] is False
    assert after["active_zones"] == ["Centro, Norte", "Sur"]
    assert after["min_order_amount"] is None
    assert after == await read(client)
    audit = (await db.scalars(select(AuditLog))).one()
    assert audit.user_id == actor.id
    assert audit.old_values == {key: before[key] for key in patch}
    assert audit.new_values == {key: after[key] for key in patch}


async def test_stale_snapshot_cannot_overwrite_any_fields_or_append_an_audit(
    settings_client,
):
    client, db, _ = settings_client
    before = await read(client)
    first = await client.patch(
        "/api/v1/settings", json={"delivery_fee_base": 9}, headers=match(before)
    )
    assert first.status_code == 200
    stale = await client.patch(
        "/api/v1/settings",
        json={"delivery_fee_base": 4, "support_email": "stale@example.com"},
        headers=match(before),
    )
    assert stale.status_code == 412
    assert await read(client) == first.json()
    assert await db.scalar(select(func.count()).select_from(AuditLog)) == 1


async def test_reversing_a_value_does_not_revalidate_an_old_snapshot(settings_client):
    client, _, _ = settings_client
    original = await read(client)
    one = await client.patch(
        "/api/v1/settings", json={"delivery_fee_base": 1}, headers=match(original)
    )
    two = await client.patch(
        "/api/v1/settings", json={"delivery_fee_base": None}, headers=match(one.json())
    )
    assert two.status_code == 200
    assert two.json()["delivery_fee_base"] is None
    assert (
        len({original["revision"], one.json()["revision"], two.json()["revision"]}) == 3
    )


@pytest.mark.parametrize(
    "role", [UserRole.GERENTE, UserRole.OPERADOR, UserRole.REPARTIDOR]
)
async def test_non_admin_roles_cannot_bypass_revision_protection(settings_client, role):
    client, db, actor = settings_client
    before = await read(client)
    actor.role = role
    response = await client.patch(
        "/api/v1/settings", json={"delivery_fee_base": 4}, headers=match(before)
    )
    assert response.status_code == 403
    assert await db.scalar(select(func.count()).select_from(AuditLog)) == 0


@pytest.mark.parametrize(
    "body",
    [
        {"revision": "must-not-be-a-setting"},
        {"unknown_setting": 1},
        {"commission_percentage": 101},
        {"delivery_fee_base": -1},
    ],
)
async def test_invalid_updates_do_not_modify_settings(settings_client, body):
    client, db, _ = settings_client
    before = await read(client)
    response = await client.patch("/api/v1/settings", json=body, headers=match(before))
    assert response.status_code == 422
    assert await read(client) == before
    assert await db.scalar(select(func.count()).select_from(AuditLog)) == 0


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e309"])
async def test_non_finite_numbers_are_rejected_without_persisting(
    settings_client, number
):
    client, _, _ = settings_client
    before = await read(client)
    response = await client.patch(
        "/api/v1/settings",
        content='{"delivery_fee_base":' + number + "}",
        headers={**match(before), "Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert await read(client) == before


async def test_empty_update_checks_revision_but_does_not_create_audit(settings_client):
    client, db, _ = settings_client
    before = await read(client)
    response = await client.patch("/api/v1/settings", json={}, headers=match(before))
    assert response.status_code == 200
    assert response.json() == before
    assert await db.scalar(select(func.count()).select_from(AuditLog)) == 0
