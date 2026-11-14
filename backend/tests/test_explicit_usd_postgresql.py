"""Real migration and accounting boundaries: unknown history never becomes USD."""

from decimal import Decimal
import importlib.util
from pathlib import Path
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text, func

from tests.test_delivery_financial_postgresql import payment_db  # noqa: F401
from app.core.security import create_access_token
from app.models.financial import Financial, TransactionType, PaymentStatus
from app.models.payout import Payout, PayoutStatus, PayoutStatusHistory
from app.models.audit_log import AuditLog
from app.models.rider import Rider
from app.models.order import Order, OrderStatus
from app.services.financial_service import FinancialService
from app.services.cache_reconciliation import CacheReconciliationService

spec = importlib.util.spec_from_file_location(
    "usd91", Path(__file__).parents[1] / "alembic/versions/20261114_explicit_usd.py"
)
revision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(revision)


async def migration(engine, direction):
    async with engine.begin() as connection:

        def apply(conn):
            with Operations.context(MigrationContext.configure(conn)):
                getattr(revision, direction)()

        await connection.run_sync(apply)


@pytest.fixture
async def usd_db(payment_db, monkeypatch):
    client, sessions, ids = payment_db
    engine = sessions.kw["bind"]
    async with engine.begin() as connection:
        for model in (Payout, PayoutStatusHistory, AuditLog):
            await connection.run_sync(
                lambda conn, m=model: m.__table__.create(conn, checkfirst=True)
            )
    async with sessions() as db:
        legacy = Payout(
            rider_id=ids["rider"],
            amount=40,
            status=PayoutStatus.PENDIENTE,
            balance_before=100,
            balance_after=60,
            requested_by_user_id=ids["owner"],
        )
        db.add(legacy)
        await db.flush()
        ids["legacy_payout"] = legacy.id
        db.add(PayoutStatusHistory(payout_id=legacy.id, new_status="PENDIENTE"))
        await db.commit()
    # Reconstruct the pre-migration physical schema, without modifying amounts.
    async with engine.begin() as connection:
        for table, column in revision.UNITS:
            await connection.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))
    await migration(engine, "upgrade")
    monkeypatch.setattr("app.api.v1.payouts._notify_requested", AsyncMock())
    monkeypatch.setattr("app.services.notification_hooks.notify_event", AsyncMock())
    yield client, sessions, ids, engine


def call(fixture, method, path, *, staff=False, body=None):
    client, _, ids, _ = fixture
    return client.request(
        method,
        "/api/v1/" + path,
        headers={
            "Authorization": "Bearer "
            + create_access_token(ids["staff" if staff else "owner"])
        },
        json=body,
    )


async def credit(fixture, amount="25.00", key=None):
    async with fixture[1]() as db:
        return await FinancialService(db).create_ledger_entry(
            rider_id=fixture[2]["rider"],
            amount=amount,
            transaction_type=TransactionType.PAGO_ENTREGA,
            idempotency_key=key or str(uuid4()),
        )


@pytest.mark.parametrize("table,column", revision.UNITS)
async def test_migration_does_not_backfill_units_or_add_server_defaults(
    usd_db, table, column
):
    async with usd_db[3].connect() as db:
        assert (
            await db.scalar(
                text(f"SELECT count(*) FROM {table} WHERE {column} IS NOT NULL")
            )
            == 0
        )
        assert (
            await db.scalar(
                text(
                    "SELECT count(*) FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=:t AND column_name=:c AND column_default IS NOT NULL"
                ),
                {"t": table, "c": column},
            )
            == 0
        )
    async with usd_db[1]() as db:
        old = (await db.scalars(select(Financial))).one()
        assert (old.amount, old.balance_before, old.balance_after) == (
            Decimal("100.00"),
            Decimal("0.00"),
            Decimal("100.00"),
        )
        assert (await db.get(Rider, usd_db[2]["rider"])).wallet_balance == Decimal(
            "3.00"
        )


