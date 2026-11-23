"""Commit boundaries, savepoint rollback and optional transport isolation."""

import asyncio
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.services import assignment_realtime as realtime


@pytest.fixture
async def context(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.execute(text("CREATE TABLE proof (id INTEGER PRIMARY KEY)"))
    schedule = Mock()
    monkeypatch.setattr(realtime, "_schedule", schedule)
    try:
        yield engine, async_sessionmaker(engine), schedule
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_only_outer_commit_schedules_deduplicated_ids_and_session_reuse(context):
    engine, sessions, schedule = context
    first, second = uuid4(), uuid4()
    async with sessions() as db:
        await db.execute(text("INSERT INTO proof VALUES (1)"))
        realtime.queue_assignment_nudge(db, first)
        realtime.queue_assignment_nudge(db, first)
        schedule.assert_not_called()
        await db.commit()
        assert schedule.call_count == 1
        assert schedule.call_args.args == (engine, (first,))
        await db.execute(text("INSERT INTO proof VALUES (2)"))
        realtime.queue_assignment_nudge(db, second)
        await db.commit()
    assert schedule.call_count == 2
    assert schedule.call_args.args == (engine, (second,))


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["rollback", "close", "constraint_failure"])
async def test_failed_or_abandoned_transaction_never_announces(context, outcome):
    _, sessions, schedule = context
    async with sessions() as db:
        await db.execute(text("INSERT INTO proof VALUES (1)"))
        realtime.queue_assignment_nudge(db, uuid4())
        if outcome == "rollback":
            await db.rollback()
        if outcome == "constraint_failure":
            with pytest.raises(IntegrityError):
                await db.execute(text("INSERT INTO proof VALUES (1)"))
            await db.rollback()
    schedule.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "nested_commit,outer_commit",
    [(True, True), (True, False), (False, True), (False, False)],
)
async def test_savepoint_is_provisional_until_outer_commit(
    context, nested_commit, outer_commit
):
    engine, sessions, schedule = context
    outer, nested = uuid4(), uuid4()
    async with sessions() as db:
        await db.execute(text("INSERT INTO proof VALUES (1)"))
        realtime.queue_assignment_nudge(db, outer)
        savepoint = await db.begin_nested()
        realtime.queue_assignment_nudge(db, nested)
        if nested_commit:
            await savepoint.commit()
        else:
            await savepoint.rollback()
        schedule.assert_not_called()
        if outer_commit:
            await db.commit()
        else:
            await db.rollback()
    if outer_commit:
        schedule.assert_called_once()
        assert schedule.call_args.args[0] is engine
        assert set(schedule.call_args.args[1]) == (
            {outer, nested} if nested_commit else {outer}
        )
    else:
        schedule.assert_not_called()


@pytest.mark.asyncio
async def test_nested_rollback_discards_committed_grandchild(context):
    _, sessions, schedule = context
    outer = uuid4()
    async with sessions() as db:
        await db.begin()
        realtime.queue_assignment_nudge(db, outer)
        savepoint = await db.begin_nested()
        realtime.queue_assignment_nudge(db, uuid4())
        child = await db.begin_nested()
        realtime.queue_assignment_nudge(db, uuid4())
        await child.commit()
        await savepoint.rollback()
        await db.commit()
    assert schedule.call_args.args[1] == (outer,)


@pytest.mark.asyncio
async def test_different_sessions_do_not_mix_recipients(context):
    _, sessions, schedule = context
    first, second = uuid4(), uuid4()
    async with sessions() as a, sessions() as b:
        await a.begin()
        await b.begin()
        realtime.queue_assignment_nudge(a, first)
        realtime.queue_assignment_nudge(b, second)
        await a.rollback()
        await b.commit()
    schedule.assert_called_once()
    assert schedule.call_args.args[1] == (second,)


@pytest.mark.asyncio
async def test_connection_bound_session_retains_rest_without_sharing_connection(
    context,
):
    engine, _, schedule = context
    async with engine.connect() as connection:
        async with async_sessionmaker(connection)() as db:
            await db.begin()
            realtime.queue_assignment_nudge(db, uuid4())
            await db.commit()
    schedule.assert_not_called()


@pytest.mark.asyncio
async def test_transport_failure_cannot_undo_commit(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    publish = AsyncMock(side_effect=ConnectionError("offline"))
    monkeypatch.setattr(realtime, "_publish", publish)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE proof (id INTEGER PRIMARY KEY)"))
        async with async_sessionmaker(engine)() as db:
            await db.execute(text("INSERT INTO proof VALUES (1)"))
            realtime.queue_assignment_nudge(db, uuid4())
            await db.commit()
            await asyncio.sleep(0)
            if realtime._tasks:
                await asyncio.gather(*tuple(realtime._tasks))
            publish.assert_awaited_once()
            assert await db.scalar(text("SELECT count(*) FROM proof")) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_cancelled_nudge_keeps_committed_data_and_releases_task(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    entered = asyncio.Event()

    async def blocked(*args):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(realtime, "_publish", blocked)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE proof (id INTEGER PRIMARY KEY)"))
        async with async_sessionmaker(engine)() as db:
            await db.execute(text("INSERT INTO proof VALUES (1)"))
            realtime.queue_assignment_nudge(db, uuid4())
            await db.commit()
            await asyncio.wait_for(entered.wait(), 2)
            tasks = tuple(realtime._tasks)
            assert len(tasks) == 1
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.sleep(0)
            assert not realtime._tasks
            assert await db.scalar(text("SELECT count(*) FROM proof")) == 1
    finally:
        await engine.dispose()
