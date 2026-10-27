"""Transactional device registration and immutable provider feedback revisions."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Literal
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import UserDeviceToken


@dataclass(frozen=True)
class DeviceRevision:
    id: UUID
    user_id: UUID
    last_seen_at: datetime


def device_revisions(rows: Iterable[UserDeviceToken]) -> dict[str, DeviceRevision]:
    result: dict[str, DeviceRevision] = {}
    for row in rows:
        if isinstance(row.last_seen_at, datetime):
            result[str(row.device_token)] = DeviceRevision(
                UUID(str(row.id)), UUID(str(row.user_id)), row.last_seen_at
            )
    return result


async def _device_now(db: AsyncSession) -> datetime:
    if db.get_bind().dialect.name == "postgresql":
        now = await db.scalar(select(func.timezone("UTC", func.clock_timestamp())))
        if not isinstance(now, datetime):
            raise ValueError("Device clock unavailable")
        return now
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _next_revision(now: datetime, previous: datetime) -> datetime:
    # A heartbeat must fence old feedback even after a backwards clock change.
    return max(now, previous + timedelta(microseconds=1))


async def register_device_token(
    db: AsyncSession, user_id: UUID, token: str, platform: str
) -> Literal["created", "updated"]:
    """Flush in the caller's transaction; unique conflicts never abort it."""
    dialect = db.get_bind().dialect.name
    if dialect not in {"postgresql", "sqlite"}:
        raise ValueError("Unsupported device database")
    now = await _device_now(db)
    insert = pg_insert if dialect == "postgresql" else sqlite_insert
    statement = (
        insert(UserDeviceToken)
        .values(
            id=uuid4(),
            user_id=user_id,
            device_token=token,
            platform=platform,
            failure_count=0,
            is_active=True,
            last_seen_at=now,
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=[UserDeviceToken.device_token])
        .returning(UserDeviceToken.id)
    )
    if await db.scalar(statement) is not None:
        return "created"
    row = await db.scalar(
        select(UserDeviceToken)
        .where(UserDeviceToken.device_token == token)
        .with_for_update(of=UserDeviceToken)
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise ValueError("Device registration changed")
    observed = device_revisions([row])[token]
    reset = observed.user_id != user_id or not bool(row.is_active)
    now = _next_revision(await _device_now(db), observed.last_seen_at)
    await db.execute(
        update(UserDeviceToken)
        .where(UserDeviceToken.id == observed.id)
        .values(
            user_id=user_id,
            platform=platform,
            last_seen_at=now,
            is_active=True,
            failure_count=0 if reset else UserDeviceToken.failure_count,
        )
        .execution_options(synchronize_session="fetch")
    )
    return "updated"


async def unregister_device_token(db: AsyncSession, user_id: UUID, token: str) -> None:
    """Idempotent owner-scoped deactivation; never disclose other ownership."""
    row = await db.scalar(
        select(UserDeviceToken)
        .where(
            UserDeviceToken.device_token == token, UserDeviceToken.user_id == user_id
        )
        .with_for_update(of=UserDeviceToken)
        .execution_options(populate_existing=True)
    )
    if row is None or not bool(row.is_active):
        return
    observed = device_revisions([row])[token]
    now = _next_revision(await _device_now(db), observed.last_seen_at)
    await db.execute(
        update(UserDeviceToken)
        .where(UserDeviceToken.id == observed.id)
        .values(is_active=False, last_seen_at=now)
        .execution_options(synchronize_session="fetch")
    )
