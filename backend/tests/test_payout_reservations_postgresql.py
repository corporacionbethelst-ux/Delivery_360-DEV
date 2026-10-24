"""Real PostgreSQL interleavings for reserve/approve/reject decisions."""

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
import pytest
from sqlalchemy import select, func

from tests.test_reconciliation_postgresql import pg_reconciliation  # noqa: F401
from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from app.api.v1 import payouts as api
from app.models.payout import Payout, PayoutStatusHistory
from app.models.financial import Financial, TransactionType
from app.models.rider import Rider
from app.models.user import User, UserRole
from app.services.financial_service import FinancialService


@pytest.fixture
async def pg_requests(pg_reconciliation, monkeypatch):
    sessions, rider_id = pg_reconciliation
    async with sessions() as session:
        connection = await session.connection()
        for model in (Payout, PayoutStatusHistory):
            await connection.run_sync(
                lambda conn, model=model: model.__table__.create(conn, checkfirst=True)
            )
        other_id = await session.scalar(select(Rider.id).where(Rider.id != rider_id))
        user_ids = [
            await session.scalar(select(Rider.user_id).where(Rider.id == parent))
            for parent in (rider_id, other_id)
        ]
        manager = User(
            email="manager@example.test",
            hashed_password="unused",
            first_name="Manager",
            last_name="Test",
            role=UserRole.GERENTE,
        )
        session.add(manager)
        await session.commit()
        manager_id = manager.id
        await FinancialService(session).create_ledger_entry(
            rider_id=other_id, amount=100, transaction_type=TransactionType.INGRESO
        )
    monkeypatch.setattr(api, "_notify_requested", AsyncMock())
    monkeypatch.setattr(
        api, "get_redis_audit_logger", lambda: SimpleNamespace(connected=False)
    )
    monkeypatch.setattr("app.services.notification_hooks.notify_event", AsyncMock())
    return sessions, rider_id, user_ids, manager_id


async def request(sessions, user_id, amount, key=None, barrier=None):
    async with sessions() as session:
        user = await session.scalar(select(User).where(User.id == user_id))

        async def submit():
            return await api.request_payout(
                api.PayoutRequestBody(amount=amount, idempotency_key=key),
                db=session,
                current_user=user,
            )

        try:
            if barrier is None:
                return await submit()
            original_flush = session.flush

            async def flush(*args, **kwargs):
                await barrier.wait()
                return await original_flush(*args, **kwargs)

            with patch.object(session, "flush", flush):
                return await submit()
        except HTTPException as error:
            return error


async def decision(sessions, manager_id, payout_id, reject=False):
    async with sessions() as session:
        manager = await session.scalar(select(User).where(User.id == manager_id))
        if reject:
            return await api.reject_payout(
                payout_id,
                api.PayoutRejectBody(reason="Rejected"),
                db=session,
                current_user=manager,
            )
        return await api.approve_payout(payout_id, db=session, current_user=manager)


@pytest.mark.asyncio
async def test_two_requests_cannot_reserve_more_than_the_ledger(pg_requests):
    sessions, rider_id, users, _ = pg_requests
    results = await asyncio.gather(
        request(sessions, users[0], 80), request(sessions, users[0], 80)
    )
    assert sum(isinstance(item, dict) for item in results) == 1
    assert (
        sum(
            isinstance(item, HTTPException) and item.status_code == 400
            for item in results
        )
        == 1
    )
    async with sessions() as session:
        assert (await api._calculate_available_balance(session, rider_id))[
            "available"
        ] == 20
        assert (
            await session.scalar(select(func.count()).select_from(PayoutStatusHistory))
            == 1
        )


@pytest.mark.asyncio
async def test_same_request_key_only_reserves_once(pg_requests):
    sessions, rider_id, users, _ = pg_requests
    a, b = await asyncio.gather(
        request(sessions, users[0], 60, "same"), request(sessions, users[0], 60, "same")
    )
    assert a["id"] == b["id"]
    async with sessions() as session:
        assert (await api._calculate_available_balance(session, rider_id))[
            "available"
        ] == 40
        assert await session.scalar(select(func.count()).select_from(Payout)) == 1
        assert (
            await session.scalar(select(func.count()).select_from(PayoutStatusHistory))
            == 1
        )


