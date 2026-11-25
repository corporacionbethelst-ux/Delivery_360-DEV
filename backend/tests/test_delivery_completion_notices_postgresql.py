"""Completion receipts share the order/delivery/ledger transaction."""

import asyncio
import hashlib
import json
import os
from urllib.parse import urlparse
from uuid import uuid4
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import httpx
from redis import asyncio as aioredis
from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_delivery_financial_postgresql import payment_db  # noqa: F401
from app.core.security import create_access_token
from app.models.order import Order, OrderStatus
from app.models.delivery import Delivery, DeliveryStatus, ProofType
from app.models.financial import Financial, RiderWallet
from app.models.rider import Rider
from app.models.notification import (
    NotificationLog,
    NotificationChannel as Channel,
    OmnichannelStatus as Status,
)
from app.models.platform_setting import PlatformSetting
from app.services import (
    delivery_notifications as notices,
    assignment_realtime as realtime,
)
from app.services.assignment_realtime import _publish as real_publish
from app.api.v1 import notifications as notification_api
from app.main import app
from tests.asgi_socket import open_socket


def complete(client, ids, path, code="001234"):
    headers = {"Authorization": "Bearer " + create_access_token(ids["staff"])}
    if path == "order":
        return client.patch(
            f"/api/v1/orders/{ids['order']}/status?new_status=ENTREGADO",
            headers=headers,
            json={"otp_code": code},
        )
    if path == "legacy":
        return client.post(
            f"/api/v1/deliveries/{ids['delivery']}/complete",
            headers=headers,
            json={"otp_code": code},
        )
    return client.patch(
        f"/api/v1/deliveries/{ids['delivery']}/status",
        headers=headers,
        json={"status": "COMPLETADA", "otp_code": code},
    )


async def prepare(sessions, ids, bonus="2.50"):
    async with sessions() as db:
        record = await db.get(Delivery, ids["delivery"])
        record.proof_type = ProofType.OTP
        record.proof_otp = "001234"
        await db.execute(
            update(PlatformSetting)
            .where(PlatformSetting.key == "rider_delivery_bonus")
            .values(value=bonus)
        )
        await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["legacy", "unified", "order"])
@pytest.mark.parametrize("bonus", ["2.50", "0.00"])
async def test_each_completion_path_records_one_owned_receipt_even_without_bonus(
    payment_db, path, bonus
):
    client, sessions, ids = payment_db
    await prepare(sessions, ids, bonus)
    response = complete(client, ids, path)
    assert response.status_code == 200, response.text
    async with sessions() as db:
        record = await db.scalar(select(NotificationLog))
        assert record.user_id == ids["owner"] and record.delivery_id == ids["delivery"]
        assert record.channel == Channel.IN_APP and record.template_code == notices.CODE
        assert record.status == Status.ENVIADO and record.sent_at is not None
        assert record.next_retry_at is None and record.payout_id is None
        payload = json.loads(record.payload_json)
        assert payload["order_id"] == str(ids["order"])
        assert not any(
            key in payload for key in ("amount", "currency", "otp_code", "proof_otp")
        )
        assert (await db.get(Order, ids["order"])).status == OrderStatus.ENTREGADO
        assert (
            await db.get(Delivery, ids["delivery"])
        ).status == DeliveryStatus.COMPLETADA
        assert await db.scalar(select(func.count()).select_from(Financial)) == (
            2 if bonus == "2.50" else 1
        )
        notice_id = record.id
    owner = {"Authorization": "Bearer " + create_access_token(ids["owner"])}
    inbox = client.get("/api/v1/notifications/inbox", headers=owner)
    assert inbox.status_code == 200 and inbox.json()["unread_count"] == 1
    assert inbox.json()["items"][0]["id"] == str(notice_id)
    assert (
        client.patch(
            f"/api/v1/notifications/{notice_id}/read", headers=owner
        ).status_code
        == 200
    )
    assert complete(client, ids, path).status_code in (400, 409)
    async with sessions() as db:
        records = list((await db.scalars(select(NotificationLog))).all())
        assert len(records) == 1 and records[0].id == notice_id
        assert records[0].status == Status.LEIDO
        assert await db.scalar(select(func.count()).select_from(Financial)) == (
            2 if bonus == "2.50" else 1
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["legacy", "unified", "order"])
async def test_invalid_otp_never_creates_receipt_or_credit(payment_db, path):
    client, sessions, ids = payment_db
    await prepare(sessions, ids)
    assert complete(client, ids, path, "wrong").status_code == 400
    async with sessions() as db:
        assert (await db.get(Order, ids["order"])).status == OrderStatus.EN_RUTA
        assert (
            await db.get(Delivery, ids["delivery"])
        ).status == DeliveryStatus.EN_ROUTE
        assert await db.scalar(select(func.count()).select_from(NotificationLog)) == 0
        assert await db.scalar(select(func.count()).select_from(Financial)) == 1


