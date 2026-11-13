"""Historical aggregation and Numeric rounding on PostgreSQL, not SQLite mocks."""

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from app.models.delivery import DeliveryStatus, LockedBonusType
from app.services.bonus_simulation import historical_bonus_scenario
from tests.test_platform_settings_postgresql import settings_pg  # noqa: F401


@pytest.fixture
async def history_pg(settings_pg):
    sessions, _ = settings_pg
    table = sa.Table(
        "deliveries",
        sa.MetaData(),
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("status", sa.Enum(DeliveryStatus, name="deliverystatus")),
        sa.Column("completed_at", sa.DateTime),
        sa.Column("bonus_snapshot_date", sa.DateTime),
        sa.Column(
            "locked_bonus_type", sa.Enum(LockedBonusType, name="lockedbonustype")
        ),
        sa.Column("locked_bonus_amount", sa.Numeric(10, 2)),
    )
    async with sessions() as db:
        conn = await db.connection()
        await conn.run_sync(table.create)
        await db.commit()
    yield sessions, table


async def test_native_decimal_sum_bounded_window_and_flat_scenario(history_pg):
    sessions, table = history_pg
    now = datetime(2026, 11, 13, 2)
    async with sessions() as db:
        await db.execute(
            table.insert(),
            [
                {
                    "id": uuid4(),
                    "status": DeliveryStatus.COMPLETADA,
                    "completed_at": now - timedelta(days=7),
                    "locked_bonus_type": LockedBonusType.SUCCESS,
                    "locked_bonus_amount": Decimal("0.10"),
                },
                {
                    "id": uuid4(),
                    "status": DeliveryStatus.COMPLETADA,
                    "completed_at": now - timedelta(hours=1),
                    "locked_bonus_type": LockedBonusType.SUCCESS,
                    "locked_bonus_amount": Decimal("0.20"),
                },
                {
                    "id": uuid4(),
                    "status": DeliveryStatus.FALLIDA,
                    "completed_at": now - timedelta(hours=1),
                    "locked_bonus_type": LockedBonusType.FAILED_ATTEMPT,
                    "locked_bonus_amount": Decimal("1.00"),
                },
                {
                    "id": uuid4(),
                    "status": DeliveryStatus.COMPLETADA,
                    "completed_at": now,
                    "locked_bonus_type": LockedBonusType.SUCCESS,
                    "locked_bonus_amount": Decimal("99.99"),
                },
            ],
        )
        await db.commit()
        row = await historical_bonus_scenario(db, Decimal("2.675"), 7, now)
        assert row["recorded_completed_bonus"] == 0.3 and row["historical_cost"] == 1.3
        assert row["scenario_cost"] == 6.36 and row["difference"] == 5.06
        assert row["completed_deliveries"] == 2 and row["failed_bonus_deliveries"] == 1


async def test_native_nan_is_rejected_instead_of_serialized(history_pg):
    sessions, table = history_pg
    now = datetime(2026, 11, 13, 2)
    async with sessions() as db:
        await db.execute(
            table.insert().values(
                id=uuid4(),
                status=DeliveryStatus.COMPLETADA,
                completed_at=now - timedelta(hours=1),
                locked_bonus_type=LockedBonusType.SUCCESS,
                locked_bonus_amount=Decimal("NaN"),
            )
        )
        await db.commit()
        with pytest.raises(ValueError, match="no válidos"):
            await historical_bonus_scenario(db, Decimal("1"), 7, now)


async def test_history_metrics_use_one_read_only_statement(history_pg):
    sessions, _ = history_pg
    async with sessions() as db:
        connection = await db.connection()
        statements = []

        def track(conn, cursor, statement, params, context, executemany):
            statements.append(statement)

        sa.event.listen(connection.sync_connection, "before_cursor_execute", track)
        try:
            await historical_bonus_scenario(
                db, Decimal("0"), 7, datetime(2026, 11, 13, 2)
            )
        finally:
            sa.event.remove(connection.sync_connection, "before_cursor_execute", track)
        assert len(statements) == 1 and statements[0].lstrip().upper().startswith(
            "SELECT"
        )
