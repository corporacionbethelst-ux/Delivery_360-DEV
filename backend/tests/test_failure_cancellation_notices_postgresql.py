"""Durable terminal notices share business commit, ownership and rollback."""

import asyncio
import hashlib
import json
import os
from decimal import Decimal
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx
import pytest
from redis import asyncio as aioredis
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_delivery_financial_postgresql import payment_db  # noqa: F401
from tests.test_order_cancellation_postgresql import cancel_db, REASON  # noqa: F401
from tests.asgi_socket import open_socket
from app.main import app
from app.core.security import create_access_token
from app.models.audit_log import AuditLog
from app.models.delivery import Delivery, DeliveryStatus
from app.models.financial import Financial, RiderWallet
from app.models.notification import (
    Alert,
    NotificationLog,
    NotificationChannel as Channel,
    OmnichannelStatus as Status,
)
from app.models.order import Order, OrderStatus
from app.models.platform_setting import PlatformSetting
from app.models.rider import Rider
from app.models.route import Route
from app.services import (
    delivery_notifications as notices,
    assignment_realtime as realtime,
)
from app.services.assignment_realtime import _publish as real_publish
from app.api.v1 import notifications as notification_api


def invoke(client, ids, path, cause="CLIENTE_NO_ESTA"):
    headers = {"Authorization": "Bearer " + create_access_token(ids["staff"])}
    if path == "legacy":
        return client.post(
            f"/api/v1/deliveries/{ids['delivery']}/fail",
            headers=headers,
            json={"failure_cause": cause},
        )
    if path == "unified":
        return client.patch(
            f"/api/v1/deliveries/{ids['delivery']}/status",
            headers=headers,
            json={"status": "FALLIDA", "issue_type": cause},
        )
    if path == "generic_cancel":
        return client.patch(
            f"/api/v1/orders/{ids['order']}/status",
            headers=headers,
            params={"new_status": "CANCELADO"},
        )
    return client.patch(
        f"/api/v1/orders/{ids['order']}/cancel",
        headers=headers,
        json={"reason": REASON},
    )


async def state(sessions, ids):
    async with sessions() as db:
        return (
            (await db.get(Order, ids["order"])).status,
            (await db.get(Delivery, ids["delivery"])).status,
            await db.scalar(select(func.count()).select_from(Financial)),
            await db.scalar(select(func.count()).select_from(NotificationLog)),
            await db.scalar(select(func.count()).select_from(AuditLog)),
            (await db.get(Rider, ids["rider"])).wallet_balance,
            (await db.scalar(select(RiderWallet))).balance_cents,
            (await db.get(Route, ids["route"])).status,
            tuple((await db.scalars(select(Alert.status).order_by(Alert.id))).all()),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["legacy", "unified"])
@pytest.mark.parametrize("cause", ["CLIENTE_NO_ESTA", "REPARTIDOR_ERROR_PROPIO"])
@pytest.mark.parametrize("bonus", ["1.00", "0.00"])
async def test_failure_receipt_is_operational_even_without_a_bonus(
    cancel_db, path, cause, bonus
):
    client, sessions, ids = cancel_db
    async with sessions() as db:
        await db.execute(
            update(PlatformSetting)
            .where(PlatformSetting.key == "rider_failed_attempt_bonus")
            .values(value=bonus)
        )
        await db.commit()
    result = invoke(client, ids, path, cause)
    assert result.status_code == 200, result.text
    async with sessions() as db:
        note = await db.scalar(select(NotificationLog))
        assert note.user_id == ids["owner"] and note.delivery_id == ids["delivery"]
        assert (
            note.template_code == "entrega_fallida" and note.channel == Channel.IN_APP
        )
        payload = json.loads(note.payload_json)
        assert payload["order_id"] == str(ids["order"])
        assert payload["recorded_at"].endswith("+00:00")
        assert not {"amount", "currency", "otp_code", "failure_cause"}.intersection(
            payload
        )
        assert (await db.get(Order, ids["order"])).status == OrderStatus.FALLIDO
        assert (
            await db.get(Delivery, ids["delivery"])
        ).status == DeliveryStatus.FALLIDA
        expected = 2 if cause == "CLIENTE_NO_ESTA" and bonus == "1.00" else 1
        assert await db.scalar(select(func.count()).select_from(Financial)) == expected
    before = await state(sessions, ids)
    assert invoke(client, ids, path, cause).status_code in (400, 409)
    assert await state(sessions, ids) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["cancel", "generic_cancel"])
