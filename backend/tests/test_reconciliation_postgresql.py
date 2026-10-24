"""Concurrency regressions sharing the isolated PostgreSQL-only test fixture."""

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from tests.test_wallet_postgresql import pg_wallets  # noqa: F401 - pytest fixture
from app.models.financial import Financial, PaymentStatus, TransactionType
from app.models.rider import Rider
from app.services.financial_service import FinancialService


@pytest.fixture
async def pg_reconciliation(pg_wallets):
    sessions, _, riders = pg_wallets
    async with sessions() as session:
        await session.execute(
            text(
                "ALTER TABLE riders ADD COLUMN wallet_balance NUMERIC(10,2) DEFAULT 3, ADD COLUMN version INTEGER NOT NULL DEFAULT 0, ADD COLUMN updated_at TIMESTAMP"
            )
        )
        await session.execute(text("CREATE TABLE shifts (id UUID PRIMARY KEY)"))
        connection = await session.connection()
        await connection.run_sync(
            lambda conn: Financial.__table__.create(conn, checkfirst=True)
        )
        session.add(
            Financial(
                rider_id=riders[0],
                amount=100,
                transaction_type=TransactionType.INGRESO,
                status=PaymentStatus.PROCESADO,
                balance_before=0,
                balance_after=100,
            )
        )
        await session.commit()
    return sessions, riders[0]


@pytest.mark.asyncio
async def test_compare_and_swap_allows_only_one_same_version_update(pg_reconciliation):
    sessions, rider_id = pg_reconciliation

    async def update():
        async with sessions() as session:
            result = await FinancialService(session).update_wallet_balance_optimistic(
                str(rider_id), Decimal("20.00"), 0
            )
            await session.commit()
            return result

    results = await asyncio.gather(update(), update())
    assert sorted(results) == [False, True]
    async with sessions() as session:
        result = (
            await session.execute(
                select(Rider.wallet_balance, Rider.version).where(Rider.id == rider_id)
            )
        ).one()
        assert tuple(result) == (Decimal("20.00"), 1)


@pytest.mark.asyncio
async def test_concurrent_sync_does_not_increment_twice_or_add_movements(
    pg_reconciliation,
):
    sessions, rider_id = pg_reconciliation

    async def synchronize():
        async with sessions() as session:
            return await FinancialService(session).reconcile_wallet_with_ledger(
                str(rider_id), dry_run=False
            )

    results = await asyncio.gather(synchronize(), synchronize())
    assert sorted(item["status"] for item in results) == ["ok", "reconciled"]
    async with sessions() as session:
        result = (
            await session.execute(
                select(Rider.wallet_balance, Rider.version).where(Rider.id == rider_id)
            )
        ).one()
        assert tuple(result) == (Decimal("100.00"), 1)
        assert await session.scalar(select(func.count()).select_from(Financial)) == 1
        assert await FinancialService(session).get_current_balance(
            str(rider_id)
        ) == Decimal("100.00")
