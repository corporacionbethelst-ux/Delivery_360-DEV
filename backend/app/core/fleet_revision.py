"""Compare-and-swap fingerprints of fleet state, independent of GPS/finances.

This is a state precondition, not an event counter, credential or audit proof.
Returning to identical fleet values yields the same fingerprint.
"""

import hashlib
import hmac
import json
import re
from fastapi import HTTPException
from app.models.rider import Rider


def assignment_revision(rider: Rider) -> str:
    kind = rider.vehicle_type
    values = [
        str(rider.id),
        str(rider.user_id),
        rider.vehicle_ownership_type,
        str(rider.assigned_vehicle_id) if rider.assigned_vehicle_id else None,
        getattr(kind, "value", kind),
        rider.vehicle_plate,
        rider.vehicle_model,
    ]
    return hashlib.sha256(
        json.dumps(values, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def ensure_assignment_revision(rider: Rider, expected: str | None) -> None:
    if expected is None:
        raise HTTPException(
            status_code=409,
            detail="Recargue el perfil para revisar la asignación actual",
        )
    if not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise HTTPException(status_code=422, detail="Revisión de asignación inválida")
    if not hmac.compare_digest(assignment_revision(rider), expected):
        raise HTTPException(
            status_code=409,
            detail="Los datos del vehículo cambiaron. Recargue el perfil antes de guardar",
        )
