"""Assignment guards; caller locks Order first and owns commit/rollback.

Lock order: Order, Delivery, Route, Rider, Users (UUID order, shared). Automatic
selection skips locked Riders instead of waiting for another Rider lock.
Document writers use the same Rider parent lock. No eligibility denial
commits safety changes or the caller's payload.
"""

from dataclasses import dataclass, replace
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload
from app.core.operation_permissions import OPERATIONS_STAFF
from app.models.audit_log import AuditLog, ActionType
from app.models.delivery import Delivery, DeliveryStatus
from app.models.order import Order, OrderStatus
from app.models.rider import Rider, RiderStatus, utc_now_naive
from app.models.route import Route, RouteStatus
from app.models.user import User, UserRole
from app.services.document_review import document_readiness_error
from app.services.route_geometry import coordinate


@dataclass(frozen=True)
class AssignmentCandidate:
    rider: Rider
    owner: User
    actor: User
    changed: bool = False


async def lock_assignment_delivery(db: AsyncSession, order: Order) -> Delivery | None:
    if order.status not in (OrderStatus.PENDIENTE, OrderStatus.ASIGNADO):
        raise HTTPException(status_code=409, detail="El pedido ya no admite asignación")
    deliveries = list(
        (
            await db.scalars(
                select(Delivery)
                .where(Delivery.order_id == order.id)
                .order_by(Delivery.id)
                .limit(2)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    if len(deliveries) > 1:
        raise HTTPException(
            status_code=409,
            detail="La orden tiene entregas ambiguas; requiere revisión",
        )
    delivery = deliveries[0] if deliveries else None
    if delivery is not None and (
        delivery.status not in (DeliveryStatus.PENDIENTE, DeliveryStatus.INICIADA)
        or any(
            value is not None
            for value in (
                delivery.arrived_pickup_at,
                delivery.left_pickup_at,
                delivery.arrived_delivery_at,
                delivery.completed_at,
                delivery.issue_type,
                delivery.issue_description,
            )
        )
        or delivery.has_issues
        or (
            order.assigned_rider_id is not None
            and delivery.rider_id is not None
            and order.assigned_rider_id != delivery.rider_id
        )
    ):
        raise HTTPException(
            status_code=409,
            detail="La entrega tiene avance o vínculos que requieren revisión",
        )
    if delivery is not None:
        routes = list(
            (
                await db.scalars(
                    select(Route)
                    .where(Route.delivery_id == delivery.id)
                    .order_by(Route.id)
                    .limit(2)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).all()
        )
        if len(routes) > 1 or any(
            route.status != RouteStatus.PLANIFICADA
            or route.started_at is not None
            or route.completed_at is not None
            for route in routes
        ):
            raise HTTPException(
                status_code=409,
                detail="La ruta tiene avance o requiere revisión antes de asignar",
            )
    return delivery


async def assignment_candidate(
    db: AsyncSession,
    rider_id: UUID,
    actor_id: UUID,
    expected_token_version: int | None,
    *,
    require_online: bool = False,
    skip_locked: bool = False,
) -> AssignmentCandidate | None:
    rider = await db.scalar(
        select(Rider)
        .options(raiseload("*"))
        .where(Rider.id == rider_id)
        .with_for_update(skip_locked=skip_locked)
        .execution_options(populate_existing=True)
    )
    if rider is None:
        return None
    # Shared locks serialize deactivation/revocation without mutating accounts.
    users = {
        user.id: user
        for user in (
            await db.scalars(
                select(User)
                .options(raiseload("*"))
                .where(User.id.in_({actor_id, rider.user_id}))
                .order_by(User.id)
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
        ).all()
    }
    actor = users.get(actor_id)
    if (
        actor is None
        or not actor.is_active
        or (
            expected_token_version is not None
            and actor.token_version != expected_token_version
        )
    ):
        raise HTTPException(
            status_code=401, detail="La cuenta o sus credenciales ya no están vigentes"
        )
    if actor.role not in OPERATIONS_STAFF:
        raise HTTPException(
            status_code=403, detail="La asignación requiere personal operativo"
        )
    owner = users.get(rider.user_id)
    if (
        rider.status != RiderStatus.ACTIVO
        or (require_online and rider.is_online is not True)
        or owner is None
        or not owner.is_active
        or owner.role != UserRole.REPARTIDOR
        or await document_readiness_error(db, rider.id)
    ):
        return None
    if require_online:
        try:
            coordinate(rider.last_lat, rider.last_lng)
        except ValueError:
            return None
        if rider.last_location is None:
            return None
    return AssignmentCandidate(rider, owner, actor)


async def apply_order_assignment(
    db: AsyncSession,
    order: Order,
    delivery: Delivery | None,
    candidate: AssignmentCandidate,
    *,
    source: str,
) -> bool:
    old_rider = order.assigned_rider_id
    same_order_assignment = (
        order.status == OrderStatus.ASIGNADO and old_rider == candidate.rider.id
    )
    if (
        same_order_assignment
        and delivery is not None
        and delivery.rider_id == candidate.rider.id
        and delivery.status == DeliveryStatus.INICIADA
    ):
        # An eligible replay acknowledges the persisted assignment. Unknown
        # timestamps stay unknown; a retry must not invent a fresh SLA clock.
        return False
    old = {
        "rider_id": str(old_rider) if old_rider else None,
        "order_status": order.status.value if order.status else None,
        "delivery_id": str(delivery.id) if delivery else None,
        "delivery_rider_id": (
            str(delivery.rider_id) if delivery and delivery.rider_id else None
        ),
        "accepted_at": order.accepted_at.isoformat() if order.accepted_at else None,
        "started_at": (
            delivery.started_at.isoformat()
            if delivery and delivery.started_at
            else None
        ),
    }
    now = utc_now_naive()
    order.assigned_rider_id = candidate.rider.id
    order.status = OrderStatus.ASIGNADO
    if not same_order_assignment:
        order.accepted_at = now
    if delivery is None:
        delivery = Delivery(
            order_id=order.id,
            rider_id=candidate.rider.id,
            status=DeliveryStatus.INICIADA,
            started_at=now,
            sla_expected_minutes=getattr(order, "sla_minutes", 60),
        )
        db.add(delivery)
    else:
        if (
            delivery.rider_id != candidate.rider.id
            or delivery.status == DeliveryStatus.PENDIENTE
        ):
            delivery.started_at = now
        delivery.rider_id = candidate.rider.id
        delivery.status = DeliveryStatus.INICIADA
    await db.flush()
    db.add(
        AuditLog(
            user_id=candidate.actor.id,
            user_email=candidate.actor.email,
            user_role=candidate.actor.role.value if candidate.actor.role else None,
            action_type=(
                ActionType.REASSIGN
                if old_rider and old_rider != candidate.rider.id
                else ActionType.ASSIGN
            ),
            resource_type="ORDER",
            resource_id=str(order.id),
            description=f"Pedido asignado al rider {candidate.rider.id}",
            old_values=old,
            new_values={
                "rider_id": str(candidate.rider.id),
                "delivery_id": str(delivery.id),
                "order_status": "ASIGNADO",
                "source": source,
                "accepted_at": (
                    order.accepted_at.isoformat() if order.accepted_at else None
                ),
                "started_at": (
                    delivery.started_at.isoformat() if delivery.started_at else None
                ),
            },
            success=True,
        )
    )
    return True


async def assign_order_manually(
    db: AsyncSession,
    order: Order,
    rider_id: UUID,
    actor_id: UUID,
    expected_token_version: int | None = None,
    *,
    source: str = "manual",
) -> AssignmentCandidate:
    delivery = await lock_assignment_delivery(db, order)
    candidate = await assignment_candidate(
        db, rider_id, actor_id, expected_token_version
    )
    if candidate is None:
        raise HTTPException(
            status_code=400, detail="Repartidor no disponible o documentación pendiente"
        )
    changed = await apply_order_assignment(
        db, order, delivery, candidate, source=source
    )
    return replace(candidate, changed=changed)
