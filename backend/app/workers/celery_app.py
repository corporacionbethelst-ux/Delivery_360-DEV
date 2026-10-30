"""Canonical Celery registry and explicit, non-financial scheduling allowlist."""

from celery import Celery
from celery.schedules import crontab
from app.core.config import settings

WORKER_MODULES = (
    "app.workers.sla_monitor_worker",
    "app.workers.liquidation_worker",
    "app.workers.productivity_worker",
    "app.workers.notification_worker",
    "app.workers.cleanup_worker",
    "app.workers.route_analysis_worker",
    "app.workers.alert_worker",
    "app.workers.report_worker",
)


def build_beat_schedule():
    if not settings.CELERY_BEAT_ENABLED:
        return {}
    schedule = {}
    if settings.WORKER_SLA_MONITOR_ENABLED:
        schedule["check-sla-every-5-min"] = {
            "task": "app.workers.sla_monitor_worker.check_sla_breaches",
            "schedule": crontab(minute="*/5"),
        }
    if settings.WORKER_PRODUCTIVITY_ENABLED:
        schedule["daily-productivity"] = {
            "task": "app.workers.productivity_worker.calculate_daily_productivity",
            "schedule": crontab(hour=1, minute=0),
        }
    return schedule


celery_app = Celery(
    "delivery360",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=list(WORKER_MODULES),
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone=settings.CELERY_TIMEZONE,
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    beat_schedule=build_beat_schedule(),
)
