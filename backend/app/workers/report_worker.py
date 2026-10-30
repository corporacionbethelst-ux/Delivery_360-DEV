"""Real read-only operational snapshots; no fabricated financial report/files."""

from celery import shared_task
from app.core.config import settings
from app.services.worker_jobs import WorkerJobs
from app.workers.runtime import closed_day, worker_session, execute_task, disabled


async def run_report(date: str):
    day = closed_day(date)
    async with worker_session() as db:
        return await WorkerJobs(db).operations_report(day)


@shared_task(bind=True, max_retries=3)
def generate_daily_report(self, date: str, report_type: str = "operations"):
    if not settings.WORKER_REPORTS_ENABLED:
        return disabled()
    if report_type != "operations":
        return {"success": False, "reason": "verified_financial_report_required"}
    return execute_task(self, lambda: run_report(date))
