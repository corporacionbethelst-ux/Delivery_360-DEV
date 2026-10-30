"""Per-invocation async DB resources; no engine pooled across Celery event loops."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from app.core.config import settings
from app.core.database import db_url


@asynccontextmanager
async def worker_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(db_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            try:
                yield db
            except BaseException:
                await db.rollback()
                raise
    finally:
        await engine.dispose()


def period(day: date) -> tuple[datetime, datetime]:
    zone = ZoneInfo(settings.CELERY_TIMEZONE)
    start = datetime.combine(day, time(), zone)
    end = datetime.combine(day + timedelta(days=1), time(), zone)
    return (
        start.astimezone(timezone.utc).replace(tzinfo=None),
        end.astimezone(timezone.utc).replace(tzinfo=None),
    )


def closed_day(value: str | None, now: datetime | None = None) -> date:
    today = (
        (now or datetime.now(timezone.utc))
        .astimezone(ZoneInfo(settings.CELERY_TIMEZONE))
        .date()
    )
    if value is None:
        return today - timedelta(days=1)
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError("Invalid calendar day")
    day = date.fromisoformat(value)
    if day.isoformat() != value or day >= today or day == date.min:
        raise ValueError("A closed calendar day is required")
    return day


def execute_task(
    task, operation: Callable[[], Awaitable[dict[str, object]]]
) -> dict[str, object]:
    async def invoke() -> dict[str, object]:
        return await operation()

    try:
        return asyncio.run(invoke())
    except ValueError:
        return {"success": False, "reason": "manual_review_required"}
    except Exception:
        pass
    # Celery.retry raises itself. Call after leaving the handler so the original
    # exception cannot become the context of the retry or final failure traceback.
    raise task.retry(
        exc=RuntimeError("Worker operation unavailable"), countdown=60
    ) from None


def disabled() -> dict[str, object]:
    return {"success": False, "reason": "worker_disabled"}
