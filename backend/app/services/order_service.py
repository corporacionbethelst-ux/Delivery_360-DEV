"""
Servicio de Gestión de Pedidos (AsyncSession nativo)
"""

from datetime import datetime, timedelta
import uuid
from typing import Optional, List

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.serialization import optional_enum_value
from app.core.json_types import json_value
from app.models.order import Order, OrderStatus, OrderPriority
from app.core.exceptions import AppException, ValidationError
from app.services.order_cancellation import (
    cancel_order as coordinated_cancel,
    LEGACY_REASON,
)
from app.schemas.order import OrderCreate, OrderUpdate


class OrderService:
    """Servicio para gestión de pedidos"""

    async def get_order(
        self, db: AsyncSession, order_id: uuid.UUID, *, lock: bool = False
    ) -> Order:
        query = select(Order).where(Order.id == order_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        result = await db.execute(query)
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Pedido no encontrado"
            )
        return order

    async def create_order(
        self,
        db: AsyncSession,
        order_data: OrderCreate,
        created_by: int,
    ) -> Order:
        now = datetime.utcnow()
        estimated_delivery = now.replace(microsecond=0) + timedelta(minutes=60)
        data = order_data.model_dump()
        data["items"] = json_value(order_data.items)
        data["priority"] = (
            OrderPriority(order_data.priority.value)
            if order_data.priority is not None
            else None
        )
        data["status"] = OrderStatus.PENDIENTE
        data["estimated_delivery_time"] = estimated_delivery
        data["sla_deadline"] = estimated_delivery
        order = Order(**data)
        if order_data.assigned_rider_id is not None:
            order.status = OrderStatus.ASIGNADO
            order.accepted_at = now

        db.add(order)
        await db.commit()
        await db.refresh(order)
        return order

    async def update_order(
        self,
        db: AsyncSession,
        order_id: uuid.UUID,
        order_data: OrderUpdate,
        updated_by: int,
    ) -> Order:
        order = await self.get_order(db, order_id, lock=True)
        update_data = order_data.model_dump(exclude_unset=True)
        if "items" in update_data:
            update_data["items"] = json_value(update_data["items"])
        if order_data.priority is not None:
            update_data["priority"] = OrderPriority(order_data.priority.value)
        if order_data.status is not None:
            update_data["status"] = OrderStatus(order_data.status.value)
        target = update_data.get("status")
        if target == OrderStatus.CANCELADO:
            if set(update_data) != {"status"}:
                raise ValidationError(
                    "Cancele la orden sin combinar cambios adicionales"
                )
            return await coordinated_cancel(
                db, order_id, str(updated_by), LEGACY_REASON, commit=True
            )
        if (
            target is not None
            and target != order.status
            and order.status
            in (OrderStatus.CANCELADO, OrderStatus.ENTREGADO, OrderStatus.FALLIDO)
        ):
            raise AppException(
                "Una orden terminal no puede reabrirse mediante edición", 409
            )
        for key, value in update_data.items():
            setattr(order, key, value)

        db.add(order)
        await db.commit()
        await db.refresh(order)
        return order

    async def assign_rider_to_order(
        self,
        db: AsyncSession,
        order_id: uuid.UUID,
        rider_id: uuid.UUID,
        assigned_by: int,
    ) -> Order:
        order = await self.get_order(db, order_id, lock=True)
        if order.status not in [OrderStatus.PENDIENTE, OrderStatus.ASIGNADO]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se puede asignar repartidor. Estado actual: {optional_enum_value(order.status)}",
            )

        order.assigned_rider_id = rider_id
        order.status = OrderStatus.ASIGNADO
        order.accepted_at = datetime.utcnow()
        db.add(order)
        await db.commit()
        await db.refresh(order)
        return order

    async def update_status(
        self,
        db: AsyncSession,
        order_id: uuid.UUID,
        new_status: OrderStatus,
        updated_by: int,
    ) -> Order:
        if new_status == OrderStatus.CANCELADO:
            return await coordinated_cancel(
                db, order_id, str(updated_by), LEGACY_REASON, commit=True
            )
        order = await self.get_order(db, order_id, lock=True)
        valid_transitions = {
            OrderStatus.PENDIENTE: [OrderStatus.ASIGNADO, OrderStatus.CANCELADO],
            OrderStatus.ASIGNADO: [OrderStatus.RECOLECTADO, OrderStatus.CANCELADO],
            OrderStatus.RECOLECTADO: [OrderStatus.EN_RUTA, OrderStatus.CANCELADO],
            OrderStatus.EN_RUTA: [
                OrderStatus.ENTREGADO,
                OrderStatus.FALLIDO,
                OrderStatus.CANCELADO,
            ],
        }
        if order.status is None:
            raise HTTPException(
                status_code=400, detail="El pedido no tiene estado definido"
            )
        allowed = valid_transitions.get(order.status, [])
        if new_status not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Transición inválida de {optional_enum_value(order.status)} a {new_status.value}",
            )

        now = datetime.utcnow()
        order.status = new_status
        if new_status == OrderStatus.RECOLECTADO:
            order.picked_up_at = now
        elif new_status == OrderStatus.ENTREGADO:
            order.delivered_at = now
        elif new_status == OrderStatus.FALLIDO:
            order.failure_reason = "delivery_failed"

        db.add(order)
        await db.commit()
        await db.refresh(order)
        return order

    async def cancel_order(
        self,
        db: AsyncSession,
        order_id: uuid.UUID,
        cancellation_reason: str,
        cancelled_by: int,
    ) -> Order:
        return await coordinated_cancel(
            db, order_id, str(cancelled_by), cancellation_reason, commit=True
        )

    async def list_orders(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        status_filter: Optional[OrderStatus] = None,
        rider_id: Optional[uuid.UUID] = None,
    ) -> List[Order]:
        q = select(Order)
        if status_filter:
            q = q.where(Order.status == status_filter)
        if rider_id:
            q = q.where(Order.assigned_rider_id == rider_id)
        q = q.order_by(Order.created_at.desc()).offset(skip).limit(limit)
        result = await db.execute(q)
        return list(result.scalars().all())

    async def get_orders_by_rider(
        self,
        db: AsyncSession,
        rider_id: uuid.UUID,
        status_filter: Optional[OrderStatus] = None,
    ) -> List[Order]:
        return await self.list_orders(
            db, skip=0, limit=1000, status_filter=status_filter, rider_id=rider_id
        )


order_service = OrderService()
