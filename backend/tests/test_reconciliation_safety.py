"""Persisted checks: previews and GET requests cannot move money."""

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, MetaData

from app.api.v1 import reconciliation as api
from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.core.exception_handlers import register_exception_handlers
from app.models.financial import Financial, PaymentStatus, TransactionType
from app.models.audit_log import AuditLog
from app.models.rider import Rider, RiderStatus
from app.models.user import UserRole
from app.services.financial_service import FinancialService


@pytest.fixture
async def reconciliation_context(test_engine, db_session, test_user):
    async with test_engine.begin() as connection:
        await connection.run_sync(lambda conn: Financial.__table__.create(conn))
    rider = Rider(
        user_id=test_user.id, status=RiderStatus.ACTIVO, wallet_balance=Decimal("3.00")
    )
    db_session.add(rider)
    await db_session.flush()
    db_session.add(
        Financial(
            rider_id=rider.id,
            amount=Decimal("100.00"),
            transaction_type=TransactionType.INGRESO,
            status=PaymentStatus.PROCESADO,
            balance_before=0,
            balance_after=100,
            created_at=datetime(2026, 10, 24, 10),
        )
    )
    await db_session.commit()
    return db_session, rider.id, test_user


async def persisted_state(session, rider_id):
    cache = (
        await session.execute(
            select(Rider.wallet_balance, Rider.version).where(Rider.id == rider_id)
        )
    ).one()
    count = await session.scalar(select(func.count()).select_from(Financial))
    ledger = await FinancialService(session).get_current_balance(str(rider_id))
    return cache.wallet_balance, cache.version, count, ledger


@pytest.mark.asyncio
async def test_preview_preserves_cache_version_and_ledger(reconciliation_context):
    session, rider_id, _ = reconciliation_context
    before = await persisted_state(session, rider_id)
    assert await FinancialService(session).get_current_balance(rider_id) == Decimal(
        "100.00"
    )
    result = await FinancialService(session).reconcile_wallet_with_ledger(str(rider_id))
    assert result["status"] == "discrepancy"
    assert result["dry_run"] is True
    assert result["adjustment_amount"] == 97
    assert await persisted_state(session, rider_id) == before


@pytest.mark.asyncio
async def test_apply_syncs_cache_without_fabricating_ledger_and_retry_is_noop(
    reconciliation_context,
):
    session, rider_id, _ = reconciliation_context
    service = FinancialService(session)
    result = await service.reconcile_wallet_with_ledger(str(rider_id), dry_run=False)
    assert result["status"] == "reconciled"
    assert await persisted_state(session, rider_id) == (
        Decimal("100.00"),
        1,
        1,
        Decimal("100.00"),
    )
    assert (await service.reconcile_wallet_with_ledger(str(rider_id), dry_run=False))[
        "status"
    ] == "ok"
    assert await persisted_state(session, rider_id) == (
        Decimal("100.00"),
        1,
        1,
        Decimal("100.00"),
    )


@pytest.mark.asyncio
async def test_failed_commit_rolls_back_cache_sync(reconciliation_context):
    session, rider_id, _ = reconciliation_context
    before = await persisted_state(session, rider_id)
    with patch.object(session, "commit", side_effect=RuntimeError("commit failed")):
        with pytest.raises(RuntimeError):
            await FinancialService(session).reconcile_wallet_with_ledger(
                str(rider_id), dry_run=False
            )
    assert await persisted_state(session, rider_id) == before


@pytest.mark.asyncio
async def test_missing_rider_and_cent_tolerance(reconciliation_context):
    session, rider_id, _ = reconciliation_context
    assert (await FinancialService(session).reconcile_wallet_with_ledger(str(uuid4())))[
        "status"
    ] == "error"
    from sqlalchemy import update

    await session.execute(
        update(Rider)
        .where(Rider.id == rider_id)
        .values(wallet_balance=Decimal("99.99"))
    )
    await session.commit()
    before = await persisted_state(session, rider_id)
    assert (
        await FinancialService(session).reconcile_wallet_with_ledger(
            str(rider_id), dry_run=False
        )
    )["status"] == "ok"
    assert await persisted_state(session, rider_id) == before


@pytest.mark.asyncio
async def test_daily_liquidation_returns_integer_count_even_when_empty(
    reconciliation_context,
):
    session, rider_id, _ = reconciliation_context
    result = await FinancialService(session).create_daily_liquidation(
        str(rider_id), date(2026, 10, 24)
    )
    assert result["transaction_count"] == 1
    assert type(result["transaction_count"]) is int
    result = await FinancialService(session).create_daily_liquidation(
        str(rider_id), date(2020, 1, 1)
    )
    assert result["transaction_count"] == 0


