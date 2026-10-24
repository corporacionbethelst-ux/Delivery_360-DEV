"""HTTP cache must not bypass API authorization or reuse private responses."""
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.middleware import cache_middleware as cache


@pytest.fixture
def cache_backend(monkeypatch):
    monkeypatch.setattr(cache.settings, "CACHE_ENABLED", True)
    monkeypatch.setattr(cache.cache_service, "connected", True)
    get = AsyncMock(return_value={"status_code": 200, "body": '{"owner":"someone-else"}', "media_type": "application/json", "headers": {}})
    put = AsyncMock()
    monkeypatch.setattr(cache.cache_service, "get", get)
    monkeypatch.setattr(cache.cache_service, "set", put)
    return get, put


@pytest.mark.parametrize("path", ["/api/v1/orders", "/api/v1/deliveries", "/api/v1/payouts"])
async def test_api_always_executes_authorization_even_when_cache_has_a_hit(cache_backend, path):
    app = FastAPI()
    app.add_middleware(cache.CacheMiddleware)
    @app.get(path)
    async def private(request: Request):
        owner = request.headers.get("authorization")
        if owner is None:
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
        return {"owner": owner}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        a = await client.get(path, headers={"Authorization": "Bearer A"})
        b = await client.get(path, headers={"Authorization": "Bearer B"})
        anonymous = await client.get(path)
    assert a.json() == {"owner": "Bearer A"}
    assert b.json() == {"owner": "Bearer B"}
    assert anonymous.status_code == 401
    get, put = cache_backend
    get.assert_not_awaited()
    put.assert_not_awaited()


@pytest.mark.parametrize("headers", [{"Authorization": "Bearer A"}, {"Cookie": "session=A"}])
async def test_session_requests_bypass_cache_on_other_paths(cache_backend, headers):
    app = FastAPI()
    app.add_middleware(cache.CacheMiddleware)
    @app.get("/private")
    async def private():
        return {"fresh": True}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/private", headers=headers)
    assert response.json() == {"fresh": True}
    cache_backend[0].assert_not_awaited()
    cache_backend[1].assert_not_awaited()


async def test_public_cache_hit_accepts_deserialized_backend_value(cache_backend):
    app = FastAPI()
    app.add_middleware(cache.CacheMiddleware)
    @app.get("/public")
    async def public():
        return {"fresh": True}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/public")
    assert response.status_code == 200
    assert response.headers["X-Cache"] == "HIT"
    assert response.json() == {"owner": "someone-else"}
