"""Assignment/payout outboxes use durable claims without moving any money."""

import asyncio
import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_delivery_financial_postgresql import payment_db  # noqa: F401
from tests.test_order_cancellation_postgresql import cancel_db  # noqa: F401
from tests.test_sla_monitor_postgresql import sla_db  # noqa: F401
from tests.test_runtime_contracts_postgresql import runtime_db  # noqa: F401
from tests.test_assignment_eligibility_postgresql import (
    assignment_db,
    request,
)  # noqa: F401
from tests.test_terminal_external_postgresql import headers, review, worker
from app.core.config import settings
from app.models.audit_log import AuditLog, ActionType
from app.models.financial import Financial
from app.models.notification import (
    NotificationLog,
    NotificationTemplate,
    UserDeviceToken,
    NotificationChannel as C,
    OmnichannelStatus as S,
    utc_now_naive,
)
from app.models.order import Order, OrderStatus
from app.models.payout import Payout, PayoutStatus
from app.models.user import User, UserRole
from app.services import terminal_notifications as durable
from app.services.omnichannel_service import OmnichannelNotificationService as Service
from app.services.payout_notifications import enqueue_payout_notice

EVENTS = {
    "assignment": "nuevo_pedido_asignado",
    "requested": "payout_solicitado",
    "approved": "payout_aprobado",
    "rejected": "payout_rechazado",
}
STATES = {
    "requested": PayoutStatus.PENDIENTE,
    "approved": PayoutStatus.EN_PROCESO,
    "rejected": PayoutStatus.RECHAZADO,
}


@pytest.fixture
async def managed_db(assignment_db, monkeypatch):
    client, sessions, ids = assignment_db
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True)
    monkeypatch.setattr(settings, "TWILIO_ACCOUNT_SID", "synthetic")
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "synthetic")
    monkeypatch.setattr(settings, "TWILIO_FROM_NUMBER", "+15555550100")
    monkeypatch.setattr(settings, "FCM_CREDENTIALS_JSON_PATH", "/mocked-only.json")
    monkeypatch.setattr(durable, "smtp_email_is_configured", lambda *a: True)
    for method in ("dispatch_email", "dispatch_sms", "dispatch_push"):
        monkeypatch.setattr(Service, method, AsyncMock(return_value=True))
    async with sessions() as db:
        connection = await db.connection()
        await connection.run_sync(
            lambda c: UserDeviceToken.__table__.create(c, checkfirst=True)
        )
        user = await db.get(User, ids["owner"])
        user.email, user.phone = "rider@example.com", "+15555550123"
        db.add(
            UserDeviceToken(
                user_id=user.id,
                device_token="managed-test-token",
                platform="android",
                is_active=True,
            )
        )
        for name, code in EVENTS.items():
            db.add(
                NotificationTemplate(
                    code=code,
                    channel=C.EMAIL,
                    is_active=True,
                    subject="Aviso operativo",
                    body_template=(
                        "Orden {{order_code}}"
                        if name == "assignment"
                        else "Solicitud {{amount_label}}: {{status}}"
                    ),
                )
            )
        await db.commit()
    return assignment_db


async def enqueue(ctx, name, channel=C.EMAIL):
    client, sessions, ids = ctx
    async with sessions() as db:
        await db.execute(
            update(NotificationTemplate)
            .where(NotificationTemplate.code == EVENTS[name])
            .values(channel=channel)
        )
        await db.commit()
    if name == "assignment":
        response = request(client, ids, "manual")
        assert response.status_code == 200, response.text
    else:
        async with sessions() as db:
            payout = Payout(
                id=uuid4(),
                rider_id=ids["rider"],
                amount=Decimal("10.01"),
                currency_code="USD",
                status=STATES[name],
            )
            db.add(payout)
            await db.flush()
            await enqueue_payout_notice(db, payout, name)
            await db.commit()
    async with sessions() as db:
        return await db.scalar(
            select(NotificationLog).where(
                NotificationLog.template_code == EVENTS[name],
                NotificationLog.channel != C.IN_APP,
            )
        )