@pytest.mark.asyncio
async def test_http_previews_roles_explicit_apply_and_historical_date(
    reconciliation_context,
    test_engine,
):
    # SQLite has no PostgreSQL gen_random_uuid() DDL syntax. Clone the test table
    # and retain the ORM's Python UUID default, without changing production metadata.
    from app.models.user import User

    def audit_table(connection):
        metadata = MetaData()
        User.__table__.to_metadata(metadata)
        table = AuditLog.__table__.to_metadata(metadata)
        table.c.id.server_default = None
        table.create(connection, checkfirst=True)

    async with test_engine.begin() as connection:
        await connection.run_sync(audit_table)
    session, rider_id, user = reconciliation_context
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(api.router, prefix="/api/v1")

    async def database():
        yield session

    async def current_user():
        return user

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = current_user
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        user.role = UserRole.OPERADOR
        assert (
            await client.get(f"/api/v1/reconciliation/wallet/{rider_id}")
        ).status_code == 403
        user.role = UserRole.GERENTE
        before = await persisted_state(session, rider_id)
        assert (await client.get(f"/api/v1/reconciliation/wallet/{rider_id}")).json()[
            "status"
        ] == "discrepancy"
        assert await persisted_state(session, rider_id) == before
        assert (
            await client.post(
                f"/api/v1/reconciliation/wallet/{rider_id}/sync?dry_run=false"
            )
        ).status_code == 403
        user.role = UserRole.SUPERADMIN
        await session.commit()
        response = await client.post("/api/v1/reconciliation/fix-all-discrepancies")
        assert response.status_code == 200, response.text
        assert response.json()["dry_run"] is True
        assert response.json()["fixed_count"] == 0
        assert response.json()["discrepancy_count"] == 1
        assert response.json()["total_adjusted_amount"] == "0.00"
        assert await persisted_state(session, rider_id) == before
        response = await client.get(
            "/api/v1/reconciliation/batch/daily?target_date=2020-01-01"
        )
        assert response.status_code == 422
        assert (await client.get("/api/v1/reconciliation/batch/daily")).json()[
            "discrepancy_count"
        ] == 1
        response = await client.post(
            "/api/v1/reconciliation/fix-all-discrepancies?dry_run=false"
        )
        assert response.status_code == 409, response.text
        assert await persisted_state(session, rider_id) == before
        preview = (await client.get(f"/api/v1/reconciliation/wallet/{rider_id}")).json()
        response = await client.post(
            f"/api/v1/reconciliation/wallet/{rider_id}/sync?dry_run=false",
            json={
                "expected_version": preview["version"],
                "expected_fingerprint": preview["fingerprint"],
                "reason": "Revisión explícita de la caché",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "reconciled"
        assert await persisted_state(session, rider_id) == (
            Decimal("100.00"),
            1,
            1,
            Decimal("100.00"),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [PaymentStatus.PENDIENTE, PaymentStatus.RECHAZADO])
async def test_unprocessed_rows_do_not_override_real_balance(
    reconciliation_context, status
):
    session, rider_id, _ = reconciliation_context
    session.add(
        Financial(
            rider_id=rider_id,
            amount=999,
            balance_after=999,
            transaction_type=TransactionType.INGRESO,
            status=status,
            created_at=datetime(2026, 10, 24, 11),
        )
    )
    await session.commit()
    assert await FinancialService(session).get_current_balance(
        str(rider_id)
    ) == Decimal("100.00")


@pytest.mark.asyncio
async def test_legacy_null_snapshots_do_not_double_count_manual_adjustment(
    reconciliation_context,
):
    session, rider_id, _ = reconciliation_context
    session.add(
        Financial(
            rider_id=rider_id,
            amount=5,
            transaction_type=TransactionType.AJUSTE_MANUAL,
            status=PaymentStatus.PROCESADO,
            created_at=datetime(2026, 10, 24, 11),
        )
    )
    await session.flush()
    from sqlalchemy import update

    await session.execute(update(Financial).values(balance_after=None))
    await session.commit()
    assert await FinancialService(session).get_current_balance(
        str(rider_id)
    ) == Decimal("95.00")


@pytest.mark.asyncio
async def test_optimistic_update_rejects_stale_version(reconciliation_context):
    session, rider_id, _ = reconciliation_context
    service = FinancialService(session)
    assert await service.update_wallet_balance_optimistic(
        str(rider_id), Decimal("20.00"), 0
    )
    assert not await service.update_wallet_balance_optimistic(
        str(rider_id), Decimal("999.00"), 0
    )
    await session.commit()
    assert (await persisted_state(session, rider_id))[:2] == (Decimal("20.00"), 1)
    with pytest.raises(ValueError, match="no encontrado"):
        await service.update_wallet_balance_optimistic(
            str(uuid4()), Decimal("20.00"), 0
        )
