"""Fleet events share the business transaction; a failed audit never commits it.

Callers authorize the operation, capture before-state under fleet locks and own
commit/rollback. These records are durable SQL history, not tamper-proof receipts.
"""

from typing import Any, Literal
from uuid import UUID, uuid4
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.fleet_revision import assignment_revision
from app.models.audit_log import AuditLog, ActionType
from app.models.rider import Rider, utc_now_naive
from app.models.user import User
from app.models.vehicle import Vehicle

FleetAuditSource = Literal["admin_create", "rider_patch", "self_profile"]


def _value(value: Any) -> Any:
    return getattr(value, "value", value)


def fleet_snapshot(rider: Rider, vehicles: dict[UUID, Vehicle]) -> dict[str, Any]:
    return {
        "rider_id": str(rider.id),
        "user_id": str(rider.user_id),
        "vehicle_ownership_type": rider.vehicle_ownership_type,
        "assigned_vehicle_id": (
            str(rider.assigned_vehicle_id) if rider.assigned_vehicle_id else None
        ),
        "vehicle_type": _value(rider.vehicle_type),
        "vehicle_plate": rider.vehicle_plate,
        "vehicle_model": rider.vehicle_model,
        "status": _value(rider.status),
        "is_online": rider.is_online,
        "assignment_revision": assignment_revision(rider),
        "vehicle_links": {
            str(key): str(vehicle.rider_id) if vehicle.rider_id else None
            for key, vehicle in vehicles.items()
        },
    }


async def record_fleet_change(
    db: AsyncSession,
    rider: Rider,
    actor: User,
    *,
    before: dict[str, Any] | None,
    source: FleetAuditSource,
    documents_invalidated: int = 0,
    selected_vehicle_revision: str | None = None,
) -> UUID:
    role = _value(actor.role)
    if not isinstance(actor.id, UUID) or role not in {
        "SUPERADMIN",
        "GERENTE",
        "OPERADOR",
        "REPARTIDOR",
    }:
        raise ValueError("Fleet audit requires an authenticated actor")
    try:
        await db.flush()
        ids = {UUID(key) for key in (before or {}).get("vehicle_links", {})}
        if rider.assigned_vehicle_id:
            ids.add(rider.assigned_vehicle_id)
        after = fleet_snapshot(rider, {})
        if ids:
            rows = (
                await db.execute(
                    select(Vehicle.id, Vehicle.rider_id).where(Vehicle.id.in_(ids))
                )
            ).all()
            after["vehicle_links"] = {
                str(row.id): str(row.rider_id) if row.rider_id else None for row in rows
            }
        if before is None:
            operation, action = "CREATE", ActionType.CREATE
        elif before["assigned_vehicle_id"] != after["assigned_vehicle_id"]:
            if after["assigned_vehicle_id"] is None:
                operation, action = "UNASSIGN", ActionType.UPDATE
            elif before["assigned_vehicle_id"] is None:
                operation, action = "ASSIGN", ActionType.ASSIGN
            else:
                operation, action = "REASSIGN", ActionType.REASSIGN
        elif (
            before["assignment_revision"] == after["assignment_revision"]
            and before["vehicle_links"] != after["vehicle_links"]
        ):
            operation, action = "LINK_REPAIR", ActionType.UPDATE
        else:
            operation, action = "VEHICLE_UPDATE", ActionType.UPDATE
        fields = [
            "vehicle_ownership_type",
            "assigned_vehicle_id",
            "vehicle_type",
            "vehicle_plate",
            "vehicle_model",
            "vehicle_links",
            "status",
            "is_online",
        ]
        event_time = utc_now_naive()
        after.update(
            {
                "event_family": "RIDER_FLEET",
                "occurred_at_utc": event_time.isoformat() + "Z",
                "schema_version": 1,
                "selected_vehicle_revision": selected_vehicle_revision,
                "source": source,
                "operation": operation,
                "documents_invalidated": documents_invalidated,
                "status_changed_to": after["status"],
                "changed_fields": [
                    key for key in fields if before is None or before[key] != after[key]
                ],
            }
        )
        event_id = uuid4()
        entry = AuditLog(
            id=event_id,
            user_id=actor.id,
            user_role=role,
            action_type=action,
            resource_type="Rider",
            resource_id=str(rider.id),
            description="Cambio de flota y documentación (RIDER_FLEET v1)",
            old_values=before,
            new_values=after,
            changes_summary=f"Flota: {operation}; documentos invalidados: {documents_invalidated}",
            request_method=(
                "POST"
                if source == "admin_create"
                else "PUT" if source == "self_profile" else "PATCH"
            ),
            request_path=(
                "/api/v1/riders"
                if source == "admin_create"
                else (
                    "/api/v1/riders/me"
                    if source == "self_profile"
                    else f"/api/v1/riders/{rider.id}"
                )
            ),
            status_code=201 if source == "admin_create" else 200,
            success=True,
            contains_personal_data=True,
            created_at=event_time,
        )
        db.add(entry)
        await db.flush()
        return event_id
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=503,
            detail="No se pudo registrar la auditoría. La operación no se confirmó",
        ) from None
