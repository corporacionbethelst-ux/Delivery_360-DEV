"""Recipient email OTP: authorization, durable retries and transport failures."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from app.api.v1.auth import get_current_user
from app.api.v1.orders import router
from app.core.database import get_db
from app.models.delivery import DeliveryStatus, ProofType
from app.models.order import OrderStatus
from app.models.user import UserRole
from app.services import delivery_otp as service
from tests.test_password_recovery_email import smtp  # noqa: F401
from tests.test_password_recovery_smtp import local_smtp  # noqa: F401


def make_app(context):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def current_user():
        return context.actor

    async def database():
        yield context.db

    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[get_db] = database
    return app


@pytest.fixture
def context(monkeypatch):
    actor = SimpleNamespace(
        id=uuid4(),
        email="staff@example.com",
        role=UserRole.GERENTE,
        token_version=2,
        is_active=True,
    )
    record = SimpleNamespace(
        id=uuid4(),
        proof_type=ProofType.OTP,
        proof_otp=None,
        status=DeliveryStatus.EN_ROUTE,
        rider_id=uuid4(),
    )
    order = SimpleNamespace(
        id=uuid4(),
        status=OrderStatus.EN_RUTA,
        assigned_rider_id=record.rider_id,
        customer_email="recipient@example.com",
        external_id="ORD-<1>",
    )
    db = MagicMock()
    db.scalar = AsyncMock(side_effect=lambda query: None)
    db.scalar.side_effect = [order, actor, None]
    db.scalars = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[record])))
    db.commit = AsyncMock()
    sender = AsyncMock(return_value=True)
    monkeypatch.setattr(service, "send_smtp_email", sender)
    monkeypatch.setattr(service, "smtp_email_is_configured", lambda: True)
    return SimpleNamespace(
        db=db, actor=actor, order=order, record=record, sender=sender
    )


@pytest.mark.asyncio
async def test_code_is_durable_before_transport_and_never_returned_or_audited(context):
    c = context

    async def send(*args):
        assert c.db.commit.await_count == 1
        assert len(c.record.proof_otp) == 6
        assert c.record.proof_otp in args[2]
        assert "ORD-&lt;1&gt;" in args[2]
        return True

    c.sender.side_effect = send
    result = await service.email_delivery_otp(c.db, c.order.id, c.actor)
    assert result["status"] == "accepted"
    assert "otp" not in result
    assert c.record.proof_otp not in json.dumps(result)
    assert c.db.commit.await_count == 2
    for call in c.db.add.call_args_list:
        audit = call.args[0]
        assert c.record.proof_otp not in json.dumps(audit.new_values)
        assert c.order.customer_email not in json.dumps(audit.new_values)


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted", [True, False])
async def test_resend_keeps_code_even_if_provider_fails(context, accepted):
    c = context
    c.record.proof_otp = "001234"
    c.sender.return_value = accepted
    if accepted:
        await service.email_delivery_otp(c.db, c.order.id, c.actor)
    else:
        with pytest.raises(HTTPException) as error:
            await service.email_delivery_otp(c.db, c.order.id, c.actor)
        assert error.value.status_code == 503
    assert c.record.proof_otp == "001234"
    assert c.db.add.call_args_list[0].args[0].new_values["generated"] is False
    assert c.db.add.call_args_list[-1].args[0].success is accepted


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,status",
    [
        ("no_order", 404),
        ("not_en_route", 409),
        ("ambiguous", 409),
        ("assignment", 409),
        ("wrong_proof", 409),
        ("terminal", 400),
        ("bad_email", 409),
        ("no_smtp", 503),
        ("cooldown", 429),
        ("revoked", 401),
        ("demoted", 403),
    ],
)
async def test_failed_preconditions_never_send_or_change_code(
    context, monkeypatch, case, status
):
    c = context
    actor = c.actor
    recent = None
    if case == "no_order":
        c.order = None
    if case == "not_en_route":
        c.order.status = OrderStatus.ENTREGADO
    if case == "ambiguous":
        c.db.scalars.return_value.all.return_value = [c.record, c.record]
    if case == "assignment":
        c.order.assigned_rider_id = uuid4()
    if case == "wrong_proof":
        c.record.proof_type = ProofType.FOTO
    if case == "terminal":
        c.record.status = DeliveryStatus.COMPLETADA
    if case == "bad_email":
        c.order.customer_email = "invalid"
    if case == "no_smtp":
        monkeypatch.setattr(service, "smtp_email_is_configured", lambda: False)
    if case == "cooldown":
        recent = uuid4()
    if case in ("revoked", "demoted"):
        actor = SimpleNamespace(**vars(c.actor))
        if case == "revoked":
            actor.token_version = 3
        else:
            actor.role = UserRole.OPERADOR
    c.db.scalar.side_effect = [c.order, actor, recent]
    with pytest.raises(HTTPException) as error:
        await service.email_delivery_otp(c.db, uuid4(), c.actor)
    assert error.value.status_code == status
    c.sender.assert_not_awaited()
    c.db.commit.assert_not_awaited()
    assert c.record.proof_otp is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role", [UserRole.REPARTIDOR, UserRole.OPERADOR, UserRole.AUDITOR, UserRole.CLIENTE]
)
async def test_http_roles_cannot_issue_or_read_recipient_code(context, role):
    c = context
    c.actor.role = role
    app = make_app(c)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(f"/api/v1/orders/{uuid4()}/delivery-otp/email")
    assert response.status_code == 403
    c.db.scalar.assert_not_awaited()
    c.sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_http_staff_uses_real_service_and_does_not_expose_otp(context):
    c = context
    app = make_app(c)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(f"/api/v1/orders/{c.order.id}/delivery-otp/email")
    assert response.status_code == 200
    assert c.record.proof_otp not in response.text
    assert "recipient@example.com" not in response.text


@pytest.mark.asyncio
async def test_persistence_failure_never_calls_transport(context):
    c = context
    c.db.commit.side_effect = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError):
        await service.email_delivery_otp(c.db, c.order.id, c.actor)
    c.sender.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("implicit", [False, True])
async def test_recipient_otp_uses_real_authenticated_tls(
    context, local_smtp, monkeypatch, implicit
):
    from app.core.email_service import send_smtp_email

    c = context
    c.record.proof_otp = "001234"
    monkeypatch.setattr(service, "send_smtp_email", send_smtp_email)
    async with local_smtp(implicit=implicit) as (commands, credentials, messages, _):
        result = await service.email_delivery_otp(c.db, c.order.id, c.actor)
    assert result["status"] == "accepted"
    assert credentials == [b"\x00test-login\x00test-only-password"]
    assert len(messages) == 1
    message = messages[0]
    assert message["To"] == "recipient@example.com"
    assert "001234" in message.get_body(preferencelist=("plain",)).get_content()
    assert "ORD-&lt;1&gt;" in message.get_body(preferencelist=("html",)).get_content()
    assert all(
        encrypted
        for verb, encrypted in commands
        if verb in ("AUTH", "MAIL", "RCPT", "DATA")
    )
