"""Exercise the actual legacy enum, rather than an ORM-created superset."""

import importlib.util
from pathlib import Path
from decimal import Decimal
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.api.v1.payouts import _requested_notice

spec = importlib.util.spec_from_file_location(
    "notice_enum115",
    Path(__file__).parents[1] / "alembic/versions/20261122_notification_kinds.py",
)
revision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(revision)


@pytest.mark.asyncio
async def test_legacy_enum_upgrade_preserves_rows_and_accepts_durable_notices(
    pg_wallets,
):
    sessions, _, _ = pg_wallets
    engine = sessions.kw["bind"]
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TYPE notificationtype AS ENUM ('ALERTA_OPERACIONAL','ASIGNACION_PEDIDO','ESTADO_ENTREGA','RECORDATORIO','LOGRO','SISTEMA','URGENTE')"
            )
        )
        await conn.run_sync(lambda c: Notification.__table__.create(c, checkfirst=True))
    async with sessions() as db:
        uid = await db.scalar(select(User.id).limit(1))
        db.add(
            Notification(
                user_id=uid,
                notification_type=NotificationType.SISTEMA,
                title="Historical",
                message="Preserved",
                data={"original": True},
            )
        )
        await db.commit()
        before = await db.scalar(text("SELECT to_jsonb(n)::text FROM notifications n"))
        db.add(_requested_notice(uuid4(), uid, Decimal("60.01")))
        with pytest.raises(DBAPIError):
            await db.commit()
        await db.rollback()

    async def migrate(direction):
        async with engine.begin() as conn:

            def apply(c):
                with Operations.context(MigrationContext.configure(c)):
                    getattr(revision, direction)()

            await conn.run_sync(apply)

    await migrate("upgrade")
    await migrate("upgrade")
    async with sessions() as db:
        assert (
            await db.scalar(text("SELECT to_jsonb(n)::text FROM notifications n"))
            == before
        )
        labels = (
            (
                await db.execute(
                    text("SELECT unnest(enum_range(NULL::notificationtype))::text")
                )
            )
            .scalars()
            .all()
        )
        assert set(labels) == {kind.value for kind in NotificationType}
        db.add(_requested_notice(uuid4(), uid, Decimal("60.01")))
        await db.commit()
        saved = (
            (
                await db.execute(
                    text("SELECT to_jsonb(n)::text FROM notifications n ORDER BY id")
                )
            )
            .scalars()
            .all()
        )
    await migrate("downgrade")
    async with sessions() as db:
        assert (
            await db.execute(
                text("SELECT to_jsonb(n)::text FROM notifications n ORDER BY id")
            )
        ).scalars().all() == saved
