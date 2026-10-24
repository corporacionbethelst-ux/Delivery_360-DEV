"""Real row-lock tests in a private schema of an explicitly selected test DB.

Run with TEST_DATABASE_URL=postgresql+asyncpg://.../test_db. No application
DATABASE_URL fallback is permitted, and non-test database names are refused.
"""

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.exceptions import (
    DuplicateTransactionError,
    InsufficientFundsError,
    ValidationError,
)
from app.models.financial import (
    FinancialTransaction,
    PayoutRequest,
    RiderWallet,
    TransactionType,
)
from app.models.user import User, UserRole
from app.services.wallet_service import WalletService


@pytest.fixture
async def pg_wallets():
    raw_url = os.environ.get("TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("TEST_DATABASE_URL not configured; row locks require PostgreSQL")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or not (url.database or "").startswith(
        "test_"
    ):
        pytest.fail(
            "Wallet integration tests require an explicit PostgreSQL test_* database"
        )
    url = url.set(drivername="postgresql+asyncpg")
    schema = "wallet_test_" + uuid4().hex
    # TestClient/pytest fixtures may use separate loops; do not share asyncpg
    # connections across them. Production pooling remains unchanged.
    admin = create_async_engine(url, poolclass=NullPool)
    engine = None
    try:
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(
            url,
            poolclass=NullPool,
            connect_args={"server_settings": {"search_path": schema}},
        )
        async with engine.begin() as connection:
            await connection.run_sync(lambda conn: User.__table__.create(conn))
            # Only the parent identifiers are needed; avoid unrelated PostGIS models.
            await connection.execute(
                text(
                    "CREATE TABLE riders (id UUID PRIMARY KEY, user_id UUID NOT NULL UNIQUE REFERENCES users(id))"
                )
            )
            for model in (RiderWallet, FinancialTransaction, PayoutRequest):
                await connection.run_sync(
                    lambda conn, model=model: model.__table__.create(conn)
                )
        sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        rider_ids = [uuid4(), uuid4()]
        wallet_ids = []
        async with sessions() as session:
            for rider_id in rider_ids:
                user = User(
                    email=f"{rider_id}@example.test",
                    hashed_password="unused-test-only",
                    first_name="Test",
                    last_name="Wallet",
                    role=UserRole.REPARTIDOR,
                )
                session.add(user)
                await session.flush()
                await session.execute(
                    text("INSERT INTO riders (id, user_id) VALUES (:id, :user_id)"),
                    {"id": rider_id, "user_id": user.id},
                )
            await session.commit()
            service = WalletService(session)
            for rider_id in rider_ids:
                wallet = await service.get_or_create_wallet(rider_id)
                wallet_ids.append(wallet.id)
                await service.add_funds(
                    wallet.id, 1000, TransactionType.INGRESO, "initial"
                )
        yield sessions, wallet_ids, rider_ids
    finally:
        if engine is not None:
            await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()


@pytest.mark.asyncio
async def test_concurrent_debits_cannot_overdraw(pg_wallets):
    sessions, wallets, _ = pg_wallets

    async def debit():
        async with sessions() as session:
            return await WalletService(session).withdraw_funds(
                wallets[0], 800, TransactionType.RETIRO, "debit"
            )

    results = await asyncio.gather(debit(), debit(), return_exceptions=True)
    assert sum(isinstance(item, FinancialTransaction) for item in results) == 1
    assert sum(isinstance(item, InsufficientFundsError) for item in results) == 1
    async with sessions() as session:
        assert (
            await session.scalar(
                select(RiderWallet.balance_cents).where(RiderWallet.id == wallets[0])
            )
            == 200
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(FinancialTransaction)
                .where(FinancialTransaction.wallet_id == wallets[0])
            )
            == 2
        )


@pytest.mark.asyncio
async def test_concurrent_same_key_posts_only_once(pg_wallets):
    sessions, wallets, _ = pg_wallets

    async def credit(wallet_id):
        async with sessions() as session:
            return await WalletService(session).add_funds(
                wallet_id,
                250,
                TransactionType.INGRESO,
                "credit",
                idempotency_key="shared-key",
            )

    results = await asyncio.gather(credit(wallets[0]), credit(wallets[0]))
    assert results[0].id == results[1].id
    async with sessions() as session:
        assert (
            await session.scalar(
                select(RiderWallet.balance_cents).where(RiderWallet.id == wallets[0])
            )
            == 1250
        )


