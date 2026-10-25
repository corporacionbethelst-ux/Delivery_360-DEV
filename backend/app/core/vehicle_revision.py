"""State fingerprint of a selected vehicle; not a credential or event counter."""

import hashlib
import hmac
import json
import re
from fastapi import HTTPException
from app.models.vehicle import Vehicle


def vehicle_revision(vehicle: Vehicle) -> str:
    values = [
        str(vehicle.id),
        vehicle.type,
        vehicle.plate,
        vehicle.model,
        vehicle.color,
        vehicle.year,
        vehicle.status,
        vehicle.insurance_expiry.isoformat() if vehicle.insurance_expiry else None,
        str(vehicle.rider_id) if vehicle.rider_id else None,
    ]
    return hashlib.sha256(
        json.dumps(values, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def ensure_vehicle_revision(vehicle: Vehicle, expected: str | None) -> None:
    if expected is None:
        raise HTTPException(
            status_code=409,
            detail="Recargue y revise la ficha del vehículo seleccionado",
        )
    if not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise HTTPException(status_code=422, detail="Revisión de vehículo inválida")
    if not hmac.compare_digest(vehicle_revision(vehicle), expected):
        raise HTTPException(
            status_code=409,
            detail="La ficha del vehículo cambió. Recargue y vuelva a seleccionarlo",
        )


def vehicle_edit_revision(vehicle: Vehicle) -> str:
    """Protect all editable inventory fields, including administrative notes."""
    values = [vehicle_revision(vehicle), vehicle.notes]
    return hashlib.sha256(
        json.dumps(values, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def ensure_vehicle_edit_revision(vehicle: Vehicle, expected: str | None) -> None:
    if expected is None:
        raise HTTPException(
            status_code=409,
            detail="Recargue la ficha del vehículo antes de modificarla o eliminarla",
        )
    token = (
        expected[1:-1]
        if len(expected) == 66 and expected.startswith('"') and expected.endswith('"')
        else expected
    )
    if not re.fullmatch(r"[a-f0-9]{64}", token):
        raise HTTPException(status_code=422, detail="If-Match de vehículo inválido")
    if not hmac.compare_digest(vehicle_edit_revision(vehicle), token):
        raise HTTPException(
            status_code=409,
            detail="La ficha del vehículo cambió. Recargue y revise los datos antes de continuar",
        )
