"""Configuration presence is neither provider authentication nor delivery."""

from pathlib import Path
from unittest.mock import Mock, AsyncMock
import json

import pytest
from sqlalchemy import select, func, update

from tests.test_delivery_financial_postgresql import payment_db  # noqa: F401
from tests.test_terminal_external_postgresql import headers
from app.core.config import settings
from app.core.email_service import smtp_email_is_configured
from app.models.financial import Financial
from app.models.notification import NotificationLog
from app.models.user import User, UserRole
from app.schemas.notification_diagnostics import NotificationProviderDiagnostics
from app.services import notification_diagnostics as diagnostics
from app.services.omnichannel_service import OmnichannelNotificationService as Service


@pytest.fixture
def configured(monkeypatch, tmp_path):
    key = tmp_path / "private-fcm-reference.json"
    key.write_text("PRIVATE_FILE_CONTENT_MUST_NOT_BE_READ")
    values = {
        "NOTIFICATIONS_ENABLED": True,
        "EMAILS_ENABLED": True,
        "SMTP_HOST": "smtp.private.example.com",
        "SMTP_PORT": 587,
        "SMTP_TLS": True,
        "SMTP_SSL": False,
        "SMTP_TIMEOUT_SECONDS": 10.0,
        "SMTP_USER": "PRIVATE_SMTP_USERNAME",
        "SMTP_PASSWORD": "PRIVATE_SMTP_PASSWORD",
        "EMAIL_FROM": "private-sender@example.com",
        "NOTIFICATION_EMAIL_FROM": None,
        "TWILIO_ACCOUNT_SID": "AC" + "1" * 32,
        "TWILIO_AUTH_TOKEN": "PRIVATE_TWILIO_TOKEN",
        "TWILIO_FROM_NUMBER": "+15555550123",
        "FCM_PROJECT_ID": "private-project-127",
        "FCM_CREDENTIALS_JSON_PATH": str(key),
        "NOTIFICATION_PROVIDER_TIMEOUT_SECONDS": 10.0,
    }
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(diagnostics, "find_spec", lambda name: object())
    return values


def provider(channel):
    return next(
        row for row in diagnostics.diagnostics().providers if row.channel == channel
    )


def checks(channel):
    return {check.code: check.state for check in provider(channel).checks}


def test_local_report_has_no_values_and_never_claims_external_delivery(configured):
    report = diagnostics.diagnostics()
    assert report.scope == "local_only" and report.external_delivery_verified is False
    assert len(report.providers) == 3
    assert all(row.state == "locally_configured" for row in report.providers)
    wire = report.model_dump_json()
    for name, value in configured.items():
        if isinstance(value, str):
            assert value not in wire, name
    assert "PRIVATE_FILE_CONTENT" not in wire


@pytest.mark.parametrize(
    "field,channel,code,value,expected",
    [
        ("SMTP_HOST", "EMAIL", "host", "", "missing"),
        ("SMTP_HOST", "EMAIL", "host", "smtp. host", "invalid"),
        ("SMTP_PORT", "EMAIL", "port", 0, "invalid"),
        ("SMTP_PORT", "EMAIL", "port", 65536, "invalid"),
        ("SMTP_USER", "EMAIL", "authentication", None, "missing"),
        ("SMTP_PASSWORD", "EMAIL", "authentication", "", "missing"),
        ("EMAIL_FROM", "EMAIL", "sender", "not-an-email", "invalid"),
        ("EMAIL_FROM", "EMAIL", "sender", "", "missing"),
        ("SMTP_TIMEOUT_SECONDS", "EMAIL", "timeout", 0.0, "invalid"),
        ("SMTP_TIMEOUT_SECONDS", "EMAIL", "timeout", float("nan"), "invalid"),
        ("SMTP_TIMEOUT_SECONDS", "EMAIL", "timeout", float("inf"), "invalid"),
        ("TWILIO_ACCOUNT_SID", "SMS", "account_sid", None, "missing"),
        ("TWILIO_ACCOUNT_SID", "SMS", "account_sid", "private-bad-sid", "invalid"),
        ("TWILIO_AUTH_TOKEN", "SMS", "auth_token", None, "missing"),
        ("TWILIO_FROM_NUMBER", "SMS", "sender", "04141234567", "invalid"),
        ("TWILIO_FROM_NUMBER", "SMS", "sender", None, "missing"),
        ("NOTIFICATION_PROVIDER_TIMEOUT_SECONDS", "SMS", "timeout", 0.5, "invalid"),
        ("NOTIFICATION_PROVIDER_TIMEOUT_SECONDS", "PUSH", "timeout", 61.0, "invalid"),
        ("FCM_CREDENTIALS_JSON_PATH", "PUSH", "credentials_reference", None, "missing"),
        (
            "FCM_CREDENTIALS_JSON_PATH",
            "PUSH",
            "credentials_file",
            "/missing/private-file.json",
            "invalid",
        ),
    ],
)
def test_each_invalid_or_missing_setting_is_reported_without_echo(
    configured, monkeypatch, field, channel, code, value, expected
):
    monkeypatch.setattr(settings, field, value)
    report = provider(channel)
    assert report.state == "incomplete"
    assert checks(channel)[code] == expected
    if isinstance(value, str) and len(value) > 3:
        assert value not in report.model_dump_json()