@pytest.mark.asyncio
async def test_cross_wallet_key_conflict_rolls_back_loser(pg_wallets):
    sessions, wallets, _ = pg_wallets

    async def credit(wallet_id):
        async with sessions() as session:
            return await WalletService(session).add_funds(
                wallet_id,
                250,
                TransactionType.INGRESO,
                "credit",
                idempotency_key="cross-wallet-key",
            )

    results = await asyncio.gather(
        *(credit(wallet_id) for wallet_id in wallets), return_exceptions=True
    )
    assert sum(isinstance(item, FinancialTransaction) for item in results) == 1
    assert sum(isinstance(item, DuplicateTransactionError) for item in results) == 1
    async with sessions() as session:
        balances = (
            await session.scalars(
                select(RiderWallet.balance_cents).order_by(RiderWallet.balance_cents)
            )
        ).all()
        assert list(balances) == [1000, 1250]


@pytest.mark.asyncio
async def test_concurrent_reservations_and_rejections_refund_once(pg_wallets):
    sessions, wallets, riders = pg_wallets

    async def reserve():
        async with sessions() as session:
            return await WalletService(session).create_payout_request(
                riders[0], 800, "1234", "Bank", "Owner"
            )

    results = await asyncio.gather(reserve(), reserve(), return_exceptions=True)
    payouts = [item for item in results if isinstance(item, PayoutRequest)]
    assert len(payouts) == 1
    assert sum(isinstance(item, InsufficientFundsError) for item in results) == 1

    async def reject():
        async with sessions() as session:
            return await WalletService(session).reject_payout(payouts[0].id, "Rejected")

    results = await asyncio.gather(reject(), reject(), return_exceptions=True)
    assert sum(isinstance(item, PayoutRequest) for item in results) == 1
    assert sum(isinstance(item, ValidationError) for item in results) == 1
    async with sessions() as session:
        assert (
            await session.scalar(
                select(RiderWallet.balance_cents).where(RiderWallet.id == wallets[0])
            )
            == 1000
        )


@pytest.mark.asyncio
async def test_locked_refresh_does_not_use_stale_identity_balance(pg_wallets):
    sessions, wallets, _ = pg_wallets
    async with sessions() as stale_session:
        stale_wallet = await WalletService(stale_session).get_wallet_by_id(wallets[0])
        assert stale_wallet.balance_cents == 1000
        async with sessions() as other_session:
            await WalletService(other_session).withdraw_funds(
                wallets[0], 800, TransactionType.RETIRO, "other debit"
            )
        with pytest.raises(InsufficientFundsError):
            await WalletService(stale_session).withdraw_funds(
                wallets[0], 800, TransactionType.RETIRO, "stale debit"
            )
        assert (
            await stale_session.scalar(
                select(RiderWallet.balance_cents).where(RiderWallet.id == wallets[0])
            )
            == 200
        )


@pytest.mark.asyncio
async def test_concurrent_wallet_creation_uses_parent_lock(pg_wallets):
    sessions, wallets, riders = pg_wallets
    from sqlalchemy import delete

    async with sessions() as session:
        await session.execute(delete(RiderWallet).where(RiderWallet.id == wallets[0]))
        await session.commit()

    async def create():
        async with sessions() as session:
            return await WalletService(session).get_or_create_wallet(riders[0])

    first, second = await asyncio.gather(create(), create())
    assert first.id == second.id
    async with sessions() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(RiderWallet)
                .where(RiderWallet.rider_id == riders[0])
            )
            == 1
        )


@pytest.mark.asyncio
async def test_concurrent_payout_retries_reserve_only_once(pg_wallets):
    sessions, wallets, riders = pg_wallets

    async def reserve():
        async with sessions() as session:
            return await WalletService(session).create_payout_request(
                riders[0], 800, "1234", "Bank", "Owner", "same-request"
            )

    first, second = await asyncio.gather(reserve(), reserve())
    assert first.id == second.id
    async with sessions() as session:
        assert (
            await session.scalar(
                select(RiderWallet.balance_cents).where(RiderWallet.id == wallets[0])
            )
            == 200
        )
