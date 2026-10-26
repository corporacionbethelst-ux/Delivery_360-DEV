"""Unsubscription during an asynchronous check must drop an in-flight fan-out."""

import asyncio
from unittest.mock import AsyncMock
from types import SimpleNamespace
import pytest
from starlette.websockets import WebSocketState
from app.core.websocket import ConnectionManager


@pytest.mark.asyncio
async def test_unsubscribe_during_authorization_drops_queued_topic_message():
    manager = ConnectionManager()
    socket = SimpleNamespace(
        accept=AsyncMock(),
        send_json=AsyncMock(),
        close=AsyncMock(),
        application_state=WebSocketState.CONNECTED,
    )
    started, release = asyncio.Event(), asyncio.Event()

    async def guard():
        started.set()
        await release.wait()
        return True

    await manager.connect(socket, "connection", user_id="user", authorize_send=guard)
    manager.subscribe("connection", "rider:target")
    task = asyncio.create_task(
        manager.broadcast_to_topic({"type": "POSITION_UPDATE"}, "rider:target")
    )
    await asyncio.wait_for(started.wait(), 2)
    manager.unsubscribe("connection", "rider:target")
    assert not manager.topic_subscriptions
    release.set()
    await asyncio.wait_for(task, 2)
    socket.send_json.assert_not_awaited()
    socket.close.assert_not_awaited()
    assert "connection" in manager.active_connections
    manager.disconnect("connection")
    assert (
        not manager.active_connections
        and not manager.send_guards
        and not manager.send_locks
    )