async def test_new_usd_chain_starts_at_zero_without_spending_or_relabelling_history(
    usd_db,
):
    entry = await credit(usd_db)
    assert (entry.currency_code, entry.balance_before, entry.balance_after) == (
        "USD",
        Decimal("0.00"),
        Decimal("25.00"),
    )
    async with usd_db[1]() as db:
        assert await FinancialService(db).get_current_balance(
            usd_db[2]["rider"]
        ) == Decimal("25.00")
        old = (
            await db.scalars(select(Financial).where(Financial.currency_code.is_(None)))
        ).one()
        assert old.balance_after == Decimal("100.00")
    balance = call(usd_db, "GET", "payouts/balance").json()
    assert (balance["available"], balance["reserved"], balance["currency"]) == (
        25,
        0,
        "USD",
    )
    assert (
        balance["unverified_financial_count"],
        balance["unverified_payout_count"],
    ) == (1, 1)


async def test_zero_usd_balance_cannot_withdraw_unverified_history(usd_db):
    response = call(
        usd_db,
        "POST",
        "payouts/request",
        body={"amount": "10.00", "idempotency_key": "no-usd"},
    )
    assert response.status_code == 400
    assert call(usd_db, "GET", "payouts/balance").json()["available"] == 0
    async with usd_db[1]() as db:
        assert await db.scalar(select(func.count()).select_from(Payout)) == 1


async def test_usd_reservation_approval_and_replay_do_not_use_unknown_reservations(
    usd_db,
):
    await credit(usd_db)
    body = {"amount": "10.00", "currency": "USD", "idempotency_key": "usd-withdrawal"}
    first = call(usd_db, "POST", "payouts/request", body=body)
    assert first.status_code == 201, first.text
    row = first.json()
    assert row["currency"] == "USD"
    assert call(usd_db, "POST", "payouts/request", body=body).json()["id"] == row["id"]
    assert call(usd_db, "GET", "payouts/balance").json()["available"] == 15
    denied = call(
        usd_db,
        "PATCH",
        "payouts/" + str(usd_db[2]["legacy_payout"]) + "/approve",
        staff=True,
    )
    assert denied.status_code == 409
    approved = call(usd_db, "PATCH", "payouts/" + row["id"] + "/approve", staff=True)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "EN_PROCESO"
    balance = call(usd_db, "GET", "payouts/balance").json()
    assert (balance["available"], balance["ledger_balance"], balance["reserved"]) == (
        15,
        15,
        0,
    )
    async with usd_db[1]() as db:
        history = list(
            (
                await db.scalars(
                    select(PayoutStatusHistory).where(
                        PayoutStatusHistory.payout_id == row["id"]
                    )
                )
            ).all()
        )
        assert len(history) == 2 and all(x.currency_code == "USD" for x in history)


async def test_rejecting_unknown_payout_preserves_its_original_snapshots(usd_db):
    await credit(usd_db)
    response = call(
        usd_db,
        "PATCH",
        "payouts/" + str(usd_db[2]["legacy_payout"]) + "/reject",
        staff=True,
        body={"reason": "Revisión de solicitud histórica"},
    )
    assert response.status_code == 200, response.text
    row = response.json()
    assert (row["currency"], row["balance_before"], row["balance_after"]) == (
        None,
        100,
        60,
    )
    history = call(usd_db, "GET", "payouts/" + row["id"] + "/history").json()
    assert history[-1]["currency"] is None
    assert (
        history[-1]["balance_before"] is None and history[-1]["balance_after"] is None
    )
    assert call(usd_db, "GET", "payouts/balance").json()["available"] == 25


@pytest.mark.parametrize("table,column", revision.UNITS)
async def test_database_prevents_historical_relabelling(usd_db, table, column):
    with pytest.raises(Exception, match="cannot be relabelled"):
        async with usd_db[3].begin() as db:
            await db.execute(text(f"UPDATE {table} SET {column}='USD'"))


async def test_downgrade_cannot_drop_new_unit_evidence(usd_db):
    await credit(usd_db)
    with pytest.raises(RuntimeError, match="preserve declared currency history"):
        await migration(usd_db[3], "downgrade")
    assert call(usd_db, "GET", "payouts/balance").json()["available"] == 25


async def test_empty_unit_downgrade_preserves_legacy_amounts(usd_db):
    await migration(usd_db[3], "downgrade")
    async with usd_db[3].connect() as db:
        assert await db.scalar(text("SELECT balance_after FROM financials")) == Decimal(
            "100.00"
        )


