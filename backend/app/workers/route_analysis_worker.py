"""Manual Celery route analysis, with an async engine scoped to each invocation."""

import asyncio
from uuid import UUID
from celery import shared_task
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from app.core.database import db_url
from app.services.route_service import RouteService


async def run_analysis(delivery_id: UUID) -> dict[str, object]:
    engine = create_async_engine(db_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            return await RouteService(db).analyze_route(delivery_id)
    finally:
        await engine.dispose()


@shared_task(bind=True, max_retries=3)
def analyze_route_deviations(self, delivery_id: str):
    try:
        identifier = UUID(delivery_id)
    except (ValueError, TypeError, AttributeError):
        return {"success": False, "reason": "Invalid delivery UUID"}
    try:
        return asyncio.run(run_analysis(identifier))
    except ValueError:
        return {"success": False, "reason": "Route requires manual review"}
    except Exception:
        pass
    # retry() raises internally: leave the exception handler before invoking it.
    raise self.retry(
        exc=RuntimeError("Route analysis unavailable"), countdown=60
    ) from None
