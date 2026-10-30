"""CRUD operations for Delivery (alineado al contrato actual)."""

from datetime import datetime
import uuid
from typing import Optional, List, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.delivery import Delivery, DeliveryStatus
from app.core.exceptions import AppException
from app.services.order_cancellation import ensure_order_not_cancelled


class CRUDDelivery:
    async def get(self, db: AsyncSession, delivery_id: uuid.UUID) -> Optional[Delivery]:
        result = await db.execute(select(Delivery).where(Delivery.id == delivery_id))
        return result.scalar_one_or_none()

    async def get_by_order_id(
        self, db: AsyncSession, order_id: uuid.UUID
    ) -> Optional[Delivery]:
        result = await db.execute(select(Delivery).where(Delivery.order_id == order_id))
        return result.scalar_one_or_none()

    async def get_multi(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        rider_id: Optional[uuid.UUID] = None,
        status: Optional[DeliveryStatus] = None,
        created_at_gte: Optional[datetime] = None,
        created_at_lte: Optional[datetime] = None,
    ) -> List[Delivery]:
        query = select(Delivery)
        if rider_id is not None:
            query = query.where(Delivery.rider_id == rider_id)
        if status is not None:
            query = query.where(Delivery.status == status)
        if created_at_gte is not None:
            query = query.where(Delivery.created_at >= created_at_gte)
        if created_at_lte is not None:
            query = query.where(Delivery.created_at <= created_at_lte)

        query = query.order_by(Delivery.created_at.desc()).offset(skip).limit(limit)
        result = await db.execute(query)
        return list(result.scalars().all())

    async def create(self, db: AsyncSession, obj_in: dict[str, Any]) -> Delivery:
        await ensure_order_not_cancelled(db, obj_in["order_id"], lock=True)
        if obj_in.get("status") == DeliveryStatus.CANCELADA:
            raise AppException("Cancele la entrega desde su orden", 409)
        db_obj = Delivery(**obj_in)
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def update(
        self,
        db: AsyncSession,
        db_obj: Delivery,
        obj_in: dict[str, Any],
        *,
        commit: bool = True,
    ) -> Delivery:
        await ensure_order_not_cancelled(db, db_obj.order_id, lock=True)
        current = await db.scalar(
            select(Delivery.status).where(Delivery.id == db_obj.id).with_for_update()
        )
        if (
            current == DeliveryStatus.CANCELADA
            or obj_in.get("status") == DeliveryStatus.CANCELADA
        ):
            raise AppException(
                "La cancelación no puede sobrescribirse mediante edición", 409
            )
        for field, value in obj_in.items():
            setattr(db_obj, field, value)
        db.add(db_obj)
        if commit:
            await db.commit()
            await db.refresh(db_obj)
        else:
            await db.flush()
        return db_obj

    async def get_by_rider(
        self,
        db: AsyncSession,
        rider_id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Delivery]:
        return await self.get_multi(db, skip=skip, limit=limit, rider_id=rider_id)


delivery = CRUDDelivery()
