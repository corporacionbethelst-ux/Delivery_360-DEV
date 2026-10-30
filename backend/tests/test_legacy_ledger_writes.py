"""Strict ledger ingestion, evidence guards and caller-owned transactions."""

import asyncio
import ast
from pathlib import Path
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import AppException, DuplicateTransactionError, ValidationError
from app.models.financial import Financial, PaymentStatus, TransactionType, RiderWallet
from app.models.rider import Rider
from app.services.financial_service import FinancialService, ledger_delta
from app.services.legacy_ledger import CREDIT_TYPES, DEBIT_TYPES, LEGACY_LEDGER_TYPES
from tests.test_reconciliation_postgresql import pg_reconciliation  # noqa: F401
from tests.test_wallet_postgresql import pg_wallets  # noqa: F401


def test_production_legacy_rows_have_one_guarded_constructor():
    app_root = Path(__file__).resolve().parents[1] / "app"
    calls = []
    for path in app_root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        names = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module == "app.models.financial"
            for alias in node.names
            if alias.name == "Financial"
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in names
            ):
                calls.append(str(path.relative_to(app_root)))
    assert calls == ["services/financial_service.py"]


@pytest.mark.parametrize(
    "kind", [x for x in TransactionType if x not in LEGACY_LEDGER_TYPES]
)
def test_unmapped_modern_types_have_no_implicit_legacy_direction(kind):
    with pytest.raises(ValidationError):
        ledger_delta(Decimal("10"), kind)


@pytest.mark.parametrize("kind", list(LEGACY_LEDGER_TYPES))
@pytest.mark.parametrize("sign", [-1, 1])
def test_explicit_legacy_directions_preserve_signed_adjustments(kind, sign):
    amount = Decimal("2.75") * sign
    expected = (
        abs(amount)
        if kind in CREDIT_TYPES
        else -abs(amount) if kind in DEBIT_TYPES else amount
    )
    assert ledger_delta(amount, kind) == expected


INVALID_INPUTS = (
    [
        {"transaction_type": kind, "status": status}
        for kind in TransactionType
        if kind not in LEGACY_LEDGER_TYPES
        for status in PaymentStatus
    ]
    + [
        {"amount": value}
        for value in [
            None,
            True,
            False,
            0,
            "-0.00",
            "NaN",
            "Infinity",
            "-Infinity",
            "1.001",
            "10.235",
            "-10.235",
            0.1 + 0.2,
            "100000000",
        ]
    ]
    + [
        {"balance_before": value}
        for value in [True, "NaN", "Infinity", "1.001", "100000000"]
    ]
    + [{"commit": value} for value in [None, "false", 0, 1]]
    + [{"transaction_type": "INGRESO"}, {"status": "PROCESADO"}]
    + [
        {"description": object()},
        {"description": "x" * 501},
        {"description": "bad\x00data"},
        {"description": "bad\ud800data"},
        {"reference_id": "x" * 101},
        {"source_type": "x" * 51},
        {"source_id": "x" * 101},
        {"idempotency_key": "x" * 101},
        {"idempotency_key": " "},
        {"idempotency_key": 123},
    ]
)


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", INVALID_INPUTS)
async def test_invalid_ingestion_fails_before_any_database_or_transaction_io(changes):
    db = AsyncMock(spec=AsyncSession)
    params = dict(
        rider_id=uuid4(),
        amount="10.00",
        transaction_type=TransactionType.INGRESO,
        idempotency_key="strict-key",
        **{},
    )
    params.update(changes)
    with pytest.raises(ValidationError):
        await FinancialService(db).create_ledger_entry(**params)
    db.execute.assert_not_awaited()
    db.scalar.assert_not_awaited()
    db.flush.assert_not_awaited()
    db.commit.assert_not_awaited()
    db.rollback.assert_not_awaited()