@pytest.mark.parametrize(
    "starttls,implicit,expected",
    [
        (True, False, "ok"),
        (False, True, "ok"),
        (False, False, "invalid"),
        (True, True, "invalid"),
    ],
)
def test_tls_policy_agrees_with_shared_smtp_transport(
    configured, monkeypatch, starttls, implicit, expected
):
    monkeypatch.setattr(settings, "SMTP_TLS", starttls)
    monkeypatch.setattr(settings, "SMTP_SSL", implicit)
    assert checks("EMAIL")["tls"] == expected
    assert smtp_email_is_configured(settings.notification_email_from_computed) == (
        expected == "ok"
    )


def test_pause_is_distinct_from_configuration_and_mail_has_its_own_gate(
    configured, monkeypatch
):
    monkeypatch.setattr(settings, "EMAILS_ENABLED", False)
    assert (
        provider("EMAIL").state == "paused"
        and checks("EMAIL")["mail_enabled"] == "disabled"
    )
    assert provider("SMS").state == "locally_configured"
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", False)
    assert all(row.state == "paused" for row in diagnostics.diagnostics().providers)


def test_notification_sender_override_matches_transport_fallback(
    configured, monkeypatch
):
    monkeypatch.setattr(settings, "EMAIL_FROM", "invalid-default")
    monkeypatch.setattr(
        settings, "NOTIFICATION_EMAIL_FROM", "private-override@example.com"
    )
    assert checks("EMAIL")["sender"] == "ok" and smtp_email_is_configured(
        settings.notification_email_from_computed
    )
    monkeypatch.setattr(settings, "NOTIFICATION_EMAIL_FROM", None)
    assert checks("EMAIL")["sender"] == "invalid"


@pytest.mark.parametrize(
    "channel,package", [("SMS", "twilio"), ("PUSH", "firebase_admin")]
)
def test_missing_optional_sdk_is_not_a_ready_provider(
    configured, monkeypatch, channel, package
):
    monkeypatch.setattr(
        diagnostics, "find_spec", lambda name: None if name == package else object()
    )
    assert (
        provider(channel).state == "incomplete" and checks(channel)["sdk"] == "missing"
    )


def test_finder_and_file_errors_do_not_leak_exception_text(
    configured, monkeypatch, caplog
):
    def broken(*args):
        raise RuntimeError("PRIVATE_EXCEPTION_DETAIL")

    monkeypatch.setattr(diagnostics, "find_spec", broken)
    report = diagnostics.diagnostics()
    assert provider("SMS").state == "incomplete"
    assert "PRIVATE_EXCEPTION_DETAIL" not in report.model_dump_json() + caplog.text

    def inaccessible(*args, **kwargs):
        raise PermissionError("PRIVATE_PATH_DETAIL")

    monkeypatch.setattr(Path, "stat", inaccessible)
    assert checks("PUSH")["credentials_file"] == "invalid"
    assert (
        "PRIVATE_PATH_DETAIL"
        not in diagnostics.diagnostics().model_dump_json() + caplog.text
    )


