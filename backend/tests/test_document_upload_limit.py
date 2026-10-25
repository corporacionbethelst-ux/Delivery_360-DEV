"""ASGI request limits before multipart parsing, not trusting Content-Length."""

import pytest
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from app.middleware import document_upload_limit as module

PATH = "/api/v1/riders/me/documents/upload"


async def invoke(path=PATH, *, headers=None, chunks=None, app=None, method="POST"):
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers or [],
        "server": ("test", 80),
        "client": ("test", 123),
    }
    pending = list(
        chunks
        if chunks is not None
        else [{"type": "http.request", "body": b"", "more_body": False}]
    )
    sent, reads, consumed = [], [], []

    async def receive():
        reads.append(True)
        return pending.pop(0) if pending else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    async def downstream(scope, receive, send):
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body", False):
                break
        consumed.append(body)
        await JSONResponse({"length": len(body)})(scope, receive, send)

    limiter = module.DocumentUploadLimitMiddleware(app or downstream)
    await limiter(scope, receive, send)
    return sent, reads, consumed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        PATH,
        "/api/v1/riders/123/documents/upload",
        "/api/v1/auth/register-rider",
        PATH + "/",
    ],
)
async def test_declared_oversize_rejected_without_receiving_body_or_running_handler(
    path,
):
    sent, reads, consumed = await invoke(
        path, headers=[(b"content-length", b"999999999")]
    )
    assert sent[0]["status"] == 413 and not reads and not consumed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "lengths", [[b"-1"], [b"invalid"], [b""], [b"1", b"2"], [b"9" * 21]]
)
async def test_malformed_or_duplicate_lengths_are_rejected(lengths):
    sent, reads, consumed = await invoke(
        headers=[(b"content-length", value) for value in lengths]
    )
    assert sent[0]["status"] == 400 and not reads and not consumed


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", [None, b"1"])
async def test_actual_chunked_size_is_counted_even_without_or_with_false_length(
    declared,
):
    limit = module.MAX_DOCUMENT_BYTES + 1024 * 1024
    sent, _, consumed = await invoke(
        headers=[] if declared is None else [(b"content-length", declared)],
        chunks=[
            {"type": "http.request", "body": b"x" * (limit // 2), "more_body": True},
            {
                "type": "http.request",
                "body": b"x" * (limit // 2 + 1),
                "more_body": False,
            },
        ],
    )
    assert sent[0]["status"] == 413 and not consumed


@pytest.mark.asyncio
async def test_length_mismatch_is_not_passed_to_parser():
    sent, _, consumed = await invoke(
        headers=[(b"content-length", b"1")],
        chunks=[{"type": "http.request", "body": b"two", "more_body": False}],
    )
    assert sent[0]["status"] == 400 and not consumed


@pytest.mark.asyncio
async def test_spooled_body_is_replayed_exactly_and_closed(monkeypatch):
    factory = module.tempfile.SpooledTemporaryFile
    created = []

    def tracked(*args, **kwargs):
        file = factory(*args, **kwargs)
        created.append(file)
        return file

    monkeypatch.setattr(module.tempfile, "SpooledTemporaryFile", tracked)
    payload = b"a" * (1024 * 1024) + b"final"
    sent, _, consumed = await invoke(
        chunks=[
            {"type": "http.request", "body": payload[:1000], "more_body": True},
            {"type": "http.request", "body": payload[1000:], "more_body": False},
        ]
    )
    assert sent[0]["status"] == 200 and consumed == [payload]
    assert len(created) == 1 and created[0].closed and created[0]._rolled


@pytest.mark.asyncio
async def test_client_disconnect_closes_spool_without_calling_parser(monkeypatch):
    factory = module.tempfile.SpooledTemporaryFile
    created = []

    def tracked(*args, **kwargs):
        file = factory(*args, **kwargs)
        created.append(file)
        return file

    monkeypatch.setattr(module.tempfile, "SpooledTemporaryFile", tracked)
    sent, _, consumed = await invoke(
        chunks=[
            {"type": "http.request", "body": b"partial", "more_body": True},
            {"type": "http.disconnect"},
        ]
    )
    assert not sent and not consumed and created[0].closed


@pytest.mark.asyncio
async def test_unrelated_route_is_not_given_document_request_limit():
    sent, _, consumed = await invoke(
        "/api/v1/orders",
        headers=[(b"content-length", b"999999999")],
        chunks=[{"type": "http.request", "body": b"small", "more_body": False}],
    )
    assert sent[0]["status"] == 200 and consumed == [b"small"]


@pytest.mark.asyncio
async def test_cors_header_is_preserved_on_early_rejection():
    from httpx import ASGITransport, AsyncClient

    async def unused(scope, receive, send):
        raise AssertionError("Parser must not run")

    app = CORSMiddleware(
        module.DocumentUploadLimitMiddleware(unused),
        allow_origins=["https://frontend.example.test"],
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            PATH,
            headers={
                "origin": "https://frontend.example.test",
                "content-length": "999999999",
            },
        )
    assert response.status_code == 413
    assert (
        response.headers["access-control-allow-origin"]
        == "https://frontend.example.test"
    )


def test_application_wraps_limit_with_cors_and_rate_limit():
    from app.main import app

    classes = [item.cls.__name__ for item in app.user_middleware]
    assert classes.index("CORSMiddleware") < classes.index(
        "DocumentUploadLimitMiddleware"
    )
    assert classes.index("RateLimitMiddleware") < classes.index(
        "DocumentUploadLimitMiddleware"
    )


@pytest.mark.asyncio
async def test_real_application_rejects_oversize_before_registration_parser():
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    from app.core.config import settings

    headers = {"content-length": "999999999"}
    if settings.cors_origins:
        headers["origin"] = settings.cors_origins[0]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        response = await client.post("/api/v1/auth/register-rider", headers=headers)
    assert response.status_code == 413
    if settings.cors_origins:
        assert (
            response.headers["access-control-allow-origin"] == settings.cors_origins[0]
        )
