"""Atomic attendance transitions used by the registered operator API.

The caller owns commit/rollback. Lock order is Rider then Shift so requests for
separate shifts of one rider serialize without locking joined/geometry rows.
"""

from datetime import datetime, time, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rider import Rider
from app.models.shift import CheckInOut, Shift, ShiftStatus


def utc_naive(value: datetime) -> datetime:
    """Interpret legacy naive input as UTC; normalize explicit offsets to UTC."""
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def schedule_columns(
    start: datetime, end: datetime | None
) -> tuple[datetime, time, time]:
    """Represent a positive schedule of at most 24h in the existing columns."""
    start = utc_naive(start)
    if end is None:
        end = start.replace(hour=23, minute=59, second=0, microsecond=0)
        if end <= start:
            end += timedelta(days=1)
    else:
        end = utc_naive(end)
    duration = end - start
    if duration <= timedelta(0) or duration > timedelta(days=1):
        raise HTTPException(
            status_code=422,
            detail="El turno debe durar más de cero y como máximo 24 horas",
        )
    return start, start.time(), end.time()


async def transition_shift(
    db: AsyncSession, shift_id: UUID, target: ShiftStatus
) -> None:
    """Apply a transition once, including its attendance event, without commit."""
    rider_id = await db.scalar(select(Shift.rider_id).where(Shift.id == shift_id))
    if rider_id is None:
        raise HTTPException(status_code=404, detail="Turno no encontrado")
    parent = await db.scalar(
        select(Rider.id).where(Rider.id == rider_id).with_for_update()
    )
    if parent is None:
        raise HTTPException(status_code=404, detail="Repartidor no encontrado")
    row = (
        await db.execute(
            select(Shift.status, Shift.check_in_at, Shift.check_out_at)
            .where(Shift.id == shift_id, Shift.rider_id == rider_id)
            .with_for_update()
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Turno no encontrado")
    current, checked_in, checked_out = row

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
                Shift.rider_id == rider_id,
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
            if checked_in is None or checked_out is not None:
                raise HTTPException(
                    status_code=409, detail="Las marcas del turno requieren revisión"
                )
            return
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        await db.execute(
            update(Shift)
            .where(Shift.id == shift_id)
            .values(status=target, check_in_at=now, check_out_at=None, updated_at=now)
        )
        db.add(
            CheckInOut(
                rider_id=rider_id, shift_id=shift_id, check_type="IN", timestamp=now
            )
        )
    elif target == ShiftStatus.COMPLETADO:
        if current == target:
            if checked_in is None or checked_out is None or checked_out < checked_in:
                raise HTTPException(
                    status_code=409, detail="Las marcas del turno requieren revisión"
                )
            return
        if current != ShiftStatus.EN_CURSO:
            raise HTTPException(status_code=400, detail="El turno no está activo")
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if checked_in is None or checked_in > now:
            raise HTTPException(
                status_code=409,
                detail="El inicio real del turno requiere revisión antes de finalizar",
            )
        await db.execute(
            update(Shift)
            .where(Shift.id == shift_id)
            .values(status=target, check_out_at=now, updated_at=now)
        )
        db.add(
            CheckInOut(
                rider_id=rider_id, shift_id=shift_id, check_type="OUT", timestamp=now
            )
        )
    elif target == ShiftStatus.CANCELADO:
        if current == target:
            return
        if current == ShiftStatus.EN_CURSO:
            raise HTTPException(
                status_code=409, detail="Finaliza el turno activo antes de cancelarlo"
            )
        if current not in (ShiftStatus.PROGRAMADO, ShiftStatus.INCOMPLETO):
            raise HTTPException(status_code=400, detail="El turno no se puede cancelar")
        await db.execute(
            update(Shift)
            .where(Shift.id == shift_id)
            .values(status=target, cancellation_reason="Cancelado desde panel operador")
        )
    else:
        raise HTTPException(status_code=400, detail="Transición de turno inválida")
    # Surface attendance insert errors while the caller still owns both changes.
    await db.flush()
