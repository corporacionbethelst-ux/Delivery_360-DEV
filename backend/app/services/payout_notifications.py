"""Transactional payout receipts/queue and isolated post-commit WS nudges."""

import hashlib
import asyncio
import logging
import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.notification import (
    NotificationChannel as Channel,
    NotificationLog,
    NotificationTemplate,
    OmnichannelStatus as Status,
    utc_now_naive,
)
from app.models.rider import Rider
from app.models.user import User
from app.services.notification_hooks import payout_context
from app.services.omnichannel_service import (
    OmnichannelNotificationService,
    render_template,
)

EVENTS = {
    "requested": ("payout_solicitado", "Solicitud de retiro creada", "se registró"),
    "approved": (
        "payout_aprobado",
        "Retiro aprobado contablemente",
        "se aprobó contablemente",
    ),
    "rejected": ("payout_rechazado", "Solicitud de retiro rechazada", "se rechazó"),
}


def schedule_inbox_notice(payout_id: Any, event: str) -> None:
    """Best-effort WS nudge after commit; loss never loses the persisted inbox."""
    try:
        asyncio.get_running_loop().create_task(_publish_inbox(payout_id, event))
    except RuntimeError:
        logging.getLogger(__name__).warning("Payout inbox nudge unavailable")


async def _publish_inbox(payout_id: Any, event: str) -> None:
    from app.core.database import AsyncSessionLocal

    key = hashlib.sha256(
        f"payout:{payout_id}:{EVENTS[event][0]}:{Channel.IN_APP.value}".encode()
    ).hexdigest()
    try:
        async with AsyncSessionLocal() as db:
            log = await db.scalar(
                select(NotificationLog).where(NotificationLog.dedupe_key == key)
            )
            if log is not None:
                await OmnichannelNotificationService(db)._publish_new_notification(log)
    except Exception:
        logging.getLogger(__name__).warning("Payout inbox nudge unavailable")


async def enqueue_payout_notice(
    db: AsyncSession, payout: Any, event: str, reason: str = ""
) -> None:
    """Caller owns rollback/commit. Payout row/rider lock serializes decisions."""
    code, title, verb = EVENTS[event]
    user = await db.scalar(
        select(User)
        .join(Rider, Rider.user_id == User.id)
        .where(Rider.id == payout.rider_id)
    )
    if user is None:
        raise ValueError("Payout notification recipient missing")
    try:
        context = payout_context(payout, {"reason": reason})
    except ValueError:
        if event != "rejected" or payout.currency_code == "USD":
            raise
        # Rejection of unverifiable legacy requests must not invent an amount.
        context = {
            "payout_id": str(payout.id),
            "currency_code": payout.currency_code,
            "amount_label": "importe histórico por revisar",
            "monetary_review": True,
            "reason": reason,
        }
    body = f"La solicitud de retiro por {context['amount_label']} {verb}."
    if event == "approved":
        body += " Esto no confirma una transferencia bancaria."
    if reason:
        body += " Motivo: " + reason
    now = utc_now_naive()
    payload = json.dumps(context, sort_keys=True, ensure_ascii=False)
    planned: list[
        tuple[Channel, str, str, str, Status, datetime | None, str | None]
    ] = [(Channel.IN_APP, title, body, code, Status.ENVIADO, None, None)]
    if settings.NOTIFICATIONS_ENABLED and user.is_active:
        # Read policy from SQL, without template caches or any provider I/O.
        template = await db.scalar(
            select(NotificationTemplate)
            .where(
                NotificationTemplate.code == code,
                NotificationTemplate.is_active.is_(True),
            )
            .execution_options(populate_existing=True)
        )
        if template is not None:
            channels = await OmnichannelNotificationService(
                db, redis_client=False
            ).resolve_channels(user, template, code)
            unsafe = bool(
                re.search(
                    r"\{\{\s*amount_cents\s*\}\}",
                    (template.body_template or "") + (template.subject or ""),
                )
            )
            for channel in dict.fromkeys(channels):
                if channel == Channel.IN_APP:
                    continue
                rendered = (
                    body if unsafe else render_template(template.body_template, context)
                )
                subject = title
                if not unsafe and template.subject:
                    subject = render_template(template.subject, context)
                planned.append(
                    (
                        channel,
                        subject[:255],
                        rendered,
                        code,
                        Status.FALLIDO if unsafe else Status.PENDIENTE,
                        None if unsafe else now,
                        (
                            "Plantilla monetaria requiere revisión; no se envió"
                            if unsafe
                            else None
                        ),
                    )
                )
    for channel, subject, text, template_code, status, due, error in planned:
        key = hashlib.sha256(
            f"payout:{payout.id}:{code}:{channel.value}".encode()
        ).hexdigest()
        existing = await db.scalar(
            select(NotificationLog).where(NotificationLog.dedupe_key == key)
        )
        if existing is not None:
            if existing.user_id != user.id or existing.payload_json != payload:
                raise ValueError("Contradictory payout notification replay")
            continue
        db.add(
            NotificationLog(
                user_id=user.id,
                payout_id=payout.id,
                template_code=template_code,
                channel=channel,
                status=status,
                payload_json=payload,
                dedupe_key=key,
                title=subject,
                body=text,
                next_retry_at=due,
                error_message=error,
                created_at=now,
                sent_at=now if channel == Channel.IN_APP else None,
            )
        )
    await db.flush()