async def test_cancellation_notice_is_owned_readable_and_keeps_read_state_on_retry(
    cancel_db, path
):
    client, sessions, ids = cancel_db
    assert invoke(client, ids, path).status_code == 200
    async with sessions() as db:
        note = await db.scalar(select(NotificationLog))
        assert note.user_id == ids["owner"] and note.template_code == "orden_cancelada"
        assert note.delivery_id == ids["delivery"]
        note_id = str(note.id)
        assert await db.scalar(select(func.count()).select_from(Financial)) == 1
    owner = {"Authorization": "Bearer " + create_access_token(ids["owner"])}
    assert (
        client.get("/api/v1/notifications/inbox", headers=owner).json()["unread_count"]
        == 1
    )
    assert (
        client.patch(f"/api/v1/notifications/{note_id}/read", headers=owner).status_code
        == 200
    )
    assert invoke(client, ids, path).status_code == 200
    async with sessions() as db:
        rows = list((await db.scalars(select(NotificationLog))).all())
        assert (
            len(rows) == 1
            and str(rows[0].id) == note_id
            and rows[0].status == Status.LEIDO
        )
        assert rows[0].read_at is not None
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("assigned", [True, False])
async def test_cancellation_without_delivery_only_notifies_a_real_assigned_account(
    cancel_db, assigned
):
    client, sessions, ids = cancel_db
    async with sessions() as db:
        await db.execute(delete(Alert))
        await db.execute(delete(Route))
        await db.execute(delete(Delivery))
        if not assigned:
            await db.execute(
                update(Order).values(
                    assigned_rider_id=None, status=OrderStatus.PENDIENTE
                )
            )
        await db.commit()
    assert invoke(client, ids, "cancel").status_code == 200
    async with sessions() as db:
        rows = list((await db.scalars(select(NotificationLog))).all())
        assert len(rows) == int(assigned)
        if assigned:
            assert rows[0].delivery_id is None and rows[0].user_id == ids["owner"]
            assert json.loads(rows[0].payload_json)["delivery_id"] is None


@pytest.mark.asyncio
async def test_historical_cancellation_retry_never_backfills_missing_notices(cancel_db):
    client, sessions, ids = cancel_db
    assert invoke(client, ids, "cancel").status_code == 200
    async with sessions() as db:
        await db.execute(delete(NotificationLog))
        await db.commit()
    assert invoke(client, ids, "cancel").status_code == 200
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(NotificationLog)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["legacy", "unified", "cancel", "generic_cancel"])
@pytest.mark.parametrize("failure", ["receipt", "commit"])
async def test_receipt_and_commit_faults_rollback_every_business_effect(
    cancel_db, monkeypatch, path, failure
):
    client, sessions, ids = cancel_db
    before = await state(sessions, ids)
    method = (
        "enqueue_failure_notice"
        if path in ("legacy", "unified")
        else "enqueue_cancellation_notice"
    )
    original = getattr(notices, method)

    async def marked(db, *args, **kwargs):
        await original(db, *args, **kwargs)
        if failure == "receipt":
            raise RuntimeError("notice persistence failed")
        db.info["terminal_commit_fault"] = True

    monkeypatch.setattr(notices, method, marked)
    original_commit = AsyncSession.commit

    async def commit(db):
        if db.info.get("terminal_commit_fault"):
            raise RuntimeError("terminal commit failed")
        await original_commit(db)

    monkeypatch.setattr(AsyncSession, "commit", commit)
    assert invoke(client, ids, path).status_code == 500
    assert await state(sessions, ids) == before
    realtime._publish.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["legacy", "unified"])
