"""Real row-lock and persistence checks in disposable test_* schemas."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select, func

from tests.test_delivery_financial_postgresql import payment_db  # noqa: F401
from app.models.audit_log import AuditLog
from app.models.delivery import Delivery, ProofType
from app.models.financial import Financial
from app.models.order import Order, OrderStatus
from app.models.user import User
from app.services import delivery_otp as service
from app.core.security import create_access_token


async def prepare(sessions, ids):
    async with sessions() as db:
        connection = await db.connection()
        await connection.run_sync(
            lambda sync: AuditLog.__table__.create(sync, checkfirst=True)
        )
        order = await db.get(Order, ids["order"])
        order.customer_email = "recipient@example.com"
        record = await db.get(Delivery, ids["delivery"])
        record.proof_type = ProofType.OTP
        record.proof_otp = None
        await db.commit()


@pytest.mark.asyncio
async def test_simultaneous_email_requests_send_once_and_keep_order_open(
    payment_db, monkeypatch
):
    _, sessions, ids = payment_db
    await prepare(sessions, ids)
    sender = AsyncMock(return_value=True)
    monkeypatch.setattr(service, "smtp_email_is_configured", lambda: True)
    monkeypatch.setattr(service, "send_smtp_email", sender)

    async def request():
        async with sessions() as db:
            actor = await db.get(User, ids["staff"])
            try:
                return await service.email_delivery_otp(db, ids["order"], actor)
            except HTTPException as error:
                return error.status_code

    results = await asyncio.gather(request(), request())
    assert (
        sum(
            isinstance(result, dict) and result["status"] == "accepted"
            for result in results
        )
        == 1
    )
    assert results.count(429) == 1
    sender.assert_awaited_once()
    async with sessions() as db:
        record = await db.get(Delivery, ids["delivery"])
        assert len(record.proof_otp) == 6
        assert record.proof_otp.isdecimal()
        assert (await db.get(Order, ids["order"])).status == OrderStatus.EN_RUTA
        assert await db.scalar(select(func.count()).select_from(Financial)) == 1
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.resource_type == service.ATTEMPT_RESOURCE)
            )
            == 1
        )


@pytest.mark.asyncio
async def test_provider_failure_retains_committed_code_without_changing_money(
    payment_db, monkeypatch
):
    _, sessions, ids = payment_db
    await prepare(sessions, ids)
    monkeypatch.setattr(service, "smtp_email_is_configured", lambda: True)

    async def failed_transport(*args):
        async with sessions() as read:
            record = await read.get(Delivery, ids["delivery"])
            assert record.proof_otp and record.proof_otp in args[3]
        return False

    monkeypatch.setattr(service, "send_smtp_email", failed_transport)
    async with sessions() as db:
        actor = await db.get(User, ids["staff"])
        with pytest.raises(HTTPException) as error:
            await service.email_delivery_otp(db, ids["order"], actor)
        assert error.value.status_code == 503
    async with sessions() as db:
        record = await db.get(Delivery, ids["delivery"])
        assert record.proof_otp is not None
        assert (await db.get(Order, ids["order"])).status == OrderStatus.EN_RUTA
        assert await db.scalar(select(func.count()).select_from(Financial)) == 1
        outcome = await db.scalar(
            select(AuditLog).where(
                AuditLog.resource_type == "DELIVERY_OTP_EMAIL_RESULT"
            )
        )
        assert outcome.success is False


@pytest.mark.asyncio
async def test_http_issue_then_complete_with_recipient_code(payment_db, monkeypatch):
    client, sessions, ids = payment_db
    await prepare(sessions, ids)
    received = []

    async def transport(recipient, subject, html, plain):
        async with sessions() as read:
            code = (await read.get(Delivery, ids["delivery"])).proof_otp
            assert code in plain
            received.append(code)
        return True

    monkeypatch.setattr(service, "smtp_email_is_configured", lambda: True)
    monkeypatch.setattr(service, "send_smtp_email", transport)
    headers = {"Authorization": "Bearer " + create_access_token(ids["staff"])}
    path = f"/api/v1/orders/{ids['order']}"
    response = client.post(path + "/delivery-otp/email", headers=headers)
    assert response.status_code == 200, response.text
    assert len(received) == 1
    assert received[0] not in response.text
    missing = client.patch(
        path + "/status?new_status=ENTREGADO", headers=headers, json={}
    )
    assert missing.status_code == 400
    completed = client.patch(
        path + "/status?new_status=ENTREGADO",
        headers=headers,
        json={"otp_code": received[0]},
    )
    assert completed.status_code == 200, completed.text
    async with sessions() as read:
        assert (await read.get(Order, ids["order"])).status == OrderStatus.ENTREGADO
        assert await read.scalar(select(func.count()).select_from(Financial)) == 2
