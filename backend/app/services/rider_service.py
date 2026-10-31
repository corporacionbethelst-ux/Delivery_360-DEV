"""Legacy rider adapter using physical fields and guarded administrative approval.

Fleet, online/tier edits and counters require their canonical workflows; this
adapter cannot invent missing rating/approval/counter columns.
"""

from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import AppException, NotFoundError, ValidationError
from app.models.rider import Rider, RiderStatus, RiderTier, VehicleType
from app.models.user import User, UserRole
from app.models.audit_log import AuditLog, ActionType
from app.schemas.rider import RiderCreate, RiderUpdate, RiderApprovalRequest
from app.services.document_review import document_readiness_error, lock_rider
from app.services.notification_values import notification_uuid, notification_text


def utc_now_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RiderService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_rider(
        self, rider_data: RiderCreate, user_id: UUID, *, commit: bool = False
    ) -> Rider:
        uid = notification_uuid(user_id, "Usuario")
        if uid != rider_data.user_id:
            raise ValidationError("El usuario del perfil no coincide")
        if (
            (rider_data.status is not None and rider_data.status.value != "PENDIENTE")
            or (rider_data.tier is not None and rider_data.tier.value != "BRONCE")
            or rider_data.is_online
            or rider_data.total_points
            or rider_data.level not in (None, 1)
            or rider_data.badges
        ):
            raise ValidationError(
                "El registro no admite privilegios, disponibilidad o recompensas iniciales"
            )
        if rider_data.assigned_vehicle_id is not None or (
            rider_data.vehicle_ownership_type is not None
            and rider_data.vehicle_ownership_type.value == "EMPRESA"
        ):
            raise AppException(
                "La asignación de flota requiere su operación con revisión", 409
            )
        if type(commit) is not bool:
            raise ValidationError("Opción transaccional inválida")
        try:
            owner = await self.db.scalar(
                select(User)
                .where(User.id == uid)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if owner is None or owner.role != UserRole.REPARTIDOR:
                raise ValidationError(
                    "El perfil requiere un usuario repartidor existente"
                )
            if (
                await self.db.scalar(select(Rider.id).where(Rider.user_id == uid))
                is not None
            ):
                raise AppException("El usuario ya tiene perfil de repartidor", 409)
            rider = Rider(
                user_id=uid,
                status=RiderStatus.PENDIENTE,
                tier=RiderTier.BRONCE,
                is_online=False,
                vehicle_type=(
                    VehicleType(rider_data.vehicle_type.value)
                    if rider_data.vehicle_type
                    else None
                ),
                vehicle_plate=rider_data.vehicle_plate,
                vehicle_model=rider_data.vehicle_model,
                operating_zone=rider_data.operating_zone,
                cpf=rider_data.cpf,
                cnh=rider_data.cnh,
                notes=rider_data.notes,
            )
            self.db.add(rider)
            await self.db.flush()
            if commit:
                await self.db.commit()
            return rider
        except BaseException:
            if commit:
                await self.db.rollback()
            raise

    async def get_rider_by_user_id(self, user_id: UUID) -> Rider | None:
        return await self.db.scalar(select(Rider).where(Rider.user_id == user_id))

    async def get_rider_by_id(
        self, rider_id: UUID, *, lock: bool = False
    ) -> Rider | None:
        query = select(Rider).where(Rider.id == rider_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        return await self.db.scalar(query)

    async def update_rider(self, rider_id: UUID, rider_data: RiderUpdate) -> Rider:
        values = rider_data.model_dump(exclude_unset=True)
        if set(values) - {"operating_zone"}:
            raise AppException(
                "Use los flujos de perfil/flota, estado y nivel con sus permisos y revisión",
                409,
            )
        try:
            rider = await self.get_rider_by_id(rider_id, lock=True)
            if rider is None:
                raise NotFoundError("Repartidor no encontrado")
            if "operating_zone" in values:
                rider.operating_zone = values["operating_zone"]
            rider.updated_at = utc_now_naive()
            await self.db.commit()
            return rider
        except BaseException:
            await self.db.rollback()
            raise

    async def _approver(self, uid: UUID) -> User:
        actor = await self.db.scalar(
            select(User).where(User.id == uid).execution_options(populate_existing=True)
        )
        if (
            actor is None
            or not actor.is_active
            or actor.role not in (UserRole.SUPERADMIN, UserRole.GERENTE)
        ):
            raise AppException("La aprobación requiere gerencia activa", 403)
        return actor

    async def approve_rider(
        self, rider_id: UUID, approval_data: RiderApprovalRequest, approver_id: UUID
    ) -> Rider:
        uid = notification_uuid(approver_id, "Responsable")
        reason = (
            notification_text(approval_data.rejection_reason, "Motivo de rechazo", 2000)
            if not approval_data.approved
            else (
                notification_text(approval_data.notes, "Observaciones", 2000)
                if approval_data.notes
                else "Aprobación manual"
            )
        )
        try:
            await self._approver(uid)
            await lock_rider(self.db, rider_id)
            rider = await self.get_rider_by_id(rider_id, lock=True)
            if rider is None:
                raise NotFoundError("Repartidor no encontrado")
            if approval_data.approved:
                error = await document_readiness_error(self.db, rider_id)
                if error:
                    raise AppException("No se puede aprobar: " + error, 409)
            actor = await self._approver(uid)
            before = {
                "status": rider.status.value if rider.status else None,
                "approved_at": (
                    rider.approved_at.isoformat() if rider.approved_at else None
                ),
                "is_online": rider.is_online,
            }
            rider.status = (
                RiderStatus.ACTIVO if approval_data.approved else RiderStatus.SUSPENDIDO
            )
            rider.is_online = False
            if approval_data.approved:
                rider.approved_at = utc_now_naive()
            rider.updated_at = utc_now_naive()
            self.db.add(
                AuditLog(
                    user_id=uid,
                    user_role=actor.role.value if actor.role else None,
                    action_type=ActionType.STATUS_CHANGE,
                    resource_type="Rider",
                    resource_id=str(rider.id),
                    description="Decisión administrativa sobre perfil de repartidor",
                    changes_summary=reason[:500],
                    old_values=before,
                    new_values={
                        "reason": reason,
                        "status": rider.status.value,
                        "approved_at": (
                            rider.approved_at.isoformat() if rider.approved_at else None
                        ),
                        "is_online": False,
                    },
                    success=True,
                )
            )
            await self.db.commit()
            return rider
        except BaseException:
            await self.db.rollback()
            raise

    async def update_status(self, rider_id: UUID, status: RiderStatus) -> Rider:
        if status not in (
            RiderStatus.PENDIENTE,
            RiderStatus.INACTIVO,
            RiderStatus.SUSPENDIDO,
        ):
            raise AppException(
                "La activación o disponibilidad requiere su operación autorizada", 409
            )
        try:
            rider = await self.get_rider_by_id(rider_id, lock=True)
            if rider is None:
                raise NotFoundError("Repartidor no encontrado")
            rider.status = status
            rider.is_online = False
            rider.updated_at = utc_now_naive()
            await self.db.commit()
            return rider
        except BaseException:
            await self.db.rollback()
            raise

    async def get_riders_by_status(self, status: RiderStatus) -> list[Rider]:
        return list(
            (await self.db.scalars(select(Rider).where(Rider.status == status))).all()
        )

    async def increment_delivery_count(
        self, rider_id: UUID, success: bool = True
    ) -> None:
        raise AppException(
            "Los contadores se derivan de entregas persistidas; no existe contador mutable en Rider",
            501,
        )

    async def update_rating(self, rider_id: UUID, new_rating: float) -> Rider:
        raise AppException(
            "Las calificaciones requieren un historial verificado aún no implementado",
            501,
        )
