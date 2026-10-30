"""Validation shared by legacy inbox writers; no database or provider I/O."""

import json
import unicodedata
from uuid import UUID
from app.core.exceptions import ValidationError
from app.core.json_types import JsonValue, json_value


def notification_uuid(value: object, field: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise ValidationError(f"{field} debe ser un UUID válido")
    try:
        return UUID(value)
    except ValueError as exc:
        raise ValidationError(f"{field} debe ser un UUID válido") from exc


def notification_text(value: object, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field} debe ser texto")
    result = value.strip()
    if not 1 <= len(result) <= limit or any(
        c == "\x00" or unicodedata.category(c) == "Cs" for c in result
    ):
        raise ValidationError(f"{field} vacío, demasiado largo o no representable")
    return result


def notification_payload(value: object) -> JsonValue:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValidationError("Los datos de notificación deben ser un objeto JSON")
    try:
        result = json_value(value)
        # Reject unpaired surrogates in keys/values before they reach PostgreSQL or HTTP.
        json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")
        encoded = json.dumps(result, ensure_ascii=True, allow_nan=False)
        if len(encoded.encode()) > 16384:
            raise ValueError("payload limit")
        return result
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValidationError(
            "Datos de notificación inválidos o demasiado grandes"
        ) from exc


def notification_recipients(values: object) -> list[UUID]:
    if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= 200:
        raise ValidationError("Indique entre uno y 200 destinatarios")
    return list(
        dict.fromkeys(notification_uuid(value, "Destinatario") for value in values)
    )
