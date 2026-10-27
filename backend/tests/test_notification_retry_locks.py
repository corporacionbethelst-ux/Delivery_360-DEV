"""Native PostgreSQL competing retry workers, failure and cancellation recovery."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select, event, text
from sqlalchemy.exc import SQLAlchemyError
from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from tests.test_notification_dispatch_postgresql import dispatch_db  # noqa: F401
from app.models.notification import (
    NotificationLog,
    NotificationChannel as Channel,
    OmnichannelStatus as Status,
    UserDeviceToken,
    utc_now_naive,
)
from app.services.omnichannel_service import OmnichannelNotificationService as Service


@pytest.fixture
async def retry_db(dispatch_db):
    return dispatch_db


async def seed(sessions, uid, count=1, channel=Channel.EMAIL):
    ids = []
    async with sessions() as db:
        for i in range(count):
            row = NotificationLog(
                id=uuid4(),
                user_id=uid,
                channel=channel,
                status=Status.PENDIENTE,
                body=f"row-{i}",
                title="Notice",
                retry_count=0,
                next_retry_at=utc_now_naive()
                - timedelta(minutes=2)
                + timedelta(seconds=i),
            )
            db.add(row)
            ids.append(row.id)
        await db.commit()
    return ids


def service(db):
    svc = Service(db, redis_client=False)
    svc.dispatch_email = AsyncMock(return_value=True)
    return svc


async def persisted(sessions, key):
    async with sessions() as db:
        return await db.get(NotificationLog, key)


@pytest.mark.asyncio
async def test_second_worker_skips_same_locked_log(retry_db):
    sessions, uid = retry_db
    ids = await seed(sessions, uid)
    entered, resume = asyncio.Event(), asyncio.Event()
    async with sessions() as first, sessions() as second:
        a, b = service(first), service(second)

        async def wait(*args):
            entered.set()
            await asyncio.wait_for(resume.wait(), 5)
            return True

        a.dispatch_email.side_effect = wait
        task = asyncio.create_task(a.process_retry_queue())
        try:
            await asyncio.wait_for(entered.wait(), 5)
            assert await asyncio.wait_for(b.process_retry_queue(), 3) == 0
            b.dispatch_email.assert_not_awaited()
            resume.set()
            assert await task == 1
        finally:
            resume.set()
            await asyncio.gather(task, return_exceptions=True)
    assert (await persisted(sessions, ids[0])).status == Status.ENVIADO


@pytest.mark.asyncio
async def test_workers_can_process_different_rows_without_waiting(retry_db):
    sessions, uid = retry_db
    ids = await seed(sessions, uid, 2)
    entered, resume = asyncio.Event(), asyncio.Event()
    async with sessions() as first, sessions() as second:
        a, b = service(first), service(second)

        async def wait(*args):
            entered.set()
            await asyncio.wait_for(resume.wait(), 5)
            return True

        a.dispatch_email.side_effect = wait
        task = asyncio.create_task(a.process_retry_queue(batch_size=1))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            assert await asyncio.wait_for(b.process_retry_queue(batch_size=1), 3) == 1
            assert b.dispatch_email.await_args.args[2] == "row-1"
            assert (await persisted(sessions, ids[1])).status == Status.ENVIADO
            resume.set()
            assert await task == 1
            assert a.dispatch_email.await_args.args[2] == "row-0"
        finally:
            resume.set()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancelled_worker_rolls_back_and_releases_row(retry_db):
    sessions, uid = retry_db
    ids = await seed(sessions, uid)
    entered = asyncio.Event()
    async with sessions() as first:
        a = service(first)

        async def wait(*args):
            entered.set()
            await asyncio.Future()

        a.dispatch_email.side_effect = wait
        task = asyncio.create_task(a.process_retry_queue())
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not first.in_transaction()
    row = await persisted(sessions, ids[0])
    assert row.status == Status.PENDIENTE and row.retry_count == 0
    async with sessions() as db:
        assert await service(db).process_retry_queue() == 1


@pytest.mark.asyncio
async def test_sql_failure_keeps_prior_commit_and_releases_current_row(retry_db):
    sessions, uid = retry_db
    ids = await seed(sessions, uid, 2)
    async with sessions() as db:
        svc = service(db)
        commits = 0

        def fail_second(session):
            nonlocal commits
            commits += 1
            if commits == 2:
                session.execute(
                    text("SELECT missing_retry_column FROM notification_logs")
                )

        event.listen(db.sync_session, "before_commit", fail_second)
        try:
            with pytest.raises(SQLAlchemyError):
                await svc.process_retry_queue()
        finally:
            event.remove(db.sync_session, "before_commit", fail_second)
        assert svc.dispatch_email.await_count == 2
        assert not db.in_transaction()
        assert (
            await db.scalar(
                select(NotificationLog.id).where(NotificationLog.id == ids[0])
            )
            == ids[0]
        )
    assert (await persisted(sessions, ids[0])).status == Status.ENVIADO
    assert (await persisted(sessions, ids[1])).status == Status.PENDIENTE
    async with sessions() as db:
        b = service(db)
        assert await b.process_retry_queue() == 1
        assert b.dispatch_email.await_args.args[2] == "row-1"
    # External acceptance before a failed commit can still duplicate delivery.


@pytest.mark.asyncio
async def test_token_failure_flush_does_not_release_notification_lock(retry_db):
    sessions, uid = retry_db
    ids = await seed(sessions, uid, channel=Channel.PUSH)
    async with sessions() as db:
        token = UserDeviceToken(
            user_id=uid, device_token="test-token", failure_count=2, is_active=True
        )
        db.add(token)
        await db.commit()
        token_id = token.id
    entered, resume = asyncio.Event(), asyncio.Event()
    async with sessions() as first, sessions() as second:
        a, b = service(first), service(second)

        async def push(tokens, *args, **kwargs):
            await a._mark_token_failures(tokens)
            entered.set()
            await asyncio.wait_for(resume.wait(), 5)
            return False

        a.dispatch_push = AsyncMock(side_effect=push)
        b.dispatch_push = AsyncMock(return_value=False)
        task = asyncio.create_task(a.process_retry_queue())
        try:
            await asyncio.wait_for(entered.wait(), 5)
            assert await asyncio.wait_for(b.process_retry_queue(), 3) == 0
            b.dispatch_push.assert_not_awaited()
            resume.set()
            assert await task == 1
        finally:
            resume.set()
            await asyncio.gather(task, return_exceptions=True)
    async with sessions() as db:
        token = await db.get(UserDeviceToken, token_id)
        assert token.failure_count == 3 and token.is_active is False
    assert (await persisted(sessions, ids[0])).status == Status.PENDIENTE


@pytest.mark.asyncio
async def test_provider_exception_releases_row_for_next_scan(retry_db):
    sessions, uid = retry_db
    ids = await seed(sessions, uid)
    async with sessions() as db:
        a = service(db)
        a.dispatch_email.side_effect = RuntimeError("injected provider failure")
        with pytest.raises(RuntimeError):
            await a.process_retry_queue()
        assert not db.in_transaction()
    assert (await persisted(sessions, ids[0])).retry_count == 0
    async with sessions() as db:
        assert await service(db).process_retry_queue() == 1


@pytest.mark.asyncio
async def test_batch_limit_and_eligibility_are_respected(retry_db):
    sessions, uid = retry_db
    ids = await seed(sessions, uid, 2)
    async with sessions() as db:
        for status, deadline in [
            (Status.ENVIADO, utc_now_naive()),
            (Status.LEIDO, utc_now_naive()),
            (Status.PENDIENTE, None),
            (Status.PENDIENTE, utc_now_naive() + timedelta(days=1)),
        ]:
            db.add(
                NotificationLog(
                    user_id=uid,
                    channel=Channel.EMAIL,
                    status=status,
                    body="ineligible",
                    next_retry_at=deadline,
                )
            )
        await db.commit()
    async with sessions() as db:
        svc = service(db)
        assert await svc.process_retry_queue(batch_size=1) == 1
        assert svc.dispatch_email.await_args.args[2] == "row-0"
        assert await svc.process_retry_queue(batch_size=1) == 1
        assert svc.dispatch_email.await_args.args[2] == "row-1"
        assert await svc.process_retry_queue() == 0
        assert svc.dispatch_email.await_count == 2
    final_rows = [await persisted(sessions, key) for key in ids]
    assert all(row.status == Status.ENVIADO for row in final_rows)


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [0, -1, 101, True, 1.5])
async def test_invalid_batch_size_does_not_touch_session(size):
    db = SimpleNamespace(execute=AsyncMock())
    with pytest.raises(ValueError):
        await service(db).process_retry_queue(size)
    db.execute.assert_not_awaited()
