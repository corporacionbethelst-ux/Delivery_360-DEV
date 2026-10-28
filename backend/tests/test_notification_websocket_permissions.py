"""Mounted notification sockets: live identity, private rows and Redis lifecycle."""

import asyncio
import concurrent.futures
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from anyio.from_thread import start_blocking_portal
from sqlalchemy import update, delete
from starlette.websockets import WebSocketDisconnect
from tests.test_tracking_permissions import sockets, clean  # noqa: F401
from app.api.v1 import notifications as api
from app.core.security import create_access_token, create_refresh_token
from app.core.config import settings
from app.models.user import User, UserRole
from app.models.rider import Rider, RiderStatus
from app.models.notification import (
    NotificationLog,
    NotificationChannel,
    OmnichannelStatus,
)


class Broker:
    def __init__(self):
        self.clients = []
        self.subscribers = []
        self.available = True

    def client(self):
        broker = self

        class Client:
            closed = False

            def pubsub(self):
                sub = Subscriber(broker)
                broker.subscribers.append(sub)
                return sub

            async def aclose(self):
                self.closed = True

        result = Client()
        self.clients.append(result)
        return result

    async def publish(self, topic, data, *, channel=None):
        pending = []
        for sub in self.subscribers:
            if topic not in sub.topics or sub.closed:
                continue
            ack = concurrent.futures.Future()
            message = {
                "type": "message",
                "channel": channel or topic,
                "data": (
                    json.dumps(data) if not isinstance(data, (str, Exception)) else data
                ),
            }
            if isinstance(data, Exception):
                message = data
            sub.loop.call_soon_threadsafe(sub.queue.put_nowait, (message, ack))
            pending.append(asyncio.wrap_future(ack))
        if pending:
            await asyncio.wait_for(asyncio.gather(*pending), 10)

    def assert_closed(self):
        assert all(c.closed for c in self.clients)
        assert all(s.closed and not s.topics for s in self.subscribers)


class Subscriber:
    def __init__(self, broker):
        self.broker = broker
        self.queue = asyncio.Queue()
        self.loop = asyncio.get_running_loop()
        self.topics = set()
        self.closed = False

    async def subscribe(self, topic):
        if not self.broker.available:
            raise ConnectionError("private-redis-credential-diagnostic")
        self.topics.add(topic)

    async def unsubscribe(self, topic):
        self.topics.discard(topic)

    async def aclose(self):
        self.closed = True

    async def listen(self):
        while True:
            message, ack = await self.queue.get()
            try:
                if isinstance(message, Exception):
                    raise message
                yield message
            finally:
                if not ack.done():
                    ack.set_result(None)


