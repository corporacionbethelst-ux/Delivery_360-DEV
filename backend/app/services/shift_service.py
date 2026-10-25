"""Internal shift workflows using canonical persistence and attendance rules.

No actor authentication occurs here. HTTP callers must authorize the actor and
supply the rider resolved from that identity for self-service operations.
"""

from datetime import datetime, timedelta, timezone
from typing import TypedDict
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.shift_rules import (
    lock_shift,
    planned_datetimes,
    schedule_columns,
    transition_shift,
    utc_naive,
)
from app.crud.shift import shift as shift_crud, finish_shift
from app.models.shift import CheckInOut, Shift, ShiftStatus
from app.schemas.shift import ShiftCreate, ShiftUpdate, CheckInRequest, CheckOutRequest


class ShiftStatistics(TypedDict):
    total_shifts: int
    total_hours: float
    avg_hours: float
    period_days: int
    shifts_requiring_review: int


class ShiftService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_shift(
        self, rider_id: UUID, shift_data: ShiftCreate, *, commit: bool = True
    ) -> Shift:
        if rider_id != shift_data.rider_id:
            raise HTTPException(
                status_code=422, detail="El repartidor no coincide con la solicitud"
            )
        return await shift_crud.create(
            self.db,
            rider_id,
            shift_data.scheduled_start,
            scheduled_end=shift_data.scheduled_end,
            notes=shift_data.notes,
            commit=commit,
        )

    async def get_shift_by_id(self, shift_id: UUID) -> Shift | None:
        return await shift_crud.get(self.db, shift_id)

    async def get_active_shift(self, rider_id: UUID) -> Shift | None:
        return await shift_crud.get_active_shift(self.db, rider_id)

    async def _attendance(
        self,
        rider_id: UUID,
        data: CheckInRequest | CheckOutRequest,
        target: ShiftStatus,
        commit: bool,
    ) -> tuple[Shift, CheckInOut]:
        event = await transition_shift(
            self.db,
            data.shift_id,
            target,
            expected_rider_id=rider_id,
            latitude=data.latitude,
            longitude=data.longitude,
            notes=data.notes,
        )
        shift = await self.get_shift_by_id(data.shift_id)
        if shift is None or event is None:
            raise HTTPException(
                status_code=409, detail="El historial del turno requiere revisión"
            )
        await finish_shift(self.db, shift, commit)
        await self.db.refresh(event)
        return shift, event

    async def check_in(
        self, rider_id: UUID, check_in_data: CheckInRequest, *, commit: bool = True
    ) -> tuple[Shift, CheckInOut]:
        return await self._attendance(
            rider_id, check_in_data, ShiftStatus.EN_CURSO, commit
        )

    async def check_out(
        self, rider_id: UUID, check_out_data: CheckOutRequest, *, commit: bool = True
    ) -> tuple[Shift, CheckInOut]:
        return await self._attendance(
            rider_id, check_out_data, ShiftStatus.COMPLETADO, commit
        )

    async def update_shift(
        self, shift_id: UUID, shift_data: ShiftUpdate, *, commit: bool = True
    ) -> Shift:
        shift = await lock_shift(self.db, shift_id)
        if shift.status not in (
            ShiftStatus.PROGRAMADO,
            ShiftStatus.INCOMPLETO,
            ShiftStatus.EN_CURSO,
        ):
            raise HTTPException(
                status_code=409,
                detail="El turno es de solo lectura o requiere revisión",
            )
        schedule_fields = {
            "scheduled_start",
            "scheduled_end",
        } & shift_data.model_fields_set
        if schedule_fields:
            if shift.status == ShiftStatus.EN_CURSO:
                raise HTTPException(
                    status_code=409, detail="No se puede reprogramar un turno activo"
                )
            start, end = planned_datetimes(shift)
            if shift_data.scheduled_start is not None:
                start = shift_data.scheduled_start
            if shift_data.scheduled_end is not None:
                end = shift_data.scheduled_end
            shift.shift_date, shift.start_time, shift.end_time = schedule_columns(
                start, end
            )
        if "notes" in shift_data.model_fields_set:
            shift.notes = shift_data.notes
        return await finish_shift(self.db, shift, commit)

    async def cancel_shift(
        self, shift_id: UUID, reason: str, *, commit: bool = True
    ) -> Shift:
        await transition_shift(
            self.db, shift_id, ShiftStatus.CANCELADO, cancellation_reason=reason
        )
        shift = await self.get_shift_by_id(shift_id)
        if shift is None:
            raise HTTPException(status_code=404, detail="Turno no encontrado")
        return await finish_shift(self.db, shift, commit)

    async def get_shifts_by_rider(self, rider_id: UUID, limit: int = 50) -> list[Shift]:
        return await shift_crud.get_by_rider(self.db, rider_id, limit=limit)

    async def get_shifts_by_date_range(
        self, start_date: datetime, end_date: datetime, rider_id: UUID | None = None
    ) -> list[Shift]:
        start, end = utc_naive(start_date), utc_naive(end_date)
        if end < start:
            raise HTTPException(status_code=422, detail="Rango de fechas inválido")
        first_day = start.replace(hour=0, minute=0, second=0, microsecond=0)
        last_day = end.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
            days=1
        )
        query = select(Shift).where(
            Shift.shift_date >= first_day, Shift.shift_date < last_day
        )
        if rider_id is not None:
            query = query.where(Shift.rider_id == rider_id)
        rows = (
            await self.db.scalars(
                query.order_by(
                    Shift.shift_date.desc(), Shift.start_time.desc(), Shift.id.desc()
                )
            )
        ).all()
        # Historical shift_date can be midnight; Time still carries the schedule.
        return [row for row in rows if start <= planned_datetimes(row)[0] <= end]

    async def get_shift_statistics(
        self, rider_id: UUID, days: int = 30
    ) -> ShiftStatistics:
        if not 1 <= days <= 366:
            raise HTTPException(
                status_code=422, detail="El periodo debe estar entre 1 y 366 días"
            )
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        rows = await self.get_shifts_by_date_range(
            now - timedelta(days=days), now, rider_id
        )
        completed = [row for row in rows if row.status == ShiftStatus.COMPLETADO]
        durations = [
            (row.check_out_at - row.check_in_at).total_seconds() / 3600
            for row in completed
            if row.check_in_at is not None
            and row.check_out_at is not None
            and row.check_in_at <= row.check_out_at <= now
        ]
        return {
            "total_shifts": len(completed),
            "total_hours": sum(durations),
            "avg_hours": sum(durations) / len(durations) if durations else 0.0,
            "period_days": days,
            "shifts_requiring_review": len(completed) - len(durations),
        }

    async def get_active_shifts_count(self) -> int:
        return (
            await self.db.scalar(
                select(func.count(Shift.id)).where(Shift.status == ShiftStatus.EN_CURSO)
            )
            or 0
        )
