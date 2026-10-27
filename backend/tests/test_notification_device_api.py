"""Mounted authenticated device lifecycle, validation and failure privacy."""

from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from tests.test_tracking_permissions import sockets  # noqa: F401
from app.api.v1 import notifications as api
from app.core.security import create_access_token
from app.models.notification import UserDeviceToken
from app.services.omnichannel_service import OmnichannelNotificationService as Service

TOKEN = "private-device-token"


@pytest.fixture
async def devices_client(sockets):
    client, sessions, ids, _ = sockets
    async with sessions.kw["bind"].begin() as connection:
        await connection.run_sync(UserDeviceToken.__table__.create)
    return client, sessions, ids


def headers(ids, who="owner"):
    return {"Authorization": "Bearer " + create_access_token(ids[who])}


async def stored(sessions):
    async with sessions() as db:
        return await db.scalar(select(UserDeviceToken))


async def test_mounted_registration_transfer_and_owner_only_idempotent_deactivation(
    devices_client,
):
    client, sessions, ids = devices_client
    payload = {"device_token": TOKEN, "user_id": str(ids["rival"])}
    first = client.post(
        "/api/v1/notifications/register-device", headers=headers(ids), json=payload
    )
    assert first.status_code == 200 and first.json() == {
        "status": "ok",
        "action": "created",
    }
    original = await stored(sessions)
    assert original.user_id == ids["owner"]  # request cannot choose another owner
    again = client.post(
        "/api/v1/notifications/register-device", headers=headers(ids), json=payload
    )
    assert again.json() == {"status": "ok", "action": "updated"}
    refreshed = await stored(sessions)
    assert (
        refreshed.id == original.id and refreshed.last_seen_at > original.last_seen_at
    )
    other = client.request(
        "DELETE",
        "/api/v1/notifications/unregister-device",
        headers=headers(ids, "rival"),
        json=payload,
    )
    assert other.status_code == 200 and other.json() == {"status": "ok"}
    assert (await stored(sessions)).is_active
    transfer = client.post(
        "/api/v1/notifications/register-device",
        headers=headers(ids, "rival"),
        json={"device_token": TOKEN, "platform": "ios"},
    )
    assert transfer.json()["action"] == "updated"
    assert (await stored(sessions)).user_id == ids["rival"]
    old_owner = client.request(
        "DELETE",
        "/api/v1/notifications/unregister-device",
        headers=headers(ids),
        json=payload,
    )
    assert old_owner.json() == {"status": "ok"} and (await stored(sessions)).is_active
    for _ in range(2):
        response = client.request(
            "DELETE",
            "/api/v1/notifications/unregister-device",
            headers=headers(ids, "rival"),
            json=payload,
        )
        assert response.status_code == 200 and response.json() == {"status": "ok"}
    row = await stored(sessions)
    assert not row.is_active and row.last_seen_at > refreshed.last_seen_at
    missing = client.request(
        "DELETE",
        "/api/v1/notifications/unregister-device",
        headers=headers(ids, "rival"),
        json={"device_token": "missing-device-token"},
    )
    assert missing.json() == {"status": "ok"}


@pytest.mark.parametrize(
    "method,path", [("POST", "register-device"), ("DELETE", "unregister-device")]
)
async def test_device_routes_require_authentication(devices_client, method, path):
    client, sessions, _ = devices_client
    assert (
        client.request(
            method, "/api/v1/notifications/" + path, json={"device_token": TOKEN}
        ).status_code
        == 401
    )
    assert await stored(sessions) is None


@pytest.mark.parametrize("who", ["inactive", "roleless"])
@pytest.mark.parametrize(
    "method,path", [("POST", "register-device"), ("DELETE", "unregister-device")]
)
async def test_unavailable_accounts_cannot_mutate_devices(
    devices_client, who, method, path
):
    client, sessions, ids = devices_client
    assert (
        client.request(
            method,
            "/api/v1/notifications/" + path,
            headers=headers(ids, who),
            json={"device_token": TOKEN},
        ).status_code
        == 401
    )
    assert await stored(sessions) is None


@pytest.mark.parametrize(
    "token",
    [
        "short",
        "x" * 256,
        " private-token",
        "private-token\n",
        "private\x00token",
        "private\u200btoken",
    ],
)
async def test_bad_tokens_are_rejected_before_storage(devices_client, token):
    client, sessions, ids = devices_client
    assert (
        client.post(
            "/api/v1/notifications/register-device",
            headers=headers(ids),
            json={"device_token": token},
        ).status_code
        == 422
    )
    assert await stored(sessions) is None


@pytest.mark.parametrize("who", ["owner", "customer", "manager"])
async def test_active_roles_can_register_only_their_own_device(devices_client, who):
    client, sessions, ids = devices_client
    response = client.post(
        "/api/v1/notifications/register-device",
        headers=headers(ids, who),
        json={"device_token": TOKEN},
    )
    assert response.status_code == 200 and (await stored(sessions)).user_id == ids[who]


@pytest.mark.parametrize("unregister", [False, True])
@pytest.mark.parametrize("rollback_fails", [False, True])
async def test_device_commit_errors_return_generic_503_and_attempt_rollback(
    monkeypatch, caplog, unregister, rollback_fails
):
    name = "unregister_device_token" if unregister else "register_device_token"
    monkeypatch.setattr(api, name, AsyncMock(return_value="created"))
    db = NS(
        commit=AsyncMock(side_effect=SQLAlchemyError("private-token database-secret")),
        rollback=AsyncMock(
            side_effect=RuntimeError("private-rollback") if rollback_fails else None
        ),
    )
    function = api.unregister_device if unregister else api.register_device
    body = (
        api.DeviceTokenRequest(device_token=TOKEN)
        if unregister
        else api.RegisterDeviceRequest(device_token=TOKEN)
    )
    with pytest.raises(HTTPException) as error:
        await function(body, current_user=NS(id=uuid4()), db=db)
    assert error.value.status_code == 503
    db.rollback.assert_awaited_once()
    assert not any(
        s in str(error.value.detail) + caplog.text
        for s in ["private-token", "database-secret", "private-rollback"]
    )


@pytest.mark.parametrize("invalid", [False, True])
async def test_unrequested_provider_tokens_never_query_or_update_sql(invalid):
    db = NS(scalars=AsyncMock(), flush=AsyncMock())
    await Service(db, redis_client=False)._apply_push_feedback(
        {}, () if invalid else (TOKEN,), (TOKEN,) if invalid else ()
    )
    db.scalars.assert_not_awaited()
    db.flush.assert_not_awaited()
