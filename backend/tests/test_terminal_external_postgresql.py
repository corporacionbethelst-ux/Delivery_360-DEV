"""Closure outbox commits before I/O and unknown acceptance never resends."""

import asyncio
import json
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_delivery_financial_postgresql import payment_db, request  # noqa: F401
from tests.test_order_cancellation_postgresql import cancel_db  # noqa: F401
from tests.test_failure_cancellation_notices_postgresql import invoke
from app.core.config import settings
from app.core.security import create_access_token
from app.models.audit_log import AuditLog
from app.models.delivery import Delivery, DeliveryStatus
from app.models.financial import Financial
from app.models.notification import (
    NotificationLog,
    NotificationTemplate,
    NotificationPreference,
    UserDeviceToken,
    NotificationChannel as C,
    OmnichannelStatus as S,
    utc_now_naive,
)
from app.models.order import Order, OrderStatus
from app.models.user import User, UserRole
from app.services import terminal_notifications as terminal
from app.services.omnichannel_service import OmnichannelNotificationService as Service

CODES = {
    "complete": "entrega_completada",
    "fail": "entrega_fallida",
    "cancel": "orden_cancelada",
}


@pytest.fixture
async def terminal_db(cancel_db, monkeypatch):
    client, sessions, ids = cancel_db
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True)
    monkeypatch.setattr(terminal, "smtp_email_is_configured", lambda *a: True)
    for name in ("dispatch_email", "dispatch_sms", "dispatch_push"):
        monkeypatch.setattr(Service, name, AsyncMock(return_value=True))
    async with sessions() as db:
        conn = await db.connection()
        await conn.run_sync(
            lambda c: UserDeviceToken.__table__.create(c, checkfirst=True)
        )
        owner = await db.get(User, ids["owner"])
        owner.email = "rider@example.com"
        owner.phone = "+15555550123"
        db.add(
            UserDeviceToken(
                user_id=ids["owner"],
                device_token="synthetic-device",
                platform="android",
                is_active=True,
            )
        )
        for code in CODES.values():
            db.add(
                NotificationTemplate(
                    code=code,
                    channel=C.EMAIL,
                    is_active=True,
                    subject="Cierre {{order_code}}",
                    body_template="Aviso {{event}} para {{order_code}}",
                )
            )
        await db.commit()
    return cancel_db


def close(client, ids, event):
    return (
        request(client, ids, "service_success")
        if event == "complete"
        else invoke(client, ids, "legacy" if event == "fail" else "cancel")
    )


async def external(sessions):
    async with sessions() as db:
        return await db.scalar(
            select(NotificationLog).where(NotificationLog.channel != C.IN_APP)
        )


async def worker(sessions):
    async with sessions() as db:
        return await Service(db, redis_client=False).process_retry_queue(5)


def headers(ids, actor="staff"):
    return {"Authorization": "Bearer " + create_access_token(ids[actor])}