@pytest.mark.asyncio
async def test_competing_completion_paths_keep_one_receipt_and_one_credit(payment_db):
    client, sessions, ids = payment_db
    await prepare(sessions, ids)
    responses = await asyncio.gather(
        asyncio.to_thread(complete, client, ids, "legacy"),
        asyncio.to_thread(complete, client, ids, "order"),
    )
    assert sorted(response.status_code for response in responses) in (
        [200, 400],
        [200, 409],
    )
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(NotificationLog)) == 1
        assert await db.scalar(select(func.count()).select_from(Financial)) == 2
        assert (await db.get(Order, ids["order"])).status == OrderStatus.ENTREGADO


@pytest.mark.asyncio
async def test_order_closure_creates_receipt_when_legacy_delivery_record_is_absent(
    payment_db,
):
    client, sessions, ids = payment_db
    async with sessions() as db:
        # Minimal test schema intentionally omits route tables/ORM cascades.
        await db.execute(delete(Delivery).where(Delivery.id == ids["delivery"]))
        await db.commit()
    assert complete(client, ids, "order").status_code == 200
    async with sessions() as db:
        delivery = await db.scalar(
            select(Delivery).where(Delivery.order_id == ids["order"])
        )
        receipt = await db.scalar(select(NotificationLog))
        assert (
            delivery.id != ids["delivery"]
            and delivery.status == DeliveryStatus.COMPLETADA
        )
        assert receipt.delivery_id == delivery.id and receipt.user_id == ids["owner"]
        assert await db.scalar(select(func.count()).select_from(Financial)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["legacy", "unified", "order"])
@pytest.mark.parametrize("failure", ["receipt", "commit"])
async def test_receipt_or_commit_failure_rolls_back_closure_and_money(
    payment_db, monkeypatch, path, failure
):
    client, sessions, ids = payment_db
    await prepare(sessions, ids)
    original = notices.enqueue_completion_notice

    async def marked(db, *args, **kwargs):
        await original(db, *args, **kwargs)
        if failure == "receipt":
            raise RuntimeError("receipt unavailable")
        db.info["completion_commit_fault"] = True

    monkeypatch.setattr(notices, "enqueue_completion_notice", marked)
    original_commit = AsyncSession.commit

    async def commit(db):
        if db.info.get("completion_commit_fault"):
            raise RuntimeError("completion commit fault")
        await original_commit(db)

    monkeypatch.setattr(AsyncSession, "commit", commit)
    publisher = realtime._publish
    assert complete(client, ids, path).status_code == 500
    async with sessions() as db:
        assert (await db.get(Order, ids["order"])).status == OrderStatus.EN_RUTA
        assert (
            await db.get(Delivery, ids["delivery"])
        ).status == DeliveryStatus.EN_ROUTE
        assert await db.scalar(select(func.count()).select_from(NotificationLog)) == 0
        assert await db.scalar(select(func.count()).select_from(Financial)) == 1
        assert (await db.get(Rider, ids["rider"])).wallet_balance == Decimal("3.00")
        wallet = await db.scalar(
            select(RiderWallet).where(RiderWallet.rider_id == ids["rider"])
        )
        assert wallet.balance_cents == 1000
    publisher.assert_not_awaited()


