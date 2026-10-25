"""Shared scheduled-shift and attendance rules; callers own commit/rollback.

Lock order is Rider then Shift, including schedule edits. Internal callers still
must authorize the actor; expected_rider_id binds self-service to its resource.
"""

import math
from datetime import datetime, time, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rider import Rider
from app.models.shift import CheckInOut, Shift, ShiftStatus


def utc_naive(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def schedule_columns(
    start: datetime, end: datetime | None
) -> tuple[datetime, time, time]:
    """Represent a positive schedule of at most 24h in the existing columns."""
    try:
        start = utc_naive(start)
        if end is None:
            end = start.replace(hour=23, minute=59, second=0, microsecond=0)
            if end <= start:
                end += timedelta(days=1)
        else:
            end = utc_naive(end)
        duration = end - start
    except (ValueError, OverflowError) as exc:
        raise HTTPException(
            status_code=422, detail="Fechas de turno fuera de rango"
        ) from exc
    if duration <= timedelta(0) or duration > timedelta(days=1):
        raise HTTPException(
            status_code=422,
            detail="El turno debe durar más de cero y como máximo 24 horas",
        )
    return start, start.time(), end.time()


def planned_datetimes(shift: Shift) -> tuple[datetime, datetime]:
    start = datetime.combine(shift.shift_date.date(), shift.start_time)
    end = datetime.combine(shift.shift_date.date(), shift.end_time)
    if end <= start:
        end += timedelta(days=1)
    return start, end


def validate_notes(notes: str | None) -> None:
    if notes is not None and len(notes) > 500:
        raise HTTPException(
            status_code=422, detail="Las notas admiten hasta 500 caracteres"
        )


async def create_scheduled_shift(
    db: AsyncSession,
    rider_id: UUID,
    start: datetime,
    end: datetime | None = None,
    notes: str | None = None,
) -> Shift:
    validate_notes(notes)
    shift_date, start_time, end_time = schedule_columns(start, end)
    if await db.scalar(select(Rider.id).where(Rider.id == rider_id)) is None:
        raise HTTPException(status_code=404, detail="Repartidor no encontrado")
    shift = Shift(
        rider_id=rider_id,
        shift_date=shift_date,
        start_time=start_time,
        end_time=end_time,
        notes=notes,
        status=ShiftStatus.PROGRAMADO,
    )
    db.add(shift)
    await db.flush()
    return shift


async def lock_shift(
    db: AsyncSession, shift_id: UUID, expected_rider_id: UUID | None = None
) -> Shift:
    rider_id = await db.scalar(select(Shift.rider_id).where(Shift.id == shift_id))
    if rider_id is None:
        raise HTTPException(status_code=404, detail="Turno no encontrado")
    if expected_rider_id is not None and rider_id != expected_rider_id:
        raise HTTPException(
            status_code=403, detail="El turno no pertenece al repartidor"
        )
    if (
        await db.scalar(select(Rider.id).where(Rider.id == rider_id).with_for_update())
        is None
    ):
        raise HTTPException(status_code=404, detail="Repartidor no encontrado")
    shift = await db.scalar(
        select(Shift)
        .where(Shift.id == shift_id, Shift.rider_id == rider_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if shift is None:
        raise HTTPException(status_code=404, detail="Turno no encontrado")
    return shift


async def _existing_attendance(
    db: AsyncSession, shift: Shift, check_type: str, timestamp: datetime
) -> CheckInOut:
    events = list(
        (
            await db.scalars(
                select(CheckInOut)
                .where(
                    CheckInOut.shift_id == shift.id,
                    CheckInOut.rider_id == shift.rider_id,
                    CheckInOut.check_type == check_type,
                    CheckInOut.timestamp == timestamp,
                )
                .limit(2)
            )
        ).all()
    )
    if len(events) != 1:
        raise HTTPException(
            status_code=409, detail="El historial de asistencia requiere revisión"
        )
    return events[0]


async def transition_shift(
    db: AsyncSession,
    shift_id: UUID,
    target: ShiftStatus,
    *,
    expected_rider_id: UUID | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    notes: str | None = None,
    cancellation_reason: str = "Cancelado desde panel operador",
) -> CheckInOut | None:
    """Apply once, or return the original event without changing its evidence."""
    validate_notes(notes)
    if (latitude is None) != (longitude is None):
        raise HTTPException(
            status_code=422, detail="Latitud y longitud deben enviarse juntas"
        )
    for value, bound in ((latitude, 90), (longitude, 180)):
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or abs(value) > bound
        ):
            raise HTTPException(status_code=422, detail="Coordenadas inválidas")
    if target == ShiftStatus.CANCELADO and (
        not cancellation_reason.strip() or len(cancellation_reason) > 255
    ):
        raise HTTPException(
            status_code=422, detail="El motivo requiere entre 1 y 255 caracteres"
        )
    shift = await lock_shift(db, shift_id, expected_rider_id)
    current, checked_in, checked_out = (
        shift.status,
        shift.check_in_at,
        shift.check_out_at,
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    attendance = None

    if target == ShiftStatus.EN_CURSO:
        if current not in (
            ShiftStatus.PROGRAMADO,
            ShiftStatus.INCOMPLETO,
            ShiftStatus.EN_CURSO,
        ):
            raise HTTPException(status_code=400, detail="El turno no se puede iniciar")
        other_active = await db.scalar(
            select(Shift.id)
            .where(
                Shift.rider_id == shift.rider_id,
                Shift.status == ShiftStatus.EN_CURSO,
                Shift.id != shift_id,
            )
            .limit(1)
        )
        if other_active is not None:
            raise HTTPException(
                status_code=409, detail="El repartidor ya tiene otro turno activo"
            )
        if current == target:
            if checked_in is None or checked_out is not None or checked_in > now:
                raise HTTPException(
                    status_code=409, detail="Las marcas del turno requieren revisión"
                )
            return await _existing_attendance(db, shift, "IN", checked_in)
        await db.execute(
            update(Shift)
            .where(Shift.id == shift_id)
            .values(
                status=target,
                check_in_at=now,
                check_out_at=None,
                check_in_latitude=latitude,
                check_in_longitude=longitude,
                updated_at=now,
            )
        )
        attendance = CheckInOut(
            rider_id=shift.rider_id,
            shift_id=shift_id,
            check_type="IN",
            timestamp=now,
            latitude=latitude,
            longitude=longitude,
            notes=notes,
        )
    elif target == ShiftStatus.COMPLETADO:
        if current == target:
            if (
                checked_in is None
                or checked_out is None
                or checked_out < checked_in
                or checked_out > now
            ):
                raise HTTPException(
                    status_code=409, detail="Las marcas del turno requieren revisión"
                )
            return await _existing_attendance(db, shift, "OUT", checked_out)
        if current != ShiftStatus.EN_CURSO:
            raise HTTPException(status_code=400, detail="El turno no está activo")
        if checked_in is None or checked_in > now or checked_out is not None:
            raise HTTPException(
                status_code=409,
                detail="El inicio real del turno requiere revisión antes de finalizar",
            )
        await db.execute(
            update(Shift)
            .where(Shift.id == shift_id)
            .values(
                status=target,
                check_out_at=now,
                check_out_latitude=latitude,
                check_out_longitude=longitude,
                updated_at=now,
            )
        )
        attendance = CheckInOut(
            rider_id=shift.rider_id,
            shift_id=shift_id,
            check_type="OUT",
            timestamp=now,
            latitude=latitude,
            longitude=longitude,
            notes=notes,
        )
    elif target == ShiftStatus.CANCELADO:
        if current == target:
            return None
        if current == ShiftStatus.EN_CURSO:
            raise HTTPException(
                status_code=409, detail="Finaliza el turno activo antes de cancelarlo"
            )
        if current not in (ShiftStatus.PROGRAMADO, ShiftStatus.INCOMPLETO):
            raise HTTPException(status_code=400, detail="El turno no se puede cancelar")
        await db.execute(
            update(Shift)
            .where(Shift.id == shift_id)
            .values(status=target, cancellation_reason=cancellation_reason)
        )
    else:
        raise HTTPException(status_code=400, detail="Transición de turno inválida")
    if attendance is not None:
        db.add(attendance)
    await db.flush()
    return attendance
