"""Shared live account checks for access, refresh and password login."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rider import Rider, RiderStatus
from app.models.user import User, UserRole


async def ensure_session_allowed(db: AsyncSession, user: User) -> None:
    if not user.is_active or user.role is None:
        raise HTTPException(status_code=401, detail="Cuenta no disponible")
    if user.role == UserRole.REPARTIDOR:
        rider_status = await db.scalar(
            select(Rider.status).where(Rider.user_id == user.id)
        )
        if rider_status not in (RiderStatus.ACTIVO, RiderStatus.OCUPADO):
            raise HTTPException(
                status_code=403,
                detail="Tu cuenta de repartidor no está habilitada. Contacta a soporte.",
            )