@pytest.mark.asyncio
async def test_same_transaction_and_later_replay_preserve_id_and_read_state(payment_db):
    _, sessions, ids = payment_db
    async with sessions() as db:
        order = await db.get(Order, ids["order"])
        delivery = await db.get(Delivery, ids["delivery"])
        order.status = OrderStatus.ENTREGADO
        delivery.status = DeliveryStatus.COMPLETADA
        delivery.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        first = await notices.enqueue_completion_notice(
            db, order, delivery, source="test"
        )
        assert (
            await notices.enqueue_completion_notice(db, order, delivery, source="test")
            == first
        )
        await db.commit()
        record = await db.get(NotificationLog, first)
        record.status = Status.LEIDO
        record.read_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await db.commit()
        assert (
            await notices.enqueue_completion_notice(db, order, delivery, source="test")
            == first
        )
        await db.commit()
        assert await db.scalar(select(func.count()).select_from(NotificationLog)) == 1
        assert (await db.get(NotificationLog, first)).status == Status.LEIDO


@pytest.mark.asyncio
async def test_conflicting_recipient_prevents_closure_without_rewriting_history(
    payment_db,
):
    client, sessions, ids = payment_db
    await prepare(sessions, ids)
    async with sessions() as db:
        db.add(
            NotificationLog(
                user_id=ids["staff"],
                delivery_id=ids["delivery"],
                template_code=notices.CODE,
                channel=Channel.IN_APP,
                status=Status.ENVIADO,
                dedupe_key=hashlib.sha256(
                    f"order:{ids['order']}:{notices.CODE}:IN_APP".encode()
                ).hexdigest(),
            )
        )
        await db.commit()
    assert complete(client, ids, "order").status_code == 409
    async with sessions() as db:
        assert (await db.get(Order, ids["order"])).status == OrderStatus.EN_RUTA
        assert await db.scalar(select(func.count()).select_from(Financial)) == 1
        assert (await db.scalar(select(NotificationLog))).user_id == ids["staff"]


@pytest.fixture
async def completion_stream(payment_db, monkeypatch):
    selected = os.environ.get("TEST_NOTIFICATION_REDIS_URL")
    if not selected:
        pytest.skip("Explicit loopback Redis test database /15 required")
    parsed = urlparse(selected)
    if (
        parsed.scheme != "redis"
        or parsed.hostname not in ("localhost", "127.0.0.1")
        or parsed.path != "/15"
    ):
        pytest.fail("Dedicated loopback Redis test database /15 required")
    _, sessions, ids = payment_db
    monkeypatch.setattr(realtime, "_publish", real_publish)
    from app.core.config import settings

    monkeypatch.setattr(settings, "REDIS_URL", selected)
    monkeypatch.setattr(
        settings, "REDIS_NOTIF_CHANNEL_PREFIX", "test.completion." + uuid4().hex
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
            await asyncio.gather(*tuple(realtime._tasks))


@pytest.mark.asyncio
async def test_completion_reaches_owned_websocket_after_commit_only_once(
    completion_stream,
):
    client, sessions, ids = completion_stream

    def address(uid):
        return "/api/v1/notifications/ws?token=" + create_access_token(uid)

    async with (
        open_socket(app, address(ids["owner"])) as owner,
        open_socket(app, address(ids["staff"])) as other,
    ):
        assert (await owner.receive_json())["realtime_available"] is True
        assert (await other.receive_json())["realtime_available"] is True
        response = await client.patch(
            f"/api/v1/orders/{ids['order']}/status?new_status=ENTREGADO",
            headers={"Authorization": "Bearer " + create_access_token(ids["staff"])},
            json={},
        )
        assert response.status_code == 200, response.text
        frame = await owner.receive_json()
        assert (
            frame["type"] == "NEW_NOTIFICATION"
            and frame["template_code"] == notices.CODE
        )
        assert frame["unread_count"] == 1
        assert frame["created_at"].endswith("+00:00")
        async with sessions() as db:
            receipt = await db.get(NotificationLog, frame["id"])
            assert (
                receipt.user_id == ids["owner"]
                and receipt.delivery_id == ids["delivery"]
            )
            assert (await db.get(Order, ids["order"])).status == OrderStatus.ENTREGADO
            assert await db.scalar(select(func.count()).select_from(Financial)) == 2
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(other.receive_json(), 0.15)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(owner.receive_json(), 0.15)