@pytest.fixture
async def inbox(sockets, monkeypatch):
    client, sessions, ids, manager = sockets
    async with sessions() as db:
        conn = await db.connection()
        await conn.run_sync(NotificationLog.__table__.create)
        rows = {
            name: NotificationLog(
                id=uuid4(),
                user_id=ids[owner],
                channel=channel,
                status=status,
                title=title,
                body="Persisted body",
            )
            for name, owner, channel, status, title in [
                ("own", "owner", "IN_APP", "PENDIENTE", "Owned notification"),
                ("read", "owner", "IN_APP", "LEIDO", "Already read"),
                (
                    "foreign",
                    "rival",
                    "IN_APP",
                    "PENDIENTE",
                    "Foreign private notification",
                ),
                ("push", "owner", "PUSH", "ENVIADO", "Push only"),
            ]
        }
        db.add_all(rows.values())
        await db.commit()
        ids.update({name + "_log": row.id for name, row in rows.items()})
    broker = Broker()
    monkeypatch.setattr(api, "manager", manager)
    monkeypatch.setattr(api, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(api, "_notification_redis_client", broker.client)
    return client, sessions, ids, manager, broker


def address(ids, who="owner"):
    return "/api/v1/notifications/ws?token=" + create_access_token(ids[who])


def topic(ids, who="owner"):
    return f"{settings.REDIS_NOTIF_CHANNEL_PREFIX}:{ids[who]}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "who", ["manager", "super", "operator", "auditor", "customer", "owner"]
)
async def test_active_roles_receive_only_their_own_snapshot_and_frontend_ping(
    inbox, who
):
    client, _, ids, manager, broker = inbox
    with client.websocket_connect(address(ids, who)) as ws:
        first = ws.receive_json()
        assert first == {
            "type": "CONNECTED",
            "channel": topic(ids, who),
            "unread_count": int(who == "owner"),
            "realtime_available": True,
        }
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
        ws.send_json({"action": "ping"})
        assert ws.receive_json() == {"type": "pong"}
    clean(manager)
    broker.assert_closed()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    [
        "missing",
        "invalid",
        "refresh",
        "expired",
        "subject",
        "nonexistent",
        "inactive",
        "roleless",
        "missingprofile",
    ],
)
async def test_bad_credentials_or_accounts_are_rejected_before_accept(inbox, kind):
    client, _, ids, manager, broker = inbox
    tokens = {
        "missing": None,
        "invalid": "invalid",
        "refresh": create_refresh_token(str(ids["owner"])),
        "expired": create_access_token(ids["owner"], timedelta(seconds=-1)),
        "subject": create_access_token("invalid-id"),
        "nonexistent": create_access_token(uuid4()),
        **{
            k: create_access_token(ids[k])
            for k in ["inactive", "roleless", "missingprofile"]
        },
    }
    token = tokens[kind]
    url = "/api/v1/notifications/ws" + ("" if token is None else "?token=" + token)
    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect(url):
            pass
    assert error.value.code == 1008
    clean(manager)
    assert not broker.clients


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["inactive", "suspend", "roleless", "delete"])
async def test_outgoing_notification_rechecks_live_account(inbox, change):
    client, sessions, ids, manager, broker = inbox
    with client.websocket_connect(address(ids)) as ws:
        ws.receive_json()
        async with sessions() as db:
            if change == "inactive":
                await db.execute(
                    update(User).where(User.id == ids["owner"]).values(is_active=False)
                )
            elif change == "suspend":
                await db.execute(
                    update(Rider)
                    .where(Rider.id == ids["rider"])
                    .values(status=RiderStatus.SUSPENDIDO)
                )
            elif change == "roleless":
                await db.execute(
                    update(User).where(User.id == ids["owner"]).values(role=None)
                )
            else:
                await db.execute(delete(User).where(User.id == ids["owner"]))
            await db.commit()
        cid = manager.user_connections[str(ids["owner"])][0]
        ws.portal.call(manager.send_personal_message, {"type": "NEW_NOTIFICATION"}, cid)
        message = ws.receive()
        assert message["type"] == "websocket.close" and message["code"] == 1008
    clean(manager)
    broker.assert_closed()


@pytest.mark.asyncio
async def test_expiration_is_rechecked_before_a_frame(inbox, monkeypatch):
    from jose import jwt

    client, _, ids, manager, broker = inbox
    token = create_access_token(ids["owner"], timedelta(minutes=5))
    expires = jwt.get_unverified_claims(token)["exp"]

    class Later(datetime):
        @classmethod
        def utcnow(cls):
            return datetime.fromtimestamp(expires + 1, timezone.utc).replace(
                tzinfo=None
            )

        @classmethod
        def now(cls, tz=None):
            return datetime.fromtimestamp(expires + 1, timezone.utc)

    with client.websocket_connect("/api/v1/notifications/ws?token=" + token) as ws:
        ws.receive_json()
        monkeypatch.setattr(jwt, "datetime", Later)
        cid = manager.user_connections[str(ids["owner"])][0]
        ws.portal.call(manager.send_personal_message, {"type": "NEW_NOTIFICATION"}, cid)
        assert ws.receive()["code"] == 1008
    clean(manager)
    broker.assert_closed()


