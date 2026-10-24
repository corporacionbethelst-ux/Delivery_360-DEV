"""Requests are backed by ledger money, and reserves survive terminal states."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import delete, select, func

from tests.test_ledger_integrity import payout_context  # noqa: F401
from tests.test_ledger_integrity import ledger_context  # noqa: F401
from tests.test_reconciliation_safety import reconciliation_context  # noqa: F401
from app.api.v1 import payouts as api
from app.api.v1.payouts import _notify_requested as real_notify_requested
from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.financial import Financial, TransactionType, PaymentStatus, PayoutStatus
from app.models.payout import Payout, PayoutStatusHistory
from app.models.user import UserRole
from app.services.financial_service import FinancialService


@pytest.fixture
async def reservation_context(payout_context, monkeypatch):
    session, rider_id, user, _ = payout_context
    await session.execute(delete(Payout))
    user.role = UserRole.REPARTIDOR
    await session.commit()
    monkeypatch.setattr(api, "_notify_requested", AsyncMock())
    monkeypatch.setattr(
        api, "get_redis_audit_logger", lambda: SimpleNamespace(connected=False)
    )
    return session, rider_id, user


@pytest.mark.asyncio
async def test_retry_matches_amount_method_bank_and_actor(reservation_context):
    session, rider_id, user = reservation_context
    first = await api.request_payout(
        api.PayoutRequestBody(
            amount=60, idempotency_key="same", bank_account_last4="1234"
        ),
        db=session,
        current_user=user,
    )
    retry = await api.request_payout(
        api.PayoutRequestBody(
            amount=60, idempotency_key="same", bank_account_last4="1234"
        ),
        db=session,
        current_user=user,
    )
    assert first["id"] == retry["id"]
    from fastapi import HTTPException

    for change in (
        {"amount": 61},
        {"bank_account_last4": "4321"},
        {"method": "EFECTIVO"},
    ):
        data = dict(amount=60, idempotency_key="same", bank_account_last4="1234")
        data.update(change)
        with pytest.raises(HTTPException) as error:
            await api.request_payout(
                api.PayoutRequestBody(**data), db=session, current_user=user
            )
        assert error.value.status_code == 409
    assert await session.scalar(select(func.count()).select_from(Payout)) == 1
    assert (
        await session.scalar(select(func.count()).select_from(PayoutStatusHistory)) == 1
    )
    assert (await api._calculate_available_balance(session, rider_id))[
        "available"
    ] == 40


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        PayoutStatus.PENDIENTE,
        PayoutStatus.APROBADO,
        PayoutStatus.EN_PROCESO,
        PayoutStatus.COMPLETADO,
        None,
    ],
)
async def test_unposted_reserves_remain_held_in_all_committed_states(
    reservation_context, status
):
    session, rider_id, _ = reservation_context
    session.add(Payout(rider_id=rider_id, amount=30, status=status))
    await session.commit()
    assert (await api._calculate_available_balance(session, rider_id))[
        "available"
    ] == 70


@pytest.mark.asyncio
async def test_posted_withdrawal_is_not_deducted_again_when_completed(
    reservation_context,
):
    session, rider_id, _ = reservation_context
    payout = Payout(rider_id=rider_id, amount=30, status=PayoutStatus.COMPLETADO)
    session.add(payout)
    await session.commit()
    await FinancialService(session).create_ledger_entry(
        rider_id=rider_id,
        amount=30,
        transaction_type=TransactionType.RETIRO,
        reference_id=str(payout.id),
        source_type="PAYOUT",
        source_id=str(payout.id),
    )
    balance = await api._calculate_available_balance(session, rider_id)
    assert balance["ledger_balance"] == 70
    assert balance["reserved"] == 0
    assert balance["available"] == 70


@pytest.mark.asyncio
async def test_deductions_and_negative_adjustments_reduce_withdrawable_money(
    reservation_context,
):
    session, rider_id, _ = reservation_context
    service = FinancialService(session)
    await service.create_ledger_entry(
        rider_id=rider_id, amount=20, transaction_type=TransactionType.PENALIZACION
    )
    await service.create_ledger_entry(
        rider_id=rider_id, amount=-5, transaction_type=TransactionType.AJUSTE
    )
    assert (await api._calculate_available_balance(session, rider_id))[
        "available"
    ] == 75


@pytest.mark.asyncio
async def test_no_ledger_means_no_withdrawable_credit(reservation_context):
    session, rider_id, _ = reservation_context
    await session.execute(delete(Financial))
    await session.commit()
    assert (await api._calculate_available_balance(session, rider_id))["available"] == 0


@pytest.mark.asyncio
async def test_http_amount_key_and_bank_validation(reservation_context):
    session, _, user = reservation_context
    app = FastAPI()
    app.include_router(api.router)

    async def database():
        yield session

    async def current_user():
        return user

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = current_user
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        for invalid in (
            {"amount": True},
            {"amount": 10.001},
            {"amount": "NaN"},
            {"amount": 100000000},
            {"idempotency_key": " "},
            {"bank_account_last4": "AB12"},
        ):
            response = await client.post(
                "/payouts/request", json={"amount": 60, **invalid}
            )
            assert response.status_code == 422, response.text
        response = await client.post(
            "/payouts/request", json={"amount": 60, "idempotency_key": "http"}
        )
        assert response.status_code == 201, response.text
        assert response.json()["status"] == "PENDIENTE"


@pytest.mark.asyncio
async def test_bad_historical_reservation_is_not_treated_as_extra_money(
    reservation_context,
):
    from fastapi import HTTPException

    session, rider_id, _ = reservation_context
    session.add(Payout(rider_id=rider_id, amount=-30, status=PayoutStatus.PENDIENTE))
    await session.commit()
    with pytest.raises(HTTPException) as error:
        await api._calculate_available_balance(session, rider_id)
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_failed_notification_session_does_not_change_committed_request(
    reservation_context, monkeypatch
):
    import asyncio
    from unittest.mock import patch

    session, _, user = reservation_context
    monkeypatch.setattr(api, "_notify_requested", real_notify_requested)
    original_commit = session.commit
    with (
        patch.object(session, "commit", wraps=original_commit) as commit,
        patch(
            "app.core.database.AsyncSessionLocal",
            side_effect=RuntimeError("notification unavailable"),
        ),
    ):
        response = await api.request_payout(
            api.PayoutRequestBody(amount=60), db=session, current_user=user
        )
        await asyncio.sleep(0)
        assert commit.await_count == 1
    assert response["status"] == "PENDIENTE"
    assert await session.scalar(select(func.count()).select_from(Payout)) == 1
    assert (
        await session.scalar(select(func.count()).select_from(PayoutStatusHistory)) == 1
    )