def review(client, ids, log, decision="accepted", body=None):
    data = body or dict(
        review_id=str(uuid4()),
        attempt_id=json.loads(log.payload_json)["dispatch"]["attempt_id"],
        decision=decision,
        reference="Proveedor caso-1234",
        note="Verificación del registro externo",
    )
    return (
        client.post(
            f"/api/v1/notifications/terminal-dispatch/{log.id}/review",
            json=data,
            headers=headers(ids),
        ),
        data,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("event", CODES)
@pytest.mark.parametrize("channel", [C.EMAIL, C.SMS, C.PUSH])
async def test_each_closure_queues_configured_channel_without_io_and_dispatches_once(
    terminal_db, monkeypatch, event, channel
):
    client, sessions, ids = terminal_db
    monkeypatch.setattr(settings, "TWILIO_ACCOUNT_SID", "synthetic")
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "synthetic")
    monkeypatch.setattr(settings, "TWILIO_FROM_NUMBER", "+15555550100")
    monkeypatch.setattr(
        settings, "FCM_CREDENTIALS_JSON_PATH", "/not-used-mocked-provider.json"
    )
    async with sessions() as db:
        await db.execute(
            update(NotificationTemplate)
            .where(NotificationTemplate.code == CODES[event])
            .values(channel=channel)
        )
        await db.commit()
    result = close(client, ids, event)
    assert result.status_code == 200, result.text
    for name in ("dispatch_email", "dispatch_sms", "dispatch_push"):
        getattr(Service, name).assert_not_awaited()
    log = await external(sessions)
    assert (
        log.channel == channel
        and log.status == S.PENDIENTE
        and log.next_retry_at is not None
    )
    assert json.loads(log.payload_json)["dispatch"] == {"version": 1, "state": "queued"}
    async with sessions() as db:
        count = await db.scalar(select(func.count()).select_from(Financial))
    assert await worker(sessions) == 1
    log = await external(sessions)
    assert (
        log.status == S.ENVIADO and log.next_retry_at is None and log.retry_count == 1
    )
    detail = json.loads(log.payload_json)["dispatch"]
    assert detail["state"] == "accepted" and UUID(detail["attempt_id"])
    assert len(detail["destination_sha256"]) == 64 and detail["destination_hint"]
    assert await worker(sessions) == 0
    name = {C.EMAIL: "dispatch_email", C.SMS: "dispatch_sms", C.PUSH: "dispatch_push"}[
        channel
    ]
    getattr(Service, name).assert_awaited_once()
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(NotificationLog)) == 2
        assert await db.scalar(select(func.count()).select_from(Financial)) == count


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    [
        "disabled",
        "inactive_template",
        "in_app_template",
        "preference",
        "unsafe",
        "missing_template",
    ],
)
async def test_planning_respects_policy_and_never_invents_template_variables(
    terminal_db, monkeypatch, mode
):
    client, sessions, ids = terminal_db
    async with sessions() as db:
        template = await db.scalar(
            select(NotificationTemplate).where(
                NotificationTemplate.code == CODES["complete"]
            )
        )
        if mode == "disabled":
            monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", False)
        if mode == "inactive_template":
            template.is_active = False
        if mode == "in_app_template":
            template.channel = C.IN_APP
        if mode == "missing_template":
            await db.delete(template)
        if mode == "unsafe":
            template.body_template = "Monto {{amount_cents}} y OTP {{otp_code}}"
        if mode == "preference":
            db.add(
                NotificationPreference(
                    user_id=ids["owner"],
                    event_code=CODES["complete"],
                    channel=C.EMAIL,
                    enabled=False,
                )
            )
        await db.commit()
    assert close(client, ids, "complete").status_code == 200
    log = await external(sessions)
    if mode == "unsafe":
        assert log.status == S.FALLIDO and log.next_retry_at is None
    else:
        assert log is None
    assert await worker(sessions) == 0
    Service.dispatch_email.assert_not_awaited()
    async with sessions() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(NotificationLog)
                .where(NotificationLog.channel == C.IN_APP)
            )
            == 1
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("event", CODES)
async def test_external_planning_failure_rolls_back_the_business_unit(
    terminal_db, monkeypatch, event
):
    client, sessions, ids = terminal_db
    original = terminal.enqueue_external

    async def broken(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("outbox insertion unavailable")

    monkeypatch.setattr(terminal, "enqueue_external", broken)
    assert close(client, ids, event).status_code == 500
    async with sessions() as db:
        assert (await db.get(Order, ids["order"])).status == OrderStatus.EN_RUTA
        assert (
            await db.get(Delivery, ids["delivery"])
        ).status == DeliveryStatus.EN_ROUTE
        assert await db.scalar(select(func.count()).select_from(NotificationLog)) == 0
        assert await db.scalar(select(func.count()).select_from(Financial)) == 1
    Service.dispatch_email.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [False, "truthy", "exception", "cancelled"])
