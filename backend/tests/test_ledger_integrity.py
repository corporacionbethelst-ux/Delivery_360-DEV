"""Persisted ledger identities and outer transaction ownership."""

from decimal import Decimal
from unittest.mock import patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import event, func, select

from tests.test_reconciliation_safety import reconciliation_context  # noqa: F401
from app.core.exception_handlers import register_exception_handlers
from app.core.exceptions import DuplicateTransactionError, ValidationError
from app.models.financial import Financial, PaymentStatus, TransactionType
from app.services.financial_service import FinancialService


@pytest.fixture
async def ledger_context(reconciliation_context, test_engine):
    # SQLite legacy mode does not BEGIN for SELECT. Ensure SAVEPOINT is truly
    # inside an outer transaction, as it always is in production PostgreSQL.
    event.listen(
        test_engine.sync_engine, "begin", lambda conn: conn.exec_driver_sql("BEGIN")
    )
    return reconciliation_context


async def create(session, rider_id, **overrides):
    params = dict(
        rider_id=rider_id,
        amount=Decimal("10.00"),
        transaction_type=TransactionType.INGRESO,
        idempotency_key="ledger-key",
        description="earning",
    )
    params.update(overrides)
    return await FinancialService(session).create_ledger_entry(**params)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"amount": Decimal("11")},
        {"transaction_type": TransactionType.RETIRO},
        {"description": "different"},
        {"reference_id": "different"},
        {"source_type": "ORDER"},
        {"source_id": "different"},
        {"status": PaymentStatus.PENDIENTE},
    ],
)
async def test_reused_key_must_match_all_operation_fields(ledger_context, changes):
    session, rider_id, _ = ledger_context
    await create(session, rider_id)
    with pytest.raises(DuplicateTransactionError):
        await create(session, rider_id, **changes)
    assert await session.scalar(select(func.count()).select_from(Financial)) == 2
    assert await FinancialService(session).get_current_balance(rider_id) == Decimal(
        "110.00"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "amount",
    [
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        Decimal("0"),
        Decimal("0.001"),
        Decimal("100000000"),
        True,
    ],
)
async def test_invalid_amounts_never_insert(ledger_context, amount):
    session, rider_id, _ = ledger_context
    with pytest.raises(ValidationError):
        await create(session, rider_id, amount=amount)
    assert await session.scalar(select(func.count()).select_from(Financial)) == 1


@pytest.mark.asyncio
async def test_commit_false_can_be_rolled_back_by_the_caller(ledger_context):
    session, rider_id, _ = ledger_context
    await create(session, rider_id, commit=False)
    assert await FinancialService(session).get_current_balance(rider_id) == Decimal(
        "110"
    )
    await session.rollback()
    assert await FinancialService(session).get_current_balance(rider_id) == Decimal(
        "100"
    )
    assert await session.scalar(select(func.count()).select_from(Financial)) == 1


@pytest.mark.asyncio
async def test_commit_failure_does_not_leave_an_entry(ledger_context):
    session, rider_id, _ = ledger_context
    with patch.object(session, "commit", side_effect=RuntimeError("commit failed")):
        with pytest.raises(RuntimeError):
            await create(session, rider_id)
    assert await session.scalar(select(func.count()).select_from(Financial)) == 1


@pytest.mark.asyncio
async def test_stale_explicit_balance_is_rejected(ledger_context):
    session, rider_id, _ = ledger_context
    with pytest.raises(ValidationError, match="saldo inicial"):
        await create(session, rider_id, balance_before=Decimal("5.00"))
    assert await FinancialService(session).get_current_balance(rider_id) == Decimal(
        "100"
    )


@pytest.mark.asyncio
async def test_domain_conflicts_keep_http_status_and_do_not_expose_internal_data():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/conflict")
    async def conflict():
        raise DuplicateTransactionError("La clave identifica otro movimiento")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/conflict")
    assert response.status_code == 409
    assert response.json()["detail"] == "La clave identifica otro movimiento"


@pytest.fixture
async def payout_context(ledger_context, test_engine):
    from app.models.payout import Payout, PayoutStatusHistory, PayoutStatus
    from app.models.user import UserRole

    session, rider_id, user = ledger_context
    async with test_engine.begin() as connection:
        for model in (Payout, PayoutStatusHistory):
            await connection.run_sync(
                lambda conn, model=model: model.__table__.create(conn, checkfirst=True)
            )
    user.role = UserRole.GERENTE
    payout = Payout(rider_id=rider_id, amount=30, status=PayoutStatus.PENDIENTE)
    session.add(payout)
    session.add(Payout(rider_id=rider_id, amount=20, status=PayoutStatus.PENDIENTE))
    await session.commit()
    return session, rider_id, user, payout.id


