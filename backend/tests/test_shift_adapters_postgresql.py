"""Mixed-writer concurrency: internal adapters share the operator lock protocol."""

import asyncio
from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from tests.test_shift_postgresql import pg_shifts  # noqa: F401
from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from app.core.shift_rules import transition_shift
from app.crud.shift import shift as crud
from app.models.shift import CheckInOut, Shift, ShiftStatus
from app.schemas.shift import CheckInRequest, CheckOutRequest, ShiftUpdate
from app.services.shift_service import ShiftService


@pytest.mark.asyncio
async def test_service_and_crud_cannot_start_separate_shifts_of_same_rider(pg_shifts):
    sessions, ids = pg_shifts

    async def service_start():
        async with sessions() as db:
            rider = await db.scalar(select(Shift.rider_id).where(Shift.id == ids[0]))
            await ShiftService(db).check_in(rider, CheckInRequest(shift_id=ids[0]))

    async def crud_start():
        async with sessions() as db:
            row = await crud.get(db, ids[1])
            await crud.start_shift(db, row, (10, -66))

    results = await asyncio.gather(
        service_start(), crud_start(), return_exceptions=True
    )
    assert sum(result is None for result in results) == 1
    failures = [result for result in results if isinstance(result, HTTPException)]
    assert len(failures) == 1 and failures[0].status_code == 409
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(CheckInOut)) == 1
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Shift)
                .where(Shift.status == ShiftStatus.EN_CURSO)
            )
            == 1
        )


@pytest.mark.asyncio
async def test_concurrent_service_retries_recover_same_event(pg_shifts):
    sessions, ids = pg_shifts

    async def mark(request_type, method):
        async with sessions() as db:
            rider = await db.scalar(select(Shift.rider_id).where(Shift.id == ids[0]))
            _, event = await getattr(ShiftService(db), method)(
                rider, request_type(shift_id=ids[0], latitude=10, longitude=-66)
            )
            return event.id

    starts = await asyncio.gather(*(mark(CheckInRequest, "check_in") for _ in range(2)))
    assert starts[0] == starts[1]
    ends = await asyncio.gather(*(mark(CheckOutRequest, "check_out") for _ in range(2)))
    assert ends[0] == ends[1] and starts[0] != ends[0]
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(CheckInOut)) == 2


@pytest.mark.asyncio
async def test_replanning_and_start_share_lock_and_cannot_change_active_schedule(
    pg_shifts,
):
    sessions, ids = pg_shifts

    async def replan():
        async with sessions() as db:
            return await ShiftService(db).update_shift(
                ids[0],
                ShiftUpdate(
                    scheduled_start=datetime(2026, 10, 25, 10),
                    scheduled_end=datetime(2026, 10, 25, 18),
                ),
            )

    async def start():
        async with sessions() as db:
            await transition_shift(db, ids[0], ShiftStatus.EN_CURSO)
            await db.commit()

    results = await asyncio.gather(replan(), start(), return_exceptions=True)
    assert results[1] is None
    if isinstance(results[0], HTTPException):
        assert results[0].status_code == 409
        expected_date = datetime(2026, 10, 24).date()
        expected_hour = 9
    else:
        assert isinstance(results[0], Shift)
        expected_date = datetime(2026, 10, 25).date()
        expected_hour = 10
    async with sessions() as db:
        row = await crud.get(db, ids[0])
        assert row.status == ShiftStatus.EN_CURSO
        assert (
            row.shift_date.date() == expected_date
            and row.start_time.hour == expected_hour
        )
        assert await db.scalar(select(func.count()).select_from(CheckInOut)) == 1


@pytest.mark.asyncio
async def test_service_commit_false_preserves_outer_rollback_on_postgresql(pg_shifts):
    sessions, ids = pg_shifts
    async with sessions() as db:
        rider = await db.scalar(select(Shift.rider_id).where(Shift.id == ids[0]))
        await ShiftService(db).check_in(
            rider, CheckInRequest(shift_id=ids[0]), commit=False
        )
        await db.rollback()
    async with sessions() as db:
        assert (
            await db.scalar(select(Shift.status).where(Shift.id == ids[0]))
            == ShiftStatus.PROGRAMADO
        )
        assert await db.scalar(select(func.count()).select_from(CheckInOut)) == 0