async def test_uncertain_result_survives_restart_without_automatic_retry(
    terminal_db, outcome
):
    client, sessions, ids = terminal_db
    assert close(client, ids, "complete").status_code == 200
    if outcome in ("exception", "cancelled"):
        Service.dispatch_email.side_effect = (
            RuntimeError("provider unknown")
            if outcome == "exception"
            else asyncio.CancelledError()
        )
        with pytest.raises(
            RuntimeError if outcome == "exception" else asyncio.CancelledError
        ):
            await worker(sessions)
    else:
        Service.dispatch_email.return_value = outcome
        assert await worker(sessions) == 1
    log = await external(sessions)
    assert log.status == S.PENDIENTE and log.next_retry_at is None
    assert json.loads(log.payload_json)["dispatch"]["state"] == "uncertain"
    assert await worker(sessions) == 0
    Service.dispatch_email.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_ack_commit_keeps_durable_claim_instead_of_resending(
    terminal_db, monkeypatch
):
    client, sessions, ids = terminal_db
    assert close(client, ids, "complete").status_code == 200
    async with sessions() as db:
        service = Service(db, redis_client=False)
        original = db.commit

        async def provider(*args):
            db.info["ack_fault"] = True
            return True

        async def commit():
            if db.info.get("ack_fault"):
                raise RuntimeError("ack commit unavailable")
            await original()

        monkeypatch.setattr(service, "dispatch_email", AsyncMock(side_effect=provider))
        monkeypatch.setattr(db, "commit", commit)
        with pytest.raises(RuntimeError):
            await service.process_retry_queue()
        service.dispatch_email.assert_awaited_once()
    log = await external(sessions)
    assert log.status == S.PENDIENTE and log.next_retry_at is None
    assert await worker(sessions) == 0
    Service.dispatch_email.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_claim_commit_never_calls_provider_and_is_safe_to_retry(
    terminal_db, monkeypatch
):
    client, sessions, ids = terminal_db
    assert close(client, ids, "complete").status_code == 200
    async with sessions() as db:
        service = Service(db, redis_client=False)
        monkeypatch.setattr(
            db, "commit", AsyncMock(side_effect=RuntimeError("claim failed"))
        )
        with pytest.raises(RuntimeError):
            await service.process_retry_queue()
    log = await external(sessions)
    assert (
        log.next_retry_at is not None
        and json.loads(log.payload_json)["dispatch"]["state"] == "queued"
    )
    Service.dispatch_email.assert_not_awaited()
    assert await worker(sessions) == 1
    Service.dispatch_email.assert_awaited_once()


@pytest.mark.asyncio
async def test_second_worker_cannot_claim_row_during_provider_io(terminal_db):
    client, sessions, ids = terminal_db
    assert close(client, ids, "complete").status_code == 200
    entered, release = asyncio.Event(), asyncio.Event()

    async def provider(*args):
        entered.set()
        await release.wait()
        return True

    Service.dispatch_email.side_effect = provider
    async with asyncio.timeout(15):
        first = asyncio.create_task(worker(sessions))
        try:
            await entered.wait()
            assert await worker(sessions) == 0
        finally:
            release.set()
        assert await first == 1
    Service.dispatch_email.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "inactive",
        "role",
        "assignment",
        "status",
        "template",
        "channel",
        "preference",
        "pause",
        "configuration",
    ],
)
async def test_retry_revalidates_recipient_event_and_policy_before_io(
    terminal_db, monkeypatch, change
):
    client, sessions, ids = terminal_db
    assert close(client, ids, "complete").status_code == 200
    async with sessions() as db:
        if change == "inactive":
            await db.execute(
                update(User).where(User.id == ids["owner"]).values(is_active=False)
            )
        if change == "role":
            await db.execute(
                update(User)
                .where(User.id == ids["owner"])
                .values(role=UserRole.OPERADOR)
            )
        if change == "assignment":
            await db.execute(update(Order).values(assigned_rider_id=None))
        if change == "status":
            await db.execute(update(Order).values(status=OrderStatus.EN_RUTA))
        if change == "template":
            await db.execute(update(NotificationTemplate).values(is_active=False))
        if change == "channel":
            await db.execute(update(NotificationTemplate).values(channel=C.PUSH))
        if change == "preference":
            db.add(
                NotificationPreference(
                    user_id=ids["owner"],
                    event_code=CODES["complete"],
                    channel=C.EMAIL,
                    enabled=False,
                )
            )
        await db.commit()
    if change == "pause":
        monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", False)
    if change == "configuration":
        monkeypatch.setattr(terminal, "smtp_email_is_configured", lambda *a: False)
    assert await worker(sessions) == 1
    Service.dispatch_email.assert_not_awaited()
    log = await external(sessions)
    if change in ("pause", "configuration"):
        assert (
            log.status == S.PENDIENTE
            and log.next_retry_at is not None
            and log.retry_count == 0
        )
    else:
        assert log.status == S.FALLIDO and log.next_retry_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role",
    [
        UserRole.SUPERADMIN,
        UserRole.GERENTE,
        UserRole.OPERADOR,
        UserRole.REPARTIDOR,
        UserRole.AUDITOR,
        UserRole.CLIENTE,
    ],
)
async def test_review_is_authenticated_audited_idempotent_and_never_resends(
    terminal_db, role
):
    client, sessions, ids = terminal_db
    Service.dispatch_email.return_value = False
    assert close(client, ids, "complete").status_code == 200
    assert await worker(sessions) == 1
    async with sessions() as db:
        await db.execute(update(User).where(User.id == ids["staff"]).values(role=role))
        await db.commit()
    log = await external(sessions)
    result, body = review(client, ids, log)
    allowed = role in (UserRole.SUPERADMIN, UserRole.GERENTE)
    assert result.status_code == (200 if allowed else 403), result.text
    if allowed:
        assert review(client, ids, log, body=body)[0].status_code == 200
        altered = {**body, "reference": "Otro caso-5678"}
        assert review(client, ids, log, body=altered)[0].status_code == 409
    current = await external(sessions)
    assert current.status == (S.ENVIADO if allowed else S.PENDIENTE)
    async with sessions() as db:
        assert await db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.resource_type == terminal.RESOURCE)
        ) == int(allowed)
    assert await worker(sessions) == 0
    Service.dispatch_email.assert_awaited_once()


