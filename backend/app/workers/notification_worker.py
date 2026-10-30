"""Persisted retry dispatch only; legacy untracked sends never report success."""

from celery import shared_task
from app.core.config import settings
from app.services.omnichannel_service import OmnichannelNotificationService
from app.workers.runtime import worker_session, execute_task, disabled


async def run_retries(batch_size: int = 50):
    if type(batch_size) is not int or not 1 <= batch_size <= 100:
        raise ValueError("Invalid batch size")
    async with worker_session() as db:
        count = await OmnichannelNotificationService(db).process_retry_queue(batch_size)
        return {
            "success": True,
            "processed_logs": count,
            "provider_acceptance_not_delivery": True,
        }


@shared_task(bind=True, max_retries=3)
def process_notification_retries(self, batch_size: int = 50):
    if not settings.WORKER_NOTIFICATION_RETRY_ENABLED:
        return disabled()
    return execute_task(self, lambda: run_retries(batch_size))


@shared_task
def send_push_notification(
    user_id: str, title: str, message: str, data: dict | None = None
):
    return {"success": False, "reason": "persisted_notification_required"}


@shared_task
def send_email_notification(email: str, subject: str, body: str):
    return {"success": False, "reason": "persisted_notification_required"}


@shared_task
def send_sms_notification(phone: str, message: str):
    return {"success": False, "reason": "persisted_notification_required"}
