"""Native SQL policy changes must take effect before queued provider calls."""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, select, text, update
from sqlalchemy.exc import SQLAlchemyError

from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from tests.test_notification_dispatch_postgresql import dispatch_db  # noqa: F401
from app.core.config import settings
from app.models.user import User
from app.models.notification import (
    NotificationChannel as Channel,
    NotificationLog,
    NotificationPreference,
    NotificationTemplate,
    OmnichannelStatus as Status,
    utc_now_naive,
)
from app.services.omnichannel_service import OmnichannelNotificationService as Service

EXTERNAL = [Channel.EMAIL, Channel.PUSH, Channel.SMS]


async def queued(sessions, uid, channel=Channel.EMAIL, code="transaction_test"):
    async with sessions() as db:
        row = NotificationLog(
            user_id=uid,
            channel=channel,
            template_code=code,
            title="Persisted title",
            body="Persisted body",
            status=Status.PENDIENTE,
            retry_count=2,
            next_retry_at=utc_now_naive() - timedelta(minutes=1),
            error_message="Previous provider failure",
        )
        db.add(row)
        await db.commit()
        return row.id


def providers(db):
    svc = Service(db, redis_client=False)
    for name in ["dispatch_email", "dispatch_push", "dispatch_sms"]:
        setattr(svc, name, AsyncMock(return_value=True))
    return svc


def no_provider(svc):
    for name in ["dispatch_email", "dispatch_push", "dispatch_sms"]:
        getattr(svc, name).assert_not_awaited()


async def snapshot(sessions, key):
    async with sessions() as db:
        return await db.get(NotificationLog, key)


def stopped(row, reason):
    assert row.status == Status.FALLIDO
    assert row.error_message == reason
    assert row.next_retry_at is None and row.retry_count == 2
    assert row.sent_at is None and row.delivered_at is None
    assert row.body == "Persisted body"


@pytest.mark.parametrize("channel", list(Channel))
async def test_account_deactivation_stops_every_queued_channel(dispatch_db, channel):
    sessions, uid = dispatch_db
    key = await queued(sessions, uid, channel)
    async with sessions() as db:
        await db.execute(update(User).where(User.id == uid).values(is_active=False))
        await db.commit()
    async with sessions() as db:
        svc = providers(db)
        assert await svc.process_retry_queue() == 1
        no_provider(svc)
    stopped(await snapshot(sessions, key), "Cuenta inactiva en reintento")


async def test_initial_send_rejects_deactivated_account_despite_loaded_user(
    dispatch_db,
):
    sessions, uid = dispatch_db
    async with sessions() as db:
        old = await db.get(User, uid)
        assert old.is_active
        async with sessions() as writer:
            await writer.execute(
                update(User).where(User.id == uid).values(is_active=False)
            )
            await writer.commit()
        svc = providers(db)
        assert await svc.send(uid, "transaction_test", {}, channels=EXTERNAL) == []
        no_provider(svc)
    async with sessions() as db:
        assert not list((await db.scalars(select(NotificationLog))).all())


@pytest.mark.parametrize("channel", EXTERNAL)
async def test_revoked_preference_stops_only_persisted_event_channel(
    dispatch_db, channel
):
    sessions, uid = dispatch_db
    key = await queued(sessions, uid, channel)
    async with sessions() as db:
        db.add(
            NotificationPreference(
                user_id=uid,
                event_code="transaction_test",
                channel=channel,
                enabled=False,
            )
        )
        await db.commit()
    async with sessions() as db:
        svc = providers(db)
        assert await svc.process_retry_queue() == 1
        no_provider(svc)
    stopped(await snapshot(sessions, key), "Canal deshabilitado por preferencia")
    # A later opt-in does not resurrect the historical rejected delivery.
    async with sessions() as db:
        await db.execute(update(NotificationPreference).values(enabled=True))
        await db.commit()
        assert await providers(db).process_retry_queue() == 0


@pytest.mark.parametrize("different", ["user", "event", "channel"])
async def test_unrelated_opt_out_does_not_block_eligible_delivery(
    dispatch_db, different
):
    sessions, uid = dispatch_db
    key = await queued(sessions, uid)
    async with sessions() as db:
        other = await db.scalar(select(User.id).where(User.id != uid))
        db.add(
            NotificationPreference(
                user_id=other if different == "user" else uid,
                event_code=(
                    "another_event" if different == "event" else "transaction_test"
                ),
                channel=Channel.PUSH if different == "channel" else Channel.EMAIL,
                enabled=False,
            )
        )
        await db.commit()
    async with sessions() as db:
        svc = providers(db)
        assert await svc.process_retry_queue() == 1
        svc.dispatch_email.assert_awaited_once_with(
            (await db.get(User, uid)).email, "Persisted title", "Persisted body"
        )
    row = await snapshot(sessions, key)
    assert row.status == Status.ENVIADO and row.sent_at is not None
    assert row.error_message is None and row.next_retry_at is None