async def test_usd_summary_has_no_order_fallback_and_keeps_unknown_detail(usd_db):
    summary = call(usd_db, "GET", "financial/riders/me").json()
    assert summary["currency"] == "USD" and summary["total_earned"] == 0
    await credit(usd_db)
    assert call(usd_db, "GET", "financial/riders/me").json()["total_earned"] == 25
    history = call(usd_db, "GET", "financial/riders/me/earnings").json()["items"]
    assert len(history) == 2 and {x["currency"] for x in history} == {"USD", None}


async def test_unknown_cached_balance_cannot_be_overwritten_by_usd_reconciliation(
    usd_db,
):
    await credit(usd_db)
    async with usd_db[1]() as db:
        result = await CacheReconciliationService(db).preview(usd_db[2]["rider"])
        assert result.status == "requires_review" and not result.can_apply
        assert "unverified_cache_currency" in result.cache_issues
        with pytest.raises(Exception, match="moneda"):
            await FinancialService(db).reconcile_wallet_with_ledger(
                str(usd_db[2]["rider"]), dry_run=False
            )
    async with usd_db[1]() as db:
        assert (await db.get(Rider, usd_db[2]["rider"])).wallet_balance == Decimal(
            "3.00"
        )


@pytest.mark.parametrize("currency", ["COP", "VES", "BRL", "usd", None, 1])
async def test_withdrawal_rejects_other_or_unknown_units(usd_db, currency):
    response = call(
        usd_db,
        "POST",
        "payouts/request",
        body={"amount": "10.00", "currency": currency},
    )
    assert response.status_code == 422


async def test_global_usd_reports_exclude_unknown_orders_and_earnings(usd_db):
    from datetime import datetime

    async with usd_db[1]() as db:
        old = await db.get(Order, usd_db[2]["order"])
        old.status = OrderStatus.ENTREGADO
        old.payment_status = "PAGADO"
        old.total, old.delivery_fee = 900, 90
        old.delivered_at = datetime.utcnow()
        db.add(
            Order(
                customer_name="USD",
                customer_phone="123",
                pickup_address="A",
                delivery_address="B",
                total=20,
                delivery_fee=2,
                subtotal=18,
                status=OrderStatus.ENTREGADO,
                payment_status="PAGADO",
                delivered_at=datetime.utcnow(),
            )
        )
        await db.commit()
    await credit(usd_db)
    response = call(usd_db, "GET", "financial/summary", staff=True)
    assert response.status_code == 200, response.text
    summary = response.json()
    assert (
        summary["currency"],
        summary["total_revenue"],
        summary["gross_order_value"],
        summary["rider_earnings_accrued"],
    ) == ("USD", 2, 20, 25)
    report = call(usd_db, "GET", "financial/reports/orders", staff=True).json()
    assert report["currency"] == "USD" and report["total_orders"] == 1
    result = call(usd_db, "GET", "financial/reconciliation", staff=True).json()
    assert (
        result["currency"],
        result["delivery_revenue"],
        result["rider_earnings"],
    ) == ("USD", 2, 25)


async def test_old_order_prices_cannot_be_edited_as_usd(usd_db):
    async with usd_db[1]() as db:
        old = await db.get(Order, usd_db[2]["order"])
        old.status = OrderStatus.ASIGNADO
        await db.commit()
    response = call(
        usd_db,
        "PATCH",
        "orders/" + str(usd_db[2]["order"]),
        staff=True,
        body={"subtotal": 10, "delivery_fee": 2, "total": 12},
    )
    assert response.status_code == 409, response.text
    async with usd_db[1]() as db:
        old = await db.get(Order, usd_db[2]["order"])
        assert old.currency_code is None and old.total == 0


async def test_usd_earnings_summary_accounts_for_deductions(usd_db):
    await credit(usd_db)
    async with usd_db[1]() as db:
        await FinancialService(db).create_ledger_entry(
            rider_id=usd_db[2]["rider"],
            amount="5.00",
            transaction_type=TransactionType.PENALIZACION,
        )
    result = call(usd_db, "GET", "financial/riders/me").json()
    assert (
        result["currency"] == "USD"
        and result["total_earned"] == 25
        and result["pending_payout"] == 20
    )
