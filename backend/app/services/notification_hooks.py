"""
Fase 9 — Helpers de hook para servicios de negocio (payouts/tracking/deliveries).

El dispatch usa siempre una sesión propia. Si se proporciona db, solo selecciona
su engine y exige que no tenga una transacción activa: el llamador debe invocar
el hook después de commit. No se confirma ni revierte trabajo del llamador.
Este hook es best-effort, sin outbox ni garantía durable de ejecución.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, AsyncEngine, async_sessionmaker

logger = logging.getLogger(__name__)


async def record_legacy_notice(
    db: AsyncSession,
    *,
    user_id: Any,
    notification_type: str,
    title: str,
    message: str,
    data: Dict[str, Any] | None = None,
) -> bool:
    """Post-commit inbox persistence; failure never rolls back the caller session."""
    if db.in_transaction() or not isinstance(db.bind, AsyncEngine):
        logger.warning("Legacy notice requires a post-commit engine-bound session")
        return False
    factory = async_sessionmaker(db.bind, expire_on_commit=False, autoflush=False)
    try:
        from app.services.notification_service import NotificationService

        async with factory() as own_db:
            await NotificationService(own_db).create_notification(
                user_id=user_id,
                notification_type=notification_type,
                title=title,
                message=message,
                data=data,
                channel="push",
            )
        return True
    except Exception:
        logger.warning("Legacy notification persistence failed")
        return False


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
            if db.in_transaction():
                logger.warning("Notification hook requires post-commit invocation")
                return
            if not isinstance(db.bind, AsyncEngine):
                # A connection-bound session could share the owner's transaction.
                logger.warning("Notification hook requires an engine-bound session")
                return
            session_factory = async_sessionmaker(
                db.bind, expire_on_commit=False, autoflush=False
            )
        else:
            from app.core.database import AsyncSessionLocal

            session_factory = AsyncSessionLocal

        async with session_factory() as own_db:
            service = OmnichannelNotificationService(own_db)
            await service.send(
                user_id,
                template_code,
                context,
                delivery_id=delivery_id,
                payout_id=payout_id,
                title=title,
            )
    except Exception:  # Operational hook failures never alter caller transactions.
        logger.warning("Notification hook failed")


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
