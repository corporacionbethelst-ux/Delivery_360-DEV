"""Assignment and its inbox/queue have one durable transaction boundary."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_delivery_financial_postgresql import payment_db  # noqa: F401
from tests.test_order_cancellation_postgresql import cancel_db  # noqa: F401
from tests.test_sla_monitor_postgresql import sla_db  # noqa: F401
from tests.test_runtime_contracts_postgresql import runtime_db  # noqa: F401
from tests.test_assignment_eligibility_postgresql import (
    assignment_db,
    request,
)  # noqa: F401
from app.core.config import settings
from app.models.audit_log import AuditLog
from app.models.delivery import Delivery
from app.models.financial import Financial
from app.models.notification import (
    NotificationLog,
    NotificationChannel as Channel,
    OmnichannelStatus as Status,
    NotificationTemplate,
    NotificationPreference,
    utc_now_naive,
)
from app.models.order import Order, OrderStatus
from app.services import order_assignment as assignments
from app.services.omnichannel_service import OmnichannelNotificationService
from app.models.user import User, UserRole
from app.core.security import create_access_token
from datetime import timedelta


async def receipts(sessions):
    async with sessions() as db:
        return list(
            (
                await db.scalars(
                    select(NotificationLog).where(
                        NotificationLog.template_code == "nuevo_pedido_asignado",
                        NotificationLog.channel == Channel.IN_APP,
                    )
                )
            ).all()
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["manual", "delivery", "auto", "create"])
async def test_all_http_assignment_paths_commit_one_visible_receipt(
    assignment_db, path
):
    client, sessions, ids = assignment_db
    response = request(client, ids, path)
    assert response.status_code in (200, 201), response.text
    rows = await receipts(sessions)
    assert len(rows) == 1
    notice = rows[0]
    context = json.loads(notice.payload_json)
    assert notice.user_id == ids["owner"]
    assert notice.status == Status.ENVIADO and notice.next_retry_at is None
    assert notice.sent_at is not None and notice.read_at is None
    assert "payment_cents" not in context and "amount_cents" not in context
    owner_headers = {"Authorization": "Bearer " + create_access_token(ids["owner"])}
    inbox = client.get("/api/v1/notifications/inbox", headers=owner_headers)
    assert inbox.status_code == 200, inbox.text
    assert inbox.json()["unread_count"] == 1
    assert [item["id"] for item in inbox.json()["items"]] == [str(notice.id)]
    staff_inbox = client.get(
        "/api/v1/notifications/inbox",
        headers={"Authorization": "Bearer " + create_access_token(ids["staff"])},
    )
    assert staff_inbox.status_code == 200 and staff_inbox.json()["items"] == []
    read = client.patch(
        f"/api/v1/notifications/{notice.id}/read", headers=owner_headers
    )
    assert read.status_code == 200, read.text
    async with sessions() as db:
        audit = await db.get(AuditLog, context["assignment_event_id"])
        assert audit is not None and audit.resource_id == context["order_id"]
        order = await db.get(Order, context["order_id"])
        assert order.status == OrderStatus.ASIGNADO
        assert order.assigned_rider_id == ids["rider"]
        assert await db.scalar(select(func.count()).select_from(Financial)) == 1
    if path in ("manual", "delivery"):
        assert request(client, ids, path).status_code == 200
        assert len(await receipts(sessions)) == 1
        count = client.get("/api/v1/notifications/unread-count", headers=owner_headers)
        assert count.status_code == 200 and count.json()["unread_count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["notice", "commit"])
async def test_receipt_or_commit_failure_rolls_back_assignment_and_audit(
    assignment_db, monkeypatch, failure
):
    client, sessions, ids = assignment_db
    original = assignments.enqueue_assignment_notice

    async def marked(db, *args, **kwargs):
        await original(db, *args, **kwargs)
        if failure == "notice":
            raise RuntimeError("injected receipt failure")
        db.info["assignment_receipt_failure"] = True

    monkeypatch.setattr(assignments, "enqueue_assignment_notice", marked)
    original_commit = AsyncSession.commit

    async def commit(db):
        if db.info.get("assignment_receipt_failure"):
            raise RuntimeError("injected receipt commit failure")
        await original_commit(db)

    monkeypatch.setattr(AsyncSession, "commit", commit)
    response = request(client, ids, "manual")
    assert response.status_code == 500
    async with sessions() as db:
        assert (await db.get(Order, ids["order"])).status == OrderStatus.PENDIENTE
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.resource_type == "ORDER")
            )
            == 0
        )
        assert await db.scalar(select(func.count()).select_from(NotificationLog)) == 0
        assert await db.scalar(select(func.count()).select_from(Financial)) == 1


@pytest.mark.asyncio
async def test_concurrent_replays_keep_single_event(assignment_db):
    client, sessions, ids = assignment_db
    responses = await asyncio.gather(
        *[asyncio.to_thread(request, client, ids, "manual") for _ in range(2)]
    )
    assert [response.status_code for response in responses] == [200, 200]
    rows = await receipts(sessions)
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_paused_external_channels_still_keep_internal_receipt(
    assignment_db, monkeypatch
):
    client, sessions, ids = assignment_db
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", False)
    dispatch = AsyncMock(
        side_effect=AssertionError("No provider I/O during assignment")
    )
    monkeypatch.setattr(OmnichannelNotificationService, "send", dispatch)
    assert request(client, ids, "manual").status_code == 200
    assert len(await receipts(sessions)) == 1
    dispatch.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "condition",
    [
        "retry_success",
        "preference",
        "template",
        "inactive",
        "role",
        "assignment",
        "closed",
        "pause",
    ],
)
async def test_persisted_external_work_recovers_with_current_policy(
    assignment_db, monkeypatch, condition
):
    client, sessions, ids = assignment_db
    async with sessions() as db:
        db.add(
            NotificationTemplate(
                code="nuevo_pedido_asignado",
                channel=Channel.PUSH,
                subject="Orden asignada",
                body_template="Destino {{delivery_address}}",
                is_active=True,
            )
        )
        await db.commit()
    provider = AsyncMock(return_value=False)
    monkeypatch.setattr(OmnichannelNotificationService, "dispatch_push", provider)
    assert request(client, ids, "manual").status_code == 200
    provider.assert_not_awaited()
    async with sessions() as db:
        queued = await db.scalar(
            select(NotificationLog).where(NotificationLog.channel == Channel.PUSH)
        )
        assert queued.status == Status.PENDIENTE
        original_body = queued.body
        log_id = queued.id
        await db.execute(
            update(NotificationTemplate).values(
                body_template="Texto cambiado después del evento"
            )
        )
        if condition == "preference":
            db.add(
                NotificationPreference(
                    user_id=ids["owner"],
                    event_code="nuevo_pedido_asignado",
                    channel=Channel.PUSH,
                    enabled=False,
                )
            )
        if condition == "template":
            await db.execute(update(NotificationTemplate).values(is_active=False))
        if condition == "inactive":
            await db.execute(
                update(User).where(User.id == ids["owner"]).values(is_active=False)
            )
        if condition == "role":
            await db.execute(
                update(User)
                .where(User.id == ids["owner"])
                .values(role=UserRole.OPERADOR)
            )
        if condition == "assignment":
            await db.execute(update(Order).values(assigned_rider_id=None))
        if condition == "closed":
            await db.execute(update(Order).values(status=OrderStatus.ENTREGADO))
        await db.commit()
    if condition == "pause":
        monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", False)
    # New session models worker/process recovery; no business request is alive.
    async with sessions() as db:
        assert (
            await OmnichannelNotificationService(
                db, redis_client=False
            ).process_retry_queue(10)
            == 1
        )
    async with sessions() as db:
        queued = await db.get(NotificationLog, log_id)
        assert queued.body == original_body
        if condition == "retry_success":
            assert queued.status == Status.PENDIENTE and queued.retry_count == 1
            queued.next_retry_at = utc_now_naive() - timedelta(seconds=1)
            await db.commit()
        elif condition == "pause":
            assert queued.status == Status.PENDIENTE and queued.retry_count == 0
        else:
            assert queued.status == Status.FALLIDO and queued.next_retry_at is None
    if condition == "retry_success":
        provider.return_value = True
        async with sessions() as db:
            assert (
                await OmnichannelNotificationService(
                    db, redis_client=False
                ).process_retry_queue(10)
                == 1
            )
        async with sessions() as db:
            assert (await db.get(NotificationLog, log_id)).status == Status.ENVIADO
        assert provider.await_count == 2
        assert provider.await_args.args[2] == original_body
    else:
        provider.assert_not_awaited()
    assert len(await receipts(sessions)) == 1
