"""Compatibility CRUD delegates sensitive rider writes to guarded workflows."""

from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.rider import Rider, RiderStatus
from app.models.rider_document import RiderDocument
from app.schemas.rider import RiderCreate, RiderUpdate, RiderApprovalRequest
from app.services.rider_service import RiderService
from app.core.exceptions import ValidationError


class CRUDRider:
    async def get(self, db: AsyncSession, rider_id: UUID) -> Rider | None:
        return await RiderService(db).get_rider_by_id(rider_id)

    async def get_by_user_id(self, db: AsyncSession, user_id: UUID) -> Rider | None:
        return await RiderService(db).get_rider_by_user_id(user_id)

    async def get_multi(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        status: RiderStatus | None = None,
        is_approved: bool | None = None,
    ) -> list[Rider]:
        if (
            type(skip) is not int
            or skip < 0
            or type(limit) is not int
            or not 1 <= limit <= 200
            or (is_approved is not None and type(is_approved) is not bool)
        ):
            raise ValidationError("Paginación o filtro de repartidores inválido")
        query = select(Rider)
        if status is not None:
            query = query.where(Rider.status == status)
        if is_approved is not None:
            query = query.where(
                Rider.approved_at.is_not(None)
                if is_approved
                else Rider.approved_at.is_(None)
            )
        return list(
            (await db.scalars(query.order_by(Rider.id).offset(skip).limit(limit))).all()
        )

    async def create(
        self, db: AsyncSession, obj_in: RiderCreate, user_id: UUID
    ) -> Rider:
        return await RiderService(db).create_rider(obj_in, user_id, commit=True)

    async def update(
        self, db: AsyncSession, db_obj: Rider, obj_in: RiderUpdate
    ) -> Rider:
        return await RiderService(db).update_rider(db_obj.id, obj_in)

    async def approve(
        self, db: AsyncSession, rider_id: UUID, approved_by: UUID
    ) -> Rider | None:
        if await self.get(db, rider_id) is None:
            return None
        return await RiderService(db).approve_rider(
            rider_id, RiderApprovalRequest(approved=True), approved_by
        )

    async def reject(
        self, db: AsyncSession, rider_id: UUID, rejection_reason: str, rejected_by: UUID
    ) -> Rider | None:
        if await self.get(db, rider_id) is None:
            return None
        return await RiderService(db).approve_rider(
            rider_id,
            RiderApprovalRequest(approved=False, rejection_reason=rejection_reason),
            rejected_by,
        )

    async def get_documents(self, db: AsyncSession, rider_id: UUID) -> dict | None:
        rider = await self.get(db, rider_id)
        if rider is None:
            return None
        rows = list(
            (
                await db.scalars(
                    select(RiderDocument)
                    .where(RiderDocument.rider_id == rider_id)
                    .order_by(RiderDocument.id)
                )
            ).all()
        )
        return {
            "rider_id": str(rider_id),
            "metadata": rider.documents_metadata,
            "documents": [
                {
                    "id": str(doc.id),
                    "type": doc.type.value,
                    "status": doc.status.value,
                    "file_url": doc.file_url,
                }
                for doc in rows
            ],
        }


rider = CRUDRider()
