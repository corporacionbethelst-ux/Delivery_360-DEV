"""Transactional closure outbox and one-shot external dispatch with review.

A durable uncertain marker precedes provider I/O. Unknown outcomes never requeue.
This does not provide external exactly-once delivery or device acknowledgement.
"""

import hashlib
import json
import re
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.email_service import smtp_email_is_configured
from app.core.serialization import utc_isoformat
from app.models.audit_log import AuditLog, ActionType
from app.models.delivery import Delivery, DeliveryStatus
from app.models.notification import (
    NotificationLog,
    NotificationTemplate,
    NotificationChannel as Channel,
    OmnichannelStatus as Status,
    UserDeviceToken,
    utc_now_naive,
)
from app.models.order import Order, OrderStatus
from app.models.rider import Rider
from app.models.user import User, UserRole

EVENTS = {
    "entrega_completada": (OrderStatus.ENTREGADO, DeliveryStatus.COMPLETADA),
    "entrega_fallida": (OrderStatus.FALLIDO, DeliveryStatus.FALLIDA),
    "orden_cancelada": (OrderStatus.CANCELADO, DeliveryStatus.CANCELADA),
}
EXTERNAL = (Channel.PUSH, Channel.SMS, Channel.EMAIL)
RESOURCE = "terminal_notification_review"


