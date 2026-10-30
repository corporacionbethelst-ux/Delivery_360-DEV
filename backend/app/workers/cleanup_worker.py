"""No destructive global retention without a reviewed per-table policy."""

from celery import shared_task


@shared_task(name="app.workers.cleanup_worker.cleanup_old_data")
def cleanup_old_data():
    return {
        "success": False,
        "reason": "reviewed_retention_policy_required",
        "deleted_records": 0,
    }


async def _cleanup():
    return cleanup_old_data.run()
