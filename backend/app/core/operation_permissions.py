"""Shared access policy for operational orders and deliveries.

Customers have no ownership relation in the current operational API. They must
not inherit staff access merely because they are authenticated.
"""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rider import Rider
from app.models.user import User, UserRole

OPERATIONS_STAFF = frozenset((UserRole.SUPERADMIN, UserRole.GERENTE, UserRole.OPERADOR))


def ensure_operation_role(user: User, *, write: bool = False) -> None:
    allowed = OPERATIONS_STAFF | {UserRole.REPARTIDOR}
    if not write:
        allowed = allowed | {UserRole.AUDITOR}
    if user.role not in allowed:
        raise HTTPException(status_code=403, detail="Acceso operativo denegado")


async def ensure_rider_resource_access(
    db: AsyncSession, user: User, assigned_rider_id, *, write: bool = False
) -> None:
    """Allow staff, read-only auditors, or the assigned rider; deny all others."""
    ensure_operation_role(user, write=write)
    if user.role != UserRole.REPARTIDOR:
        return
    result = await db.execute(select(Rider).where(Rider.user_id == user.id))
    rider = result.scalar_one_or_none()
    if (
        rider is None
        or assigned_rider_id is None
        or str(rider.id) != str(assigned_rider_id)
    ):
        raise HTTPException(
            status_code=403, detail="No tienes permiso para acceder a este recurso"
        )