@pytest.mark.asyncio
async def test_cross_rider_key_race_returns_conflict_without_duplicate_reservation(
    pg_requests,
):
    sessions, _, users, _ = pg_requests
    barrier = asyncio.Barrier(2)
    results = await asyncio.gather(
        *(request(sessions, user_id, 60, "global", barrier) for user_id in users)
    )
    assert sum(isinstance(item, dict) for item in results) == 1
    assert (
        sum(
            isinstance(item, HTTPException) and item.status_code == 409
            for item in results
        )
        == 1
    )
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Payout)) == 1
        assert (
            await session.scalar(select(func.count()).select_from(PayoutStatusHistory))
            == 1
        )


@pytest.mark.asyncio
async def test_approval_and_new_request_cannot_spend_the_same_reserve(pg_requests):
    sessions, rider_id, users, manager = pg_requests
    payout = await request(sessions, users[0], 60)
    approved, denied = await asyncio.gather(
        decision(sessions, manager, payout["id"]), request(sessions, users[0], 50)
    )
    assert approved["status"] == "EN_PROCESO"
    assert isinstance(denied, HTTPException) and denied.status_code == 400
    async with sessions() as session:
        assert (await api._calculate_available_balance(session, rider_id))[
            "available"
        ] == 40


@pytest.mark.asyncio
async def test_two_approvals_consume_exactly_the_reserved_ledger_amount(pg_requests):
    sessions, rider_id, users, manager = pg_requests
    a = await request(sessions, users[0], 60)
    b = await request(sessions, users[0], 40)
    results = await asyncio.gather(
        *(decision(sessions, manager, item["id"]) for item in (a, b))
    )
    assert all(item["status"] == "EN_PROCESO" for item in results)
    async with sessions() as session:
        balance = await api._calculate_available_balance(session, rider_id)
        assert balance["available"] == 0
        assert balance["ledger_balance"] == 0
        assert balance["reserved"] == 0


@pytest.mark.asyncio
async def test_rejection_racing_new_reservation_never_overcommits(pg_requests):
    sessions, rider_id, users, manager = pg_requests
    payout = await request(sessions, users[0], 80)
    rejected, result = await asyncio.gather(
        decision(sessions, manager, payout["id"], reject=True),
        request(sessions, users[0], 70),
    )
    assert rejected["status"] == "RECHAZADO"
    async with sessions() as session:
        balance = await api._calculate_available_balance(session, rider_id)
        assert balance["available"] == (30 if isinstance(result, dict) else 100)
        assert balance["reserved"] <= balance["ledger_balance"]


@pytest.mark.asyncio
async def test_stale_identity_cannot_reject_a_previously_approved_payout(pg_requests):
    sessions, _, users, manager_id = pg_requests
    payout = await request(sessions, users[0], 60)
    import uuid

    async with sessions() as stale:
        loaded = await stale.scalar(
            select(Payout).where(Payout.id == uuid.UUID(payout["id"]))
        )
        manager = await stale.scalar(select(User).where(User.id == manager_id))
        await decision(sessions, manager_id, payout["id"])
        with pytest.raises(HTTPException) as error:
            await api.reject_payout(
                str(loaded.id),
                api.PayoutRejectBody(reason="Stale"),
                db=stale,
                current_user=manager,
            )
        assert error.value.status_code == 400


@pytest.mark.asyncio
async def test_legacy_paymentstatus_without_pagado_can_read_existing_balances(
    pg_requests,
):
    from sqlalchemy import text

    sessions, rider_id, _, _ = pg_requests
    async with sessions() as session:
        for statement in (
            "ALTER TABLE financials ALTER COLUMN status TYPE TEXT USING status::TEXT",
            "DROP TYPE paymentstatus",
            "CREATE TYPE paymentstatus AS ENUM ('PENDIENTE', 'PROCESADO', 'RECHAZADO')",
            "ALTER TABLE financials ALTER COLUMN status TYPE paymentstatus USING status::paymentstatus",
        ):
            await session.execute(text(statement))
        await session.commit()
        balance = await api._calculate_available_balance(session, rider_id)
        assert balance["available"] == 100
        assert balance["total_earned"] == 100
