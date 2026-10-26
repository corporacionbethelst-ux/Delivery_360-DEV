"""Real Redis Pub/Sub on an explicitly selected loopback test database 15."""

import asyncio
import json
import os
from urllib.parse import urlparse
from uuid import uuid4
import pytest
from redis import asyncio as aioredis
from tests.test_notification_websocket_permissions import (
    inbox,
    address,
    topic,
)  # noqa: F401
from tests.test_tracking_permissions import sockets, clean  # noqa: F401
from app.api.v1 import notifications as api
from app.core.config import settings


@pytest.fixture
async def redis_inbox(inbox, monkeypatch):
    selected = os.environ.get("TEST_NOTIFICATION_REDIS_URL")
    if not selected:
        pytest.skip("Explicit TEST_NOTIFICATION_REDIS_URL required for real Pub/Sub")
    parsed = urlparse(selected)
    if (
        parsed.scheme != "redis"
        or parsed.hostname not in ("127.0.0.1", "localhost")
        or parsed.path != "/15"
    ):
        pytest.fail("Notification Redis tests require loopback and test database /15")
    monkeypatch.setattr(
        settings, "REDIS_NOTIF_CHANNEL_PREFIX", "test.notifications." + uuid4().hex
    )
    monkeypatch.setattr(
        api,
        "_notification_redis_client",
        lambda: aioredis.from_url(
            selected,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=None,
        ),
    )
    return (*inbox, selected)


async def subscribers(selected, channel, expected):
    async with aioredis.from_url(selected, decode_responses=True) as client:
        for _ in range(500):
            values = await client.pubsub_numsub(channel)
            if values[0][1] == expected:
                return
            await asyncio.sleep(0.01)
    pytest.fail("Redis subscription count did not reach expected value")


async def publish(selected, channel, payload):
    async with aioredis.from_url(selected, decode_responses=True) as client:
        return await client.publish(channel, json.dumps(payload))


@pytest.mark.asyncio
async def test_real_redis_delivers_owned_rows_to_two_sockets_and_releases_subscriptions(
    redis_inbox,
):
    client, _, ids, manager, _, selected = redis_inbox
    channel = topic(ids)
    with client.websocket_connect(address(ids)) as first:
        assert first.receive_json()["realtime_available"] is True
        with client.websocket_connect(address(ids)) as second:
            assert second.receive_json()["realtime_available"] is True
            await subscribers(selected, channel, 2)
            assert (
                await publish(
                    selected,
                    channel,
                    {
                        "type": "NEW_NOTIFICATION",
                        "id": str(ids["own_log"]),
                        "title": "Untrusted Redis text",
                    },
                )
                == 2
            )
            for socket in [first, second]:
                frame = socket.receive_json()
                assert (
                    frame["id"] == str(ids["own_log"])
                    and frame["title"] == "Owned notification"
                )
                assert frame["unread_count"] == 1
    await subscribers(selected, channel, 0)
    clean(manager)


@pytest.mark.asyncio
async def test_real_idle_pubsub_does_not_turn_into_a_two_second_read_timeout(
    redis_inbox,
):
    client, _, ids, manager, _, selected = redis_inbox
    with client.websocket_connect(address(ids)) as ws:
        assert ws.receive_json()["realtime_available"] is True
        await subscribers(selected, topic(ids), 1)
        await asyncio.sleep(2.2)
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
        await publish(
            selected,
            topic(ids),
            {"type": "NEW_NOTIFICATION", "id": str(ids["own_log"])},
        )
        assert ws.receive_json()["id"] == str(ids["own_log"])
    await subscribers(selected, topic(ids), 0)
    clean(manager)