@pytest.mark.parametrize("kind", ["directory", "empty", "unreadable"])
def test_push_reference_only_checks_local_metadata(
    configured, monkeypatch, tmp_path, kind
):
    key = Path(configured["FCM_CREDENTIALS_JSON_PATH"])
    if kind == "directory":
        monkeypatch.setattr(settings, "FCM_CREDENTIALS_JSON_PATH", str(tmp_path))
    if kind == "empty":
        key.write_text("")
    if kind == "unreadable":
        monkeypatch.setattr(diagnostics.os, "access", lambda *args: False)
    assert checks("PUSH")["credentials_file"] == "invalid"


def test_snapshot_never_opens_credentials_initializes_sdk_or_uses_network(
    configured, monkeypatch
):
    import socket
    from app.services import notification_providers
    from app.core import email_service

    def forbidden(*args, **kwargs):
        raise AssertionError("Diagnostic attempted external or secret I/O")

    for name in ("_fcm_app", "_sms_sync", "_push_sync"):
        monkeypatch.setattr(notification_providers, name, forbidden)
    monkeypatch.setattr(email_service.aiosmtplib, "SMTP", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    assert all(
        row.state == "locally_configured" for row in diagnostics.diagnostics().providers
    )


def test_response_models_reject_accidental_private_fields(configured):
    data = diagnostics.diagnostics().model_dump()
    data["smtp_password"] = "PRIVATE_PASSWORD"
    with pytest.raises(ValueError):
        NotificationProviderDiagnostics.model_validate(data)
    del data["smtp_password"]
    data["providers"][0]["host"] = "PRIVATE_HOST"
    with pytest.raises(ValueError):
        NotificationProviderDiagnostics.model_validate(data)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", list(UserRole))
async def test_http_diagnostics_require_management_and_do_not_cache_or_write(
    payment_db, configured, monkeypatch, role
):
    client, sessions, ids = payment_db
    for name in ("dispatch_email", "dispatch_sms", "dispatch_push"):
        monkeypatch.setattr(
            Service,
            name,
            AsyncMock(side_effect=AssertionError("No dispatch from diagnostics")),
        )
    async with sessions() as db:
        await db.execute(update(User).where(User.id == ids["staff"]).values(role=role))
        await db.commit()
        before = (
            await db.scalar(select(func.count()).select_from(Financial)),
            await db.scalar(select(func.count()).select_from(NotificationLog)),
        )
    response = client.get(
        "/api/v1/notifications/providers/diagnostics", headers=headers(ids)
    )
    allowed = role in (UserRole.SUPERADMIN, UserRole.GERENTE)
    assert response.status_code == (200 if allowed else 403), response.text
    if allowed:
        assert response.headers["cache-control"] == "no-store"
        assert "Authorization" in response.headers["vary"]
        assert response.json()["external_delivery_verified"] is False
        for value in configured.values():
            if isinstance(value, str):
                assert value not in response.text
    async with sessions() as db:
        assert (
            await db.scalar(select(func.count()).select_from(Financial)),
            await db.scalar(select(func.count()).select_from(NotificationLog)),
        ) == before
    for name in ("dispatch_email", "dispatch_sms", "dispatch_push"):
        getattr(Service, name).assert_not_awaited()


@pytest.mark.asyncio
async def test_http_authentication_and_refresh_are_always_executed(
    payment_db, configured, monkeypatch
):
    client, _, ids = payment_db
    assert client.get("/api/v1/notifications/providers/diagnostics").status_code == 401
    first = client.get(
        "/api/v1/notifications/providers/diagnostics", headers=headers(ids)
    )
    assert first.status_code == 200
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", False)
    second = client.get(
        "/api/v1/notifications/providers/diagnostics", headers=headers(ids)
    )
    assert second.status_code == 200 and all(
        p["state"] == "paused" for p in second.json()["providers"]
    )
    assert second.json()["notifications_enabled"] is False
