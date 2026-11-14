"""
CRUD Operations for Order (alineado al contrato actual)
"""

from datetime import datetime
import uuid
from typing import Optional, List, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order, OrderStatus
from app.services import order_pricing
from app.core.exceptions import AppException
from app.services.order_cancellation import cancel_order as coordinated_cancel


class CRUDOrder:
    async def get(self, db: AsyncSession, order_id: uuid.UUID) -> Optional[Order]:
        result = await db.execute(select(Order).where(Order.id == order_id))
        return result.scalar_one_or_none()

    async def get_multi(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        status: Optional[OrderStatus] = None,
        rider_id: Optional[uuid.UUID] = None,
    ) -> List[Order]:
        query = select(Order)
        if status is not None:
            query = query.where(Order.status == status)
        if rider_id is not None:
            query = query.where(Order.assigned_rider_id == rider_id)

        query = query.order_by(Order.created_at.desc()).offset(skip).limit(limit)
        result = await db.execute(query)
        return list(result.scalars().all())

    async def create(self, db: AsyncSession, obj_in: dict[str, Any]) -> Order:
        if set(obj_in) & {
            "pricing_version",
            "pricing_revision",
            "subtotal_exact",
            "delivery_fee_exact",
            "total_exact",
            "items_exact",
        }:
            raise AppException(
                "El precio exacto debe calcularse desde sus datos declarados", 422
            )
        if (
            obj_in.get("currency", "USD") != "USD"
            or obj_in.get("currency_code", "USD") != "USD"
        ):
            raise AppException("Las órdenes nuevas deben declarar USD", 422)
        obj_in = {k: v for k, v in obj_in.items() if k != "currency"}
        db_obj = Order(**obj_in)
        db_obj.currency_code = "USD"
        order_pricing.apply(
            db_obj,
            order_pricing.calculate(
                obj_in.get("items"),
                obj_in.get("subtotal"),
                obj_in.get("delivery_fee"),
                obj_in.get("total"),
            ),
        )
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def update(
        self,
        db: AsyncSession,
        db_obj: Order,
        obj_in: dict[str, Any],
        *,
        commit: bool = True,
    ) -> Order:
        current_order = await db.scalar(
            select(Order)
            .where(Order.id == db_obj.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if current_order is None:
            raise AppException("Orden no encontrada", 404)
        db_obj = current_order
        if set(obj_in) & {
            "pricing_version",
            "pricing_revision",
            "subtotal_exact",
            "delivery_fee_exact",
            "total_exact",
            "items_exact",
        }:
            raise AppException("Use los datos de precio y su revisión esperada", 422)
        target = obj_in.get("status")
        if target is not None:
            current = await db.scalar(
                select(Order.status).where(Order.id == db_obj.id).with_for_update()
            )
            if target == OrderStatus.CANCELADO or current == OrderStatus.CANCELADO:
                raise AppException(
                    "La cancelación debe gestionarse desde su operación explícita", 409
                )
        order_pricing.update_price(db_obj, obj_in)
        obj_in = {
            k: v
            for k, v in obj_in.items()
            if k
            not in order_pricing.MONEY_FIELDS
            | {"expected_pricing_revision", "currency"}
        }
        for field, value in obj_in.items():
            setattr(db_obj, field, value)
        db.add(db_obj)
        if commit:
            await db.commit()
            await db.refresh(db_obj)
        else:
            await db.flush()
        return db_obj

    async def assign_rider(
        self, db: AsyncSession, order: Order, rider_id: uuid.UUID
    ) -> Order:
        current = await db.scalar(
            select(Order.status).where(Order.id == order.id).with_for_update()
        )
        if current not in (OrderStatus.PENDIENTE, OrderStatus.ASIGNADO):
            raise AppException("La orden no admite asignación de repartidor", 409)
        order.assigned_rider_id = rider_id  # type: ignore[assignment]
        order.status = OrderStatus.ASIGNADO
        order.accepted_at = datetime.utcnow()  # type: ignore[assignment]
        db.add(order)
        await db.commit()
        await db.refresh(order)
        return order

    async def get_by_rider(
        self,
        db: AsyncSession,
        rider_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Order]:
        result = await db.execute(
            select(Order)
            .where(Order.assigned_rider_id == rider_id)
            .order_by(Order.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def cancel(
        self,
        db: AsyncSession,
        order: Order,
        cancellation_reason: str,
        cancelled_by: int,
    ) -> Order:
        return await coordinated_cancel(
            db, order.id, str(cancelled_by), cancellation_reason, commit=True
        )


order = CRUDOrder()
