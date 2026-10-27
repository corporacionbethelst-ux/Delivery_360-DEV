"""Concurrent PUSH logs must not overwrite shared device failure counters."""

import asyncio
import logging
from contextlib import AsyncExitStack
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import SQLAlchemyError

from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from tests.test_notification_dispatch_postgresql import dispatch_db  # noqa: F401
from app.models.notification import (
    NotificationChannel as Channel,
    NotificationLog,
    OmnichannelStatus as Status,
    UserDeviceToken,
    utc_now_naive,
)
from app.services.omnichannel_service import OmnichannelNotificationService as Service


async def seed_tokens(sessions, uid, count=1, failures=0):
    async with sessions() as db:
        rows = [
            UserDeviceToken(
                id=uuid4(),
                user_id=uid,
                device_token="private-token-" + uuid4().hex,
                failure_count=failures,
                is_active=True,
            )
            for _ in range(count)
        ]
        db.add_all(rows)
        await db.commit()
        return [(row.id, row.device_token) for row in rows]


async def token_snapshot(sessions, key):
    async with sessions() as db:
        return await db.get(UserDeviceToken, key)


async def wait_for_sql_lock(sessions, pid):
    # Observe a native lock wait, rather than assuming a task has reached SQL.
    async with sessions() as observer:
        for _ in range(200):
            waiting = await observer.scalar(
                text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
                {"pid": pid},
            )
            if waiting == "Lock":
                return
            # PostgreSQL may cache the activity snapshot within this transaction.
            await observer.rollback()
            await asyncio.sleep(0.01)
    pytest.fail("Worker did not reach a native PostgreSQL lock wait")


async def record_and_commit(db, tokens):
    await Service(db, redis_client=False)._mark_token_failures(tokens)
    await db.commit()


@pytest.mark.parametrize("workers", [2, 4])
async def test_competing_failures_refresh_preloaded_token_and_preserve_every_increment(
    dispatch_db, workers
):
    sessions, uid = dispatch_db
    ((key, token),) = await seed_tokens(sessions, uid)
    async with AsyncExitStack() as stack:
        dbs = [await stack.enter_async_context(sessions()) for _ in range(workers)]
        # Keep every stale identity alive; a lock without refresh still loses counts.
        loaded = [await db.get(UserDeviceToken, key) for db in dbs]
        pids = [await db.scalar(text("SELECT pg_backend_pid()")) for db in dbs]
        assert all(row.failure_count == 0 for row in loaded)
        await Service(dbs[0], redis_client=False)._mark_token_failures([token])
        tasks = [asyncio.create_task(record_and_commit(db, [token])) for db in dbs[1:]]
        try:
            for pid in pids[1:]:
                await wait_for_sql_lock(sessions, pid)
            assert (await token_snapshot(sessions, key)).failure_count == 0
            await dbs[0].commit()
            await asyncio.wait_for(asyncio.gather(*tasks), 5)
        finally:
            await dbs[0].rollback()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    row = await token_snapshot(sessions, key)
    assert row.failure_count == workers
    assert row.is_active is (workers < 3)


async def test_unrelated_token_can_progress_while_another_token_is_locked(dispatch_db):
    sessions, uid = dispatch_db
    (first_id, first_token), (second_id, second_token) = await seed_tokens(
        sessions, uid, 2
    )
    async with sessions() as first, sessions() as second:
        await Service(first, redis_client=False)._mark_token_failures([first_token])
        await asyncio.wait_for(record_and_commit(second, [second_token]), 3)
        assert (await token_snapshot(sessions, second_id)).failure_count == 1
        await first.rollback()
    assert (await token_snapshot(sessions, first_id)).failure_count == 0


async def test_overlapping_batches_with_opposite_input_order_preserve_both_counts(
    dispatch_db,
):
    sessions, uid = dispatch_db
    pairs = await seed_tokens(sessions, uid, 2, failures=1)
    tokens = [token for _, token in pairs]
    async with sessions() as first, sessions() as second:
        pid = await second.scalar(text("SELECT pg_backend_pid()"))
        await Service(first, redis_client=False)._mark_token_failures(tokens)
        task = asyncio.create_task(record_and_commit(second, list(reversed(tokens))))
        try:
            await wait_for_sql_lock(sessions, pid)
            await first.commit()
            await asyncio.wait_for(task, 5)
        finally:
            await first.rollback()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    for key, _ in pairs:
        row = await token_snapshot(sessions, key)
        assert row.failure_count == 3 and row.is_active is False


async def test_threshold_update_is_not_committed_before_dispatch_owner(dispatch_db):
    sessions, uid = dispatch_db
    ((key, token),) = await seed_tokens(sessions, uid, failures=2)
    async with sessions() as db:
        await Service(db, redis_client=False)._mark_token_failures([token])
        visible = await token_snapshot(sessions, key)
        assert visible.failure_count == 2 and visible.is_active
        await db.rollback()
    row = await token_snapshot(sessions, key)
    assert row.failure_count == 2 and row.is_active