@pytest.mark.asyncio
async def test_unconfirmed_review_preserves_hold_and_owner_cannot_remove_it(
    terminal_db,
):
    client, sessions, ids = terminal_db
    assert close(client, ids, "complete").status_code == 200
    Service.dispatch_email.return_value = False
    assert await worker(sessions) == 1
    log = await external(sessions)
    result, body = review(client, ids, log, "unconfirmed")
    assert result.status_code == 200 and result.json()["state"] == "uncertain"
    assert review(client, ids, log, body=body)[0].status_code == 200
    owner = headers(ids, "owner")
    assert (
        client.patch(f"/api/v1/notifications/{log.id}/read", headers=owner).status_code
        == 409
    )
    assert (
        client.delete(f"/api/v1/notifications/{log.id}", headers=owner).status_code
        == 409
    )
    async with sessions() as db:
        await db.execute(
            update(NotificationLog)
            .where(NotificationLog.id == log.id)
            .values(created_at=utc_now_naive() - timedelta(days=100))
        )
        await db.commit()
        await Service(db, redis_client=False).purge_old_logs()
    assert (await external(sessions)).next_retry_at is None
    assert await worker(sessions) == 0
    Service.dispatch_email.assert_awaited_once()


@pytest.mark.asyncio
async def test_provider_ack_and_manual_review_keep_both_evidence_and_current_state(
    terminal_db,
):
    client, sessions, ids = terminal_db
    assert close(client, ids, "complete").status_code == 200
    entered, release = asyncio.Event(), asyncio.Event()

    async def provider(*args):
        entered.set()
        await release.wait()
        return True

    Service.dispatch_email.side_effect = provider
    async with asyncio.timeout(20):
        task = asyncio.create_task(worker(sessions))
        try:
            await entered.wait()
            log = await external(sessions)
            response, body = review(client, ids, log, "unconfirmed")
            assert response.status_code == 200
        finally:
            release.set()
        await task
    replay = review(client, ids, log, body=body)[0]
    assert replay.status_code == 200 and replay.json()["state"] == "accepted"
    Service.dispatch_email.assert_awaited_once()


