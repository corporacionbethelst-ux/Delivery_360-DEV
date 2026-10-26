"""Multichannel dispatch must not execute concurrent commits on one session."""

import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select, text, event
from sqlalchemy.exc import SQLAlchemyError
from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from app.core.config import settings
from app.models.user import User
from app.models.notification import (
    NotificationChannel as Channel,
    OmnichannelStatus as Status,
    NotificationTemplate,
    NotificationLog,
    NotificationPreference,
    UserDeviceToken,
)
from app.services.omnichannel_service import OmnichannelNotificationService

CHANNELS = [Channel.EMAIL, Channel.IN_APP, Channel.PUSH]


@pytest.fixture
async def dispatch_db(pg_wallets, monkeypatch):
    sessions, _, _ = pg_wallets
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True)
    async with sessions() as db:
        await db.execute(text("CREATE TABLE deliveries (id UUID PRIMARY KEY)"))
        await db.execute(text("CREATE TABLE payouts (id UUID PRIMARY KEY)"))
        conn = await db.connection()
        for model in [
            NotificationTemplate,
            NotificationLog,
            NotificationPreference,
            UserDeviceToken,
        ]:
            for column in model.__table__.columns:
                if hasattr(column.type, "create"):
                    await conn.run_sync(
                        lambda c, t=column.type: t.create(c, checkfirst=True)
                    )
            await conn.run_sync(model.__table__.create)
        uid = await db.scalar(select(User.id).order_by(User.id).limit(1))
        template = NotificationTemplate(
            code="transaction_test",
            channel=Channel.EMAIL,
            subject="Notice",
            body_template="Hello {{name}}",
            is_active=True,
        )
        db.add(template)
        await db.commit()
    return sessions, uid


def configure(db, monkeypatch):
    service = OmnichannelNotificationService(db, redis_client=False)
    monkeypatch.setattr(service, "dispatch_email", AsyncMock(return_value=True))
    monkeypatch.setattr(service, "dispatch_push", AsyncMock(return_value=True))
    monkeypatch.setattr(service, "_publish_new_notification", AsyncMock())
    return service


async def send(service, uid):
    return await service.send(
        uid,
        "transaction_test",
        {"name": "Test", "entity_id": str(uuid4())},
        channels=CHANNELS,
    )


@pytest.mark.asyncio
async def test_all_channels_commit_serially_on_native_session(dispatch_db, monkeypatch):
    sessions, uid = dispatch_db
    async with sessions() as db:
        service = configure(db, monkeypatch)
        original = db.commit
        active, maximum, commits = 0, 0, 0

        async def guarded_commit():
            nonlocal active, maximum, commits
            active += 1
            maximum = max(maximum, active)
            try:
                await asyncio.sleep(
                    0
                )  # expose concurrent commit calls deterministically
                assert active == 1
                await original()
                commits += 1
            finally:
                active -= 1

        monkeypatch.setattr(db, "commit", guarded_commit)
        logs = await send(service, uid)
        assert len(logs) == 3 and maximum == 1 and commits == 4
        assert [row.channel for row in logs] == CHANNELS
        service._publish_new_notification.assert_awaited_once()
    async with sessions() as db:
        rows = list((await db.scalars(select(NotificationLog))).all())
        assert len(rows) == 3 and all(row.status == Status.ENVIADO for row in rows)
        inbox = next(row for row in rows if row.channel == Channel.IN_APP)
        assert inbox.delivered_at is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("raise_error", [False, True])
async def test_provider_failure_does_not_skip_other_channels(
    dispatch_db, monkeypatch, raise_error
):
    sessions, uid = dispatch_db
    async with sessions() as db:
        service = configure(db, monkeypatch)
        if raise_error:
            service.dispatch_email.side_effect = RuntimeError("private diagnostic")
        else:
            service.dispatch_email.return_value = False
        logs = await send(service, uid)
        assert len(logs) == 3
        service.dispatch_push.assert_awaited_once()
    async with sessions() as db:
        rows = {
            row.channel: row
            for row in (await db.scalars(select(NotificationLog))).all()
        }
        assert rows[Channel.EMAIL].status == Status.PENDIENTE
        assert rows[Channel.EMAIL].next_retry_at is not None
        assert rows[Channel.EMAIL].retry_count == 1
        assert rows[Channel.EMAIL].sent_at is None
        assert "private diagnostic" not in rows[Channel.EMAIL].error_message
        assert all(
            rows[ch].status == Status.ENVIADO for ch in [Channel.IN_APP, Channel.PUSH]
        )


@pytest.mark.asyncio
async def test_sql_commit_failure_stops_dispatch_rolls_back_and_leaves_session_usable(
    dispatch_db, monkeypatch, caplog
):
    sessions, uid = dispatch_db
    async with sessions() as db:
        service = configure(db, monkeypatch)
        count = 0

        def fail_second_commit(session):
            nonlocal count
            count += 1
            if count == 2:
                # Genuine SQL failure after the queue insert committed, before
                # a channel result could be persisted. Transaction is aborted.
                session.execute(
                    text("SELECT missing_notification_column FROM notification_logs")
                )

        event.listen(db.sync_session, "before_commit", fail_second_commit)
        try:
            assert await send(service, uid) == []
        finally:
            event.remove(db.sync_session, "before_commit", fail_second_commit)
        service.dispatch_email.assert_awaited_once()
        service.dispatch_push.assert_not_awaited()
        service._publish_new_notification.assert_not_awaited()
        assert await db.scalar(select(User.id).where(User.id == uid)) == uid
    async with sessions() as db:
        rows = list((await db.scalars(select(NotificationLog))).all())
        assert len(rows) == 3 and all(row.status == Status.PENDIENTE for row in rows)
        assert all(row.sent_at is None for row in rows)
    assert "Notification dispatch failed" in caplog.text
    assert "missing_notification_column" not in caplog.text


@pytest.mark.asyncio
async def test_master_disabled_persists_only_in_app(dispatch_db, monkeypatch):
    sessions, uid = dispatch_db
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", False)
    async with sessions() as db:
        service = configure(db, monkeypatch)
        logs = await send(service, uid)
        assert len(logs) == 1 and logs[0].channel == Channel.IN_APP
        assert logs[0].status == Status.ENVIADO
        service.dispatch_email.assert_not_awaited()
        service.dispatch_push.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_contains_rollback_failure_without_exposing_diagnostics(caplog):
    from types import SimpleNamespace

    db = SimpleNamespace(
        execute=AsyncMock(side_effect=SQLAlchemyError("private query diagnostic")),
        rollback=AsyncMock(side_effect=RuntimeError("private rollback diagnostic")),
    )
    service = OmnichannelNotificationService(db, redis_client=False)
    assert await send(service, uuid4()) == []
    db.rollback.assert_awaited_once()
    assert "Notification transaction rollback failed" in caplog.text
    assert "private" not in caplog.text


@pytest.mark.asyncio
async def test_non_sql_error_does_not_discard_uncommitted_caller_changes(
    dispatch_db, monkeypatch
):
    sessions, uid = dispatch_db
    async with sessions() as db:
        user = await db.get(User, uid)
        user.phone = "+584120000001"
        service = configure(db, monkeypatch)
        monkeypatch.setattr(
            service,
            "_send_inner",
            AsyncMock(side_effect=ValueError("private template diagnostic")),
        )
        rollback = AsyncMock(wraps=db.rollback)
        monkeypatch.setattr(db, "rollback", rollback)
        assert await send(service, uid) == []
        rollback.assert_not_awaited()
        await db.commit()
    async with sessions() as db:
        assert (await db.get(User, uid)).phone == "+584120000001"