def read_payload(log: NotificationLog) -> dict[str, Any]:
    try:
        if (
            log.template_code not in EVENTS
            or log.channel not in EXTERNAL
            or log.payout_id is not None
        ):
            raise ValueError()
        if not log.payload_json or len(log.payload_json) > 16384:
            raise ValueError()
        data = json.loads(log.payload_json)
        if (
            not isinstance(data, dict)
            or data.get("event") != log.template_code
            or not isinstance(data.get("dispatch"), dict)
            or type(data["dispatch"].get("version")) is not int
            or data["dispatch"]["version"] != 1
        ):
            raise ValueError()
        UUID(data["order_id"])
        UUID(data["rider_id"])
        return data
    except (ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(
            409, "El registro de envío requiere revisión técnica"
        ) from None


async def enqueue_external(
    db: AsyncSession,
    order: Order,
    delivery: Delivery | None,
    rider_id: UUID,
    user_id: UUID,
    code: str,
    title: str,
    body: str,
    context: dict[str, Any],
) -> None:
    if not settings.NOTIFICATIONS_ENABLED:
        return
    user = await db.scalar(
        select(User).where(User.id == user_id).execution_options(populate_existing=True)
    )
    if user is None or not user.is_active or user.role != UserRole.REPARTIDOR:
        return
    template = await db.scalar(
        select(NotificationTemplate)
        .where(
            NotificationTemplate.code == code, NotificationTemplate.is_active.is_(True)
        )
        .execution_options(populate_existing=True)
    )
    if template is None or template.channel not in EXTERNAL:
        return
    from app.services.omnichannel_service import (
        OmnichannelNotificationService,
        render_template,
    )

    channels = await OmnichannelNotificationService(
        db, redis_client=False
    ).resolve_channels(user, template, code, channels=[template.channel])
    payload = {
        **context,
        "rider_id": str(rider_id),
        "order_code": order.external_id or str(order.id)[:8],
    }
    if delivery is not None and delivery.completed_at is not None:
        payload["completed_at"] = utc_isoformat(delivery.completed_at)
    present = {key for key, value in payload.items() if value is not None}
    unsafe = bool(
        set(
            re.findall(
                r"\{\{\s*(\w+)\s*\}\}",
                (template.subject or "") + (template.body_template or ""),
            )
        )
        - present
    )
    rendered_body = render_template(template.body_template, payload)
    rendered_title = (
        render_template(template.subject, payload) if template.subject else title
    )
    if not rendered_body.strip() or any(
        marker in rendered_body + rendered_title for marker in ("{{", "}}")
    ):
        unsafe = True
    payload["dispatch"] = {"version": 1, "state": "queued"}
    now = utc_now_naive()
    for channel in dict.fromkeys(channels):
        if channel not in EXTERNAL:
            continue
        key = hashlib.sha256(
            f"order:{order.id}:{code}:{channel.value}".encode()
        ).hexdigest()
        pending = any(
            isinstance(row, NotificationLog) and row.dedupe_key == key for row in db.new
        )
        existing = await db.scalar(
            select(NotificationLog.id).where(NotificationLog.dedupe_key == key)
        )
        if pending or existing is not None:
            raise HTTPException(409, "El envío externo existente requiere revisión")
        db.add(
            NotificationLog(
                id=uuid4(),
                user_id=user_id,
                delivery_id=delivery.id if delivery else None,
                template_code=code,
                channel=channel,
                status=Status.FALLIDO if unsafe else Status.PENDIENTE,
                dedupe_key=key,
                title=(
                    title if unsafe or not template.subject else rendered_title[:255]
                ),
                body=(
                    body if unsafe else render_template(template.body_template, payload)
                ),
                payload_json=json.dumps(payload, sort_keys=True, ensure_ascii=False),
                created_at=now,
                next_retry_at=None if unsafe else now,
                error_message=(
                    "Plantilla requiere revisión: variables no disponibles; no se envió"
                    if unsafe
                    else None
                ),
            )
        )


async def recipient_still_valid(
    db: AsyncSession, log: NotificationLog, user: User
) -> bool:
    try:
        payload = read_payload(log)
        expected = EVENTS.get(log.template_code or "")
        if expected is None:
            return False
        order = await db.scalar(
            select(Order)
            .where(Order.id == UUID(payload["order_id"]))
            .execution_options(populate_existing=True)
        )
        if (
            order is None
            or order.status != expected[0]
            or str(order.assigned_rider_id) != payload["rider_id"]
            or user.role != UserRole.REPARTIDOR
        ):
            return False
        owner = await db.scalar(
            select(Rider.user_id).where(Rider.id == order.assigned_rider_id)
        )
        if owner != log.user_id:
            return False
        if log.delivery_id is None:
            return (
                log.template_code == "orden_cancelada"
                and payload.get("delivery_id") is None
                and await db.scalar(
                    select(Delivery.id).where(Delivery.order_id == order.id).limit(1)
                )
                is None
            )
        delivery = await db.scalar(
            select(Delivery)
            .where(Delivery.id == log.delivery_id)
            .execution_options(populate_existing=True)
        )
        return bool(
            delivery is not None
            and str(delivery.id) == payload.get("delivery_id")
            and delivery.order_id == order.id
            and delivery.rider_id == order.assigned_rider_id
            and delivery.status == expected[1]
        )
    except HTTPException:
        return False


async def dispatch_once(service: Any, log: NotificationLog, user: User) -> None:
    db: AsyncSession = service.db
    payload = read_payload(log)
    if payload["dispatch"].get("state") != "queued":
        log.next_retry_at = None
        return
    tokens = []
    email, phone = user.email, user.phone
    ready = False
    if log.channel == Channel.EMAIL:
        from email_validator import validate_email, EmailNotValidError

        try:
            email = validate_email(
                email or "", check_deliverability=False, allow_smtputf8=False
            ).normalized
            ready = smtp_email_is_configured(settings.notification_email_from_computed)
        except EmailNotValidError:
            ready = False
    elif log.channel == Channel.SMS:
        ready = bool(
            re.fullmatch(r"\+[1-9][0-9]{6,14}", user.phone or "")
            and settings.TWILIO_ACCOUNT_SID
            and settings.TWILIO_AUTH_TOKEN
            and settings.TWILIO_FROM_NUMBER
        )
    elif log.channel == Channel.PUSH:
        tokens = list(
            (
                await db.scalars(
                    select(UserDeviceToken)
                    .where(
                        UserDeviceToken.user_id == user.id,
                        UserDeviceToken.is_active.is_(True),
                    )
                    .order_by(UserDeviceToken.id)
                )
            ).all()
        )
        ready = bool(settings.FCM_CREDENTIALS_JSON_PATH and tokens)
    if not ready:
        from app.services.omnichannel_service import compute_next_retry_at

        log.error_message = (
            "Configuración o destino no disponible; no se intentó el envío"
        )
        log.next_retry_at = compute_next_retry_at(log.retry_count)
        return
    attempt_id = str(uuid4())
    payload["dispatch"] = {
        "version": 1,
        "state": "uncertain",
        "attempt_id": attempt_id,
        "started_at": utc_isoformat(utc_now_naive()),
    }
    if log.channel == Channel.EMAIL:
        destination = email or ""
        hint = (destination[:1] + "***@" + destination.partition("@")[2])[:200]
    elif log.channel == Channel.SMS:
        destination = phone or ""
        hint = "***" + destination[-4:]
    else:
        destination = "|".join(sorted(t.device_token for t in tokens))
        hint = f"{len(tokens)} dispositivos registrados"
    payload["dispatch"]["destination_sha256"] = hashlib.sha256(
        destination.encode()
    ).hexdigest()
    payload["dispatch"]["destination_hint"] = hint
    log.payload_json = json.dumps(payload, sort_keys=True)
    log.next_retry_at = None
    log.retry_count += 1
    log.error_message = "Intento registrado; aceptación del proveedor sin confirmar. No se reenviará automáticamente"
    log_id = log.id
    title, body, channel = log.title or "", log.body or "", log.channel
    # This commit is the safety boundary. A crash at any later point retains
    # an uncertain record, including if the process dies before actual I/O.
    await db.commit()
    if channel == Channel.EMAIL:
        ok = await service.dispatch_email(email, title, body)
    elif channel == Channel.SMS:
        ok = await service.dispatch_sms(phone, body)
    else:
        from app.services.notification_devices import device_revisions

        ok = await service.dispatch_push(
            [t.device_token for t in tokens],
            title,
            body,
            revisions=device_revisions(tokens),
        )
    current = await db.scalar(
        select(NotificationLog)
        .where(NotificationLog.id == log_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if current is None:
        raise RuntimeError("Claimed notification disappeared")
    latest = read_payload(current)
    if latest["dispatch"].get("attempt_id") != attempt_id:
        raise RuntimeError("Notification attempt changed")
    if ok is True and latest["dispatch"].get("state") != "accepted":
        latest["dispatch"]["state"] = "accepted"
        latest["dispatch"]["accepted_at"] = utc_isoformat(utc_now_naive())
        current.payload_json = json.dumps(latest, sort_keys=True)
        current.status = Status.ENVIADO
        current.sent_at = utc_now_naive()
        current.error_message = None
        # The queue owner confirms the acknowledgement. Failure of that commit
        # leaves the durable uncertain claim, never an automatic resend.


async def review_result(
    db: AsyncSession,
    notification_id: UUID,
    actor_id: UUID,
    review_id: UUID,
    attempt_id: UUID,
    decision: str,
    reference: str,
    note: str,
) -> dict[str, Any]:
    if (
        decision not in ("accepted", "unconfirmed")
        or not 8 <= len(reference.strip()) <= 200
        or len(note) > 500
    ):
        raise HTTPException(422, "Decisión o referencia de revisión inválida")
    reference = reference.strip()
    note = note.strip()
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
        raise HTTPException(403, "La revisión requiere gerencia vigente")
    if log is None:
        raise HTTPException(404, "Envío no encontrado")
    if log.template_code not in EVENTS or log.channel not in EXTERNAL:
        raise HTTPException(409, "El registro no es un envío externo de cierre")
    payload = read_payload(log)
    if payload["dispatch"].get("attempt_id") != str(attempt_id):
        raise HTTPException(409, "El intento cambió; actualice la consulta")
    key = "review:" + str(review_id)
    values = {
        "attempt_id": str(attempt_id),
        "decision": decision,
        "reference": reference,
        "note": note,
    }
    old = await db.scalar(
        select(AuditLog).where(
            AuditLog.resource_type == RESOURCE,
            AuditLog.resource_id == str(log.id),
            AuditLog.changes_summary == key,
        )
    )
    if old is not None:
        if old.user_id != actor_id or old.new_values != values:
            raise HTTPException(
                409, "La clave de revisión ya corresponde a otra decisión"
            )
        await db.commit()
        return {
            "id": str(log.id),
            "review_id": str(review_id),
            "decision": decision,
            "state": payload["dispatch"]["state"],
        }
    if (
        payload["dispatch"].get("state") != "uncertain"
        or log.status != Status.PENDIENTE
        or log.next_retry_at is not None
    ):
        raise HTTPException(409, "El envío ya tiene resultado o no está retenido")
    payload["dispatch"]["last_review_id"] = str(review_id)
    if decision == "accepted":
        payload["dispatch"]["state"] = "accepted"
        payload["dispatch"]["accepted_at"] = utc_isoformat(utc_now_naive())
        log.status = Status.ENVIADO
        log.sent_at = utc_now_naive()
        log.error_message = None
    log.payload_json = json.dumps(payload, sort_keys=True)
    db.add(
        AuditLog(
            user_id=actor_id,
            user_role=actor.role.value,
            action_type=ActionType.STATUS_CHANGE,
            resource_type=RESOURCE,
            resource_id=str(log.id),
            changes_summary=key,
            description="Revisión de resultado externo; no emite un nuevo envío",
            success=True,
            old_values={"state": "uncertain"},
            new_values=values,
        )
    )
    await db.commit()
    return {
        "id": str(log.id),
        "review_id": str(review_id),
        "decision": decision,
        "state": payload["dispatch"]["state"],
    }