@pytest.mark.asyncio
async def test_review_queue_is_admin_only_masks_destination_and_blocks_generic_send(
    terminal_db,
):
    client, sessions, ids = terminal_db
    assert close(client, ids, "complete").status_code == 200
    Service.dispatch_email.return_value = False
    assert await worker(sessions) == 1
    assert (
        client.get("/api/v1/notifications/terminal-dispatch/review").status_code == 401
    )
    assert (
        client.get(
            "/api/v1/notifications/terminal-dispatch/review",
            headers=headers(ids, "owner"),
        ).status_code
        == 403
    )
    response = client.get(
        "/api/v1/notifications/terminal-dispatch/review", headers=headers(ids)
    )
    assert response.status_code == 200 and len(response.json()["items"]) == 1
    row = response.json()["items"][0]
    assert row["state"] == "uncertain" and row["destination_hint"] == "r***@example.com"
    assert (
        "rider@example.com" not in response.text
        and "destination_sha256" not in response.text
    )
    before = await external(sessions)
    assert (
        client.post(
            "/api/v1/notifications/test-send",
            headers=headers(ids),
            json={"template_code": CODES["complete"], "user_id": str(ids["owner"])},
        ).status_code
        == 409
    )
    async with sessions() as db:
        assert (
            await Service(db, redis_client=False).send(
                ids["owner"], CODES["complete"], {}
            )
            == []
        )
    assert (await external(sessions)).payload_json == before.payload_json
    Service.dispatch_email.assert_awaited_once()


@pytest.mark.asyncio
async def test_crash_after_claim_before_io_retains_uncertainty_without_a_second_attempt(
    terminal_db, monkeypatch
):
    client, sessions, ids = terminal_db
    assert close(client, ids, "complete").status_code == 200
    async with sessions() as db:
        original = db.commit

        async def commit_then_crash():
            await original()
            raise asyncio.CancelledError()

        monkeypatch.setattr(db, "commit", commit_then_crash)
        with pytest.raises(asyncio.CancelledError):
            await Service(db, redis_client=False).process_retry_queue()
    log = await external(sessions)
    assert log.status == S.PENDIENTE and log.next_retry_at is None
    assert json.loads(log.payload_json)["dispatch"]["state"] == "uncertain"
    assert await worker(sessions) == 0
    Service.dispatch_email.assert_not_awaited()


@pytest.mark.asyncio
async def test_enabling_channels_does_not_backfill_historical_closures(
    terminal_db, monkeypatch
):
    from app.services.delivery_notifications import enqueue_completion_notice

    client, sessions, ids = terminal_db
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", False)
    assert close(client, ids, "complete").status_code == 200
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True)
    async with sessions() as db:
        order = await db.get(Order, ids["order"])
        delivery = await db.get(Delivery, ids["delivery"])
        await enqueue_completion_notice(db, order, delivery, source="historical_retry")
        await db.commit()
    assert await external(sessions) is None
    assert await worker(sessions) == 0
    Service.dispatch_email.assert_not_awaited()


@pytest.mark.asyncio
async def test_review_commit_failure_rolls_back_audit_and_status_and_can_replay(
    terminal_db, monkeypatch
):
    client, sessions, ids = terminal_db
    assert close(client, ids, "complete").status_code == 200
    Service.dispatch_email.return_value = False
    await worker(sessions)
    log = await external(sessions)
    body = dict(
        review_id=str(uuid4()),
        attempt_id=json.loads(log.payload_json)["dispatch"]["attempt_id"],
        decision="accepted",
        reference="Proveedor registro-5678",
        note="Caso revisado",
    )
    original = AsyncSession.commit

    async def broken(db):
        if any(
            isinstance(row, AuditLog) and row.resource_type == terminal.RESOURCE
            for row in db.new
        ):
            raise RuntimeError("review commit unavailable")
        await original(db)

    with monkeypatch.context() as scoped:
        scoped.setattr(AsyncSession, "commit", broken)
        assert review(client, ids, log, body=body)[0].status_code == 500
    assert (await external(sessions)).status == S.PENDIENTE
    async with sessions() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.resource_type == terminal.RESOURCE)
            )
            == 0
        )
    assert review(client, ids, log, body=body)[0].status_code == 200
    Service.dispatch_email.assert_awaited_once()


