"""Closed-day productivity, disabled until explicitly enabled."""

from uuid import UUID
from celery import shared_task
from app.core.config import settings
from app.services.worker_jobs import WorkerJobs
from app.workers.runtime import closed_day, worker_session, execute_task, disabled


async def run_rider(rider_id: str, date: str):
    day = closed_day(date)
    if not isinstance(rider_id, str):
        raise ValueError("Invalid rider UUID")
    identifier = UUID(rider_id)
    async with worker_session() as db:
        return await WorkerJobs(db).rider_metrics(identifier, day)


async def run_daily(date: str | None = None):
    day = closed_day(date)
    async with worker_session() as db:
        riders = await WorkerJobs(db).daily_riders(day)
        results = []
        for rider in riders:
            results.append(await WorkerJobs(db).rider_metrics(rider, day))
        return {
            "success": True,
            "date": day.isoformat(),
            "riders_processed": len(results),
        }


@shared_task(
    bind=True,
    max_retries=3,
    name="app.workers.productivity_worker.calculate_rider_productivity",
)
def calculate_rider_productivity(self, rider_id: str, date: str):
    if not settings.WORKER_PRODUCTIVITY_ENABLED:
        return disabled()
    return execute_task(self, lambda: run_rider(rider_id, date))


@shared_task(
    bind=True,
    max_retries=3,
    name="app.workers.productivity_worker.calculate_daily_productivity",
)
def calculate_daily_productivity(self, date: str | None = None):
    if not settings.WORKER_PRODUCTIVITY_ENABLED:
        return disabled()
    return execute_task(self, lambda: run_daily(date))