@pytest.mark.parametrize("corrupt", ["terminal_order", "assignment"])
async def test_inconsistent_parent_is_not_overwritten_or_paid(cancel_db, path, corrupt):
    client, sessions, ids = cancel_db
    async with sessions() as db:
        await db.execute(
            update(Order).values(
                **(
                    {"status": OrderStatus.ENTREGADO}
                    if corrupt == "terminal_order"
                    else {"assigned_rider_id": None}
                )
            )
        )
        await db.commit()
    before = await state(sessions, ids)
    assert invoke(client, ids, path).status_code == 409
    assert await state(sessions, ids) == before


@pytest.mark.asyncio
async def test_generic_failed_status_cannot_separate_order_from_delivery(cancel_db):
    client, sessions, ids = cancel_db
    before = await state(sessions, ids)
    headers = {"Authorization": "Bearer " + create_access_token(ids["staff"])}
    result = client.patch(
        f"/api/v1/orders/{ids['order']}/status?new_status=FALLIDO", headers=headers
    )
    assert result.status_code == 409 and "motivo" in result.json()["detail"]
    assert await state(sessions, ids) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,code", [("legacy", "entrega_fallida"), ("cancel", "orden_cancelada")]
)
async def test_conflicting_existing_recipient_rolls_back_instead_of_rewriting_history(
    cancel_db, path, code
):
    client, sessions, ids = cancel_db
    async with sessions() as db:
        db.add(
            NotificationLog(
                user_id=ids["staff"],
                delivery_id=ids["delivery"],
                template_code=code,
                channel=Channel.IN_APP,
                status=Status.LEIDO,
                dedupe_key=hashlib.sha256(
                    f"order:{ids['order']}:{code}:IN_APP".encode()
                ).hexdigest(),
            )
        )
        await db.commit()
    before = await state(sessions, ids)
    assert invoke(client, ids, path).status_code == 409
    assert await state(sessions, ids) == before
    async with sessions() as db:
        assert (await db.scalar(select(NotificationLog))).user_id == ids["staff"]


@pytest.mark.asyncio
@pytest.mark.parametrize("event", ["failure", "cancel"])
async def test_same_transaction_deduplicates_each_new_event(cancel_db, event):
    _, sessions, ids = cancel_db
    async with sessions() as db:
        order, delivery = await db.get(Order, ids["order"]), await db.get(
            Delivery, ids["delivery"]
        )
        order.status = (
            OrderStatus.FALLIDO if event == "failure" else OrderStatus.CANCELADO
        )
        delivery.status = (
            DeliveryStatus.FALLIDA if event == "failure" else DeliveryStatus.CANCELADA
        )

        async def enqueue():
            if event == "failure":
                return await notices.enqueue_failure_notice(
                    db, order, delivery, source="test"
                )
            return await notices.enqueue_cancellation_notice(db, order, delivery)

        first = await enqueue()
        assert await enqueue() == first
        await db.commit()
        note = await db.get(NotificationLog, first)
        note.status = Status.LEIDO
        await db.commit()
        assert await enqueue() == first
        await db.commit()
        assert await db.scalar(select(func.count()).select_from(NotificationLog)) == 1
        assert (await db.get(NotificationLog, first)).status == Status.LEIDO


@pytest.mark.asyncio
async def test_failure_and_cancellation_compete_without_two_terminal_notices(cancel_db):
    client, sessions, ids = cancel_db
    async with asyncio.timeout(20):
        results = await asyncio.gather(
            asyncio.to_thread(invoke, client, ids, "legacy"),
            asyncio.to_thread(invoke, client, ids, "cancel"),
        )
    assert sorted(r.status_code for r in results) in ([200, 400], [200, 409])
    async with sessions() as db:
        note = await db.scalar(select(NotificationLog))
        assert await db.scalar(select(func.count()).select_from(NotificationLog)) == 1
        failed = (await db.get(Order, ids["order"])).status == OrderStatus.FALLIDO
        assert note.template_code == (
            "entrega_fallida" if failed else "orden_cancelada"
        )
        assert await db.scalar(select(func.count()).select_from(Financial)) == (
            2 if failed else 1
        )


