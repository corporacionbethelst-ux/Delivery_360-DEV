"""Persisted EMAIL states and real loopback SMTP, without external delivery."""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from tests.test_tracking_permissions import sockets  # noqa: F401
from tests.test_notification_websocket_permissions import inbox  # noqa: F401
from tests.test_password_recovery_email import smtp  # noqa: F401
from tests.test_password_recovery_smtp import local_smtp  # noqa: F401
from app.core.config import settings
from app.models.user import User
from app.models.notification import (
    NotificationLog,
    NotificationChannel,
    OmnichannelStatus,
    utc_now_naive,
)
from app.services.omnichannel_service import OmnichannelNotificationService


@pytest.fixture(autouse=True)
def notification_flags(monkeypatch):
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True)
    monkeypatch.setattr(
        settings, "NOTIFICATION_EMAIL_FROM", "notifications@example.com"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "condition",
    [
        "disabled",
        "missing_creds",
        "missing_recipient",
        "invalid_sender",
        "provider_error",
        "refused",
        "master_disabled",
    ],
)
async def test_unavailable_email_does_not_claim_success(
    inbox, smtp, monkeypatch, condition, caplog
):
    _, sessions, ids, _, _ = inbox
    if condition == "disabled":
        monkeypatch.setattr(settings, "EMAILS_ENABLED", False)
    if condition == "missing_creds":
        monkeypatch.setattr(settings, "SMTP_PASSWORD", None)
    if condition == "invalid_sender":
        monkeypatch.setattr(settings, "NOTIFICATION_EMAIL_FROM", "invalid")
    if condition == "master_disabled":
        monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", False)
    if condition == "provider_error":
        smtp.side_effect = RuntimeError("private-address secret-password private-body")
    if condition == "refused":
        smtp.return_value = ({"private@example.com": object()}, "rejected")
    async with sessions() as db:
        user = await db.get(User, ids["owner"])
        if condition == "missing_recipient":
            user.email = ""
        log = NotificationLog(
            user_id=user.id,
            channel=NotificationChannel.EMAIL,
            title="Notice",
            body="Body",
            status=OmnichannelStatus.PENDIENTE,
            retry_count=0,
        )
        db.add(log)
        await db.commit()
        key = log.id
        await OmnichannelNotificationService(db, redis_client=False)._dispatch_one(
            log, user, SimpleNamespace(code="notice"), "Body"
        )
    async with sessions() as db:
        persisted = await db.get(NotificationLog, key)
        assert persisted.status == OmnichannelStatus.PENDIENTE
        assert persisted.sent_at is None
        assert persisted.retry_count == 1 and persisted.next_retry_at is not None
        assert persisted.error_message == "Provider reportó fallo"
    for secret in [
        "secret-password",
        "private-address",
        "private-body",
        "private@example.com",
    ]:
        assert secret not in caplog.text
    if condition not in ("provider_error", "refused"):
        smtp.assert_not_awaited()


@pytest.mark.asyncio
async def test_initial_acceptance_uses_notification_sender_and_clears_retry_metadata(
    inbox, smtp
):
    _, sessions, ids, _, _ = inbox
    async with sessions() as db:
        user = await db.get(User, ids["owner"])
        log = NotificationLog(
            user_id=user.id,
            channel=NotificationChannel.EMAIL,
            title="Subject",
            body="<b>Body</b>",
            status=OmnichannelStatus.PENDIENTE,
            retry_count=1,
            error_message="previous",
            next_retry_at=utc_now_naive(),
        )
        db.add(log)
        await db.commit()
        key = log.id
        await OmnichannelNotificationService(db, redis_client=False)._dispatch_one(
            log, user, SimpleNamespace(code="notice"), log.body
        )
    async with sessions() as db:
        row = await db.get(NotificationLog, key)
        assert row.status == OmnichannelStatus.ENVIADO and row.sent_at is not None
        assert row.delivered_at is None
        assert row.error_message is None and row.next_retry_at is None
    message = smtp.await_args.args[0]
    assert "notifications@example.com" in message["From"]
    assert message["Subject"] == "Subject"
    assert "<b>Body</b>" in message.get_body(preferencelist=("html",)).get_content()
    assert smtp.await_args.kwargs["sender"] == "notifications@example.com"


@pytest.mark.asyncio
@pytest.mark.parametrize("success", [True, False])
async def test_retry_queue_records_acceptance_or_exhaustion(
    inbox, smtp, monkeypatch, success
):
    _, sessions, ids, _, _ = inbox
    if not success:
        monkeypatch.setattr(settings, "EMAILS_ENABLED", False)
    async with sessions() as db:
        row = NotificationLog(
            user_id=ids["owner"],
            channel=NotificationChannel.EMAIL,
            title="Notice",
            body="Body",
            status=OmnichannelStatus.PENDIENTE,
            retry_count=0,
            error_message="previous",
            next_retry_at=utc_now_naive() - timedelta(seconds=1),
        )
        db.add(row)
        await db.commit()
        key = row.id
        svc = OmnichannelNotificationService(db, redis_client=False)
        assert await svc.process_retry_queue() == 1
        if not success:
            for _ in range(settings.NOTIFICATION_MAX_RETRIES):
                row.next_retry_at = utc_now_naive() - timedelta(seconds=1)
                await db.commit()
                assert await svc.process_retry_queue() == 1
    async with sessions() as db:
        row = await db.get(NotificationLog, key)
        assert row.next_retry_at is None
        assert row.status == (
            OmnichannelStatus.ENVIADO if success else OmnichannelStatus.FALLIDO
        )
        assert (row.sent_at is not None) == success
        assert row.error_message == (None if success else "SMTP unavailable or failed")
    if not success:
        smtp.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("implicit", [False, True])
async def test_notification_uses_real_authenticated_tls(local_smtp, implicit):
    async with local_smtp(implicit=implicit) as (commands, credentials, messages, _):
        svc = OmnichannelNotificationService(None, redis_client=False)
        assert await svc.dispatch_email(
            "recipient@example.com", "Notice", "<b>Private body</b>"
        )
        assert credentials == [b"\x00test-login\x00test-only-password"]
        assert len(messages) == 1
        assert "notifications@example.com" in messages[0]["From"]
        assert messages[0]["Subject"] == "Notice"
        assert (
            "Private body"
            in messages[0].get_body(preferencelist=("html",)).get_content()
        )
        assert all(
            encrypted
            for verb, encrypted in commands
            if verb in ("AUTH", "MAIL", "RCPT", "DATA")
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["no_tls", "bad_certificate", "auth_rejected"])
async def test_notification_real_tls_failures_do_not_claim_acceptance(
    local_smtp, failure
):
    options = {
        "no_tls": {"advertise_tls": False},
        "bad_certificate": {"trusted": False},
        "auth_rejected": {"reject_auth": True},
    }[failure]
    async with local_smtp(**options) as (_, credentials, messages, _):
        assert not await OmnichannelNotificationService(
            None, redis_client=False
        ).dispatch_email("recipient@example.com", "Notice", "Private body")
        assert not messages
        if failure != "auth_rejected":
            assert not credentials
