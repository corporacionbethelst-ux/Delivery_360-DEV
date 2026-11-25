"""Best-effort supported inbox invalidations after the outer operation commit."""

import asyncio
import json
import logging
from uuid import UUID

from redis import asyncio as aioredis
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, SessionTransaction

from app.core.config import settings
from app.core.serialization import utc_isoformat
from app.models.notification import NotificationChannel, NotificationLog
from app.models.user import User

logger = logging.getLogger(__name__)
_KEY = "assignment_inbox_nudges"
_REGISTERED = "assignment_inbox_nudge_listeners"
_tasks: set[asyncio.Task] = set()


async def _publish(engine: AsyncEngine, ids: tuple[UUID, ...]) -> None:
    """Read committed receipts from the caller's engine, never its session."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        rows = (
            await db.scalars(
                select(NotificationLog)
                .join(User, User.id == NotificationLog.user_id)
                .where(
                    NotificationLog.id.in_(ids),
                    NotificationLog.channel == NotificationChannel.IN_APP,
                    NotificationLog.template_code.in_(
                        (
                            "nuevo_pedido_asignado",
                            "entrega_completada",
                            "entrega_fallida",
                            "orden_cancelada",
                        )
                    ),
                    User.is_active.is_(True),
                )
            )
        ).all()
        messages = [
            (
                str(row.user_id),
                json.dumps(
                    {
                        "type": "NEW_NOTIFICATION",
                        "id": str(row.id),
                        "title": row.title,
                        "template_code": row.template_code,
                        "created_at": utc_isoformat(row.created_at),
                    }
                ),
            )
            for row in rows
        ]
    if not messages:
        return
    # This client belongs only to the nudge and closes even on cancellation.
    async with aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    ) as client:
        for user_id, payload in messages:
            await client.publish(
                f"{settings.REDIS_NOTIF_CHANNEL_PREFIX}:{user_id}", payload
            )


async def _run(engine: AsyncEngine, ids: tuple[UUID, ...]) -> None:
    try:
        async with asyncio.timeout(5):
            await _publish(engine, ids)
    except Exception:
        # The committed inbox remains the source of truth, including on timeout.
        logger.warning("Operational inbox realtime nudge unavailable")


def _schedule(engine: AsyncEngine, ids: tuple[UUID, ...]) -> None:
    if not ids:
        return
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(_run(engine, ids))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    except Exception:
        logger.warning("Operational inbox realtime nudge unavailable")


def queue_inbox_nudge(db: AsyncSession, notice_id: UUID) -> None:
    """Keep savepoint events provisional until the outer transaction commits.

    A connection-bound session cannot provide an independent read transaction;
    it retains REST recovery without attempting this optional realtime nudge.
    """
    if not isinstance(db.bind, AsyncEngine):
        return
    session = db.sync_session
    transaction = session.get_nested_transaction() or session.get_transaction()
    if transaction is None:
        return
    pending = session.info.setdefault(_KEY, {})
    pending.setdefault(transaction, set()).add(notice_id)
    if session.info.get(_REGISTERED):
        return
    engine = db.bind

    def committed(owner: Session) -> None:
        current = owner.get_nested_transaction() or owner.get_transaction()
        receipts = owner.info.get(_KEY, {}).pop(current, set())
        if current is not None and current.nested and current.parent is not None:
            owner.info.setdefault(_KEY, {}).setdefault(current.parent, set()).update(
                receipts
            )
        else:
            _schedule(engine, tuple(receipts))

    def rolled_back(owner: Session, previous: SessionTransaction) -> None:
        owner.info.get(_KEY, {}).pop(previous, None)

    def ended(owner: Session, previous: SessionTransaction) -> None:
        if previous.parent is None:
            owner.info.pop(_KEY, None)

    event.listen(session, "after_commit", committed)
    event.listen(session, "after_soft_rollback", rolled_back)
    event.listen(session, "after_transaction_end", ended)
    session.info[_REGISTERED] = True


# Preserve the assignment entry point and its transaction semantics.
queue_assignment_nudge = queue_inbox_nudge
