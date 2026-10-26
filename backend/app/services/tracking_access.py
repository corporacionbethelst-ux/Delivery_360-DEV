"""Tracking subscriptions reuse operational ownership; customers have no link yet."""

from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.operation_permissions import ensure_operation_role
from app.models.user import User, UserRole
from app.models.rider import Rider
from app.models.order import Order
from app.models.delivery import Delivery

MAX_TRACKING_CHANNELS = 32


def tracking_channel(value: str) -> str:
    if value in ("dashboard", "all-riders"):
        return "dashboard"
    if not isinstance(value, str) or len(value) > 80:
        raise HTTPException(status_code=403, detail="Canal de tracking no permitido")
    kind, separator, identifier = value.partition(":")
    if not separator or kind not in ("rider", "order"):
        raise HTTPException(status_code=403, detail="Canal de tracking no permitido")
    try:
        return f"{kind}:{UUID(identifier)}"
    except ValueError:
        raise HTTPException(
            status_code=403, detail="Canal de tracking no permitido"
        ) from None


async def authorize_rider_tracking(
    db: AsyncSession, user: User, rider_id: UUID
) -> None:
    ensure_operation_role(user)
    owner = await db.scalar(select(Rider.user_id).where(Rider.id == rider_id))
    if owner is None:
        raise HTTPException(status_code=404, detail="Repartidor no encontrado")
    if user.role == UserRole.REPARTIDOR and owner != user.id:
        raise HTTPException(
            status_code=403, detail="No puedes consultar este repartidor"
        )


async def resolve_tracking_channel(
    db: AsyncSession, user: User, channel: str
) -> tuple[str, str]:
    requested = tracking_channel(channel)
    if requested == "dashboard":
        if user.role not in (UserRole.SUPERADMIN, UserRole.GERENTE):
            raise HTTPException(
                status_code=403, detail="El dashboard requiere gerencia"
            )
        return requested, requested
    ensure_operation_role(user)
    kind, identifier = requested.split(":")
    resource_id = UUID(identifier)
    if kind == "rider":
        await authorize_rider_tracking(db, user, resource_id)
        return requested, requested
    order = (
        await db.execute(
            select(Order.id, Order.assigned_rider_id).where(Order.id == resource_id)
        )
    ).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    assigned = list(
        (
            await db.scalars(
                select(Delivery.rider_id)
                .where(Delivery.order_id == resource_id)
                .limit(2)
            )
        ).all()
    )
    if (
        len(assigned) != 1
        or assigned[0] is None
        or order.assigned_rider_id != assigned[0]
    ):
        raise HTTPException(
            status_code=409, detail="La asignación del pedido requiere revisión"
        )
    await authorize_rider_tracking(db, user, assigned[0])
    return requested, f"rider:{assigned[0]}"
