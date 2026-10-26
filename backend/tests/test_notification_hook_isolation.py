"""Post-commit hooks own their session; they never commit or roll back callers."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import select, update, text, event
from sqlalchemy.ext.asyncio import AsyncSession
from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from tests.test_notification_dispatch_postgresql import dispatch_db  # noqa: F401
from app.core import database
from app.models.user import User, UserRole
from app.models.notification import NotificationLog, OmnichannelStatus
from app.services import notification_hooks as hooks
from app.services.omnichannel_service import OmnichannelNotificationService as Service


@pytest.fixture
async def hook_db(dispatch_db, monkeypatch):
    sessions, uid = dispatch_db
    async with sessions() as db:
        await db.execute(
            update(User)
            .where(User.id == uid)
            .values(role=UserRole.CLIENTE, phone="original")
        )
        await db.commit()
    monkeypatch.setattr(database, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(Service, "_get_redis", AsyncMock(return_value=None))
    monkeypatch.setattr(Service, "dispatch_email", AsyncMock(return_value=True))
    monkeypatch.setattr(Service, "_publish_new_notification", AsyncMock())
    return sessions, uid


async def notify(uid, **kwargs):
    await hooks.notify_event(
        "transaction_test", uid, {"name": "Test", "entity_id": str(uuid4())}, **kwargs
    )


async def rows(sessions):
    async with sessions() as db:
        return list((await db.scalars(select(NotificationLog))).all())


@pytest.mark.asyncio
async def test_post_commit_uses_different_session_on_callers_engine(
    hook_db, monkeypatch
):
    sessions, uid = hook_db
    observed = []
    original = Service.send

    async def observe(service, *args, **kwargs):
        observed.append(service.db)
        return await original(service, *args, **kwargs)

    monkeypatch.setattr(Service, "send", observe)
    async with sessions() as caller:
        caller.info["marker"] = "owner"
        commit, rollback = AsyncMock(wraps=caller.commit), AsyncMock(
            wraps=caller.rollback
        )
        monkeypatch.setattr(caller, "commit", commit)
        monkeypatch.setattr(caller, "rollback", rollback)
        await notify(uid, db=caller)
        assert len(observed) == 1 and observed[0] is not caller
        assert observed[0].bind is caller.bind
        assert not observed[0].in_transaction() and not caller.in_transaction()
        commit.assert_not_awaited()
        rollback.assert_not_awaited()
        assert caller.info["marker"] == "owner"
    logs = await rows(sessions)
    assert len(logs) == 2 and all(
        log.status == OmnichannelStatus.ENVIADO for log in logs
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["read_only", "unflushed", "flushed"])
@pytest.mark.parametrize("commit", [True, False])
async def test_active_transaction_is_rejected_without_touching_caller(
    hook_db, monkeypatch, state, commit, caplog
):
    sessions, uid = hook_db
    send = AsyncMock()
    monkeypatch.setattr(Service, "send", send)
    async with sessions() as caller:
        user = await caller.get(User, uid)
        if state != "read_only":
            user.phone = "pending"
            if state == "flushed":
                await caller.flush()
        commit_spy = AsyncMock(wraps=caller.commit)
        rollback_spy = AsyncMock(wraps=caller.rollback)
        monkeypatch.setattr(caller, "commit", commit_spy)
        monkeypatch.setattr(caller, "rollback", rollback_spy)
        await notify(uid, db=caller)
        assert caller.in_transaction()
        send.assert_not_awaited()
        commit_spy.assert_not_awaited()
        rollback_spy.assert_not_awaited()
        if commit:
            await caller.commit()
        else:
            await caller.rollback()
    async with sessions() as db:
        expected = "pending" if commit and state != "read_only" else "original"
        assert (await db.get(User, uid)).phone == expected
    assert not await rows(sessions)
    assert "requires post-commit invocation" in caplog.text


@pytest.mark.asyncio
async def test_default_hook_does_not_commit_unrelated_pending_caller_work(hook_db):
    sessions, uid = hook_db
    async with sessions() as caller:
        user = await caller.get(User, uid)
        user.phone = "pending"
        await notify(uid)
        assert caller.in_transaction() and user in caller.dirty
        async with sessions() as db:
            assert (await db.get(User, uid)).phone == "original"
        await caller.rollback()
    assert len(await rows(sessions)) == 2
    async with sessions() as db:
        assert (await db.get(User, uid)).phone == "original"


@pytest.mark.asyncio
async def test_sql_failure_in_owned_session_does_not_abort_caller(
    hook_db, monkeypatch, caplog
):
    sessions, uid = hook_db
    original = Service.send

    async def failing_send(service, *args, **kwargs):
        def fail_commit(session):
            session.execute(
                text("SELECT private_missing_hook_column FROM notification_logs")
            )

        event.listen(service.db.sync_session, "before_commit", fail_commit)
        try:
            return await original(service, *args, **kwargs)
        finally:
            event.remove(service.db.sync_session, "before_commit", fail_commit)

    monkeypatch.setattr(Service, "send", failing_send)
    async with sessions() as caller:
        user = await caller.get(User, uid)
        user.phone = "committed-business"
        await notify(uid)
        assert caller.in_transaction() and user in caller.dirty
        await caller.commit()
    async with sessions() as db:
        assert (await db.get(User, uid)).phone == "committed-business"
    assert not await rows(sessions)
    assert "private_missing_hook_column" not in caplog.text


@pytest.mark.asyncio
async def test_connection_bound_session_is_not_reused(hook_db, monkeypatch, caplog):
    sessions, uid = hook_db
    send = AsyncMock()
    monkeypatch.setattr(Service, "send", send)
    async with sessions() as owner:
        async with owner.bind.connect() as connection:
            async with AsyncSession(bind=connection) as caller:
                await notify(uid, db=caller)
                send.assert_not_awaited()
                assert not caller.in_transaction() and not connection.in_transaction()
                assert (
                    await connection.scalar(select(User.id).where(User.id == uid))
                    == uid
                )
    assert "requires an engine-bound session" in caplog.text


@pytest.mark.asyncio
async def test_failure_opening_own_session_is_sanitized(monkeypatch, caplog):
    factory = MagicMock(side_effect=RuntimeError("private address token password"))
    monkeypatch.setattr(database, "AsyncSessionLocal", factory)
    await notify(uuid4())
    factory.assert_called_once()
    assert "Notification hook failed" in caplog.text
    assert "private" not in caplog.text


@pytest.mark.asyncio
async def test_no_recipient_opens_no_session(monkeypatch):
    factory = MagicMock(side_effect=AssertionError("Must not open a connection"))
    monkeypatch.setattr(database, "AsyncSessionLocal", factory)
    await notify(None)
    factory.assert_not_called()
