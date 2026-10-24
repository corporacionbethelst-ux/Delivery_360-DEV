"""Real PostgreSQL serialization and unique-key race contracts for financials."""

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import func, select

from tests.test_reconciliation_postgresql import pg_reconciliation  # noqa: F401
from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from app.core.exceptions import DuplicateTransactionError, ValidationError
from app.models.financial import Financial, TransactionType
from app.models.rider import Rider
from app.services.financial_service import FinancialService


async def credit(session, rider_id, key, *, amount=10, commit=True):
    return await FinancialService(session).create_ledger_entry(
        rider_id=rider_id,
        amount=amount,
        transaction_type=TransactionType.INGRESO,
        idempotency_key=key,
        description="credit",
        commit=commit,
    )


@pytest.mark.asyncio
async def test_concurrent_credits_have_contiguous_snapshots(pg_reconciliation):
    sessions, rider_id = pg_reconciliation

    async def post(key):
        async with sessions() as session:
            return await credit(session, rider_id, key)

    results = await asyncio.gather(post("credit-a"), post("credit-b"))
    assert sorted((row.balance_before, row.balance_after) for row in results) == [
        (Decimal("100"), Decimal("110")),
        (Decimal("110"), Decimal("120")),
    ]
    async with sessions() as session:
        assert await FinancialService(session).get_current_balance(rider_id) == Decimal(
            "120"
        )


@pytest.mark.asyncio
async def test_concurrent_retries_only_create_one_movement(pg_reconciliation):
    sessions, rider_id = pg_reconciliation

    async def post():
        async with sessions() as session:
            return await credit(session, rider_id, "same-credit")

    a, b = await asyncio.gather(post(), post())
    assert a.id == b.id
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Financial)) == 2
        assert await FinancialService(session).get_current_balance(rider_id) == Decimal(
            "110"
        )


@pytest.mark.asyncio
async def test_global_key_race_uses_savepoint_and_rolls_back_only_losing_insert(
    pg_reconciliation,
):
    sessions, rider_id = pg_reconciliation
    async with sessions() as session:
        other_id = await session.scalar(select(Rider.id).where(Rider.id != rider_id))
    barrier = asyncio.Barrier(2)

    async def post(parent_id):
        async with sessions() as session:
            original_flush = session.flush

            async def synchronized_flush(*args, **kwargs):
                await barrier.wait()
                return await original_flush(*args, **kwargs)

            with patch.object(session, "flush", synchronized_flush):
                try:
                    return await credit(session, parent_id, "global-key")
                except DuplicateTransactionError as error:
                    # Owning operations must leave a usable session after rollback.
                    assert (
                        await session.scalar(
                            select(func.count()).select_from(Financial)
                        )
                        == 2
                    )
                    return error

    results = await asyncio.gather(post(rider_id), post(other_id))
    assert sum(isinstance(item, Financial) for item in results) == 1
    assert sum(isinstance(item, DuplicateTransactionError) for item in results) == 1
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Financial)) == 2
        balances = [
            await FinancialService(session).get_current_balance(parent_id)
            for parent_id in (rider_id, other_id)
        ]
        assert sum(balances) == Decimal("110")


@pytest.mark.asyncio
async def test_outer_rollback_removes_uncommitted_ledger_entry(pg_reconciliation):
    sessions, rider_id = pg_reconciliation
    async with sessions() as session:
        await credit(session, rider_id, "outer-owned", commit=False)
        assert await FinancialService(session).get_current_balance(rider_id) == Decimal(
            "110"
        )
        await session.rollback()
    async with sessions() as session:
        assert await FinancialService(session).get_current_balance(rider_id) == Decimal(
            "100"
        )
        assert await session.scalar(select(func.count()).select_from(Financial)) == 1


@pytest.mark.asyncio
async def test_clock_regression_and_equal_times_do_not_reverse_snapshot_order(
    pg_reconciliation,
):
    sessions, rider_id = pg_reconciliation

    async with sessions() as session:
        latest = await session.scalar(select(func.max(Financial.created_at)))

        class FrozenClock:
            @staticmethod
            def utcnow():
                return latest - timedelta(microseconds=1)

        with patch("app.services.financial_service.datetime", FrozenClock):
            first = await credit(session, rider_id, "clock-a")
            second = await credit(session, rider_id, "clock-b")
        assert first.created_at < second.created_at
        assert await FinancialService(session).get_current_balance(rider_id) == Decimal(
            "120"
        )


@pytest.mark.asyncio
async def test_future_dated_history_does_not_move_new_entries_into_another_period(
    pg_reconciliation,
):
    from sqlalchemy import update

    sessions, rider_id = pg_reconciliation
    async with sessions() as session:
        await session.execute(
            update(Financial).values(created_at=datetime.utcnow() + timedelta(days=1))
        )
        await session.commit()
        with pytest.raises(ValidationError, match="cronología"):
            await credit(session, rider_id, "future-history")
        assert await session.scalar(select(func.count()).select_from(Financial)) == 1
