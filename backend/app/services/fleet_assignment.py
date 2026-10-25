"""Fleet mutation protocol: vehicles in UUID order, then rider, then documents.

Callers authorize the actor and commit/rollback the whole operation. Historical
contradictory ownership is rejected rather than repaired by guessing.
"""

from uuid import UUID
from typing import Any
from fastapi import HTTPException
from sqlalchemy import select, and_
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload
from app.models.vehicle import Vehicle
from app.models.rider import Rider, utc_now_naive
from app.models.rider_document import DocumentStatus
from app.services.document_review import (
    lock_rider,
    rider_documents,
    restrict_rider_documents,
)

VEHICLE_FIELDS = frozenset(
    {
        "vehicle_type",
        "vehicle_plate",
        "vehicle_model",
        "vehicle_ownership_type",
        "assigned_vehicle_id",
    }
)


def available_vehicle_condition() -> ColumnElement[bool]:
    """A catalog candidate must be active and unused from both sides."""
    referenced = (
        select(Rider.id).where(Rider.assigned_vehicle_id == Vehicle.id).exists()
    )
    return and_(Vehicle.status == "ACTIVO", Vehicle.rider_id.is_(None), ~referenced)


async def lock_vehicles(db: AsyncSession, ids: set[UUID]) -> dict[UUID, Vehicle]:
    vehicles = {}
    for vehicle_id in sorted(ids, key=str):
        vehicle = await db.scalar(
            select(Vehicle)
            .options(raiseload("*"))
            .where(Vehicle.id == vehicle_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if vehicle is None:
            raise HTTPException(status_code=404, detail="Vehículo no encontrado")
        vehicles[vehicle_id] = vehicle
    return vehicles


async def ensure_vehicle_unassigned(db: AsyncSession, vehicle: Vehicle) -> None:
    referenced = await db.scalar(
        select(Rider.id).where(Rider.assigned_vehicle_id == vehicle.id).limit(1)
    )
    if vehicle.rider_id is not None or referenced is not None:
        raise HTTPException(
            status_code=409,
            detail="Desasigne el vehículo antes de modificar sus datos críticos o eliminarlo",
        )


async def ensure_vehicle_available(
    db: AsyncSession, vehicle: Vehicle, user_id: UUID, rider_id: UUID | None = None
) -> None:
    if vehicle.status != "ACTIVO":
        raise HTTPException(status_code=409, detail="El vehículo no está activo")
    references = list(
        (
            await db.scalars(
                select(Rider.id).where(Rider.assigned_vehicle_id == vehicle.id)
            )
        ).all()
    )
    if vehicle.rider_id not in (None, user_id) or any(
        ref != rider_id for ref in references
    ):
        raise HTTPException(
            status_code=409,
            detail="El vehículo ya está asignado o sus vínculos requieren revisión",
        )


async def invalidate_vehicle_documents(db: AsyncSession, rider_id: UUID) -> None:
    for doc in await rider_documents(db, rider_id):
        doc.status = DocumentStatus.RECHAZADO
        doc.rejection_reason = (
            "Cambio de vehículo o asignación. Suba la documentación actualizada."
        )
        doc.updated_at = utc_now_naive()
    await db.flush()
    await restrict_rider_documents(db, rider_id)


async def prepare_vehicle_update(
    db: AsyncSession, rider: Rider, payload: dict[str, Any]
) -> bool:
    """Lock, validate both links and normalize fleet fields before caller applies them."""
    previous_id = rider.assigned_vehicle_id
    requested_id = payload.get("assigned_vehicle_id", previous_id)
    ids = {value for value in (previous_id, requested_id) if value is not None}
    vehicles = await lock_vehicles(db, ids)
    await lock_rider(db, rider.id)
    fields = list(VEHICLE_FIELDS) + ["status", "is_online"]
    await db.refresh(rider, attribute_names=fields)
    if rider.assigned_vehicle_id != previous_id:
        raise HTTPException(
            status_code=409,
            detail="La asignación cambió. Recargue el perfil antes de reintentar",
        )
    ownership = payload.get("vehicle_ownership_type", rider.vehicle_ownership_type)
    if ownership not in ("PROPIO", "EMPRESA"):
        raise HTTPException(status_code=422, detail="Propiedad de vehículo inválida")
    target = requested_id if ownership == "EMPRESA" else None
    if ownership == "EMPRESA":
        if target is None:
            raise HTTPException(
                status_code=400, detail="EMPRESA requiere un vehículo asignado"
            )
        vehicle = vehicles[target]
        await ensure_vehicle_available(db, vehicle, rider.user_id, rider.id)
        canonical = {
            "vehicle_type": vehicle.type,
            "vehicle_plate": vehicle.plate,
            "vehicle_model": vehicle.model,
        }
        if not {"assigned_vehicle_id", "vehicle_ownership_type"}.intersection(payload):
            if any(
                key in payload and payload[key] != value
                for key, value in canonical.items()
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Edite el vehículo de empresa desde flota después de desasignarlo",
                )
        payload.update(canonical)
    elif (
        requested_id is not None
        and "assigned_vehicle_id" in payload
        and payload.get("vehicle_ownership_type") != "PROPIO"
    ):
        raise HTTPException(
            status_code=400, detail="PROPIO no admite vehículo de empresa asignado"
        )
    if {"assigned_vehicle_id", "vehicle_ownership_type"}.intersection(payload):
        payload["assigned_vehicle_id"] = target
    changed = any(
        getattr(rider, key) != value
        for key, value in payload.items()
        if key in VEHICLE_FIELDS
    )
    if previous_id is not None:
        old = vehicles[previous_id]
        references = list(
            (
                await db.scalars(
                    select(Rider.id).where(Rider.assigned_vehicle_id == previous_id)
                )
            ).all()
        )
        if old.rider_id not in (None, rider.user_id) or any(
            ref != rider.id for ref in references
        ):
            raise HTTPException(
                status_code=409,
                detail="La asignación anterior requiere revisión de sus vínculos",
            )
        if target != previous_id:
            old.rider_id = None
    if target is not None:
        vehicles[target].rider_id = rider.user_id
    return changed