@pytest.mark.asyncio
async def test_redis_payload_is_replaced_with_the_owned_database_record(inbox):
    client, _, ids, manager, broker = inbox
    with client.websocket_connect(address(ids)) as ws:
        ws.receive_json()
        ws.portal.call(
            broker.publish,
            topic(ids),
            {
                "type": "NEW_NOTIFICATION",
                "id": str(ids["own_log"]),
                "title": "Injected content",
                "unread_count": 999,
            },
        )
        frame = ws.receive_json()
        assert (
            frame["id"] == str(ids["own_log"])
            and frame["title"] == "Owned notification"
        )
        assert frame["body"] == "Persisted body" and frame["channel"] == "IN_APP"
        assert frame["unread_count"] == 1
    clean(manager)
    broker.assert_closed()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", ["foreign", "push", "missing", "invalid", "wrong-channel", "wrong-type"]
)
async def test_foreign_or_invalid_redis_event_is_not_delivered(inbox, kind):
    client, _, ids, manager, broker = inbox
    key = {
        "foreign": str(ids["foreign_log"]),
        "push": str(ids["push_log"]),
        "missing": str(uuid4()),
        "invalid": "invalid",
        "wrong-channel": str(ids["foreign_log"]),
        "wrong-type": str(ids["foreign_log"]),
    }[kind]
    with client.websocket_connect(address(ids)) as ws:
        ws.receive_json()
        data = {"type": "NEW_NOTIFICATION", "id": key, "title": "DO NOT DELIVER"}
        if kind == "wrong-type":
            data["type"] = "POSITION_UPDATE"
        if kind == "wrong-channel":

            async def misroute():
                await broker.publish(topic(ids), data, channel=topic(ids, "rival"))

            ws.portal.call(misroute)
        else:
            ws.portal.call(broker.publish, topic(ids), data)
        ws.send_json({"action": "ping"})
        assert ws.receive_json() == {"type": "pong"}
    clean(manager)
    broker.assert_closed()


@pytest.mark.asyncio
async def test_two_sockets_receive_one_copy_each_without_cross_broadcast(
    inbox, monkeypatch
):
    client, _, ids, manager, broker = inbox
    # Model a single ASGI worker: separate TestClient portals otherwise run each
    # socket and the shared manager/database on competing event-loop threads.
    # Starting a portal directly avoids running the application's real lifespan.
    with start_blocking_portal() as portal:
        monkeypatch.setattr(client, "portal", portal)
        with client.websocket_connect(address(ids)) as first:
            first.receive_json()
            with client.websocket_connect(address(ids)) as second:
                second.receive_json()
                assert first.portal is second.portal is portal
                assert len(broker.subscribers) == 2
                assert all(topic(ids) in sub.topics for sub in broker.subscribers)
                first.portal.call(
                    broker.publish,
                    topic(ids),
                    {"type": "NEW_NOTIFICATION", "id": str(ids["own_log"])},
                )
                assert first.receive_json()["id"] == str(ids["own_log"])
                assert second.receive_json()["id"] == str(ids["own_log"])
                for socket in [first, second]:
                    socket.send_json({"type": "ping"})
                    assert socket.receive_json() == {"type": "pong"}
    clean(manager)
    broker.assert_closed()


@pytest.mark.asyncio
async def test_redis_unavailable_advertises_polling_without_leaking_error(
    inbox, capsys
):
    client, _, ids, manager, broker = inbox
    broker.available = False
    with client.websocket_connect(address(ids)) as ws:
        connected = ws.receive_json()
        assert (
            connected["realtime_available"] is False and connected["unread_count"] == 1
        )
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
    clean(manager)
    broker.assert_closed()
    capture = capsys.readouterr()
    assert "private-redis-credential-diagnostic" not in capture.out + capture.err


@pytest.mark.asyncio
async def test_subscription_or_impersonation_commands_are_not_supported(inbox):
    client, _, ids, manager, broker = inbox
    with client.websocket_connect(address(ids)) as ws:
        ws.receive_json()
        ws.send_json({"action": "subscribe", "topic": topic(ids, "rival")})
        assert ws.receive()["code"] == 1008
    clean(manager)
    broker.assert_closed()


@pytest.mark.asyncio
async def test_redis_failure_after_connect_closes_to_allow_reconnect(inbox):
    client, _, ids, manager, broker = inbox
    with client.websocket_connect(address(ids)) as ws:
        ws.receive_json()
        ws.portal.call(
            broker.publish, topic(ids), ConnectionError("private-redis-error")
        )
        assert ws.receive()["code"] == 1011
    clean(manager)
    broker.assert_closed()


@pytest.mark.asyncio
async def test_database_failure_does_not_fake_zero_unread(inbox, monkeypatch):
    client, _, ids, manager, broker = inbox

    async def broken(db, user_id):
        raise RuntimeError("private-database-error")

    monkeypatch.setattr(api, "_notification_unread", broken)
    with client.websocket_connect(address(ids)) as ws:
        message = ws.receive()
        assert message["type"] == "websocket.close" and message["code"] == 1011
    clean(manager)
    broker.assert_closed()