async def snapshot(sessions):
    async with sessions() as db:
        entries = (
            await db.execute(
                select(
                    Financial.id,
                    Financial.amount,
                    Financial.balance_before,
                    Financial.balance_after,
                ).order_by(Financial.id)
            )
        ).all()
        caches = (
            await db.execute(
                select(Rider.id, Rider.wallet_balance, Rider.version).order_by(Rider.id)
            )
        ).all()
        modern = (
            await db.execute(
                select(RiderWallet.id, RiderWallet.balance_cents).order_by(
                    RiderWallet.id
                )
            )
        ).all()
        return repr((entries, caches, modern))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "corruption",
    [
        "opening",
        "arithmetic",
        "null_before",
        "null_after",
        "nan_amount",
        "nan_after",
        "zero_amount",
        "modern_type",
        "unknown_status",
        "null_date",
        "discontinuity",
        "tied_dates",
    ],
)
async def test_new_writes_cannot_extend_a_corrupt_processed_chain(
    pg_reconciliation, corruption
):
    sessions, rid = pg_reconciliation
    async with sessions() as db:
        changes = {
            "opening": dict(balance_before=1, balance_after=101),
            "arithmetic": dict(balance_after=101),
            "null_before": dict(balance_before=None),
            "null_after": dict(balance_after=None),
            "nan_amount": dict(amount=Decimal("NaN")),
            "nan_after": dict(balance_after=Decimal("NaN")),
            "zero_amount": dict(amount=0),
            "modern_type": dict(transaction_type=TransactionType.STRIPE_PAYOUT),
            "unknown_status": dict(status=None),
            "null_date": dict(created_at=None),
        }
        if corruption in changes:
            await db.execute(update(Financial).values(**changes[corruption]))
        else:
            stamp = await db.scalar(select(Financial.created_at))
            db.add(
                Financial(
                    rider_id=rid,
                    amount=5,
                    balance_before=99 if corruption == "discontinuity" else 100,
                    balance_after=104 if corruption == "discontinuity" else 105,
                    transaction_type=TransactionType.INGRESO,
                    status=PaymentStatus.PROCESADO,
                    created_at=stamp
                    + (
                        timedelta(seconds=1)
                        if corruption == "discontinuity"
                        else timedelta(0)
                    ),
                )
            )
        await db.commit()
    before = await snapshot(sessions)
    async with sessions() as db:
        with pytest.raises(AppException) as error:
            await FinancialService(db).create_ledger_entry(
                rider_id=rid, amount=10, transaction_type=TransactionType.INGRESO
            )
        assert error.value.status_code == 409
        assert "requiere revisión" in error.value.message
    assert await snapshot(sessions) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [1, 2])
async def test_bounded_history_never_extends_a_partial_proof(
    pg_reconciliation, monkeypatch, limit
):
    import app.services.financial_service as module

    sessions, rid = pg_reconciliation
    async with sessions() as db:
        await FinancialService(db).create_ledger_entry(
            rider_id=rid, amount=10, transaction_type=TransactionType.INGRESO
        )
    monkeypatch.setattr(module, "MAX_LEDGER_ROWS", limit)
    before = await snapshot(sessions)
    async with sessions() as db:
        with pytest.raises(AppException) as error:
            await FinancialService(db).create_ledger_entry(
                rider_id=rid, amount=10, transaction_type=TransactionType.INGRESO
            )
        assert error.value.status_code == 409
    assert await snapshot(sessions) == before


@pytest.mark.asyncio
async def test_empty_book_and_only_pending_rows_start_from_zero_without_using_cache(
    pg_reconciliation,
):
    sessions, rid = pg_reconciliation
    async with sessions() as db:
        other = await db.scalar(select(Rider.id).where(Rider.id != rid))
        db.add(
            Financial(
                rider_id=other,
                amount=999,
                transaction_type=TransactionType.INGRESO,
                status=PaymentStatus.PENDIENTE,
                balance_before=None,
                balance_after=None,
            )
        )
        await db.commit()
        entry = await FinancialService(db).create_ledger_entry(
            rider_id=other, amount=10, transaction_type=TransactionType.INGRESO
        )
        assert entry.balance_before == 0 and entry.balance_after == 10
        assert await db.scalar(
            select(Rider.wallet_balance).where(Rider.id == other)
        ) == Decimal("3.00")
        assert await db.scalar(select(Rider.version).where(Rider.id == other)) == 0


