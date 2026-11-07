"""Real UUID/timestamp ordering across independent PostgreSQL transactions."""

from datetime import datetime

import pytest
from sqlalchemy import delete

from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from tests.test_payout_pagination import add_row, uid, ids
from app.api.v1 import payouts as api
from app.models.payout import Payout, PayoutStatus
from app.models.user import User, UserRole


@pytest.fixture
async def pg_pages(pg_wallets):
    sessions, _, riders = pg_wallets
    async with sessions() as session:
        connection = await session.connection()
        await connection.run_sync(
            lambda conn: Payout.__table__.create(conn, checkfirst=True)
        )
        manager = User(
            email="page-manager@example.test",
            hashed_password="unused",
            first_name="Page",
            last_name="Manager",
            role=UserRole.GERENTE,
        )
        session.add(manager)
        await session.commit()
        for number, at in [
            (9, datetime(2026, 11, 3)),
            (8, datetime(2026, 11, 2)),
            (7, datetime(2026, 11, 2)),
            (6, datetime(2026, 11, 1)),
            (5, None),
            (4, None),
        ]:
            await add_row(session, riders[0], number, at)
    return sessions, riders, manager


async def page(sessions, manager, cursor=None, rider_id=None):
    async with sessions() as session:
        return await api.get_payout_page(
            limit=2,
            cursor=cursor,
            rider_id=str(rider_id) if rider_id else None,
            status_filter=PayoutStatus.PENDIENTE,
            db=session,
            current_user=manager,
        )


@pytest.mark.asyncio
async def test_postgresql_continuation_survives_new_rows_and_deleted_boundary(pg_pages):
    sessions, riders, manager = pg_pages
    first = await page(sessions, manager)
    assert ids(first) == [9, 8]
    async with sessions() as session:
        await add_row(session, riders[0], 10, datetime(2026, 11, 4))
        await session.execute(delete(Payout).where(Payout.id == uid(8)))
        await session.commit()
    second = await page(sessions, manager, first["next_cursor"])
    third = await page(sessions, manager, second["next_cursor"])
    assert ids(second) == [7, 6]
    assert ids(third) == [5, 4]
    assert third["next_cursor"] is None
    assert ids(await page(sessions, manager)) == [10, 9]


@pytest.mark.asyncio
async def test_postgresql_null_boundary_and_rider_filter_are_preserved(pg_pages):
    sessions, riders, manager = pg_pages
    async with sessions() as session:
        await add_row(session, riders[1], 11, datetime(2026, 11, 4))
        await add_row(session, riders[0], 3, None)
    first = await page(sessions, manager, rider_id=riders[0])
    second = await page(sessions, manager, first["next_cursor"], riders[0])
    third = await page(sessions, manager, second["next_cursor"], riders[0])
    fourth = await page(sessions, manager, third["next_cursor"], riders[0])
    assert ids(first) + ids(second) + ids(third) + ids(fourth) == [9, 8, 7, 6, 5, 4, 3]
    assert fourth["next_cursor"] is None