@pytest.mark.asyncio
async def test_malformed_pending_payload_is_visible_for_technical_review_and_never_sent(
    terminal_db,
):
    client, sessions, ids = terminal_db
    assert close(client, ids, "complete").status_code == 200
    log = await external(sessions)
    async with sessions() as db:
        await db.execute(
            update(NotificationLog)
            .where(NotificationLog.id == log.id)
            .values(payload_json='{"event":"entrega_completada","dispatch":null}')
        )
        await db.commit()
    result = client.get(
        "/api/v1/notifications/terminal-dispatch/review", headers=headers(ids)
    )
    assert result.status_code == 200 and result.json()["items"][0]["state"] == "invalid"
    assert await worker(sessions) == 1
    Service.dispatch_email.assert_not_awaited()
    assert (await external(sessions)).status == S.FALLIDO


@pytest.mark.asyncio
async def test_competing_acceptance_reviews_have_one_winner_and_one_audit_entry(
    terminal_db,
):
    client, sessions, ids = terminal_db
    assert close(client, ids, "complete").status_code == 200
    Service.dispatch_email.return_value = False
    await worker(sessions)
    log = await external(sessions)
    async with asyncio.timeout(20):
        first, second = await asyncio.gather(
            asyncio.to_thread(review, client, ids, log),
            asyncio.to_thread(review, client, ids, log),
        )
    assert sorted([first[0].status_code, second[0].status_code]) == [200, 409]
    async with sessions() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.resource_type == terminal.RESOURCE)
            )
            == 1
        )
        assert await db.scalar(select(func.count()).select_from(Financial)) == 2
    Service.dispatch_email.assert_awaited_once()


@pytest.mark.asyncio
async def test_external_completion_clock_is_explicit_utc_without_rewriting_internal_history(
    terminal_db,
):
    client, sessions, ids = terminal_db
    async with sessions() as db:
        await db.execute(
            update(NotificationTemplate)
            .where(NotificationTemplate.code == CODES["complete"])
            .values(body_template="Hora registrada {{completed_at}}")
        )
        await db.commit()
    assert close(client, ids, "complete").status_code == 200
    log = await external(sessions)
    value = json.loads(log.payload_json)["completed_at"]
    assert value.endswith("+00:00") and log.body == "Hora registrada " + value
    async with sessions() as db:
        original = await db.scalar(
            select(NotificationLog).where(NotificationLog.channel == C.IN_APP)
        )
        assert not json.loads(original.payload_json)["completed_at"].endswith("+00:00")


@pytest.mark.asyncio
async def test_stale_attempt_cannot_confirm_a_different_provider_operation(terminal_db):
    client, sessions, ids = terminal_db
    assert close(client, ids, "complete").status_code == 200
    Service.dispatch_email.return_value = False
    await worker(sessions)
    log = await external(sessions)
    body = dict(
        review_id=str(uuid4()),
        attempt_id=str(uuid4()),
        decision="accepted",
        reference="Proveedor caso-9012",
        note="",
    )
    assert review(client, ids, log, body=body)[0].status_code == 409
    assert (await external(sessions)).status == S.PENDIENTE
    async with sessions() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.resource_type == terminal.RESOURCE)
            )
            == 0
        )
    Service.dispatch_email.assert_awaited_once()


@pytest.mark.asyncio
async def test_reviewer_role_is_revalidated_after_authentication_before_decision(
    terminal_db, monkeypatch
):
    from concurrent.futures import Future

    client, sessions, ids = terminal_db
    assert close(client, ids, "complete").status_code == 200
    Service.dispatch_email.return_value = False
    await worker(sessions)
    log = await external(sessions)
    entered, release = Future(), Future()
    original = terminal.review_result

    async def pause(*args, **kwargs):
        entered.set_result(None)
        await asyncio.wrap_future(release)
        return await original(*args, **kwargs)

    monkeypatch.setattr(terminal, "review_result", pause)
    async with asyncio.timeout(20):
        task = asyncio.create_task(asyncio.to_thread(review, client, ids, log))
        try:
            await asyncio.wrap_future(entered)
            async with sessions() as db:
                await db.execute(
                    update(User)
                    .where(User.id == ids["staff"])
                    .values(role=UserRole.OPERADOR)
                )
                await db.commit()
        finally:
            release.set_result(None)
        result, _ = await task
    assert result.status_code == 403
    assert (await external(sessions)).status == S.PENDIENTE
    Service.dispatch_email.assert_awaited_once()
