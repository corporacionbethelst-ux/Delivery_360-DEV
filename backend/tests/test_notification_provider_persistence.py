"""Native persisted PUSH/SMS outcomes and SQL lock retention during SDK drain."""

import asyncio
import threading
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, update

from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from tests.test_notification_dispatch_postgresql import dispatch_db  # noqa: F401
from app.core.config import settings
from app.models.notification import (
    NotificationChannel as Channel,
    NotificationLog,
    UserDeviceToken,
    OmnichannelStatus as Status,
    utc_now_naive,
)
from app.services import notification_providers as providers
from app.services import omnichannel_service as omni


@pytest.mark.parametrize("channel", [Channel.PUSH, Channel.SMS])
async def test_missing_provider_preserves_inbox_and_exhausts_real_retry_budget(
    dispatch_db, monkeypatch, channel
):
    sessions, uid = dispatch_db
    monkeypatch.setattr(settings, "FCM_CREDENTIALS_JSON_PATH", None)
    monkeypatch.setattr(settings, "TWILIO_ACCOUNT_SID", None)
    async with sessions() as db:
        svc = omni.OmnichannelNotificationService(db, redis_client=False)
        logs = await svc.send(
            uid,
            "transaction_test",
            {"name": "Test"},
            channels=[channel, Channel.IN_APP],
        )
        assert len(logs) == 2
        external = next(row for row in logs if row.channel == channel)
        key = external.id
        assert external.status == Status.PENDIENTE and external.retry_count == 1
        assert external.sent_at is None and external.next_retry_at is not None
        bell = next(row for row in logs if row.channel == Channel.IN_APP)
        assert bell.status == Status.ENVIADO and bell.delivered_at is not None
    async with sessions() as db:
        svc = omni.OmnichannelNotificationService(db, redis_client=False)
        for _ in range(settings.NOTIFICATION_MAX_RETRIES):
            await db.execute(
                update(NotificationLog)
                .where(NotificationLog.id == key)
                .values(next_retry_at=utc_now_naive() - timedelta(seconds=1))
            )
            await db.commit()
            assert await svc.process_retry_queue() == 1
        row = await db.get(NotificationLog, key)
        assert row.status == Status.FALLIDO and row.next_retry_at is None
        assert (
            row.sent_at is None and row.retry_count == settings.NOTIFICATION_MAX_RETRIES
        )
        assert row.error_message == "External provider unavailable or failed"


async def seed(sessions, uid, channel=Channel.PUSH):
    async with sessions() as db:
        row = NotificationLog(
            user_id=uid,
            channel=channel,
            status=Status.PENDIENTE,
            body="Persisted body",
            title="Notice",
            retry_count=1,
            error_message="Previous error",
            next_retry_at=utc_now_naive() - timedelta(seconds=1),
        )
        db.add(row)
        db.add(
            UserDeviceToken(user_id=uid, device_token="test-device", failure_count=2)
        )
        await db.commit()
        return row.id


async def test_push_acceptance_only_updates_permanently_invalid_device(
    dispatch_db, monkeypatch
):
    sessions, uid = dispatch_db
    key = await seed(sessions, uid)
    provider = AsyncMock(return_value=providers.PushResult(True, ("test-device",)))
    monkeypatch.setattr(omni, "send_push", provider)
    async with sessions() as db:
        assert (
            await omni.OmnichannelNotificationService(
                db, redis_client=False
            ).process_retry_queue()
            == 1
        )
    async with sessions() as db:
        row = await db.get(NotificationLog, key)
        token = await db.scalar(select(UserDeviceToken))
        assert row.status == Status.ENVIADO and row.sent_at is not None
        assert row.next_retry_at is None and row.error_message is None
        assert row.delivered_at is None  # provider acceptance is not device delivery
        assert token.failure_count == 3 and token.is_active is False


@pytest.mark.parametrize("channel", [Channel.PUSH, Channel.SMS])
async def test_provider_exceptions_leave_only_generic_persisted_diagnostics(
    dispatch_db, monkeypatch, caplog, channel
):
    sessions, uid = dispatch_db
    key = await seed(sessions, uid, channel)
    method = "send_push" if channel == Channel.PUSH else "send_sms"
    monkeypatch.setattr(
        omni,
        method,
        AsyncMock(
            side_effect=RuntimeError("private-recipient provider-secret private-body")
        ),
    )
    async with sessions() as db:
        assert (
            await omni.OmnichannelNotificationService(
                db, redis_client=False
            ).process_retry_queue()
            == 1
        )
    async with sessions() as db:
        row = await db.get(NotificationLog, key)
        assert row.status == Status.PENDIENTE and row.retry_count == 2
        assert (
            row.sent_at is None
            and row.error_message == "External provider unavailable or failed"
        )
        token = await db.scalar(select(UserDeviceToken))
        assert token.failure_count == 2 and token.is_active
    assert not any(
        value in caplog.text
        for value in ["private-recipient", "provider-secret", "private-body"]
    )


async def test_retried_inbox_has_real_delivery_timestamp(dispatch_db):
    sessions, uid = dispatch_db
    key = await seed(sessions, uid, Channel.IN_APP)
    async with sessions() as db:
        assert (
            await omni.OmnichannelNotificationService(
                db, redis_client=False
            ).process_retry_queue()
            == 1
        )
        row = await db.get(NotificationLog, key)
        assert row.sent_at is not None and row.delivered_at == row.sent_at
        assert row.next_retry_at is None and row.error_message is None


async def test_task_cancellation_keeps_log_locked_until_sdk_thread_finishes(
    dispatch_db, monkeypatch
):
    sessions, uid = dispatch_db
    key = await seed(sessions, uid)
    monkeypatch.setattr(settings, "FCM_CREDENTIALS_JSON_PATH", "not-read-test.json")
    entered, finish = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()

    def sdk(*args):
        loop.call_soon_threadsafe(entered.set)
        assert finish.wait(8)
        return providers.PushResult(True)

    monkeypatch.setattr(providers, "_push_sync", sdk)
    async with sessions() as first, sessions() as second:
        a, b = [
            omni.OmnichannelNotificationService(db, redis_client=False)
            for db in [first, second]
        ]
        task = asyncio.create_task(a.process_retry_queue())
        try:
            await asyncio.wait_for(entered.wait(), 3)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            assert await asyncio.wait_for(b.process_retry_queue(), 3) == 0
            finish.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            async with sessions() as observer:
                row = await observer.get(NotificationLog, key)
                assert row.status == Status.PENDIENTE and row.retry_count == 1
                assert row.sent_at is None
            assert await b.process_retry_queue() == 1
        finally:
            finish.set()
            await asyncio.gather(task, return_exceptions=True)
