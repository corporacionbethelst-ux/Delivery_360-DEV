"""Coordinated, audited cancellation without money movements or evidence deletion."""

from uuid import UUID
from datetime import datetime, timezone
import unicodedata
from sqlalchemy import select, cast, String, or_, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import AppException, NotFoundError, ValidationError
from app.models.order import Order, OrderStatus
from app.models.delivery import Delivery, DeliveryStatus
from app.models.route import Route, RouteStatus
from app.models.user import User, UserRole
from app.models.rider import Rider
from app.models.financial import Financial
from app.models.fiscal import ElectronicInvoice, PaymentDistributionSnapshot
from app.models.audit_log import AuditLog, ActionType
from app.models.notification import Alert

RESOURCE = "order_cancellation"
LEGACY_REASON = "Cancelación solicitada mediante cambio de estado"
ACTIVE_ORDERS = {
    OrderStatus.PENDIENTE,
    OrderStatus.ASIGNADO,
    OrderStatus.EN_RECOLECCION,
    OrderStatus.RECOLECTADO,
    OrderStatus.EN_RUTA,
}
ACTIVE_DELIVERIES = {
    DeliveryStatus.PENDIENTE,
    DeliveryStatus.INICIADA,
    DeliveryStatus.EN_PICKUP,
    DeliveryStatus.EN_ROUTE,
    DeliveryStatus.EN_DESTINO,
}


def cancellation_reason(value: object) -> str:
    if not isinstance(value, str):
        raise ValidationError("Indique un motivo de cancelación válido")
    result = value.strip()
    if not 8 <= len(result) <= 500 or any(
        unicodedata.category(c) in ("Cc", "Cf", "Cs") for c in result
    ):
        raise ValidationError(
            "El motivo debe tener entre ocho y 500 caracteres sin controles"
        )
    return result


async def ensure_order_not_cancelled(
    db: AsyncSession, order_id: UUID, *, lock: bool = False
) -> None:
    query = select(cast(Order.status, String)).where(Order.id == order_id)
    if lock:
        query = query.with_for_update()
    status = await db.scalar(query)
    if status == OrderStatus.CANCELADO.value:
        raise AppException(
            "La orden está cancelada; no admite operaciones de entrega", 409
        )


async def _enum_ready(db: AsyncSession) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    ready = await db.scalar(text("""
        SELECT EXISTS (
          SELECT 1 FROM pg_attribute a JOIN pg_enum e ON e.enumtypid=a.atttypid
          WHERE a.attrelid=to_regclass('deliveries') AND a.attname='status'
            AND NOT a.attisdropped AND e.enumlabel='CANCELADA'
        )
    """))
    if not ready:
        raise AppException(
            "La cancelación está temporalmente no disponible; contacte administración",
            503,
        )


async def _actor(db: AsyncSession, uid: UUID, expected: int | None) -> User:
    actor = await db.scalar(
        select(User).where(User.id == uid).execution_options(populate_existing=True)
    )
    if (
        actor is None
        or not actor.is_active
        or (expected is not None and actor.token_version != expected)
    ):
        raise AppException("La cuenta o sus credenciales ya no están vigentes", 401)
    if actor.role not in (UserRole.SUPERADMIN, UserRole.GERENTE):
        raise AppException(
            "La cancelación requiere gerencia o superadministración", 403
        )
    return actor


