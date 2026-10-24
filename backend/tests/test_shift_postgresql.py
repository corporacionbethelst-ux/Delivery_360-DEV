"""Real row-lock and atomicity checks in the private test_* PostgreSQL schema."""

import asyncio
from datetime import datetime, time

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from app.core.shift_rules import transition_shift
from app.models.shift import CheckInOut, Shift, ShiftStatus


@pytest.fixture
async def pg_shifts(pg_wallets):
    sessions, _, riders = pg_wallets
    async with sessions() as db:
        connection = await db.connection()
        for model in (Shift, CheckInOut):
            await connection.run_sync(model.__table__.create)
        shifts = [
            Shift(
                rider_id=rider_id,
                shift_date=datetime(2026, 10, 24),
                start_time=time(9),
                end_time=time(17),
            )
            for rider_id in (riders[0], riders[0], riders[1])
        ]
        db.add_all(shifts)
        await db.commit()
        ids = [shift.id for shift in shifts]
    yield sessions, ids


async def apply(sessions, shift_id, target):
    async with sessions() as db:
        async with db.begin():
            await transition_shift(db, shift_id, target)


async def attendance_count(db, check_type):
    return await db.scalar(
        select(func.count())
        .select_from(CheckInOut)
        .where(CheckInOut.check_type == check_type)
    )


@pytest.mark.asyncio
async def test_concurrent_retries_start_once(pg_shifts):
    sessions, ids = pg_shifts
    await asyncio.gather(
        *(apply(sessions, ids[0], ShiftStatus.EN_CURSO) for _ in range(2))
    )
    async with sessions() as db:
        assert await attendance_count(db, "IN") == 1
        assert (
            await db.scalar(select(Shift.status).where(Shift.id == ids[0]))
            == ShiftStatus.EN_CURSO
        )


@pytest.mark.asyncio
async def test_two_shifts_of_same_rider_cannot_start_together(pg_shifts):
    sessions, ids = pg_shifts
    results = await asyncio.gather(
        *(apply(sessions, shift_id, ShiftStatus.EN_CURSO) for shift_id in ids[:2]),
        return_exceptions=True,
    )
    assert sum(result is None for result in results) == 1
    failures = [result for result in results if isinstance(result, HTTPException)]
    assert len(failures) == 1 and failures[0].status_code == 409
    async with sessions() as db:
        assert await attendance_count(db, "IN") == 1
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Shift)
                .where(Shift.status == ShiftStatus.EN_CURSO)
            )
            == 1
        )


@pytest.mark.asyncio
async def test_concurrent_retries_end_once(pg_shifts):
    sessions, ids = pg_shifts
    await apply(sessions, ids[0], ShiftStatus.EN_CURSO)
    await asyncio.gather(
        *(apply(sessions, ids[0], ShiftStatus.COMPLETADO) for _ in range(2))
    )
    async with sessions() as db:
        assert await attendance_count(db, "IN") == 1
        assert await attendance_count(db, "OUT") == 1
        assert (
            await db.scalar(select(Shift.status).where(Shift.id == ids[0]))
            == ShiftStatus.COMPLETADO
        )
        assert await db.scalar(
            select(Shift.end_time).where(Shift.id == ids[0])
        ) == time(17)


@pytest.mark.asyncio
async def test_start_and_cancel_race_cannot_leave_cancelled_active_attendance(
    pg_shifts,
):
    sessions, ids = pg_shifts
    results = await asyncio.gather(
        apply(sessions, ids[0], ShiftStatus.EN_CURSO),
        apply(sessions, ids[0], ShiftStatus.CANCELADO),
        return_exceptions=True,
    )
    assert sum(result is None for result in results) == 1
    assert sum(isinstance(result, HTTPException) for result in results) == 1
    async with sessions() as db:
        status = await db.scalar(select(Shift.status).where(Shift.id == ids[0]))
        assert status in (ShiftStatus.EN_CURSO, ShiftStatus.CANCELADO)
        assert await attendance_count(db, "IN") == (
            1 if status == ShiftStatus.EN_CURSO else 0
        )


@pytest.mark.asyncio
async def test_different_riders_can_each_have_active_shift(pg_shifts):
    sessions, ids = pg_shifts
    await asyncio.gather(
        *(
            apply(sessions, shift_id, ShiftStatus.EN_CURSO)
            for shift_id in (ids[0], ids[2])
        )
    )
    async with sessions() as db:
        assert await attendance_count(db, "IN") == 2


@pytest.mark.asyncio
async def test_caller_rollback_reverts_status_and_attendance(pg_shifts):
    sessions, ids = pg_shifts
    async with sessions() as db:
        await transition_shift(db, ids[0], ShiftStatus.EN_CURSO)
        await db.rollback()
    async with sessions() as db:
        assert (
            await db.scalar(select(Shift.status).where(Shift.id == ids[0]))
            == ShiftStatus.PROGRAMADO
        )
        assert await attendance_count(db, "IN") == 0


@pytest.mark.asyncio
async def test_real_attendance_insert_failure_reverts_status(pg_shifts):
    sessions, ids = pg_shifts
    async with sessions() as db:
        # Fail a real NOT NULL constraint in the final flush, after the status UPDATE.
        db.add(CheckInOut(shift_id=ids[0], check_type="IN"))
        with pytest.raises(IntegrityError):
            await transition_shift(db, ids[0], ShiftStatus.EN_CURSO)
        await db.rollback()
    async with sessions() as db:
        assert (
            await db.scalar(select(Shift.status).where(Shift.id == ids[0]))
            == ShiftStatus.PROGRAMADO
        )
        assert await attendance_count(db, "IN") == 0
