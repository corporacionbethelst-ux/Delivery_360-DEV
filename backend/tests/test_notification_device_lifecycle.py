"""Native registration races and revision-scoped provider feedback."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, update, delete, text, event
from sqlalchemy.exc import SQLAlchemyError

from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from tests.test_notification_dispatch_postgresql import dispatch_db  # noqa: F401
from tests.test_notification_token_locks import wait_for_sql_lock
from app.models.user import User
from app.models.notification import (
    UserDeviceToken,
    NotificationLog,
    NotificationChannel as Channel,
    utc_now_naive,
)
from app.services import notification_devices as devices
from app.services import omnichannel_service as omni
from app.services.notification_providers import PushResult

TOKEN = "private-device-token"


async def register(sessions, uid, token=TOKEN, platform="web"):
    async with sessions() as db:
        action = await devices.register_device_token(db, uid, token, platform)
        await db.commit()
        return action


async def snapshot(sessions, token=TOKEN):
    async with sessions() as db:
        return await db.scalar(
            select(UserDeviceToken).where(UserDeviceToken.device_token == token)
        )


async def prepare(dispatch_db):
    sessions, uid = dispatch_db
    await register(sessions, uid)
    async with sessions() as db:
        other = await db.scalar(select(User.id).where(User.id != uid))
        await db.execute(update(UserDeviceToken).values(failure_count=2))
        await db.commit()
    row = await snapshot(sessions)
    return sessions, uid, other, row, devices.device_revisions([row])


@pytest.mark.parametrize("workers", [2, 4])
async def test_concurrent_first_registration_creates_exactly_one_device(
    dispatch_db, workers
):
    sessions, uid = dispatch_db
    async with sessions() as db:
        other = await db.scalar(select(User.id).where(User.id != uid))
    ready = asyncio.Event()
    waiting = 0

    async def one(owner):
        nonlocal waiting
        waiting += 1
        if waiting == workers:
            ready.set()
        await ready.wait()
        return await register(sessions, owner)

    actions = await asyncio.wait_for(
        asyncio.gather(*[one([uid, other][i % 2]) for i in range(workers)]), 10
    )
    assert actions.count("created") == 1 and actions.count("updated") == workers - 1
    async with sessions() as db:
        rows = list((await db.scalars(select(UserDeviceToken))).all())
        assert len(rows) == 1 and rows[0].user_id in {uid, other}
        assert rows[0].is_active and rows[0].failure_count == 0


async def test_active_owner_refresh_preserves_count_and_advances_revision(dispatch_db):
    sessions, uid, _, old, _ = await prepare(dispatch_db)
    assert await register(sessions, uid, platform="ios") == "updated"
    row = await snapshot(sessions)
    assert row.id == old.id and row.created_at == old.created_at
    assert row.platform == "ios" and row.failure_count == 2
    assert row.last_seen_at > old.last_seen_at


@pytest.mark.parametrize("change", ["owner", "reactivate"])
async def test_new_owner_or_reactivation_resets_counter(dispatch_db, change):
    sessions, uid, other, old, _ = await prepare(dispatch_db)
    if change == "reactivate":
        async with sessions() as db:
            await devices.unregister_device_token(db, uid, TOKEN)
            await db.commit()
    owner = other if change == "owner" else uid
    await register(sessions, owner)
    row = await snapshot(sessions)
    assert row.user_id == owner and row.failure_count == 0 and row.is_active
    assert row.last_seen_at > old.last_seen_at


async def test_revision_remains_monotonic_with_backwards_clock(
    dispatch_db, monkeypatch
):
    sessions, uid, _, old, _ = await prepare(dispatch_db)
    monkeypatch.setattr(
        devices,
        "_device_now",
        AsyncMock(return_value=old.last_seen_at - timedelta(days=1)),
    )
    await register(sessions, uid)
    first = await snapshot(sessions)
    await register(sessions, uid)
    second = await snapshot(sessions)
    assert first.last_seen_at == old.last_seen_at + timedelta(microseconds=1)
    assert second.last_seen_at == old.last_seen_at + timedelta(microseconds=2)


@pytest.mark.parametrize("change", ["owner", "heartbeat", "reactivate", "recreate"])
@pytest.mark.parametrize("outcome", ["accepted", "invalid"])
async def test_late_feedback_cannot_modify_a_new_device_revision(
    dispatch_db, change, outcome
):
    sessions, uid, other, old, revisions = await prepare(dispatch_db)
    if change == "reactivate":
        async with sessions() as db:
            await devices.unregister_device_token(db, uid, TOKEN)
            await db.commit()
    elif change == "recreate":
        async with sessions() as db:
            await db.execute(delete(UserDeviceToken))
            await db.commit()
    await register(sessions, other if change == "owner" else uid)
    async with sessions() as db:
        await db.execute(update(UserDeviceToken).values(failure_count=1))
        await db.commit()
        svc = omni.OmnichannelNotificationService(db, redis_client=False)
        await svc._apply_push_feedback(
            revisions,
            (TOKEN,) if outcome == "accepted" else (),
            (TOKEN,) if outcome == "invalid" else (),
        )
        await db.commit()
    row = await snapshot(sessions)
    assert row.failure_count == 1 and row.is_active
    assert row.user_id == (other if change == "owner" else uid)
    assert (
        row.id != old.id
        if change == "recreate"
        else row.last_seen_at > old.last_seen_at
    )


@pytest.mark.parametrize("retry", [False, True])
@pytest.mark.parametrize("outcome", ["accepted", "invalid"])
async def test_real_dispatch_captures_revision_before_waiting_for_provider(
    dispatch_db, monkeypatch, retry, outcome
):
    sessions, uid, other, _, _ = await prepare(dispatch_db)
    if retry:
        async with sessions() as db:
            db.add(
                NotificationLog(
                    user_id=uid,
                    channel=Channel.PUSH,
                    body="Body",
                    next_retry_at=utc_now_naive() - timedelta(seconds=1),
                )
            )
            await db.commit()
    entered, resume = asyncio.Event(), asyncio.Event()

    async def provider(*args):
        entered.set()
        await asyncio.wait_for(resume.wait(), 5)
        return PushResult(
            outcome == "accepted",
            (TOKEN,) if outcome == "invalid" else (),
            (TOKEN,) if outcome == "accepted" else (),
        )

    monkeypatch.setattr(omni, "send_push", provider)
    async with sessions() as db:
        svc = omni.OmnichannelNotificationService(db, redis_client=False)
        work = (
            svc.process_retry_queue()
            if retry
            else svc.send(
                uid, "transaction_test", {"name": "Test"}, channels=[Channel.PUSH]
            )
        )
        task = asyncio.create_task(work)
        try:
            await asyncio.wait_for(entered.wait(), 3)
            await register(sessions, other)
            async with sessions() as writer:
                await writer.execute(update(UserDeviceToken).values(failure_count=1))
                await writer.commit()
            resume.set()
            assert await task
        finally:
            resume.set()
            await asyncio.gather(task, return_exceptions=True)
    row = await snapshot(sessions)
    assert row.user_id == other and row.failure_count == 1 and row.is_active


async def test_success_resets_only_matching_accepted_device(dispatch_db):
    sessions, uid, _, _, revisions = await prepare(dispatch_db)
    await register(sessions, uid, token="second-device-token")
    async with sessions() as db:
        await db.execute(update(UserDeviceToken).values(failure_count=2))
        await db.commit()
        rows = list((await db.scalars(select(UserDeviceToken))).all())
        revisions.update(devices.device_revisions(rows))
        await omni.OmnichannelNotificationService(
            db, redis_client=False
        )._apply_push_feedback(
            revisions, (TOKEN, "unknown-device"), ("second-device-token",)
        )
        await db.commit()
    valid = await snapshot(sessions)
    invalid = await snapshot(sessions, "second-device-token")
    assert valid.failure_count == 0 and valid.is_active
    assert invalid.failure_count == 3 and invalid.is_active is False


@pytest.mark.parametrize("outcome", ["accepted", "invalid"])
async def test_feedback_never_changes_inactive_device_even_with_matching_revision(
    dispatch_db, outcome
):
    sessions, _, _, _, revisions = await prepare(dispatch_db)
    async with sessions() as db:
        await db.execute(update(UserDeviceToken).values(is_active=False))
        await db.commit()
        await omni.OmnichannelNotificationService(
            db, redis_client=False
        )._apply_push_feedback(
            revisions,
            (TOKEN,) if outcome == "accepted" else (),
            (TOKEN,) if outcome == "invalid" else (),
        )
        await db.commit()
    row = await snapshot(sessions)
    assert row.failure_count == 2 and row.is_active is False


async def test_registration_refreshes_cached_owner_after_waiting_for_lock(dispatch_db):
    sessions, uid, other, old, _ = await prepare(dispatch_db)
    async with sessions() as first, sessions() as second:
        cached = await second.get(UserDeviceToken, old.id)
        pid = await second.scalar(text("SELECT pg_backend_pid()"))
        assert cached.user_id == uid
        await devices.register_device_token(first, other, TOKEN, "web")
        await first.execute(update(UserDeviceToken).values(failure_count=2))
        task = asyncio.create_task(
            devices.register_device_token(second, uid, TOKEN, "ios")
        )
        try:
            await wait_for_sql_lock(sessions, pid)
            await first.commit()
            assert await asyncio.wait_for(task, 5) == "updated"
            await second.commit()
        finally:
            await first.rollback()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    row = await snapshot(sessions)
    assert row.user_id == uid and row.failure_count == 0 and row.platform == "ios"


async def test_success_reset_rolls_back_on_real_commit_failure(dispatch_db):
    sessions, _, _, _, revisions = await prepare(dispatch_db)
    async with sessions() as db:
        svc = omni.OmnichannelNotificationService(db, redis_client=False)
        await svc._apply_push_feedback(revisions, (TOKEN,), ())

        def fail(session):
            session.execute(text("SELECT missing_device_commit_column"))

        event.listen(db.sync_session, "before_commit", fail)
        try:
            with pytest.raises(SQLAlchemyError):
                await db.commit()
            await db.rollback()
        finally:
            event.remove(db.sync_session, "before_commit", fail)
    assert (await snapshot(sessions)).failure_count == 2