async def reload(sessions, log):
    async with sessions() as db:
        return await db.get(NotificationLog, log.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", EVENTS)
@pytest.mark.parametrize("channel", [C.EMAIL, C.PUSH, C.SMS])
async def test_each_domain_channel_is_transactional_and_one_shot(
    managed_db, name, channel
):
    client, sessions, ids = managed_db
    log = await enqueue(managed_db, name, channel)
    for method in ("dispatch_email", "dispatch_sms", "dispatch_push"):
        getattr(Service, method).assert_not_awaited()
    async with sessions() as db:
        before = await db.scalar(select(func.count()).select_from(Financial))
    assert await worker(sessions) == 1
    saved = await reload(sessions, log)
    assert (
        saved.status == S.ENVIADO
        and saved.retry_count == 1
        and saved.next_retry_at is None
    )
    assert json.loads(saved.payload_json)["dispatch"]["state"] == "accepted"
    assert await worker(sessions) == 0
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Financial)) == before
        if name != "assignment":
            payout = await db.get(Payout, saved.payout_id)
            assert payout.status == STATES[name] and payout.amount == Decimal("10.01")
            await enqueue_payout_notice(db, payout, name)
            await db.commit()
            assert (
                await db.scalar(select(func.count()).select_from(NotificationLog)) == 2
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("name", EVENTS)
@pytest.mark.parametrize("fault", ["false", "exception", "ack_commit"])
async def test_unknown_result_never_resends_and_review_is_idempotent(
    managed_db, monkeypatch, name, fault
):
    client, sessions, ids = managed_db
    log = await enqueue(managed_db, name)
    async with sessions() as db:
        service = Service(db, redis_client=False)
        original = db.commit

        async def provider(*args):
            db.info["ack_fault"] = True
            if fault == "exception":
                raise RuntimeError("response lost")
            return fault == "ack_commit"

        async def commit():
            if fault == "ack_commit" and db.info.get("ack_fault"):
                raise RuntimeError("acknowledgement commit lost")
            await original()

        monkeypatch.setattr(service, "dispatch_email", AsyncMock(side_effect=provider))
        monkeypatch.setattr(db, "commit", commit)
        if fault == "false":
            assert await service.process_retry_queue() == 1
        else:
            with pytest.raises(RuntimeError):
                await service.process_retry_queue()
    saved = await reload(sessions, log)
    assert saved.status == S.PENDIENTE and saved.next_retry_at is None
    assert await worker(sessions) == 0
    Service.dispatch_email.assert_not_awaited()
    result, body = review(client, ids, saved)
    assert result.status_code == 200, result.text
    assert review(client, ids, saved, body=body)[0].status_code == 200
    changed = {**body, "reference": "Different reference"}
    assert review(client, ids, saved, body=changed)[0].status_code == 409
    async with sessions() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.resource_type == "external_notification_review")
            )
            == 1
        )
        assert (await db.get(NotificationLog, log.id)).status == S.ENVIADO
    assert await worker(sessions) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("name", EVENTS)
async def test_two_workers_cannot_send_the_same_record(managed_db, monkeypatch, name):
    _, sessions, _ = managed_db
    log = await enqueue(managed_db, name)
    started, release = asyncio.Event(), asyncio.Event()

    async def provider(*args):
        started.set()
        await release.wait()
        return True

    mock = AsyncMock(side_effect=provider)
    monkeypatch.setattr(Service, "dispatch_email", mock)
    first = asyncio.create_task(worker(sessions))
    try:
        await asyncio.wait_for(started.wait(), 5)
        assert await asyncio.wait_for(worker(sessions), 5) == 0
    finally:
        release.set()
        await first
    mock.assert_awaited_once()
    assert (await reload(sessions, log)).status == S.ENVIADO


@pytest.mark.asyncio
@pytest.mark.parametrize("name", EVENTS)
async def test_unversioned_historical_work_is_retained_without_inventing_an_attempt(
    managed_db, name
):
    client, sessions, ids = managed_db
    log = await enqueue(managed_db, name)
    async with sessions() as db:
        saved = await db.get(NotificationLog, log.id)
        payload = json.loads(saved.payload_json)
        del payload["dispatch"]
        saved.payload_json = json.dumps(payload)
        saved.retry_count = 2
        await db.commit()
    assert await worker(sessions) == 1
    saved = await reload(sessions, log)
    assert (
        saved.status == S.FALLIDO
        and saved.next_retry_at is None
        and saved.retry_count == 2
    )
    Service.dispatch_email.assert_not_awaited()
    result = client.get(
        "/api/v1/notifications/terminal-dispatch/review", headers=headers(ids)
    )
    assert result.status_code == 200
    row = next(item for item in result.json()["items"] if item["id"] == str(log.id))
    assert row["state"] == "invalid" and row["attempt_id"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["status", "amount", "currency", "owner"])
async def test_changed_payout_cannot_send_a_stale_financial_notice(managed_db, change):
    _, sessions, ids = managed_db
    log = await enqueue(managed_db, "approved")
    async with sessions() as db:
        payout = await db.get(Payout, log.payout_id)
        if change == "status":
            payout.status = PayoutStatus.COMPLETADO
        if change == "amount":
            payout.amount = Decimal("10.02")
        if change == "currency":
            payout.currency_code = None
        if change == "owner":
            user = await db.get(User, ids["owner"])
            user.role = UserRole.OPERADOR
        await db.commit()
    assert await worker(sessions) == 1
    assert (await reload(sessions, log)).status == S.FALLIDO
    Service.dispatch_email.assert_not_awaited()


