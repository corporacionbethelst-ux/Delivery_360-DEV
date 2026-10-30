"""Awaitable ASGI WebSocket client without TestClient's polling receive loop.

Runs the real ASGI application and protocol on the test loop. Queues wake on
messages, so concurrent sockets do not spin while SQLite's worker threads run.
"""

import asyncio
import json
from contextlib import asynccontextmanager
from urllib.parse import urlsplit


class ASGISocket:
    def __init__(self, app, address):
        url = urlsplit(address)
        self.app = app
        self.scope = {
            "type": "websocket",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "scheme": "ws",
            "path": url.path,
            "raw_path": url.path.encode(),
            "root_path": "",
            "query_string": url.query.encode(),
            "headers": [],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
            "subprotocols": [],
            "state": {},
        }
        self.incoming = asyncio.Queue()
        self.outgoing = asyncio.Queue()

    async def receive_json(self):
        message = await asyncio.wait_for(self.outgoing.get(), 10)
        assert message["type"] == "websocket.send", message
        return json.loads(message["text"])

    async def send_json(self, data):
        await self.incoming.put({"type": "websocket.receive", "text": json.dumps(data)})


@asynccontextmanager
async def open_socket(app, address):
    socket = ASGISocket(app, address)
    task = asyncio.create_task(
        app(socket.scope, socket.incoming.get, socket.outgoing.put)
    )
    try:
        await socket.incoming.put({"type": "websocket.connect"})
        accepted = await asyncio.wait_for(socket.outgoing.get(), 10)
        assert accepted["type"] == "websocket.accept", accepted
        yield socket
    finally:
        await socket.incoming.put({"type": "websocket.disconnect", "code": 1000})
        try:
            await asyncio.wait_for(task, 10)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
