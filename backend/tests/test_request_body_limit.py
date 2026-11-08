"""ASGI framing, raw size, deadlines and cleanup before any body parser executes."""

import asyncio
import json
import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from app.middleware import request_body_limit as module
from app.middleware.document_upload_limit import DocumentUploadLimitMiddleware


async def invoke(
    *,
    path="/api/v1/orders",
    method="POST",
    headers=(),
    chunks=None,
    stalled=False,
    downstream_error=False,
):
    sent, parsed = [], []
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "scheme": "http",
        "path": path,
        "method": method,
        "headers": list(headers),
        "query_string": b"",
        "server": ("local", 80),
        "client": ("local", 1),
    }
    pending = list(
        chunks
        if chunks is not None
        else [{"type": "http.request", "body": b"", "more_body": False}]
    )

    async def receive():
        if stalled:
            await asyncio.Event().wait()
        return pending.pop(0) if pending else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    async def app(scope, receive, send):
        if downstream_error:
            raise RuntimeError("downstream failure")
        result = b""
        while True:
            message = await receive()
            result += message.get("body", b"")
            if not message.get("more_body", False):
                break
        parsed.append(result)
        await JSONResponse({"size": len(result)})(scope, receive, send)

    await module.RequestBodyLimitMiddleware(app)(scope, receive, send)
    return sent, parsed


@pytest.fixture
def small_policy(monkeypatch):
    monkeypatch.setattr(module.RequestBodyLimitMiddleware, "DEFAULT_LIMIT", 8)
    monkeypatch.setattr(module.RequestBodyLimitMiddleware, "LOGIN_LIMIT", 4)
    monkeypatch.setattr(module.RequestBodyLimitMiddleware, "MEMORY_SPOOL_BYTES", 4)


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize("declared", [None, b"2"])
async def test_chunked_writes_are_rejected_before_parsing(
    small_policy, method, declared
):
    headers = [] if declared is None else [(b"content-length", declared)]
    sent, parsed = await invoke(
        method=method,
        headers=headers,
        chunks=[
            {"type": "http.request", "body": b"12345", "more_body": True},
            {"type": "http.request", "body": b"6789", "more_body": False},
        ],
    )
    assert sent[0]["status"] == 413 and not parsed


@pytest.mark.parametrize(
    "lengths", [[b"-1"], [b"bad"], [b""], [b"1", b"1"], [b"9" * 21]]
)
async def test_invalid_framing_is_rejected_without_parser(small_policy, lengths):
    sent, parsed = await invoke(headers=[(b"content-length", v) for v in lengths])
    assert sent[0]["status"] == 400 and not parsed


async def test_transfer_encoding_with_content_length_is_not_accepted(small_policy):
    sent, parsed = await invoke(
        headers=[(b"transfer-encoding", b"chunked"), (b"content-length", b"0")]
    )
    assert sent[0]["status"] == 400 and not parsed


@pytest.mark.parametrize("path", ["/api/v1/auth/login", "/api/v1/auth/login/"])
async def test_login_form_has_a_separate_smaller_limit(small_policy, path):
    sent, parsed = await invoke(path=path, headers=[(b"content-length", b"5")])
    assert sent[0]["status"] == 413 and not parsed


async def test_declared_length_must_match_bytes_even_below_limit(small_policy):
    sent, parsed = await invoke(
        headers=[(b"content-length", b"3")],
        chunks=[{"type": "http.request", "body": b"12", "more_body": False}],
    )
    assert sent[0]["status"] == 400 and not parsed


@pytest.mark.parametrize("payload", [b"", b"12345678"])
async def test_empty_and_exact_boundary_bodies_are_replayed_without_changes(
    small_policy, payload
):
    sent, parsed = await invoke(
        headers=[(b"content-length", str(len(payload)).encode())],
        chunks=[{"type": "http.request", "body": payload, "more_body": False}],
    )
    assert sent[0]["status"] == 200 and parsed == [payload]