@pytest.mark.asyncio
async def test_assignment_to_same_rider_after_new_event_invalidates_old_notice(
    managed_db,
):
    _, sessions, ids = managed_db
    log = await enqueue(managed_db, "assignment")
    async with sessions() as db:
        db.add(
            AuditLog(
                user_id=ids["staff"],
                action_type=ActionType.REASSIGN,
                resource_type="ORDER",
                resource_id=str(ids["order"]),
                success=True,
                description="Later assignment back to same rider",
            )
        )
        await db.commit()
    assert await worker(sessions) == 1
    assert (await reload(sessions, log)).status == S.FALLIDO
    Service.dispatch_email.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", EVENTS)
async def test_business_events_cannot_bypass_queue_or_delete_external_history(
    managed_db, name
):
    client, sessions, ids = managed_db
    log = await enqueue(managed_db, name)
    async with sessions() as db:
        assert (
            await Service(db, redis_client=False).send(ids["owner"], EVENTS[name], {})
            == []
        )
    response = client.post(
        "/api/v1/notifications/test-send",
        json={"template_code": EVENTS[name]},
        headers=headers(ids),
    )
    assert response.status_code == 409
    assert (
        client.delete(
            f"/api/v1/notifications/{log.id}", headers=headers(ids, "owner")
        ).status_code
        == 409
    )
    assert (
        client.patch(
            f"/api/v1/notifications/{log.id}/read", headers=headers(ids, "owner")
        ).status_code
        == 409
    )
    Service.dispatch_email.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", EVENTS)
async def test_claim_commit_failure_calls_no_provider_and_can_resume(
    managed_db, monkeypatch, name
):
    _, sessions, _ = managed_db
    log = await enqueue(managed_db, name)
    async with sessions() as db:
        monkeypatch.setattr(
            db, "commit", AsyncMock(side_effect=RuntimeError("claim commit failed"))
        )
        with pytest.raises(RuntimeError):
            await Service(db, redis_client=False).process_retry_queue()
    Service.dispatch_email.assert_not_awaited()
    assert (
        json.loads((await reload(sessions, log)).payload_json)["dispatch"]["state"]
        == "queued"
    )
    assert await worker(sessions) == 1
    Service.dispatch_email.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", EVENTS)
async def test_retention_preserves_technical_and_uncertain_holds(
    managed_db, monkeypatch, name
):
    client, sessions, ids = managed_db
    log = await enqueue(managed_db, name)
    Service.dispatch_email.return_value = False
    assert await worker(sessions) == 1
    async with sessions() as db:
        saved = await db.get(NotificationLog, log.id)
        saved.created_at = utc_now_naive() - timedelta(days=1000)
        await db.commit()
        assert await Service(db, redis_client=False).purge_old_logs() >= 0
        assert await db.get(NotificationLog, log.id) is not None
    result, _ = review(client, ids, await reload(sessions, log), decision="unconfirmed")
    assert result.status_code == 200
    async with sessions() as db:
        saved = await db.get(NotificationLog, log.id)
        saved.status = S.FALLIDO
        await db.commit()
        await Service(db, redis_client=False).purge_old_logs()
    saved = await reload(sessions, log)
    assert saved is not None and saved.status == S.FALLIDO
    assert await worker(sessions) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("name", STATES)
async def test_payout_queue_rollback_never_changes_ledger_or_leaves_half_notice(
    managed_db, name
):
    _, sessions, ids = managed_db
    async with sessions() as db:
        count = await db.scalar(select(func.count()).select_from(Financial))
        payout = Payout(
            id=uuid4(),
            rider_id=ids["rider"],
            amount=Decimal("10.01"),
            currency_code="USD",
            status=STATES[name],
        )
        db.add(payout)
        await db.flush()
        await enqueue_payout_notice(db, payout, name)
        await db.rollback()
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(NotificationLog)) == 0
        assert await db.scalar(select(func.count()).select_from(Financial)) == count
    Service.dispatch_email.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", STATES)
async def test_enabling_provider_does_not_backfill_a_replayed_payout_event(
    managed_db, monkeypatch, name
):
    _, sessions, ids = managed_db
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", False)
    async with sessions() as db:
        payout = Payout(
            id=uuid4(),
            rider_id=ids["rider"],
            amount=Decimal("10.01"),
            currency_code="USD",
            status=STATES[name],
        )
        db.add(payout)
        await db.flush()
        await enqueue_payout_notice(db, payout, name)
        await db.commit()
        monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True)
        await enqueue_payout_notice(db, payout, name)
        await db.commit()
        rows = list((await db.scalars(select(NotificationLog))).all())
        assert len(rows) == 1 and rows[0].channel == C.IN_APP
    assert await worker(sessions) == 0
    Service.dispatch_email.assert_not_awaited()
