"""Mounted ASGI WebSockets and REST tracking against a private SQLite database."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Text, event, select, update
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
from starlette.websockets import WebSocketDisconnect
from app.main import app
from app.api.v1 import tracking, auth
from app.core.database import get_db
from app.core.security import create_access_token, create_refresh_token
from app.core.rate_limiter import RateLimiter
from app.middleware import rate_limit_middleware
from app.core.websocket import ConnectionManager
from app.models.user import User, UserRole
from app.models.rider import Rider, RiderStatus
from app.models.vehicle import Vehicle
from app.models.order import Order
from app.models.delivery import Delivery
from app.models.location import RiderLiveLocation


@pytest.fixture
async def sockets(tmp_path, monkeypatch):
    # Keep the real middleware and limits, without sharing IP history across cases.
    monkeypatch.setattr(rate_limit_middleware, "rate_limiter", RateLimiter())
    engine = create_async_engine(
        "sqlite+aiosqlite:///" + str(tmp_path / "tracking.db"), poolclass=NullPool
    )

    @event.listens_for(engine.sync_engine, "connect")
    def geometry(conn, record):
        conn.create_function("GeomFromEWKT", 1, lambda v: None)
        conn.create_function("AsEWKB", 1, lambda v: None)

    column = Rider.__table__.c.last_location
    original = column.type
    try:
        column.type = Text()
        async with engine.begin() as conn:
            for model in [User, Vehicle, Rider, Order, Delivery, RiderLiveLocation]:
                await conn.run_sync(model.__table__.create)
    finally:
        column.type = original
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    ids = {
        name: uuid4()
        for name in [
            "manager",
            "super",
            "operator",
            "auditor",
            "customer",
            "owner",
            "rival",
            "inactive",
            "roleless",
            "missingprofile",
        ]
    }
    roles = {
        "manager": "GERENTE",
        "super": "SUPERADMIN",
        "operator": "OPERADOR",
        "auditor": "AUDITOR",
        "customer": "CLIENTE",
        "owner": "REPARTIDOR",
        "rival": "REPARTIDOR",
        "inactive": "GERENTE",
        "roleless": None,
        "missingprofile": "REPARTIDOR",
    }
    async with sessions() as db:
        for name, uid in ids.items():
            db.add(
                User(
                    id=uid,
                    email=name + "@example.com",
                    hashed_password="unused",
                    first_name=name,
                    last_name="Test",
                    role=roles[name],
                    is_active=name != "inactive",
                )
            )
        await db.flush()
        # Explicit SQL keeps the historical nullable role from a Python default.
        await db.execute(
            update(User).where(User.id == ids["roleless"]).values(role=None)
        )
        own = Rider(id=uuid4(), user_id=ids["owner"], status=RiderStatus.ACTIVO)
        rival = Rider(id=uuid4(), user_id=ids["rival"], status=RiderStatus.ACTIVO)
        db.add_all([own, rival])
        await db.flush()
        order = Order(
            id=uuid4(),
            customer_name="Customer",
            customer_phone="123",
            pickup_address="Start",
            delivery_address="End",
            assigned_rider_id=own.id,
        )
        db.add(order)
        await db.flush()
        delivery = Delivery(id=uuid4(), order_id=order.id, rider_id=own.id)
        db.add(delivery)
        await db.commit()
        ids.update(
            rider=own.id, other_rider=rival.id, order=order.id, delivery=delivery.id
        )
    manager = ConnectionManager()
    monkeypatch.setattr(tracking, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(tracking, "manager", manager)
    overrides = app.dependency_overrides.copy()

    async def database():
        async with sessions() as db:
            yield db

    async def service():
        return SimpleNamespace(calculate_eta=lambda *args: None)

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[tracking._get_tracking_service] = service
    client = TestClient(app)
    try:
        yield client, sessions, ids, manager
    finally:
        client.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(overrides)
        await engine.dispose()


def url(ids, who, channel):
    return f"/api/v1/tracking/ws/{channel}?token={create_access_token(ids[who])}"


def clean(manager):
    assert not manager.active_connections and not manager.user_connections
    assert (
        not manager.topic_subscriptions
        and not manager.send_guards
        and not manager.send_locks
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "who,allowed",
    [
        ("manager", True),
        ("super", True),
        ("operator", False),
        ("auditor", False),
        ("customer", False),
        ("owner", False),
    ],
)
async def test_dashboard_permissions_on_the_real_mounted_route(sockets, who, allowed):
    client, _, ids, manager = sockets
    if allowed:
        with client.websocket_connect(url(ids, who, "dashboard")) as ws:
            assert ws.receive_json() == {"type": "CONNECTED", "channel": "dashboard"}
            ws.send_json({"action": "ping"})
            assert ws.receive_json() == {"type": "pong"}
    else:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(url(ids, who, "dashboard")):
                pass
        assert error.value.code == 1008
    clean(manager)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "who,allowed",
    [
        ("manager", True),
        ("operator", True),
        ("auditor", True),
        ("owner", True),
        ("rival", False),
        ("customer", False),
    ],
)
async def test_individual_rider_permissions(sockets, who, allowed):
    client, _, ids, manager = sockets
    channel = f"rider:{ids['rider']}"
    if allowed:
        with client.websocket_connect(url(ids, who, channel)) as ws:
            assert ws.receive_json()["channel"] == channel
            ws.portal.call(
                manager.broadcast_to_topic, {"type": "POSITION_UPDATE"}, channel
            )
            assert ws.receive_json()["type"] == "POSITION_UPDATE"
    else:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(url(ids, who, channel)):
                pass
        assert error.value.code == 1008
    clean(manager)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", ["missing", "invalid", "refresh", "expired", "subject", "nonexistent"]
)
async def test_credentials_are_checked_before_accept(sockets, kind):
    client, _, ids, manager = sockets
    tokens = {
        "missing": None,
        "invalid": "invalid-token",
        "refresh": create_refresh_token(str(ids["manager"])),
        "expired": create_access_token(ids["manager"], timedelta(seconds=-1)),
        "subject": create_access_token("not-a-uuid"),
        "nonexistent": create_access_token(uuid4()),
    }
    token = tokens[kind]
    address = "/api/v1/tracking/ws/dashboard" + (
        "" if token is None else "?token=" + token
    )
    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect(address):
            pass
    assert error.value.code == 1008
    clean(manager)


@pytest.mark.asyncio
@pytest.mark.parametrize("who", ["inactive", "roleless", "missingprofile"])
async def test_live_account_is_required(sockets, who):
    client, _, ids, manager = sockets
    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect(url(ids, who, f"rider:{ids['rider']}")):
            pass
    assert error.value.code == 1008
    clean(manager)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "topic",
    [
        "dashboard",
        "notifications:user:foreign",
        "rider:invalid",
        "all-riders-extra",
        None,
        ["dashboard"],
    ],
)
async def test_second_subscription_cannot_bypass_initial_authorization(sockets, topic):
    client, _, ids, manager = sockets
    with client.websocket_connect(url(ids, "owner", f"rider:{ids['rider']}")) as ws:
        ws.receive_json()
        ws.send_json({"action": "subscribe", "topic": topic})
        response = ws.receive()
        assert response["type"] == "websocket.close" and response["code"] == 1008
    clean(manager)


@pytest.mark.asyncio
async def test_order_alias_is_bound_and_cannot_follow_a_reassignment(sockets):
    client, sessions, ids, manager = sockets
    channel = f"order:{ids['order']}"
    with client.websocket_connect(url(ids, "owner", channel)) as ws:
        assert ws.receive_json()["channel"] == channel
        assert f"rider:{ids['rider']}" in manager.topic_subscriptions
        async with sessions() as db:
            await db.execute(
                update(Order)
                .where(Order.id == ids["order"])
                .values(assigned_rider_id=ids["other_rider"])
            )
            await db.execute(
                update(Delivery)
                .where(Delivery.id == ids["delivery"])
                .values(rider_id=ids["other_rider"])
            )
            await db.commit()
        ws.portal.call(
            manager.broadcast_to_topic,
            {"type": "POSITION_UPDATE"},
            f"rider:{ids['rider']}",
        )
        assert ws.receive()["code"] == 1008
    clean(manager)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["deactivate", "role", "suspend", "delete"])
async def test_revoked_access_closes_before_the_next_outgoing_position(sockets, change):
    client, sessions, ids, manager = sockets
    with client.websocket_connect(url(ids, "owner", f"rider:{ids['rider']}")) as ws:
        ws.receive_json()
        async with sessions() as db:
            if change == "deactivate":
                await db.execute(
                    update(User).where(User.id == ids["owner"]).values(is_active=False)
                )
            elif change == "role":
                await db.execute(
                    update(User)
                    .where(User.id == ids["owner"])
                    .values(role=UserRole.CLIENTE)
                )
            elif change == "suspend":
                await db.execute(
                    update(Rider)
                    .where(Rider.id == ids["rider"])
                    .values(status=RiderStatus.SUSPENDIDO)
                )
            else:
                from sqlalchemy import delete

                await db.execute(delete(User).where(User.id == ids["owner"]))
            await db.commit()
        ws.portal.call(
            manager.broadcast_to_topic,
            {"type": "POSITION_UPDATE"},
            f"rider:{ids['rider']}",
        )
        response = ws.receive()
        assert response["type"] == "websocket.close" and response["code"] == 1008
    clean(manager)


@pytest.mark.asyncio
async def test_token_expiration_is_rechecked_before_outgoing_data(sockets, monkeypatch):
    from jose import jwt

    client, _, ids, manager = sockets
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

    with client.websocket_connect(
        f"/api/v1/tracking/ws/rider:{ids['rider']}?token={token}"
    ) as ws:
        ws.receive_json()
        monkeypatch.setattr(jwt, "datetime", Later)
        ws.portal.call(
            manager.broadcast_to_topic,
            {"type": "POSITION_UPDATE"},
            f"rider:{ids['rider']}",
        )
        assert ws.receive()["code"] == 1008
    clean(manager)


@pytest.mark.asyncio
async def test_rest_fallbacks_do_not_bypass_tracking_ownership(sockets):
    client, _, ids, _ = sockets
    headers = {"Authorization": "Bearer " + create_access_token(ids["rival"])}
    for path in [
        f"/api/v1/tracking/history/{ids['rider']}",
        f"/api/v1/tracking/live/{ids['order']}",
    ]:
        assert client.get(path, headers=headers).status_code == 403
    own = {"Authorization": "Bearer " + create_access_token(ids["owner"])}
    assert (
        client.get(f"/api/v1/tracking/history/{ids['rider']}", headers=own).status_code
        == 200
    )
    assert (
        client.get(f"/api/v1/tracking/live/{ids['order']}", headers=own).status_code
        == 200
    )


@pytest.mark.asyncio
async def test_order_and_rider_alias_unsubscribe_keeps_the_other_binding(sockets):
    client, _, ids, manager = sockets
    channel = f"rider:{ids['rider']}"
    with client.websocket_connect(url(ids, "owner", channel)) as ws:
        ws.receive_json()
        ws.send_json({"action": "subscribe", "topic": f"order:{ids['order']}"})
        assert ws.receive_json()["type"] == "subscribed"
        ws.send_json({"action": "unsubscribe", "topic": f"order:{ids['order']}"})
        assert ws.receive_json()["type"] == "unsubscribed"
        ws.portal.call(manager.broadcast_to_topic, {"type": "POSITION_UPDATE"}, channel)
        assert ws.receive_json()["type"] == "POSITION_UPDATE"
    clean(manager)


@pytest.mark.asyncio
async def test_signed_role_claim_does_not_replace_live_database_role(sockets):
    from jose import jwt
    from app.core.config import settings

    client, _, ids, manager = sockets
    token = create_access_token(ids["customer"])
    claims = jwt.get_unverified_claims(token)
    claims["role"] = "SUPERADMIN"
    token = jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect("/api/v1/tracking/ws/dashboard?token=" + token):
            pass
    assert error.value.code == 1008
    clean(manager)


@pytest.mark.asyncio
async def test_denied_connection_does_not_skip_the_next_authorized_subscriber(sockets):
    client, sessions, ids, manager = sockets
    topic = f"rider:{ids['rider']}"
    with client.websocket_connect(url(ids, "owner", topic)) as owner:
        owner.receive_json()
        with client.websocket_connect(url(ids, "manager", topic)) as staff:
            staff.receive_json()
            async with sessions() as db:
                await db.execute(
                    update(User).where(User.id == ids["owner"]).values(is_active=False)
                )
                await db.commit()
            staff.portal.call(
                manager.broadcast_to_topic, {"type": "POSITION_UPDATE"}, topic
            )
            assert owner.receive()["code"] == 1008
            assert staff.receive_json()["type"] == "POSITION_UPDATE"
    clean(manager)


@pytest.mark.asyncio
async def test_database_failure_does_not_send_position_or_expose_exception(
    sockets, monkeypatch, capsys
):
    client, _, ids, manager = sockets
    topic = f"rider:{ids['rider']}"
    with client.websocket_connect(url(ids, "owner", topic)) as ws:
        ws.receive_json()

        def broken():
            raise RuntimeError("private-storage-diagnostic")

        monkeypatch.setattr(tracking, "AsyncSessionLocal", broken)
        ws.portal.call(manager.broadcast_to_topic, {"type": "POSITION_UPDATE"}, topic)
        message = ws.receive()
        assert message["type"] == "websocket.close" and message["code"] == 1011
    clean(manager)
    capture = capsys.readouterr()
    assert "private-storage-diagnostic" not in capture.out + capture.err


@pytest.mark.asyncio
@pytest.mark.parametrize("data", ["not-json", "[]", "null"])
async def test_invalid_json_never_changes_subscriptions(sockets, data):
    client, _, ids, manager = sockets
    topic = f"rider:{ids['rider']}"
    with client.websocket_connect(url(ids, "owner", topic)) as ws:
        ws.receive_json()
        ws.send_text(data)
        assert ws.receive_json()["type"] == "error"
        assert set(manager.topic_subscriptions) == {topic}
    clean(manager)


@pytest.mark.asyncio
async def test_subscription_limit_is_enforced_without_registering_another_channel(
    sockets, monkeypatch
):
    client, _, ids, manager = sockets
    monkeypatch.setattr(tracking, "MAX_TRACKING_CHANNELS", 1)
    with client.websocket_connect(url(ids, "manager", f"rider:{ids['rider']}")) as ws:
        ws.receive_json()
        ws.send_json({"action": "subscribe", "topic": f"rider:{ids['other_rider']}"})
        assert ws.receive()["code"] == 1008
    clean(manager)


@pytest.mark.asyncio
async def test_order_without_consistent_assignment_is_not_a_tracking_alias(sockets):
    client, sessions, ids, manager = sockets
    async with sessions() as db:
        await db.execute(
            update(Order).where(Order.id == ids["order"]).values(assigned_rider_id=None)
        )
        await db.commit()
    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect(url(ids, "manager", f"order:{ids['order']}")):
            pass
    assert error.value.code == 1008
    headers = {"Authorization": "Bearer " + create_access_token(ids["manager"])}
    assert (
        client.get(f"/api/v1/tracking/live/{ids['order']}", headers=headers).status_code
        == 409
    )
    clean(manager)


@pytest.mark.asyncio
async def test_excessive_message_is_closed_without_another_subscription(sockets):
    client, _, ids, manager = sockets
    with client.websocket_connect(url(ids, "owner", f"rider:{ids['rider']}")) as ws:
        ws.receive_json()
        ws.send_text("x" * 4097)
        assert ws.receive()["code"] == 1008
    clean(manager)