@pytest.mark.parametrize("failure", ["timeout", "disconnect", "oversize", "downstream"])
async def test_spool_is_closed_on_every_exit(small_policy, monkeypatch, failure):
    created = []
    factory = module.tempfile.SpooledTemporaryFile

    def tracked(*args, **kwargs):
        value = factory(*args, **kwargs)
        created.append(value)
        return value

    monkeypatch.setattr(module.tempfile, "SpooledTemporaryFile", tracked)
    monkeypatch.setattr(module.RequestBodyLimitMiddleware, "READ_TIMEOUT_SECONDS", 0.02)
    if failure == "downstream":
        with pytest.raises(RuntimeError, match="downstream failure"):
            await invoke(downstream_error=True)
    elif failure == "timeout":
        sent, parsed = await asyncio.wait_for(invoke(stalled=True), timeout=1)
        assert sent[0]["status"] == 408 and not parsed
    elif failure == "disconnect":
        sent, parsed = await invoke(chunks=[{"type": "http.disconnect"}])
        assert not sent and not parsed
    else:
        sent, parsed = await invoke(
            chunks=[{"type": "http.request", "body": b"123456789", "more_body": False}]
        )
        assert sent[0]["status"] == 413 and not parsed
    assert len(created) == 1 and created[0].closed


async def test_cancellation_propagates_after_closing_spool(small_policy, monkeypatch):
    created = []
    factory = module.tempfile.SpooledTemporaryFile

    def tracked(*args, **kwargs):
        value = factory(*args, **kwargs)
        created.append(value)
        return value

    monkeypatch.setattr(module.tempfile, "SpooledTemporaryFile", tracked)
    task = asyncio.create_task(invoke(stalled=True))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert created[0].closed


@pytest.mark.parametrize(
    "scope",
    [
        {"type": "websocket", "path": "/api/v1/tracking/ws/test"},
        {"type": "lifespan"},
        {"type": "http", "method": "GET", "path": "/health/live"},
    ],
)
async def test_body_free_protocols_and_reads_are_passed_through(scope):
    seen = []

    async def app(scope, receive, send):
        seen.append(scope)

    async def unused():
        raise AssertionError("must not receive")

    await module.RequestBodyLimitMiddleware(app)(scope, unused, unused)
    assert seen == [scope]


async def test_upload_uses_one_document_spool_and_preserves_its_higher_limit(
    small_policy, monkeypatch
):
    created = []
    factory = module.tempfile.SpooledTemporaryFile

    def tracked(*args, **kwargs):
        value = factory(*args, **kwargs)
        created.append(value)
        return value

    monkeypatch.setattr(module.tempfile, "SpooledTemporaryFile", tracked)
    app = FastAPI()
    app.add_middleware(module.RequestBodyLimitMiddleware)
    app.add_middleware(DocumentUploadLimitMiddleware)

    @app.post("/api/v1/riders/me/documents/upload")
    async def upload(request: Request):
        return {"body": (await request.body()).decode()}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://local"
    ) as client:
        response = await client.post(
            "/api/v1/riders/me/documents/upload", content=b"above-general-limit"
        )
    assert response.status_code == 200 and len(created) == 1 and created[0].closed


async def test_json_and_oauth_forms_still_parse_and_cors_covers_rejections(
    small_policy,
):
    app = FastAPI()
    app.add_middleware(module.RequestBodyLimitMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=["https://local.test"])

    @app.post("/json")
    async def body(request: Request):
        return await request.json()

    @app.post("/form")
    async def form(request: Request):
        return dict(await request.form())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://local"
    ) as client:
        assert (await client.post("/json", content=b'{"x":1}')).json() == {"x": 1}
        assert (await client.post("/form", data={"a": "b"})).json() == {"a": "b"}
        rejected = await client.post(
            "/json", content=b"x" * 9, headers={"origin": "https://local.test"}
        )
    assert (
        rejected.status_code == 413
        and rejected.headers["access-control-allow-origin"] == "https://local.test"
    )


def test_application_enforces_both_body_limits_inside_cors():
    from app.main import app

    classes = [item.cls.__name__ for item in app.user_middleware]
    assert (
        classes.index("CORSMiddleware")
        < classes.index("DocumentUploadLimitMiddleware")
        < classes.index("RequestBodyLimitMiddleware")
    )