@pytest.fixture
async def terminal_stream(cancel_db, monkeypatch):
    selected = os.environ.get("TEST_NOTIFICATION_REDIS_URL")
    if not selected:
        pytest.skip("Explicit loopback Redis /15 test database required")
    parsed = urlparse(selected)
    assert (
        parsed.scheme == "redis"
        and parsed.hostname in ("localhost", "127.0.0.1")
        and parsed.path == "/15"
    )
    _, sessions, ids = cancel_db
    monkeypatch.setattr(realtime, "_publish", real_publish)
    from app.core.config import settings

    monkeypatch.setattr(settings, "REDIS_URL", selected)
    monkeypatch.setattr(
        settings, "REDIS_NOTIF_CHANNEL_PREFIX", "test.terminal." + uuid4().hex
    )
    monkeypatch.setattr(notification_api, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(
        notification_api,
        "_notification_redis_client",
        lambda: aioredis.from_url(
            selected,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=None,
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        yield client, sessions, ids
        if realtime._tasks:
            async with asyncio.timeout(10):
                await asyncio.gather(*tuple(realtime._tasks))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,code", [("fail", "entrega_fallida"), ("cancel", "orden_cancelada")]
)
async def test_terminal_notice_reaches_only_owner_after_commit(
    terminal_stream, path, code
):
    client, sessions, ids = terminal_stream

    def address(uid):
        return "/api/v1/notifications/ws?token=" + create_access_token(uid)

    async with (
        open_socket(app, address(ids["owner"])) as owner,
        open_socket(app, address(ids["staff"])) as other,
    ):
        assert (await owner.receive_json())["realtime_available"] is True
        assert (await other.receive_json())["realtime_available"] is True
        headers = {"Authorization": "Bearer " + create_access_token(ids["staff"])}
        body = (
            {"failure_cause": "CLIENTE_NO_ESTA"}
            if path == "fail"
            else {"reason": REASON}
        )
        response = await client.request(
            "POST" if path == "fail" else "PATCH",
            f"/api/v1/"
            + (
                f"deliveries/{ids['delivery']}/fail"
                if path == "fail"
                else f"orders/{ids['order']}/cancel"
            ),
            headers=headers,
            json=body,
        )
        assert response.status_code == 200, response.text
        frame = await owner.receive_json()
        assert (
            frame["type"] == "NEW_NOTIFICATION"
            and frame["template_code"] == code
            and frame["unread_count"] == 1
        )
        assert frame["created_at"].endswith("+00:00")
        async with sessions() as db:
            assert (await db.get(NotificationLog, UUID(frame["id"]))).user_id == ids[
                "owner"
            ]
            assert (await db.get(Order, ids["order"])).status == (
                OrderStatus.FALLIDO if path == "fail" else OrderStatus.CANCELADO
            )
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(other.receive_json(), 0.15)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(owner.receive_json(), 0.15)


@pytest.mark.asyncio
async def test_failure_notes_are_preserved_in_detail_without_broadcasting_them(
    cancel_db,
):
    client, sessions, ids = cancel_db
    headers = {"Authorization": "Bearer " + create_access_token(ids["staff"])}
    context = "Se verificó la entrada con recepción; solicitar nueva coordinación"
    result = client.post(
        f"/api/v1/deliveries/{ids['delivery']}/fail",
        headers=headers,
        json={
            "failure_cause": "EDIFICIO_RESTRINGIDO",
            "issue_description": "  " + context + "  ",
        },
    )
    assert result.status_code == 200, result.text
    async with sessions() as db:
        assert (await db.get(Delivery, ids["delivery"])).issue_description == context
        assert context in (await db.get(Order, ids["order"])).failure_notes
        note = await db.scalar(select(NotificationLog))
        assert context not in note.body and context not in note.payload_json


@pytest.mark.asyncio
async def test_legacy_order_service_also_rejects_an_uncoordinated_failure(cancel_db):
    from app.core.exceptions import AppException
    from app.services.order_service import OrderService

    _, sessions, ids = cancel_db
    before = await state(sessions, ids)
    async with sessions() as db:
        with pytest.raises(AppException) as error:
            await OrderService().update_status(
                db, ids["order"], OrderStatus.FALLIDO, ids["staff"]
            )
        assert error.value.status_code == 409
    assert await state(sessions, ids) == before
