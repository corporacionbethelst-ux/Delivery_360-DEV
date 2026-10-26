"""Recovery SMTP contract and mounted routes, without external messages."""

import asyncio
from datetime import timedelta
from email.message import EmailMessage
from html import escape
from urllib.parse import parse_qs, urlsplit
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import update

from tests.test_tracking_permissions import sockets  # noqa: F401
from app.core import email_service as mail
from app.core.config import settings
from app.core.security import verify_password
from app.models.user import User, utc_now_naive
from app.services.password_reset import reset_token_digest


@pytest.fixture
def smtp(monkeypatch):
    for key, value in {
        "EMAILS_ENABLED": True,
        "SMTP_HOST": "smtp.example.test",
        "SMTP_PORT": 587,
        "SMTP_TLS": True,
        "SMTP_SSL": False,
        "SMTP_TIMEOUT_SECONDS": 1.0,
        "SMTP_USER": "test-login",
        "SMTP_PASSWORD": "test-only-password",
        "EMAIL_FROM": "noreply@example.com",
        "APP_NAME": "Delivery Test",
        "FRONTEND_URL": "https://app.example.com/portal/",
        "ENVIRONMENT": "testing",
    }.items():
        monkeypatch.setattr(settings, key, value)
    send = AsyncMock(return_value=({}, "accepted"))
    client = SimpleNamespace(
        connect=AsyncMock(), send_message=send, quit=AsyncMock(), close=MagicMock()
    )
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(mail.aiosmtplib, "SMTP", factory)
    send.smtp_client = client
    send.smtp_factory = factory
    return send


@pytest.mark.asyncio
@pytest.mark.parametrize("implicit", [False, True])
async def test_authenticated_encrypted_message_uses_pinned_client(
    smtp, monkeypatch, implicit
):
    monkeypatch.setattr(settings, "SMTP_TLS", not implicit)
    monkeypatch.setattr(settings, "SMTP_SSL", implicit)
    monkeypatch.setattr(settings, "SMTP_PORT", 465 if implicit else 587)
    link = mail.password_reset_link("opaque-token")
    assert await mail.send_reset_email(" Recipient@EXAMPLE.COM ", link)
    args, options = smtp.await_args
    message = args[0]
    assert isinstance(message, EmailMessage)
    assert message["To"] == "Recipient@example.com"
    assert message["From"] == "Delivery Test <noreply@example.com>"
    assert options == {
        "sender": "noreply@example.com",
        "recipients": ["Recipient@example.com"],
    }
    assert smtp.smtp_factory.call_args.kwargs == {
        "hostname": "smtp.example.test",
        "port": 465 if implicit else 587,
        "username": "test-login",
        "password": "test-only-password",
        "start_tls": not implicit,
        "use_tls": implicit,
        "validate_certs": True,
        "timeout": 1.0,
        "local_hostname": "delivery360",
    }
    smtp.smtp_client.close.assert_called_once()
    assert link in message.get_body(preferencelist=("plain",)).get_content()
    assert (
        escape(link, quote=True)
        in message.get_body(preferencelist=("html",)).get_content()
    )
    assert "1 hora" in message.get_body(preferencelist=("plain",)).get_content()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"EMAILS_ENABLED": False},
        {"SMTP_USER": None},
        {"SMTP_PASSWORD": None},
        {"SMTP_HOST": ""},
        {"SMTP_TLS": False, "SMTP_SSL": False},
        {"SMTP_SSL": True},
        {"SMTP_PORT": 0},
        {"SMTP_TIMEOUT_SECONDS": float("nan")},
        {"EMAIL_FROM": "bad-address"},
    ],
)
async def test_disabled_or_unsafe_configuration_never_connects(
    smtp, monkeypatch, changes
):
    for key, value in changes.items():
        monkeypatch.setattr(settings, key, value)
    assert not await mail.send_reset_email(
        "recipient@example.com", "https://example.com/reset"
    )
    smtp.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "recipient",
    [
        "invalid",
        "a@example.com\r\nBcc: thief@example.com",
        "a@example.com,b@example.com",
    ],
)
async def test_only_one_valid_recipient_is_allowed(smtp, recipient):
    assert not await mail.send_reset_email(recipient, "https://example.com/reset")
    smtp.assert_not_awaited()


@pytest.mark.asyncio
async def test_html_link_is_escaped_without_changing_plain_text(smtp):
    link = 'https://example.com/reset?token=a&extra="<script>"'
    assert await mail.send_reset_email("recipient@example.com", link)
    message = smtp.await_args.args[0]
    assert "<script>" not in message.get_body(preferencelist=("html",)).get_content()
    assert link in message.get_body(preferencelist=("plain",)).get_content()


@pytest.mark.asyncio
async def test_provider_failure_logs_no_identity_or_diagnostics(smtp, caplog):
    secret = "private@example.com secret-token test-only-password"
    smtp.side_effect = RuntimeError(secret)
    assert not await mail.send_reset_email(
        "private@example.com", "https://example.com/secret-token"
    )
    assert caplog.records
    for value in secret.split():
        assert value not in caplog.text


@pytest.mark.asyncio
async def test_total_timeout_cancels_the_provider(smtp, monkeypatch):
    cancelled = asyncio.Event()

    async def blocked(*args, **kwargs):
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    smtp.side_effect = blocked
    monkeypatch.setattr(settings, "SMTP_TIMEOUT_SECONDS", 0.02)
    assert not await mail.send_reset_email(
        "recipient@example.com", "https://example.com/reset"
    )
    assert cancelled.is_set()
    smtp.smtp_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_recipient_refusal_is_not_reported_as_acceptance(smtp):
    smtp.return_value = ({"recipient@example.com": object()}, "refused")
    assert not await mail.send_reset_email(
        "recipient@example.com", "https://example.com/reset"
    )


