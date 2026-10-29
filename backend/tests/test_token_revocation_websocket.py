"""Mounted tracking/inbox sockets must recheck persisted revocation."""

import pytest
from starlette.websockets import WebSocketDisconnect
from tests.test_tracking_permissions import sockets, clean  # noqa: F401
from tests.test_notification_websocket_permissions import inbox, address  # noqa: F401
from app.core.security import create_access_token
from app.services.token_revocation import revoke_user_tokens


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["tracking", "notifications"])
async def test_open_socket_closes_on_next_ping_after_confirmed_logout(inbox, route):
    client, _, ids, manager, broker = inbox
    token = create_access_token(ids["manager"])
    path = (
        f"/api/v1/tracking/ws/dashboard?token={token}"
        if route == "tracking"
        else "/api/v1/notifications/ws?token=" + token
    )
    with client.websocket_connect(path) as ws:
        assert ws.receive_json()["type"] == "CONNECTED"
        r = client.post(
            "/api/v1/auth/logout", headers={"Authorization": "Bearer " + token}
        )
        assert r.status_code == 200
        ws.send_json({"action": "ping"})
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_json()
        assert e.value.code == 1008
    clean(manager)
    broker.assert_closed()


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["tracking", "notifications"])
async def test_revoked_token_is_refused_at_handshake_but_new_epoch_can_connect(
    inbox, route
):
    client, sessions, ids, manager, broker = inbox
    uid = ids["manager"]
    async with sessions() as db:
        await revoke_user_tokens(db, uid)
        await db.commit()

    def path(version):
        t = create_access_token(uid, token_version=version)
        return (
            f"/api/v1/tracking/ws/dashboard?token={t}"
            if route == "tracking"
            else "/api/v1/notifications/ws?token=" + t
        )

    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect(path(0)):
            pass
    assert e.value.code == 1008
    with client.websocket_connect(path(1)) as ws:
        assert ws.receive_json()["type"] == "CONNECTED"
    clean(manager)
    broker.assert_closed()


@pytest.mark.asyncio
async def test_server_push_guard_rechecks_epoch_without_waiting_for_client_ping(inbox):
    client, sessions, ids, manager, broker = inbox
    token = create_access_token(ids["manager"])
    with client.websocket_connect(f"/api/v1/tracking/ws/dashboard?token={token}") as ws:
        ws.receive_json()
        async with sessions() as db:
            await revoke_user_tokens(db, ids["manager"])
            await db.commit()
        ws.portal.call(
            manager.broadcast_to_topic,
            {"type": "POSITION_UPDATE", "payload": {}},
            "dashboard",
        )
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_json()
        assert e.value.code == 1008
    clean(manager)
    broker.assert_closed()
