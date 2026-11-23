"""Committed assignments travel through real PostgreSQL, Redis and ASGI WS."""

import asyncio
import os
from urllib.parse import urlparse
from uuid import uuid4

import httpx
import pytest
from redis import asyncio as aioredis
from sqlalchemy import select, func

from tests.test_delivery_financial_postgresql import payment_db  # noqa: F401
from tests.test_order_cancellation_postgresql import cancel_db  # noqa: F401
from tests.test_sla_monitor_postgresql import sla_db  # noqa: F401
from tests.test_runtime_contracts_postgresql import runtime_db  # noqa: F401
from tests.test_assignment_eligibility_postgresql import assignment_db  # noqa: F401
from tests.asgi_socket import open_socket
from app.main import app
from app.api.v1 import notifications
from app.core.config import settings
from app.core.security import create_access_token
from app.models.order import Order, OrderStatus
from app.models.notification import NotificationLog
from app.models.financial import Financial
from app.services import assignment_realtime as realtime, order_assignment
from app.services.assignment_realtime import _publish as real_publish


@pytest.fixture
async def realtime_db(assignment_db, monkeypatch):
    selected = os.environ.get("TEST_NOTIFICATION_REDIS_URL")
    if not selected:
        pytest.skip("Explicit loopback TEST_NOTIFICATION_REDIS_URL /15 required")
    parsed = urlparse(selected)
    if (
        parsed.scheme != "redis"
        or parsed.hostname not in ("127.0.0.1", "localhost")
        or parsed.path != "/15"
    ):
        pytest.fail("Dedicated loopback Redis database /15 required")
    _, sessions, ids = assignment_db
    monkeypatch.setattr(settings, "REDIS_URL", selected)
    monkeypatch.setattr(
        settings, "REDIS_NOTIF_CHANNEL_PREFIX", "test.assignment." + uuid4().hex
    )
    monkeypatch.setattr(realtime, "_publish", real_publish)
    monkeypatch.setattr(notifications, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(
        notifications,
        "_notification_redis_client",
        lambda: aioredis.from_url(
            selected,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=None,
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        yield client, sessions, ids
        if realtime._tasks:
            await asyncio.gather(*tuple(realtime._tasks))


def headers(ids):
    return {"Authorization": "Bearer " + create_access_token(ids["staff"])}


def address(uid):
    return "/api/v1/notifications/ws?token=" + create_access_token(uid)


@pytest.mark.asyncio
async def test_committed_assignment_reaches_only_its_recipient_once(realtime_db):
    client, sessions, ids = realtime_db
    async with (
        open_socket(app, address(ids["owner"])) as owner,
        open_socket(app, address(ids["staff"])) as other,
    ):
        assert (await owner.receive_json())["realtime_available"] is True
        assert (await other.receive_json())["realtime_available"] is True
        path = f"/api/v1/orders/{ids['order']}/assign"
        response = await client.patch(
            path, headers=headers(ids), json={"rider_id": str(ids["rider"])}
        )
        assert response.status_code == 200, response.text
        frame = await owner.receive_json()
        assert frame["type"] == "NEW_NOTIFICATION"
        assert frame["template_code"] == "nuevo_pedido_asignado"
        assert frame["unread_count"] == 1
        async with sessions() as db:
            notice = await db.get(NotificationLog, frame["id"])
            assert (
                notice.user_id == ids["owner"] and notice.delivery_id == ids["delivery"]
            )
            assert (await db.get(Order, ids["order"])).status == OrderStatus.ASIGNADO
            assert await db.scalar(select(func.count()).select_from(Financial)) == 1
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(other.receive_json(), 0.15)
        replay = await client.patch(
            path, headers=headers(ids), json={"rider_id": str(ids["rider"])}
        )
        assert replay.status_code == 200
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(owner.receive_json(), 0.15)


@pytest.mark.asyncio
async def test_rolled_back_assignment_never_announces_over_real_redis(
    realtime_db, monkeypatch
):
    client, sessions, ids = realtime_db
    original = order_assignment.enqueue_assignment_notice

    async def fail(db, *args, **kwargs):
        await original(db, *args, **kwargs)
        raise RuntimeError("injected transaction failure")

    monkeypatch.setattr(order_assignment, "enqueue_assignment_notice", fail)
    async with open_socket(app, address(ids["owner"])) as owner:
        assert (await owner.receive_json())["realtime_available"] is True
        response = await client.patch(
            f"/api/v1/orders/{ids['order']}/assign",
            headers=headers(ids),
            json={"rider_id": str(ids["rider"])},
        )
        assert response.status_code == 500
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(owner.receive_json(), 0.15)
        async with sessions() as db:
            assert (await db.get(Order, ids["order"])).status == OrderStatus.PENDIENTE
            assert (
                await db.scalar(select(func.count()).select_from(NotificationLog)) == 0
            )


@pytest.mark.asyncio
async def test_redis_outage_preserves_commit_and_rest_inbox_recovery(
    realtime_db, monkeypatch
):
    client, sessions, ids = realtime_db
    monkeypatch.setattr(settings, "REDIS_URL", "redis://127.0.0.1:1/15")
    response = await client.patch(
        f"/api/v1/orders/{ids['order']}/assign",
        headers=headers(ids),
        json={"rider_id": str(ids["rider"])},
    )
    assert response.status_code == 200, response.text
    await asyncio.gather(*tuple(realtime._tasks))
    inbox = await client.get(
        "/api/v1/notifications/inbox",
        headers={"Authorization": "Bearer " + create_access_token(ids["owner"])},
    )
    assert inbox.status_code == 200 and inbox.json()["unread_count"] == 1
    assert len(inbox.json()["items"]) == 1
    async with sessions() as db:
        assert (await db.get(Order, ids["order"])).status == OrderStatus.ASIGNADO