@pytest.mark.parametrize(
    "url",
    [
        "/relative",
        "javascript:alert(1)",
        "https://user:pass@example.com",
        "https://example.com/?next=evil",
        "https://example.com/#fragment",
        "https://bad host",
        "https://example.com:invalid",
        "https://example.com:0",
    ],
)
def test_recovery_link_rejects_unsafe_frontend_configuration(smtp, monkeypatch, url):
    monkeypatch.setattr(settings, "FRONTEND_URL", url)
    with pytest.raises(ValueError):
        mail.password_reset_link("opaque")


def test_production_link_requires_https_and_encodes_token(smtp, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    assert (
        mail.password_reset_link("a&b")
        == "https://app.example.com/portal/reset-password?token=a%26b"
    )
    monkeypatch.setattr(settings, "FRONTEND_URL", "http://example.com")
    with pytest.raises(ValueError):
        mail.password_reset_link("opaque")


@pytest.mark.asyncio
async def test_mounted_recovery_persists_before_smtp_and_changes_password(
    sockets, smtp
):
    client, sessions, ids, _ = sockets
    observed = []

    async def accepted(message, **kwargs):
        plain = message.get_body(preferencelist=("plain",)).get_content()
        link = next(line for line in plain.splitlines() if line.startswith("https://"))
        token = parse_qs(urlsplit(link).query)["token"][0]
        async with sessions() as db:
            user = await db.get(User, ids["manager"])
            observed.append((user.reset_token, token, user.reset_token_expires))
        return {}, "accepted"

    smtp.side_effect = accepted
    response = client.post(
        "/api/v1/auth/forgot-password", json={"email": " MANAGER@EXAMPLE.COM "}
    )
    assert response.status_code == 200
    assert "token" not in response.text
    # Assert outside the provider callback: the service intentionally catches
    # provider exceptions, including assertion errors raised by a test double.
    assert len(observed) == 1
    persisted, mailed, expiry = observed[0]
    assert persisted == reset_token_digest(mailed)
    assert persisted != mailed
    assert (
        utc_now_naive() + timedelta(minutes=59)
        < expiry
        <= utc_now_naive() + timedelta(hours=1)
    )
    message = smtp.await_args.args[0]
    link = next(
        line
        for line in message.get_body(preferencelist=("plain",))
        .get_content()
        .splitlines()
        if line.startswith("https://")
    )
    token = parse_qs(urlsplit(link).query)["token"][0]
    changed = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "NewPassword123!"},
    )
    assert changed.status_code == 200
    async with sessions() as db:
        user = await db.get(User, ids["manager"])
        assert verify_password("NewPassword123!", user.hashed_password)
        assert user.reset_token is None and user.reset_token_expires is None
    assert (
        client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "new_password": "AnotherPassword123!"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            data={"username": "manager@example.com", "password": "NewPassword123!"},
        ).status_code
        == 200
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    ["unknown", "inactive", "ambiguous", "disabled", "unconfigured", "bad_frontend"],
)
async def test_no_delivery_or_token_mutation_for_unavailable_requests(
    sockets, smtp, monkeypatch, mode
):
    client, sessions, ids, _ = sockets
    address = "manager@example.com"
    async with sessions() as db:
        user = await db.get(User, ids["manager"])
        user.reset_token = "previous-token"
        user.reset_token_expires = utc_now_naive() + timedelta(minutes=10)
        if mode == "unknown":
            address = "nobody@example.com"
        elif mode == "inactive":
            user.is_active = False
        elif mode == "ambiguous":
            await db.execute(
                update(User)
                .where(User.id == ids["operator"])
                .values(email=" MANAGER@EXAMPLE.COM ")
            )
        await db.commit()
    if mode == "disabled":
        monkeypatch.setattr(settings, "EMAILS_ENABLED", False)
    if mode == "unconfigured":
        monkeypatch.setattr(settings, "SMTP_PASSWORD", None)
    if mode == "bad_frontend":
        monkeypatch.setattr(settings, "FRONTEND_URL", "/relative")
    response = client.post("/api/v1/auth/forgot-password", json={"email": address})
    assert response.status_code == 200
    assert response.json() == {
        "message": "Si el correo está registrado y activo, recibirás un enlace de recuperación."
    }
    smtp.assert_not_awaited()
    async with sessions() as db:
        assert (await db.get(User, ids["manager"])).reset_token == "previous-token"


@pytest.mark.asyncio
async def test_public_provider_failure_stays_generic_and_sanitized(
    sockets, smtp, caplog
):
    client, sessions, ids, _ = sockets
    smtp.side_effect = RuntimeError("private-provider-diagnostic manager@example.com")
    response = client.post(
        "/api/v1/auth/forgot-password", json={"email": "manager@example.com"}
    )
    assert response.status_code == 200
    assert "manager@example.com" not in response.text + caplog.text
    assert "private-provider-diagnostic" not in caplog.text
    async with sessions() as db:
        token = (await db.get(User, ids["manager"])).reset_token
        assert token and token not in response.text + caplog.text


@pytest.mark.asyncio
async def test_caller_cancellation_propagates_and_closes_transport(smtp):
    entered = asyncio.Event()

    async def blocked(*args, **kwargs):
        entered.set()
        await asyncio.Future()

    smtp.side_effect = blocked
    task = asyncio.create_task(
        mail.send_reset_email("recipient@example.com", "https://example.com/reset")
    )
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    smtp.smtp_client.close.assert_called_once()
