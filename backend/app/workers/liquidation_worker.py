"""Keep legacy entry points without inventing payments or paid states."""

from celery import shared_task
from app.workers.productivity_worker import (
    calculate_daily_productivity,
    run_daily as _calc_productivity,
)


@shared_task(name="app.workers.liquidation_worker.run_daily_liquidation")
def run_daily_liquidation():
    return {
        "success": False,
        "reason": "verified_settlement_required",
        "paid_records": 0,
    }


async def _liquidate():
    return run_daily_liquidation.run()
