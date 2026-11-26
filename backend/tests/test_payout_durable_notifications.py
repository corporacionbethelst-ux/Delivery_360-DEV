"""Financial state and visible inbox/provider queue form one transaction."""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, func, event, update

from tests.test_ledger_integrity import payout_context, ledger_context  # noqa: F401
from tests.test_reconciliation_safety import reconciliation_context  # noqa: F401
from app.api.v1 import payouts as api
from app.core.config import settings
from app.models.notification import (
    NotificationLog,
    NotificationTemplate,
    NotificationChannel as Channel,
    OmnichannelStatus as Status,
    NotificationPreference,
    utc_now_naive,
)
from app.models.financial import Financial
from app.models.payout import Payout, PayoutStatus
from app.services.payout_notifications import enqueue_payout_notice
from app.services.omnichannel_service import OmnichannelNotificationService as Service


async def approve(ctx):
    db, _, user, pid = ctx
    return await api.approve_payout(str(pid), db=db, current_user=user)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["approved", "rejected"])
async def test_decision_persists_one_visible_notice_and_replay_does_not_duplicate(
    payout_context, monkeypatch, action
):
    db, _, user, pid = payout_context
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", False)
    if action == "approved":
        await approve(payout_context)
    else:
        await api.reject_payout(
            str(pid), api.PayoutRejectBody(reason="Revisión"), db=db, current_user=user
        )
    notice = (await db.scalars(select(NotificationLog))).one()
    assert notice.user_id == user.id and notice.payout_id == pid
    assert notice.channel == Channel.IN_APP and notice.status == Status.ENVIADO
    assert notice.next_retry_at is None
    assert "30.00 USD" in notice.body
    if action == "approved":
        assert "no confirma una transferencia" in notice.body
    original = notice.id
    notice.created_at = utc_now_naive() - timedelta(days=10)
    notice.status = Status.LEIDO
    await db.commit()
    payout = await db.get(Payout, pid)
    await enqueue_payout_notice(
        db, payout, action, "Revisión" if action == "rejected" else ""
    )
    await db.commit()
    saved = (await db.scalars(select(NotificationLog))).one()
    assert saved.id == original and saved.status == Status.LEIDO


@pytest.mark.asyncio
async def test_notice_insert_failure_rolls_back_approval_and_debit(
    payout_context, monkeypatch
):
    db, _, _, pid = payout_context
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", False)
    before = await db.scalar(select(func.count()).select_from(Financial))

    def fail(*args):
        raise RuntimeError("notice write failed")

    event.listen(NotificationLog, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="notice write failed"):
            await approve(payout_context)
    finally:
        event.remove(NotificationLog, "before_insert", fail)
        await db.rollback()
    assert await db.scalar(select(func.count()).select_from(Financial)) == before
    assert (await db.get(Payout, pid)).status == PayoutStatus.PENDIENTE
    assert await db.scalar(select(func.count()).select_from(NotificationLog)) == 0


@pytest.mark.asyncio
async def test_provider_records_are_durable_without_dispatch_and_respect_preferences(
    payout_context, monkeypatch
):
    db, _, user, _ = payout_context
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True)
    push, email = AsyncMock(), AsyncMock()
    monkeypatch.setattr(Service, "dispatch_push", push)
    monkeypatch.setattr(Service, "dispatch_email", email)
    db.add(
        NotificationTemplate(
            code="payout_aprobado",
            channel=Channel.EMAIL,
            body_template="Importe {{amount_label}}",
            is_active=True,
        )
    )
    db.add(
        NotificationPreference(
            user_id=user.id,
            event_code="payout_aprobado",
            channel=Channel.PUSH,
            enabled=False,
        )
    )
    await db.commit()
    await approve(payout_context)
    logs = list((await db.scalars(select(NotificationLog))).all())
    assert {r.channel for r in logs} == {Channel.IN_APP, Channel.EMAIL}
    pending = next(r for r in logs if r.channel == Channel.EMAIL)
    assert pending.status == Status.PENDIENTE and pending.next_retry_at is not None
    assert pending.body == "Importe 30.00 USD"
    push.assert_not_awaited()
    email.assert_not_awaited()
    # A later consumer resumes the persisted row after a simulated restart.
    from app.models.user import UserRole
    from app.services import terminal_notifications

    # The administrative fixture approves the request above. Dispatch requires
    # the recipient to still have the operational rider role and valid SMTP.
    user.role = UserRole.REPARTIDOR
    user.email = "rider@example.com"
    await db.commit()
    monkeypatch.setattr(
        terminal_notifications, "smtp_email_is_configured", lambda *a: True
    )
    email.return_value = True
    monkeypatch.setattr(Service, "_publish_new_notification", AsyncMock())
    assert await Service(db, redis_client=False).process_retry_queue() == 1
    assert pending.status == Status.ENVIADO and pending.next_retry_at is None
    email.assert_awaited_once()


@pytest.mark.asyncio
async def test_unsafe_legacy_money_template_is_retained_for_review_without_send(
    payout_context, monkeypatch
):
    db, _, _, _ = payout_context
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True)
    db.add(
        NotificationTemplate(
            code="payout_aprobado",
            channel=Channel.PUSH,
            body_template="Monto ${{amount_cents}}",
            is_active=True,
        )
    )
    await db.commit()
    await approve(payout_context)
    logs = list((await db.scalars(select(NotificationLog))).all())
    assert any(r.channel == Channel.IN_APP and r.status == Status.ENVIADO for r in logs)
    external = [r for r in logs if r.channel != Channel.IN_APP]
    assert external and all(
        r.status == Status.FALLIDO
        and r.next_retry_at is None
        and "requiere revisión" in r.error_message
        for r in external
    )


@pytest.mark.asyncio
async def test_retention_keeps_old_pending_and_paused_queue_records(payout_context):
    db, _, user, pid = payout_context
    old = utc_now_naive() - timedelta(days=100)
    for status, due, key in [
        (Status.PENDIENTE, old, "pending"),
        (Status.PENDIENTE, None, "paused"),
        (Status.ENVIADO, None, "done"),
    ]:
        db.add(
            NotificationLog(
                user_id=user.id,
                payout_id=pid,
                channel=Channel.EMAIL,
                status=status,
                created_at=old,
                next_retry_at=due,
                dedupe_key=key,
            )
        )
    await db.commit()
    assert await Service(db, redis_client=False).purge_old_logs() == 1
    assert set((await db.scalars(select(NotificationLog.dedupe_key))).all()) == {
        "pending",
        "paused",
    }
