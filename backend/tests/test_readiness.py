"""Readiness must fail closed, stay bounded and never disclose connection errors."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest
from fastapi import FastAPI
from app.monitoring import health_check as health


@pytest.mark.parametrize(
    "database,redis", [(True, True), (True, False), (False, True), (False, False)]
)
async def test_http_readiness_reports_both_dependencies(monkeypatch, database, redis):
    monkeypatch.setattr(health, "_database_ready", AsyncMock(return_value=database))
    monkeypatch.setattr(health, "_redis_ready", AsyncMock(return_value=redis))
    app = FastAPI()
    app.include_router(health.router, prefix="/health")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://local.test"
    ) as client:
        response = await client.get("/health/ready")
    assert response.status_code == (200 if database and redis else 503)
    assert response.json() == {
        "status": "ready" if database and redis else "not_ready",
        "checks": {"database": database, "redis": redis},
    }
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", ["/live", "/check"])
async def test_liveness_does_not_depend_on_database_or_redis(monkeypatch, path):
    db, redis = AsyncMock(side_effect=AssertionError("must not probe")), AsyncMock(
        side_effect=AssertionError("must not probe")
    )
    monkeypatch.setattr(health, "_database_ready", db)
    monkeypatch.setattr(health, "_redis_ready", redis)
    app = FastAPI()
    app.include_router(health.router, prefix="/health")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://local.test"
    ) as client:
        assert (await client.get("/health" + path)).status_code == 200
    db.assert_not_called()
    redis.assert_not_called()


@pytest.mark.parametrize("failure", [False, True])
async def test_async_database_probe_releases_its_connection(monkeypatch, failure):
    executed, closed = [], []

    async def execute(query):
        executed.append(str(query))
        if failure:
            raise RuntimeError("postgresql://sensitive-connection")

    @asynccontextmanager
    async def connect():
        try:
            yield SimpleNamespace(execute=execute)
        finally:
            closed.append(True)

    monkeypatch.setattr(health, "engine", SimpleNamespace(connect=connect))
    assert await health._database_ready() is not failure
    assert executed == ["SELECT 1"] and closed == [True]


async def test_blocked_database_probe_times_out_and_closes(monkeypatch):
    closed = []

    @asynccontextmanager
    async def connect():
        async def execute(_query):
            await asyncio.Event().wait()

        try:
            yield SimpleNamespace(execute=execute)
        finally:
            closed.append(True)

    monkeypatch.setattr(health, "engine", SimpleNamespace(connect=connect))
    monkeypatch.setattr(health, "HEALTH_TIMEOUT_SECONDS", 0.01)
    assert await asyncio.wait_for(health._database_ready(), timeout=0.5) is False
    assert closed == [True]


@pytest.mark.parametrize("failure", [False, True])
async def test_redis_probe_closes_and_sanitizes_errors(monkeypatch, failure):
    closed, options = [], []

    @asynccontextmanager
    async def client():
        async def ping():
            if failure:
                raise RuntimeError("redis://sensitive-connection")
            return True

        try:
            yield SimpleNamespace(ping=ping)
        finally:
            closed.append(True)

    def from_url(_url, **kwargs):
        options.append(kwargs)
        return client()

    monkeypatch.setattr(health, "Redis", SimpleNamespace(from_url=from_url))
    assert await health._redis_ready() is not failure
    assert closed == [True]
    assert options[0]["socket_connect_timeout"] == health.HEALTH_TIMEOUT_SECONDS


async def test_redis_cancellation_is_not_hidden(monkeypatch):
    @asynccontextmanager
    async def client():
        yield SimpleNamespace(ping=AsyncMock(side_effect=asyncio.CancelledError()))

    monkeypatch.setattr(
        health, "Redis", SimpleNamespace(from_url=lambda *_args, **_kwargs: client())
    )
    with pytest.raises(asyncio.CancelledError):
        await health._redis_ready()