async def test_sql_commit_failure_reverts_counter_and_disabled_flag(dispatch_db):
    sessions, uid = dispatch_db
    ((key, token),) = await seed_tokens(sessions, uid, failures=2)
    async with sessions() as db:
        await Service(db, redis_client=False)._mark_token_failures([token])

        def fail(session):
            session.execute(text("SELECT nonexistent_token_commit_column"))

        event.listen(db.sync_session, "before_commit", fail)
        try:
            with pytest.raises(SQLAlchemyError):
                await db.commit()
            await db.rollback()
        finally:
            event.remove(db.sync_session, "before_commit", fail)
        row = await token_snapshot(sessions, key)
        assert row.failure_count == 2 and row.is_active
        await record_and_commit(db, [token])
    row = await token_snapshot(sessions, key)
    assert row.failure_count == 3 and row.is_active is False


async def test_duplicate_and_unknown_tokens_do_not_duplicate_counts_or_leak_tokens(
    dispatch_db, caplog
):
    sessions, uid = dispatch_db
    ((key, token),) = await seed_tokens(sessions, uid, failures=2)
    with caplog.at_level(logging.INFO, logger="app.services.omnichannel_service"):
        async with sessions() as db:
            await record_and_commit(db, [token, token, "unknown-token"])
    row = await token_snapshot(sessions, key)
    assert row.failure_count == 3 and row.is_active is False
    assert "auto-desactivado" in caplog.text
    assert token not in caplog.text and token[:12] not in caplog.text


async def test_unknown_token_does_not_create_or_modify_devices(dispatch_db):
    sessions, uid = dispatch_db
    ((key, _),) = await seed_tokens(sessions, uid, failures=1)
    async with sessions() as db:
        await record_and_commit(db, ["missing-token"])
        assert len(list((await db.scalars(select(UserDeviceToken))).all())) == 1
    assert (await token_snapshot(sessions, key)).failure_count == 1


async def test_cancelled_retry_waiting_for_shared_token_releases_its_log(dispatch_db):
    sessions, uid = dispatch_db
    ((key, token),) = await seed_tokens(sessions, uid, failures=1)
    async with sessions() as db:
        logs = [
            NotificationLog(
                user_id=uid,
                channel=Channel.PUSH,
                status=Status.PENDIENTE,
                body=f"log-{i}",
                next_retry_at=utc_now_naive()
                - timedelta(minutes=2)
                + timedelta(seconds=i),
            )
            for i in range(2)
        ]
        db.add_all(logs)
        await db.commit()
        log_ids = [row.id for row in logs]
    entered, resume = asyncio.Event(), asyncio.Event()
    async with sessions() as first, sessions() as second:
        a, b = Service(first, redis_client=False), Service(second, redis_client=False)
        pid = await second.scalar(text("SELECT pg_backend_pid()"))

        async def first_push(tokens, *args):
            assert tokens == [token]
            await a._mark_token_failures(tokens)
            entered.set()
            await asyncio.wait_for(resume.wait(), 10)
            return False

        async def next_push(tokens, *args):
            await b._mark_token_failures(tokens)
            return False

        a.dispatch_push = AsyncMock(side_effect=first_push)
        b.dispatch_push = AsyncMock(side_effect=next_push)
        first_task = asyncio.create_task(a.process_retry_queue(batch_size=1))
        second_task = None
        try:
            await asyncio.wait_for(entered.wait(), 5)
            second_task = asyncio.create_task(b.process_retry_queue(batch_size=1))
            await wait_for_sql_lock(sessions, pid)
            second_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await second_task
            assert not second.in_transaction()
            async with sessions() as observer:
                cancelled = await observer.get(NotificationLog, log_ids[1])
                assert (
                    cancelled.status == Status.PENDIENTE and cancelled.retry_count == 0
                )
            resume.set()
            assert await first_task == 1
            assert await b.process_retry_queue(batch_size=1) == 1
        finally:
            resume.set()
            for task in [first_task, second_task]:
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(
                *[task for task in [first_task, second_task] if task is not None],
                return_exceptions=True,
            )
    row = await token_snapshot(sessions, key)
    assert row.failure_count == 3 and row.is_active is False
    async with sessions() as db:
        results = list((await db.scalars(select(NotificationLog))).all())
        assert len(results) == 2
        assert all(
            row.status == Status.PENDIENTE and row.retry_count == 1 for row in results
        )


async def test_empty_failure_batch_never_queries_or_flushes_session():
    db = SimpleNamespace(execute=AsyncMock(), flush=AsyncMock(), commit=AsyncMock())
    await Service(db, redis_client=False)._mark_token_failures([])
    db.execute.assert_not_awaited()
    db.flush.assert_not_awaited()
    db.commit.assert_not_awaited()
