"""Re-evaluate a persisted SLA instead of inventing an unaddressed alert."""

from uuid import UUID
from celery import shared_task
from app.core.config import settings
from app.workers.sla_monitor_worker import run_monitor
from app.workers.runtime import execute_task, disabled


@shared_task(bind=True, max_retries=3)
def generate_operational_alert(self, alert_type: str, severity: str, details: dict):
    if not settings.WORKER_SLA_MONITOR_ENABLED:
        return disabled()
    if (
        not isinstance(severity, str)
        or alert_type not in ("sla_warning", "SLA_BREACH")
        or severity.lower() != "high"
        or not isinstance(details, dict)
    ):
        return {"success": False, "reason": "unsupported_alert_request"}
    try:
        identifier = UUID(str(details.get("delivery_id")))
    except (ValueError, TypeError, AttributeError):
        return {"success": False, "reason": "invalid_delivery_uuid"}
    return execute_task(self, lambda: run_monitor(identifier))
