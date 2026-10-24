"""
Fase 9 — Helpers de hook para servicios de negocio (payouts/tracking/deliveries).

Regla de oro: un fallo de notificación NUNCA puede revertir ni interrumpir la
transacción de negocio. Por eso notify_event() abre su PROPIA sesión y envuelve
todo en try/except. Si se le pasa una sesión existente, la usa sin commitear
nada adicional (confía en el commit del llamador) y aun así atrapa errores.
"""

from __future__ import annotations

import logging
import uuid as uuid_mod
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def notify_event(
    template_code: str,
    user_id: Any,
    context: Dict[str, Any],
    *,
    db: Optional[AsyncSession] = None,
    delivery_id: Optional[Any] = None,
    payout_id: Optional[Any] = None,
    title: Optional[str] = None,
) -> None:
    """Dispatch fire-and-safe de una notificación omnicanal Fase 9."""
    if user_id is None:
        logger.debug("notify_event(%s): user_id None → skip", template_code)
        return
    try:
        from app.services.omnichannel_service import OmnichannelNotificationService

        if db is not None:
            service = OmnichannelNotificationService(db)
            await service.send(
                user_id,
                template_code,
                context,
                delivery_id=delivery_id,
                payout_id=payout_id,
                title=title,
            )
            return

        # Sin sesión: usar sesión propia efímera (hooks desde schedulers/jobs)
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as own_db:
            service = OmnichannelNotificationService(own_db)
            await service.send(
                user_id,
                template_code,
                context,
                delivery_id=delivery_id,
                payout_id=payout_id,
                title=title,
            )
    except Exception as exc:  # noqa: BLE001 — por diseño: jamás propagar
        logger.warning("notify_event(%s) falló (no crítico): %s", template_code, exc)


async def resolve_payout_recipient(db: AsyncSession, payout: Any) -> Optional[Any]:
    """user_id del rider dueño del payout (Payout→Rider→User)."""
    try:
        from app.models.rider import Rider

        result = await db.execute(
            select(Rider.user_id).where(Rider.id == payout.rider_id)
        )
        return result.scalar_one_or_none()
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo resolver destinatario del payout: %s", exc)
        return None


def payout_context(
    payout: Any, extra: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Contexto estándar para plantillas payout_* (amount_cents, bank_last4...)."""
    amount = getattr(payout, "amount", None)
    try:
        amount_cents = int(round(float(amount) * 100)) if amount is not None else 0
    except (TypeError, ValueError):
        amount_cents = 0
    ctx: Dict[str, Any] = {
        "amount_cents": amount_cents,
        "bank_last4": getattr(payout, "bank_account_last4", None) or "0000",
        "status": getattr(getattr(payout, "status", None), "value", str(payout.status)),
        "payout_id": str(payout.id),
    }
    if extra:
        ctx.update(extra)
    return ctx
