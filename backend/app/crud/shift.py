"""Shift persistence adapters. Authorization remains the caller's responsibility."""

from datetime import datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.shift_rules import create_scheduled_shift, transition_shift, utc_naive
from app.models.shift import Shift, ShiftStatus


async def finish_shift(db: AsyncSession, shift: Shift, commit: bool) -> Shift:
    await db.flush()
    if commit:
        await db.commit()
    await db.refresh(shift)
    return shift


class CRUDShift:
    async def get(self, db: AsyncSession, shift_id: UUID) -> Shift | None:
        return await db.scalar(
            select(Shift)
            .where(Shift.id == shift_id)
            .execution_options(populate_existing=True)
        )

    async def get_by_rider(
        self, db: AsyncSession, rider_id: UUID, skip: int = 0, limit: int = 100
    ) -> list[Shift]:
        return await self.get_multi(db, skip=skip, limit=limit, rider_id=rider_id)

    async def get_active_shift(self, db: AsyncSession, rider_id: UUID) -> Shift | None:
        matches = list(
            (
                await db.scalars(
                    select(Shift)
                    .where(
                        Shift.rider_id == rider_id, Shift.status == ShiftStatus.EN_CURSO
                    )
                    .limit(2)
                )
            ).all()
        )
        if len(matches) > 1:
            raise HTTPException(
                status_code=409,
                detail="Hay turnos activos duplicados que requieren revisión",
            )
        return matches[0] if matches else None

    async def create(
        self,
        db: AsyncSession,
        rider_id: UUID,
        scheduled_start: datetime,
        *,
        scheduled_end: datetime | None = None,
        notes: str | None = None,
        commit: bool = True,
    ) -> Shift:
        shift = await create_scheduled_shift(
            db, rider_id, scheduled_start, scheduled_end, notes
        )
        return await finish_shift(db, shift, commit)

    async def start_shift(
        self,
        db: AsyncSession,
        shift: Shift,
        check_in_location: tuple[float | None, float | None],
        *,
        commit: bool = True,
    ) -> Shift:
        await transition_shift(
            db,
            shift.id,
            ShiftStatus.EN_CURSO,
            expected_rider_id=shift.rider_id,
            latitude=check_in_location[0],
            longitude=check_in_location[1],
        )
        current = await self.get(db, shift.id)
        if current is None:
            raise HTTPException(status_code=404, detail="Turno no encontrado")
        return await finish_shift(db, current, commit)

    async def end_shift(
        self,
        db: AsyncSession,
        shift: Shift,
        check_out_location: tuple[float | None, float | None],
        *,
        commit: bool = True,
    ) -> Shift:
        await transition_shift(
            db,
            shift.id,
            ShiftStatus.COMPLETADO,
            expected_rider_id=shift.rider_id,
            latitude=check_out_location[0],
            longitude=check_out_location[1],
        )
        current = await self.get(db, shift.id)
        if current is None:
            raise HTTPException(status_code=404, detail="Turno no encontrado")
        return await finish_shift(db, current, commit)

    async def get_multi(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        rider_id: UUID | None = None,
        status: ShiftStatus | None = None,
        date: datetime | None = None,
    ) -> list[Shift]:
        if skip < 0 or not 1 <= limit <= 200:
            raise HTTPException(status_code=422, detail="Paginación de turnos inválida")
        query = select(Shift)
        if rider_id is not None:
            query = query.where(Shift.rider_id == rider_id)
        if status is not None:
            query = query.where(Shift.status == status)
        if date is not None:
            day = utc_naive(date).replace(hour=0, minute=0, second=0, microsecond=0)
            query = query.where(
                Shift.shift_date >= day, Shift.shift_date < day + timedelta(days=1)
            )
        query = (
            query.order_by(
                Shift.shift_date.desc(), Shift.start_time.desc(), Shift.id.desc()
            )
            .offset(skip)
            .limit(limit)
        )
        return list((await db.scalars(query)).all())


shift = CRUDShift()
