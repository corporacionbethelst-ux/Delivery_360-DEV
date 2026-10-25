"""Inventory history shares the vehicle transaction, including physical deletion.

Callers authorize writes and capture before-state under the vehicle lock. No
independent commit, schema changes or claim of tamper-proof/exactly-once history.
"""

from typing import Any
from uuid import UUID, uuid4
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.vehicle_revision import vehicle_revision, vehicle_edit_revision
from app.models.audit_log import AuditLog, ActionType
from app.models.rider import utc_now_naive
from app.models.user import User
from app.models.vehicle import Vehicle

FIELDS = (
    "type",
    "plate",
    "model",
    "color",
    "year",
    "status",
    "insurance_expiry",
    "notes",
    "rider_id",
)


def inventory_snapshot(vehicle: Vehicle) -> dict[str, Any]:
    return {
        "vehicle_id": str(vehicle.id),
        "created_at": (
            vehicle.created_at.isoformat() + "Z" if vehicle.created_at else None
        ),
        "updated_at": (
            vehicle.updated_at.isoformat() + "Z" if vehicle.updated_at else None
        ),
        "type": vehicle.type,
        "plate": vehicle.plate,
        "model": vehicle.model,
        "color": vehicle.color,
        "year": vehicle.year,
        "status": vehicle.status,
        "insurance_expiry": (
            vehicle.insurance_expiry.isoformat() if vehicle.insurance_expiry else None
        ),
        "notes": vehicle.notes,
        "rider_id": str(vehicle.rider_id) if vehicle.rider_id else None,
        "revision": vehicle_revision(vehicle),
        "edit_revision": vehicle_edit_revision(vehicle),
    }


async def record_inventory_change(
    db: AsyncSession,
    actor: User,
    *,
    vehicle_id: UUID,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> UUID | None:
    if before is None and after is None:
        raise ValueError("Inventory audit requires a before or after state")
    if any(
        state is not None and state.get("vehicle_id") != str(vehicle_id)
        for state in (before, after)
    ):
        raise ValueError("Inventory audit state does not match its vehicle")
    if (
        before is not None
        and after is not None
        and all(before[key] == after[key] for key in FIELDS)
    ):
        return None
    role = getattr(actor.role, "value", actor.role)
    if not isinstance(actor.id, UUID) or role not in {"SUPERADMIN", "GERENTE"}:
        raise ValueError("Inventory audit requires an authenticated management actor")
    if before is None:
        operation, action, method = "CREATE", ActionType.CREATE, "POST"
    elif after is None:
        operation, action, method = "DELETE", ActionType.DELETE, "DELETE"
    elif before["status"] != after["status"]:
        operation, action, method = (
            ("DEACTIVATE" if after["status"] == "BAJA" else "STATUS_CHANGE"),
            ActionType.STATUS_CHANGE,
            "PATCH",
        )
    else:
        operation, action, method = "UPDATE", ActionType.UPDATE, "PATCH"
    changed = [
        key
        for key in FIELDS
        if before is None or after is None or before[key] != after[key]
    ]
    event_time = utc_now_naive()
    event_id = uuid4()
    try:
        # Flush the vehicle write/delete and the event in the same transaction.
        await db.flush()
        db.add(
            AuditLog(
                id=event_id,
                user_id=actor.id,
                user_role=role,
                action_type=action,
                resource_type="Vehicle",
                resource_id=str(vehicle_id),
                description="Inventario de vehículos (VEHICLE_INVENTORY v1)",
                old_values=before,
                new_values={
                    "event_family": "VEHICLE_INVENTORY",
                    "schema_version": 1,
                    "operation": operation,
                    "source": "vehicle_inventory",
                    "occurred_at_utc": event_time.isoformat() + "Z",
                    "vehicle_id": str(vehicle_id),
                    "state": after,
                    "changed_fields": changed,
                },
                changes_summary=f"Inventario de vehículo: {operation}",
                request_method=method,
                request_path=(
                    "/api/v1/vehicles"
                    if method == "POST"
                    else f"/api/v1/vehicles/{vehicle_id}"
                ),
                status_code=201 if method == "POST" else 200,
                success=True,
                contains_personal_data=True,
                created_at=event_time,
            )
        )
        await db.flush()
        return event_id
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=503,
            detail="No se pudo registrar la auditoría de inventario. La operación no se confirmó",
        ) from None