@pytest.mark.asyncio
async def test_exact_replay_honors_explicit_opening_constraint(pg_reconciliation):
    sessions, rid = pg_reconciliation
    params = dict(
        rider_id=rid,
        amount="10.00",
        transaction_type=TransactionType.INGRESO,
        idempotency_key="opening-proof",
    )
    async with sessions() as db:
        first = await FinancialService(db).create_ledger_entry(
            **params, balance_before=Decimal("100")
        )
        replay = await FinancialService(db).create_ledger_entry(
            **params, balance_before=Decimal("100")
        )
        assert first.id == replay.id
        with pytest.raises(DuplicateTransactionError):
            await FinancialService(db).create_ledger_entry(
                **params, balance_before=Decimal("99")
            )
        assert await db.scalar(select(func.count()).select_from(Financial)) == 2


@pytest.mark.asyncio
async def test_replay_returns_existing_receipt_but_new_operation_needs_valid_history(
    pg_reconciliation,
):
    sessions, rid = pg_reconciliation
    params = dict(
        rider_id=rid,
        amount=10,
        transaction_type=TransactionType.INGRESO,
        idempotency_key="saved-receipt",
    )
    async with sessions() as db:
        first = await FinancialService(db).create_ledger_entry(**params)
        await db.execute(
            update(Financial)
            .where(Financial.id != first.id)
            .values(balance_before=None)
        )
        await db.commit()
        assert (await FinancialService(db).create_ledger_entry(**params)).id == first.id
        with pytest.raises(AppException) as error:
            await FinancialService(db).create_ledger_entry(
                **{**params, "idempotency_key": "next"}
            )
        assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_history_failure_preserves_caller_owned_work_until_its_rollback(
    pg_reconciliation,
):
    sessions, rid = pg_reconciliation
    async with sessions() as db:
        await db.execute(update(Financial).values(balance_before=None))
        await db.commit()
        await db.execute(update(Rider).where(Rider.id == rid).values(wallet_balance=7))
        with pytest.raises(AppException):
            await FinancialService(db).create_ledger_entry(
                rider_id=rid,
                amount=10,
                transaction_type=TransactionType.INGRESO,
                commit=False,
            )
        assert await db.scalar(select(Rider.wallet_balance).where(Rider.id == rid)) == 7
        await db.rollback()
        assert await db.scalar(select(Rider.wallet_balance).where(Rider.id == rid)) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["update", "insert"])
async def test_evidence_rows_and_fk_insertions_are_locked_until_writer_commit(
    pg_reconciliation, monkeypatch, operation
):
    sessions, rid = pg_reconciliation
    locked, release = asyncio.Event(), asyncio.Event()

    async def append():
        async with sessions() as db:
            original = db.flush

            async def paused(*args, **kwargs):
                locked.set()
                await release.wait()
                return await original(*args, **kwargs)

            monkeypatch.setattr(db, "flush", paused)
            return await FinancialService(db).create_ledger_entry(
                rider_id=rid, amount=10, transaction_type=TransactionType.INGRESO
            )

    async def direct_write():
        async with sessions() as db:
            if operation == "update":
                await db.execute(
                    update(Financial)
                    .where(Financial.rider_id == rid)
                    .values(description="admin update")
                )
            else:
                db.add(
                    Financial(
                        rider_id=rid,
                        amount=1,
                        transaction_type=TransactionType.INGRESO,
                        status=PaymentStatus.PENDIENTE,
                    )
                )
            await db.commit()

    appending = asyncio.create_task(append())
    await asyncio.wait_for(locked.wait(), 5)
    writing = asyncio.create_task(direct_write())
    try:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(writing), 0.15)
    finally:
        release.set()
    assert (await asyncio.wait_for(appending, 5)).balance_after == 110
    await asyncio.wait_for(writing, 5)