async def cancel_order(
    db: AsyncSession,
    order_id: UUID | str,
    actor_id: UUID | str,
    reason: object,
    *,
    expected_token_version: int | None = None,
    commit: bool = False,
) -> Order:
    reason = cancellation_reason(reason)
    try:
        oid, uid = UUID(str(order_id)), UUID(str(actor_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError("Identificador de cancelación inválido") from exc
    if type(commit) is not bool:
        raise ValidationError("Opción transaccional inválida")
    if expected_token_version is not None and (
        type(expected_token_version) is not int
        or not 0 <= expected_token_version <= 2147483647
    ):
        raise ValidationError("Versión de credenciales inválida")
    try:
        actor = await _actor(db, uid, expected_token_version)
        order = await db.scalar(
            select(Order)
            .where(Order.id == oid)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if order is None:
            raise NotFoundError("Pedido no encontrado")
        deliveries = list(
            (
                await db.scalars(
                    select(Delivery)
                    .where(Delivery.order_id == oid)
                    .order_by(Delivery.id)
                    .limit(2)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).all()
        )
        if len(deliveries) > 1:
            raise AppException(
                "La orden tiene entregas ambiguas; requiere revisión", 409
            )
        delivery = deliveries[0] if deliveries else None
        if order.assigned_rider_id is not None:
            await db.execute(
                select(Rider.id)
                .where(Rider.id == order.assigned_rider_id)
                .with_for_update()
            )
        routes = (
            list(
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
            if delivery
            else []
        )
        if order.status == OrderStatus.CANCELADO:
            receipt = await db.scalar(
                select(AuditLog)
                .where(
                    AuditLog.resource_type == RESOURCE,
                    AuditLog.resource_id == str(oid),
                    AuditLog.action_type == ActionType.STATUS_CHANGE,
                    AuditLog.user_id == uid,
                    AuditLog.changes_summary == reason,
                    AuditLog.success.is_(True),
                )
                .limit(1)
            )
            if (
                receipt is not None
                and order.cancelled_by == str(uid)
                and order.cancellation_reason == reason
                and (delivery is None or delivery.status == DeliveryStatus.CANCELADA)
                and len(routes) <= 1
                and all(route.status == RouteStatus.CANCELADA for route in routes)
                and isinstance(receipt.old_values, dict)
                and receipt.old_values.get("delivery_id")
                == (str(delivery.id) if delivery else None)
                and receipt.old_values.get("assigned_rider_id")
                == (str(order.assigned_rider_id) if order.assigned_rider_id else None)
                and receipt.old_values.get("delivery_rider_id")
                == (str(delivery.rider_id) if delivery and delivery.rider_id else None)
                and receipt.old_values.get("route_ids")
                == [str(route.id) for route in routes]
                and isinstance(receipt.new_values, dict)
                and receipt.new_values.get("order_status") == "CANCELADO"
            ):

                if commit:
                    await db.commit()
                return order
            raise AppException(
                "La cancelación previa requiere revisión; no se sobrescribió", 409
            )
        if order.status not in ACTIVE_ORDERS:
            raise AppException("El estado del pedido no admite cancelación", 409)
        if delivery is not None:
            if (
                delivery.status not in ACTIVE_DELIVERIES
                or delivery.rider_id != order.assigned_rider_id
            ):
                raise AppException(
                    "El estado o la asignación de la entrega requiere revisión", 409
                )
            if any(
                value is not None
                for value in (
                    delivery.locked_bonus_amount,
                    delivery.locked_bonus_type,
                    delivery.bonus_snapshot_date,
                )
            ):
                raise AppException(
                    "Existe un bono congelado; la cancelación requiere revisión", 409
                )
            await _enum_ready(db)
        references = [str(oid)] + ([str(delivery.id)] if delivery is not None else [])
        keys = [f"pago_entrega_{oid}", f"pago_fallido_{oid}"]
        evidence = await db.scalar(
            select(Financial.id)
            .where(
                or_(
                    Financial.idempotency_key.in_(keys),
                    Financial.reference_id.in_(references),
                    Financial.source_id.in_(references),
                )
            )
            .limit(1)
        )
        invoice = await db.scalar(
            select(ElectronicInvoice.id)
            .where(ElectronicInvoice.order_id == oid)
            .limit(1)
        )
        distribution = await db.scalar(
            select(PaymentDistributionSnapshot.id)
            .where(PaymentDistributionSnapshot.order_id == oid)
            .limit(1)
        )
        if evidence is not None or invoice is not None or distribution is not None:
            raise AppException(
                "Hay evidencia financiera o fiscal; la cancelación requiere revisión",
                409,
            )
        if len(routes) > 1 or any(
            route.status not in (RouteStatus.PLANIFICADA, RouteStatus.EN_PROGRESO)
            for route in routes
        ):
            raise AppException(
                "La ruta asociada requiere revisión antes de cancelar", 409
            )
        alerts = (
            list(
                (
                    await db.scalars(
                        select(Alert)
                        .where(
                            Alert.delivery_id == delivery.id,
                            Alert.alert_type == "SLA_BREACH",
                            Alert.status.in_(("OPEN", "ACKNOWLEDGED")),
                        )
                        .order_by(Alert.id)
                        .limit(101)
                        .with_for_update()
                    )
                ).all()
            )
            if delivery
            else []
        )
        if len(alerts) > 100:
            raise AppException("Las alertas asociadas requieren revisión", 409)
        actor = await _actor(db, uid, expected_token_version)
        old = {
            "order_status": order.status.value if order.status else None,
            "delivery_id": str(delivery.id) if delivery else None,
            "delivery_status": (
                delivery.status.value if delivery and delivery.status else None
            ),
            "assigned_rider_id": (
                str(order.assigned_rider_id) if order.assigned_rider_id else None
            ),
            "delivery_rider_id": (
                str(delivery.rider_id) if delivery and delivery.rider_id else None
            ),
            "route_ids": [str(route.id) for route in routes],
            "sla_alert_ids": [str(alert.id) for alert in alerts],
        }
        order.status = OrderStatus.CANCELADO
        order.cancelled_by = str(uid)
        order.cancellation_reason = reason
        if delivery is not None:
            delivery.status = DeliveryStatus.CANCELADA
        for route in routes:
            route.status = RouteStatus.CANCELADA
        for alert in alerts:
            alert.status = "RESOLVED"
            alert.resolved_by = uid
            alert.resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
            alert.resolution_notes = "Orden cancelada: " + reason
        db.add(
            AuditLog(
                user_id=uid,
                user_role=actor.role.value if actor.role else None,
                action_type=ActionType.STATUS_CHANGE,
                resource_type=RESOURCE,
                resource_id=str(oid),
                description="Cancelación coordinada de orden y entrega",
                changes_summary=reason,
                old_values=old,
                new_values={
                    "order_status": "CANCELADO",
                    "delivery_status": "CANCELADA" if delivery else None,
                    "route_status": "CANCELADA" if routes else None,
                    "money_changed": False,
                    "resolved_sla_count": len(alerts),
                },
                success=True,
            )
        )
        await db.flush()
        if commit:
            await db.commit()
        return order
    except BaseException:
        if commit:
            await db.rollback()
        raise
