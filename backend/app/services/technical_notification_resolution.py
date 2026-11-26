"""Administrative closure of technical holds; never retries or attests delivery."""

import hashlib
import json
import re
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import String, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.serialization import utc_isoformat
from app.models.audit_log import AuditLog, ActionType
from app.models.notification import (
    NotificationLog,
    OmnichannelStatus as Status,
    utc_now_naive,
)
from app.models.user import User, UserRole
from app.services.terminal_notifications import MANAGED_EVENTS, EXTERNAL, read_payload

RESOURCE = "notification_technical_resolution"
ACTION = "close_without_resend"


def audit_reference(column):
    """Canonical UUID text also works with SQLite's compact test UUID storage.

    Keep the audit resource column bare so its existing index remains usable.
    """
    raw = cast(column, String)
    canonical = (
        func.substr(raw, 1, 8)
        .concat("-")
        .concat(func.substr(raw, 9, 4))
        .concat("-")
        .concat(func.substr(raw, 13, 4))
        .concat("-")
        .concat(func.substr(raw, 17, 4))
        .concat("-")
        .concat(func.substr(raw, 21, 12))
    )
    return case((func.length(raw) == 32, canonical), else_=raw)


def resolution_exists():
    return (
        select(AuditLog.id)
        .where(
            AuditLog.resource_type == RESOURCE,
            AuditLog.resource_id == audit_reference(NotificationLog.id),
            AuditLog.success.is_(True),
        )
        .correlate(NotificationLog)
        .exists()
    )


def classify(
    log: NotificationLog,
) -> tuple[dict[str, Any], str, str | None, str | None]:
    payload: dict[str, Any] = {}
    try:
        payload = read_payload(log)
        dispatch = payload["dispatch"]
        phase = dispatch.get("state")
        if log.status == Status.PENDIENTE:
            if (
                phase == "queued"
                and log.next_retry_at is not None
                and not dispatch.get("attempt_id")
            ):
                return payload, "queued", None, None
            if phase == "uncertain" and log.next_retry_at is None:
                return payload, "uncertain", str(UUID(dispatch["attempt_id"])), None
        return payload, "invalid", None, "policy_or_state"
    except (HTTPException, ValueError, TypeError, KeyError, AttributeError):
        # Never return arbitrary malformed payload fields, exception text or raw
        # destinations. An old record does not prove absence of a provider send.
        return {}, "invalid", None, "unverifiable_record"


def revision(log: NotificationLog) -> str:
    snapshot = {}
    for name in (
        "id",
        "user_id",
        "delivery_id",
        "payout_id",
        "template_code",
        "channel",
        "status",
        "title",
        "body",
        "payload_json",
        "dedupe_key",
        "retry_count",
        "error_message",
    ):
        value = getattr(log, name)
        snapshot[name] = (
            str(value.value if hasattr(value, "value") else value)
            if value is not None
            else None
        )
    for name in ("created_at", "sent_at", "next_retry_at", "read_at"):
        snapshot[name] = utc_isoformat(getattr(log, name))
    return hashlib.sha256(
        json.dumps(
            snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def receipt(audit: AuditLog) -> dict[str, Any]:
    values: dict[str, Any] = getattr(audit, "new_values") or {}
    return {
        "id": audit.resource_id,
        "resolution_id": values.get("resolution_id"),
        "audit_id": str(audit.id),
        "action": ACTION,
        "state": "resolved",
        "resolved_at": utc_isoformat(getattr(audit, "created_at")),
        "resolved_by": str(audit.user_id),
        "reference": values.get("reference"),
        "note": values.get("note"),
    }


async def resolve(
    db: AsyncSession,
    notification_id: UUID,
    actor_id: UUID,
    resolution_id: UUID,
    expected_revision: str,
    action: str,
    reference: str,
    note: str,
) -> dict[str, Any]:
    reference, note = reference.strip(), note.strip()
    if (
        action != ACTION
        or not re.fullmatch(r"[a-f0-9]{64}", expected_revision)
        or not 8 <= len(reference) <= 200
        or any(ord(c) < 32 for c in reference)
        or len(note) > 500
    ):
        raise HTTPException(422, "Acción o referencia de cierre inválida")
    log = await db.scalar(
        select(NotificationLog)
        .where(NotificationLog.id == notification_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    actor = await db.scalar(
        select(User)
        .where(User.id == actor_id)
        .execution_options(populate_existing=True)
    )
    if (
        actor is None
        or not actor.is_active
        or actor.role not in (UserRole.SUPERADMIN, UserRole.GERENTE)
    ):
        raise HTTPException(403, "El cierre requiere gerencia vigente")
    if log is None:
        raise HTTPException(404, "Aviso no encontrado")
    if log.template_code not in MANAGED_EVENTS or log.channel not in EXTERNAL:
        raise HTTPException(409, "El registro no es un aviso externo administrado")
    values = {
        "resolution_id": str(resolution_id),
        "revision": expected_revision,
        "action": action,
        "reference": reference,
        "note": note,
    }
    existing = await db.scalar(
        select(AuditLog).where(
            AuditLog.resource_type == RESOURCE,
            AuditLog.resource_id == str(log.id),
            AuditLog.success.is_(True),
        )
    )
    if existing is not None:
        if existing.user_id != actor_id or existing.new_values != values:
            raise HTTPException(
                409, "El aviso ya tiene otro cierre; actualice la consulta"
            )
        await db.commit()
        return receipt(existing)
    if revision(log) != expected_revision:
        raise HTTPException(
            409, "El aviso cambió; actualice la consulta antes de cerrar"
        )
    if classify(log)[1] != "invalid" or log.status not in (
        Status.PENDIENTE,
        Status.FALLIDO,
    ):
        raise HTTPException(
            409, "Solo se cierran bloqueos técnicos; revise el resultado del intento"
        )
    original = {
        "revision": expected_revision,
        "status": log.status.value,
        "next_retry_at": utc_isoformat(log.next_retry_at),
    }
    # Keep payload, body, title, retry count and original error verbatim.
    # No provider call, payout mutation, accepted flag or fabricated attempt ID.
    log.status = Status.FALLIDO
    log.next_retry_at = None
    audit = AuditLog(
        id=uuid4(),
        user_id=actor_id,
        user_role=actor.role.value,
        action_type=ActionType.STATUS_CHANGE,
        resource_type=RESOURCE,
        resource_id=str(log.id),
        changes_summary="resolution:" + str(resolution_id),
        description="Cierre administrativo de bloqueo técnico sin reenvío ni aceptación externa",
        old_values=original,
        new_values=values,
        success=True,
        created_at=utc_now_naive(),
    )
    db.add(audit)
    await db.commit()
    return receipt(audit)
