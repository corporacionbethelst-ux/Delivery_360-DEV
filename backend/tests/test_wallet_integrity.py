"""Persisted wallet contracts; SQLite tests do not claim row-lock coverage."""

import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.api.v1 import wallet as api
from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.core.exceptions import (
    DuplicateTransactionError,
    InsufficientFundsError,
    NotFoundError,
    ValidationError,
)
from app.models.financial import (
    FinancialTransaction,
    PayoutRequest,
    PayoutStatus,
    RiderWallet,
    TransactionType,
)
from app.models.rider import Rider
from app.models.user import User, UserRole
from app.services.wallet_service import MAX_CENTS, WalletService
from tests.orm_contract import mapping_contract


def test_mapped_columns_match_versioned_postgresql_schema():
    expected = json.loads(
        (Path(__file__).parent / "fixtures/wallet_orm_contract.json").read_text()
    )
    assert mapping_contract() == expected


@pytest.fixture
async def wallet_context(test_engine, db_session, test_user):
    async with test_engine.begin() as connection:
        for model in (RiderWallet, FinancialTransaction, PayoutRequest):
            await connection.run_sync(
                lambda conn, model=model: model.__table__.create(conn)
            )
    test_user.role = UserRole.REPARTIDOR
    rider = Rider(user_id=test_user.id)
    db_session.add(rider)
    await db_session.commit()
    service = WalletService(db_session)
    wallet = await service.get_or_create_wallet(rider.id)
    return service, wallet, test_user, rider


async def balance(session, wallet_id):
    return await session.scalar(
        select(RiderWallet.balance_cents).where(RiderWallet.id == wallet_id)
    )


@pytest.mark.asyncio
async def test_profile_ids_and_wallet_creation_are_distinct_and_repeatable(
    wallet_context,
):
    service, wallet, user, rider = wallet_context
    assert user.id != rider.id
    assert await service.rider_id_for_user(user.id) == rider.id
    assert (await service.get_or_create_wallet(rider.id)).id == wallet.id
    assert wallet.balance_cents == 0
    with pytest.raises(NotFoundError):
        await service.get_or_create_wallet(uuid4())
    assert await service.db.scalar(select(func.count()).select_from(RiderWallet)) == 1


