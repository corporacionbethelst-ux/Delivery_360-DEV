"""Local SLA evidence only; no final SLA/payment mutation or external delivery."""

from datetime import datetime, timezone
from uuid import UUID
from celery import shared_task
from app.core.config import settings
from app.services.worker_jobs import WorkerJobs
from app.workers.runtime import worker_session, execute_task, disabled


async def run_monitor(delivery_id: UUID | None = None):
    async with worker_session() as db:
        return await WorkerJobs(db).monitor_sla(
            datetime.now(timezone.utc).replace(tzinfo=None), delivery_id=delivery_id
        )


@shared_task(
    bind=True, max_retries=3, name="app.workers.sla_monitor_worker.check_sla_breaches"
)
def check_sla_breaches(self):
    if not settings.WORKER_SLA_MONITOR_ENABLED:
        return disabled()
    return execute_task(self, run_monitor)


_check_sla = run_monitor
