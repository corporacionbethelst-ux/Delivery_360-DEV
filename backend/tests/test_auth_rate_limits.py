"""Real ASGI middleware budgets, deterministic windows and mounted auth routes."""

from types import SimpleNamespace
import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from tests.test_tracking_permissions import sockets  # noqa: F401
from app.core import rate_limiter as core
from app.core.rate_limiter import RateLimiter
from app.core.security import create_access_token
from app.middleware import rate_limit_middleware as middleware
from app.middleware.rate_limit_middleware import RateLimitMiddleware


@pytest.fixture
async def budget(monkeypatch):
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(core, "time", SimpleNamespace(time=lambda: clock.now))
    limiter = RateLimiter()
    monkeypatch.setattr(middleware, "rate_limiter", limiter)
    calls = []

    async def endpoint(request):
        calls.append(request.url.path)
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/{path:path}", endpoint, methods=["GET", "POST"])])
    app.add_middleware(RateLimitMiddleware)
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("192.0.2.1", 123)),
        base_url="http://test",
    ) as client:
        yield client, clock, calls, app, limiter


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,limit,window",
    [
        ("login", 5, 60),
        ("forgot-password", 2, 300),
        ("reset-password", 2, 300),
        ("register-rider", 3, 300),
    ],
)
async def test_auth_blocks_at_exact_threshold_without_dispatch(
    budget, path, limit, window
):
    client, clock, calls, _, _ = budget
    url = "/api/v1/auth/" + path
    for remaining in range(limit - 1, -1, -1):
        response = await client.post(url)
        assert response.status_code == 200
        assert int(response.headers["X-RateLimit-Remaining"]) == remaining
    denied = await client.post(url)
    assert denied.status_code == 429
    assert len(calls) == limit
    assert denied.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert int(denied.headers["Retry-After"]) == window
    assert int(denied.headers["X-RateLimit-Limit"]) == limit
    clock.now += window - 0.1
    assert (await client.post(url)).status_code == 429
    clock.now += 0.1
    assert (await client.post(url)).status_code == 200


@pytest.mark.asyncio
async def test_recovery_and_ordinary_traffic_do_not_consume_login_budget(budget):
    client, _, _, _, _ = budget
    for _ in range(8):
        assert (await client.get("/other")).status_code == 200
    for _ in range(2):
        assert (await client.post("/api/v1/auth/forgot-password")).status_code == 200
        assert (await client.post("/api/v1/auth/reset-password")).status_code == 200
    assert (await client.post("/api/v1/auth/forgot-password")).status_code == 429
    for _ in range(5):
        assert (await client.post("/api/v1/auth/login")).status_code == 200
    assert (await client.post("/api/v1/auth/login")).status_code == 429


@pytest.mark.asyncio
async def test_query_slash_headers_and_jwt_rotation_cannot_reset_recovery_budget(
    budget,
):
    client, _, _, _, _ = budget
    assert (
        await client.post("/api/v1/auth/forgot-password?email=one")
    ).status_code == 200
    headers = {
        "Authorization": "Bearer " + create_access_token("one"),
        "X-Forwarded-For": "203.0.113.1",
    }
    assert (
        await client.post("/api/v1/auth/forgot-password/", headers=headers)
    ).status_code == 200
    for token in [create_access_token("two"), "invalid-token"]:
        response = await client.post(
            "/api/v1/auth/forgot-password?random=2",
            headers={
                "Authorization": "Bearer " + token,
                "X-Forwarded-For": "203.0.113.2",
            },
        )
        assert response.status_code == 429


@pytest.mark.asyncio
async def test_peer_ips_have_independent_budgets(budget):
    client, _, _, app, _ = budget
    for _ in range(2):
        assert (await client.post("/api/v1/auth/reset-password")).status_code == 200
    assert (await client.post("/api/v1/auth/reset-password")).status_code == 429
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("192.0.2.2", 123)),
        base_url="http://test",
    ) as other:
        assert (await other.post("/api/v1/auth/reset-password")).status_code == 200


@pytest.mark.asyncio
async def test_policy_cardinality_is_bounded_and_prefixes_respect_boundaries(budget):
    client, _, _, _, limiter = budget
    for i in range(20):
        assert (await client.get(f"/unknown/{i}")).status_code == 200
    assert len(limiter._local_storage) == 1
    handler = RateLimitMiddleware(None)
    assert handler._get_policy("/health-evil")[0] == "default"
    assert handler._get_policy("/api/v1/auth/login-extra")[0] == "default"
    assert handler._get_policy("/api/v1/orders-extra")[0] == "default"
    assert handler._get_limits_for_path("/api/v1/riders/id/location") == (240, 60)
    assert handler._get_limits_for_path("/api/v1/orders/id") == (30, 60)
    before = len(limiter._local_storage)
    for _ in range(10):
        assert (await client.get("/health")).status_code == 200
    assert len(limiter._local_storage) == before


@pytest.mark.asyncio
async def test_mounted_forgot_password_rejects_third_before_handler(
    sockets, monkeypatch
):
    client, _, _, _ = sockets
    from app.api.v1 import auth

    calls = []

    async def missing(db, email):
        calls.append(email)
        return None

    monkeypatch.setattr(auth, "find_email_account", missing)
    for _ in range(2):
        assert (
            client.post(
                "/api/v1/auth/forgot-password", json={"email": "nobody@example.com"}
            ).status_code
            == 200
        )
    response = client.post(
        "/api/v1/auth/forgot-password", json={"email": "other@example.com"}
    )
    assert response.status_code == 429 and len(calls) == 2
    assert response.headers["Retry-After"]


@pytest.mark.asyncio
async def test_mounted_reset_invalid_inputs_count_without_affecting_login(sockets):
    client, _, _, _ = sockets
    for _ in range(2):
        assert (
            client.post(
                "/api/v1/auth/reset-password",
                json={"token": "bad", "new_password": "NewPassword123!"},
            ).status_code
            == 400
        )
    assert (
        client.post(
            "/api/v1/auth/reset-password",
            json={"token": "bad", "new_password": "NewPassword123!"},
        ).status_code
        == 429
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            data={"username": "missing@example.com", "password": "invalid"},
        ).status_code
        == 400
    )