@pytest.mark.asyncio
async def test_credit_retry_and_conflicting_key_do_not_change_balance(wallet_context):
    service, wallet, _, _ = wallet_context
    wallet_id = wallet.id
    first = await service.add_funds(
        wallet_id,
        250,
        TransactionType.INGRESO,
        "credit",
        idempotency_key="credit-1",
        metadata_json={"a": 1},
    )
    retry = await service.add_funds(
        wallet_id,
        250,
        TransactionType.INGRESO,
        "credit",
        idempotency_key="credit-1",
        metadata_json={"a": 1},
    )
    assert first.id == retry.id
    assert json.loads(first.metadata_json) == {"a": 1}
    with pytest.raises(DuplicateTransactionError):
        await service.add_funds(
            wallet_id,
            251,
            TransactionType.INGRESO,
            "credit",
            idempotency_key="credit-1",
        )
    assert await balance(service.db, wallet_id) == 250
    assert (
        await service.db.scalar(select(func.count()).select_from(FinancialTransaction))
        == 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", [0, -1, True, 1.5, "100", MAX_CENTS + 1])
async def test_invalid_amounts_never_write(wallet_context, amount):
    service, wallet, _, _ = wallet_context
    with pytest.raises(ValidationError):
        await service.add_funds(wallet.id, amount, TransactionType.INGRESO, "invalid")
    assert await balance(service.db, wallet.id) == 0


@pytest.mark.asyncio
async def test_debit_and_overdraft_preserve_signed_history(wallet_context):
    service, wallet, _, _ = wallet_context
    wallet_id = wallet.id
    await service.add_funds(wallet_id, 1000, TransactionType.INGRESO, "credit")
    debit = await service.withdraw_funds(
        wallet_id, 300, TransactionType.RETIRO, "debit"
    )
    assert debit.amount_cents == -300
    assert debit.balance_after_cents == 700
    with pytest.raises(InsufficientFundsError):
        await service.withdraw_funds(
            wallet_id, 701, TransactionType.RETIRO, "overdraft"
        )
    assert await balance(service.db, wallet_id) == 700
    assert len(await service.get_transactions(wallet_id)) == 2


@pytest.mark.asyncio
async def test_failed_insert_rolls_back_balance(wallet_context):
    service, wallet, _, _ = wallet_context
    wallet_id = wallet.id
    with patch.object(service.db, "flush", side_effect=RuntimeError("insert failed")):
        with pytest.raises(RuntimeError, match="insert failed"):
            await service.add_funds(wallet_id, 1000, TransactionType.INGRESO, "credit")
    assert await balance(service.db, wallet_id) == 0
    assert (
        await service.db.scalar(select(func.count()).select_from(FinancialTransaction))
        == 0
    )


@pytest.mark.asyncio
async def test_payout_reserves_once_conflict_and_rejection_refunds_once(wallet_context):
    service, wallet, _, rider = wallet_context
    wallet_id, rider_id = wallet.id, rider.id
    await service.add_funds(wallet_id, 1000, TransactionType.INGRESO, "credit")
    args = (rider_id, 600, "1234", "Bank", "Owner")
    payout = await service.create_payout_request(*args, idempotency_key="payout-1")
    payout_id = payout.id
    assert (
        await service.create_payout_request(*args, idempotency_key="payout-1")
    ).id == payout_id
    assert await balance(service.db, wallet_id) == 400
    with pytest.raises(DuplicateTransactionError):
        await service.create_payout_request(
            rider_id, 601, "1234", "Bank", "Owner", "payout-1"
        )
    assert await balance(service.db, wallet_id) == 400
    await service.reject_payout(payout_id, "Rejected")
    assert await balance(service.db, wallet_id) == 1000
    with pytest.raises(ValidationError):
        await service.reject_payout(payout_id, "Again")
    assert await balance(service.db, wallet_id) == 1000


@pytest.mark.asyncio
async def test_payout_insert_failure_never_reserves_funds(wallet_context):
    service, wallet, _, rider = wallet_context
    wallet_id, rider_id = wallet.id, rider.id
    await service.add_funds(wallet_id, 1000, TransactionType.INGRESO, "credit")
    with patch.object(service.db, "flush", side_effect=RuntimeError("insert failed")):
        with pytest.raises(RuntimeError):
            await service.create_payout_request(rider_id, 600, "1234", "Bank", "Owner")
    assert await balance(service.db, wallet_id) == 1000
    assert await service.db.scalar(select(func.count()).select_from(PayoutRequest)) == 0


@pytest.mark.asyncio
async def test_approval_completion_no_second_debit_and_illegal_states(wallet_context):
    service, wallet, _, rider = wallet_context
    wallet_id = wallet.id
    await service.add_funds(wallet_id, 1000, TransactionType.INGRESO, "credit")
    payout_id = (
        await service.create_payout_request(rider.id, 600, "1234", "Bank", "Owner")
    ).id
    with pytest.raises(ValidationError):
        await service.complete_payout(payout_id)
    approved = await service.approve_payout(payout_id, "provider-ref")
    assert approved.status == PayoutStatus.APROBADO
    completed = await service.complete_payout(payout_id, '{"ok": true}')
    assert completed.status == PayoutStatus.COMPLETADO
    assert await balance(service.db, wallet_id) == 400
    for action in (service.approve_payout, service.complete_payout):
        with pytest.raises(ValidationError):
            await action(payout_id)
    assert await balance(service.db, wallet_id) == 400


@pytest.mark.asyncio
async def test_inactive_wallet_and_overflow_rejected(wallet_context):
    service, wallet, _, _ = wallet_context
    wallet_id = wallet.id
    wallet.is_active = False
    await service.db.commit()
    with pytest.raises(ValidationError):
        await service.add_funds(wallet_id, 1, TransactionType.INGRESO, "inactive")
    wallet = await service.get_wallet_by_id(wallet_id)
    wallet.is_active = True
    wallet.balance_cents = MAX_CENTS
    await service.db.commit()
    with pytest.raises(ValidationError):
        await service.add_funds(wallet_id, 1, TransactionType.INGRESO, "overflow")
    assert await balance(service.db, wallet_id) == MAX_CENTS


@pytest.fixture
def wallet_app(wallet_context):
    service, _, user, _ = wallet_context
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")

    async def current_user():
        return user

    async def session():
        yield service.db

    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[get_db] = session
    return app


@pytest.fixture
async def wallet_http(wallet_app):
    async with AsyncClient(
        transport=ASGITransport(app=wallet_app), base_url="http://test"
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_http_wallet_profile_contract_and_validation(wallet_context, wallet_http):
    service, wallet, user, rider = wallet_context
    response = await wallet_http.get("/api/v1/wallet")
    assert response.status_code == 200, response.text
    assert response.json()["rider_id"] == str(rider.id)
    await service.add_funds(wallet.id, 1000, TransactionType.INGRESO, "credit")
    payload = dict(
        amount_cents=600,
        bank_account_last4="1234",
        bank_name="Bank",
        account_holder_name="Owner",
        idempotency_key="http-1",
    )
    response = await wallet_http.post("/api/v1/wallet/payout-requests", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "PENDIENTE"
    assert response.json()["amount_decimal"] == 6
    assert (
        await wallet_http.post("/api/v1/wallet/payout-requests", json=payload)
    ).json()["id"] == response.json()["id"]
    assert (await wallet_http.get("/api/v1/wallet/transactions")).json()[0][
        "amount_decimal"
    ] == 10
    assert len((await wallet_http.get("/api/v1/wallet/payout-requests")).json()) == 1
    for amount in (True, 1.5, "600", MAX_CENTS + 1):
        assert (
            await wallet_http.post(
                "/api/v1/wallet/payout-requests",
                json={**payload, "amount_cents": amount},
            )
        ).status_code == 422
    assert (
        await wallet_http.get("/api/v1/admin/payout-requests/pending")
    ).status_code == 403
    user.role = UserRole.OPERADOR
    assert (await wallet_http.get("/api/v1/wallet")).status_code == 403


@pytest.mark.asyncio
async def test_http_administrative_transitions_preserve_balance(
    wallet_context, wallet_http
):
    service, wallet, user, rider = wallet_context
    wallet_id = wallet.id
    await service.add_funds(wallet_id, 1000, TransactionType.INGRESO, "credit")
    payout = await service.create_payout_request(rider.id, 600, "1234", "Bank", "Owner")
    payout_id = payout.id
    user.role = UserRole.GERENTE
    await service.db.commit()
    response = await wallet_http.get("/api/v1/admin/payout-requests/pending")
    assert response.status_code == 200
    assert response.json()[0]["id"] == str(payout_id)
    response = await wallet_http.post(
        f"/api/v1/admin/payout-requests/{payout_id}/approve",
        json={"provider_payout_id": "ref-1"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "APROBADO"
    response = await wallet_http.post(
        f"/api/v1/admin/payout-requests/{payout_id}/complete", json={"test": True}
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "COMPLETADO"
    assert await balance(service.db, wallet_id) == 400
    assert (await wallet_http.get("/api/v1/admin/payout-requests/pending")).json() == []


@pytest.mark.asyncio
async def test_http_rider_without_profile_returns_404_not_user_id_fallback(
    wallet_context, wallet_http, wallet_app
):
    service, _, _, _ = wallet_context
    other = User(
        email="missing-profile@example.test",
        hashed_password="unused",
        first_name="No",
        last_name="Rider",
        role=UserRole.REPARTIDOR,
    )
    service.db.add(other)
    await service.db.commit()

    async def other_user():
        return other

    wallet_app.dependency_overrides[get_current_user] = other_user
    response = await wallet_http.get("/api/v1/wallet")
    assert response.status_code == 404