@pytest.mark.asyncio
async def test_payout_approval_commits_once_and_keeps_distinct_snapshot_meanings(
    payout_context,
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.api.v1 import payouts as api
    from app.models.payout import PayoutStatusHistory

    session, rider_id, user, payout_id = payout_context
    original_commit = session.commit
    with (
        patch.object(session, "commit", wraps=original_commit) as commit,
        patch(
            "app.services.notification_service.NotificationService.create_notification",
            new_callable=AsyncMock,
        ) as legacy,
        patch.object(
            api, "get_redis_audit_logger", return_value=SimpleNamespace(connected=False)
        ),
        patch("app.services.notification_hooks.notify_event", new_callable=AsyncMock),
    ):
        response = await api.approve_payout(
            str(payout_id), db=session, current_user=user
        )
        assert commit.await_count == 1
        legacy.assert_not_awaited()
    assert response["status"] == "EN_PROCESO"
    assert response["balance_before"] == 80.0  # Excludes the other pending reserve.
    assert response["balance_after"] == 50.0
    entry = await session.scalar(
        select(Financial).where(Financial.reference_id == str(payout_id))
    )
    assert entry.balance_before == Decimal("100")
    assert entry.balance_after == Decimal("70")
    assert (
        await session.scalar(select(func.count()).select_from(PayoutStatusHistory)) == 1
    )
    assert await FinancialService(session).get_current_balance(rider_id) == Decimal(
        "70"
    )


@pytest.mark.asyncio
async def test_payout_failed_final_commit_can_rollback_state_history_and_ledger(
    payout_context,
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.api.v1 import payouts as api
    from app.models.payout import Payout, PayoutStatus, PayoutStatusHistory

    session, rider_id, user, payout_id = payout_context
    with (
        patch.object(session, "commit", side_effect=RuntimeError("commit failed")),
        patch(
            "app.services.notification_service.NotificationService.create_notification",
            new_callable=AsyncMock,
        ) as legacy,
        patch.object(
            api, "get_redis_audit_logger", return_value=SimpleNamespace(connected=False)
        ),
        patch(
            "app.services.notification_hooks.notify_event", new_callable=AsyncMock
        ) as notify,
    ):
        with pytest.raises(RuntimeError):
            await api.approve_payout(str(payout_id), db=session, current_user=user)
        legacy.assert_not_awaited()
        notify.assert_not_awaited()
    await session.rollback()  # Same ownership as get_db on failed HTTP requests.
    assert (
        await session.scalar(select(Payout.status).where(Payout.id == payout_id))
        == PayoutStatus.PENDIENTE
    )
    assert (
        await session.scalar(select(func.count()).select_from(PayoutStatusHistory)) == 0
    )
    assert await session.scalar(select(func.count()).select_from(Financial)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "before", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")]
)
async def test_nonfinite_explicit_snapshot_is_a_validation_error(
    ledger_context, before
):
    session, rider_id, _ = ledger_context
    with pytest.raises(ValidationError, match="Saldo inicial"):
        await create(session, rider_id, balance_before=before)
    assert await session.scalar(select(func.count()).select_from(Financial)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_commit", [False, True])
async def test_payout_rejection_does_not_commit_inside_legacy_notifications(
    payout_context, fail_commit
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.api.v1 import payouts as api
    from app.models.payout import Payout, PayoutStatus, PayoutStatusHistory

    session, _, user, payout_id = payout_context
    original_commit = session.commit
    with (
        patch.object(
            session,
            "commit",
            wraps=original_commit,
            side_effect=RuntimeError("commit failed") if fail_commit else None,
        ) as commit,
        patch(
            "app.services.notification_service.NotificationService.create_notification",
            new_callable=AsyncMock,
        ) as legacy,
        patch.object(
            api, "get_redis_audit_logger", return_value=SimpleNamespace(connected=False)
        ),
        patch("app.services.notification_hooks.notify_event", new_callable=AsyncMock),
    ):
        if fail_commit:
            with pytest.raises(RuntimeError):
                await api.reject_payout(
                    str(payout_id),
                    api.PayoutRejectBody(reason="Rejected"),
                    db=session,
                    current_user=user,
                )
        else:
            response = await api.reject_payout(
                str(payout_id),
                api.PayoutRejectBody(reason="Rejected"),
                db=session,
                current_user=user,
            )
            assert response["status"] == "RECHAZADO"
        assert commit.await_count == 1
        legacy.assert_not_awaited()
    if fail_commit:
        await session.rollback()
    assert await session.scalar(
        select(Payout.status).where(Payout.id == payout_id)
    ) == (PayoutStatus.PENDIENTE if fail_commit else PayoutStatus.RECHAZADO)
    assert await session.scalar(
        select(func.count()).select_from(PayoutStatusHistory)
    ) == (0 if fail_commit else 1)
    assert await session.scalar(select(func.count()).select_from(Financial)) == 1