@pytest.mark.parametrize("missing", [False, True])
async def test_withdrawn_template_stops_retry(dispatch_db, missing):
    sessions, uid = dispatch_db
    key = await queued(sessions, uid, code="missing" if missing else "transaction_test")
    if not missing:
        async with sessions() as db:
            await db.execute(update(NotificationTemplate).values(is_active=False))
            await db.commit()
    async with sessions() as db:
        svc = providers(db)
        assert await svc.process_retry_queue() == 1
        no_provider(svc)
    stopped(await snapshot(sessions, key), "Plantilla no disponible en reintento")


@pytest.mark.parametrize("policy", ["user", "template", "preference"])
async def test_preloaded_policy_does_not_hide_committed_revocation(dispatch_db, policy):
    sessions, uid = dispatch_db
    key = await queued(sessions, uid)
    async with sessions() as db:
        db.add(
            NotificationPreference(
                user_id=uid,
                event_code="transaction_test",
                channel=Channel.EMAIL,
                enabled=True,
            )
        )
        await db.commit()
    async with sessions() as db:
        # Hold ORM identities and a stale template cache across a SQL revocation.
        user = await db.get(User, uid)
        tpl = await db.scalar(select(NotificationTemplate))
        pref = await db.scalar(select(NotificationPreference))
        assert user.is_active and tpl.is_active and pref.enabled
        svc = providers(db)
        svc._get_template = AsyncMock(return_value=tpl)
        async with sessions() as writer:
            if policy == "user":
                query = update(User).where(User.id == uid).values(is_active=False)
            elif policy == "template":
                query = update(NotificationTemplate).values(is_active=False)
            else:
                query = update(NotificationPreference).values(enabled=False)
            await writer.execute(query)
            await writer.commit()
        assert await svc.process_retry_queue() == 1
        no_provider(svc)
        svc._get_template.assert_not_awaited()
    row = await snapshot(sessions, key)
    assert row.status == Status.FALLIDO and row.sent_at is None


@pytest.mark.parametrize("channel", EXTERNAL)
async def test_master_pause_defers_without_attempts_and_can_resume(
    dispatch_db, monkeypatch, channel
):
    sessions, uid = dispatch_db
    key = await queued(sessions, uid, channel)
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", False)
    async with sessions() as db:
        svc = providers(db)
        assert await svc.process_retry_queue() == 1
        assert await svc.process_retry_queue() == 0
        no_provider(svc)
    row = await snapshot(sessions, key)
    assert row.status == Status.PENDIENTE and row.retry_count == 2
    assert row.next_retry_at > utc_now_naive() and row.sent_at is None
    assert row.error_message == "Reintento pausado por configuración"
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True)
    async with sessions() as db:
        await db.execute(
            update(NotificationLog)
            .where(NotificationLog.id == key)
            .values(next_retry_at=utc_now_naive() - timedelta(seconds=1))
        )
        await db.commit()
        svc = providers(db)
        assert await svc.process_retry_queue() == 1
        assert (
            sum(
                getattr(svc, name).await_count
                for name in ["dispatch_email", "dispatch_push", "dispatch_sms"]
            )
            == 1
        )
    row = await snapshot(sessions, key)
    assert row.status == Status.ENVIADO and row.retry_count == 2
    assert row.error_message is None and row.next_retry_at is None


async def test_in_app_retains_opt_out_exception_during_master_pause(
    dispatch_db, monkeypatch
):
    sessions, uid = dispatch_db
    key = await queued(sessions, uid, Channel.IN_APP)
    async with sessions() as db:
        db.add(
            NotificationPreference(
                user_id=uid,
                event_code="transaction_test",
                channel=Channel.IN_APP,
                enabled=False,
            )
        )
        await db.commit()
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", False)
    async with sessions() as db:
        svc = providers(db)
        assert await svc.process_retry_queue() == 1
        no_provider(svc)
    row = await snapshot(sessions, key)
    assert row.status == Status.ENVIADO and row.sent_at is not None


async def test_legacy_null_template_retries_persisted_payload(dispatch_db):
    sessions, uid = dispatch_db
    key = await queued(sessions, uid, code=None)
    async with sessions() as db:
        svc = providers(db)
        assert await svc.process_retry_queue() == 1
        svc.dispatch_email.assert_awaited_once()
    assert (await snapshot(sessions, key)).status == Status.ENVIADO


async def test_policy_result_rolls_back_on_real_sql_commit_error(dispatch_db):
    sessions, uid = dispatch_db
    key = await queued(sessions, uid)
    async with sessions() as db:
        await db.execute(update(User).where(User.id == uid).values(is_active=False))
        await db.commit()
    async with sessions() as db:
        svc = providers(db)

        def fail(session):
            session.execute(text("SELECT nonexistent_retry_policy_column"))

        event.listen(db.sync_session, "before_commit", fail)
        try:
            with pytest.raises(SQLAlchemyError):
                await svc.process_retry_queue()
        finally:
            event.remove(db.sync_session, "before_commit", fail)
        no_provider(svc)
        assert await db.scalar(text("SELECT 1")) == 1
    assert (await snapshot(sessions, key)).status == Status.PENDIENTE
    async with sessions() as db:
        assert await providers(db).process_retry_queue() == 1
    stopped(await snapshot(sessions, key), "Cuenta inactiva en reintento")
