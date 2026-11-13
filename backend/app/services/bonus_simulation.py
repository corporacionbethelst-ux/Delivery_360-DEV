"""Read-only, flat-bonus counterfactual over one bounded historical snapshot."""

from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.delivery import Delivery, DeliveryStatus

CENT = Decimal("0.01")
MAX_BONUS = Decimal("99999999.99")


async def historical_bonus_scenario(
    db: AsyncSession, proposed: Decimal, days: int, end: datetime
) -> dict[str, Any]:
    """Replace completed-delivery bonuses with a uniform amount; keep failed ones."""
    start = end - timedelta(days=days)
    terminal_at = func.coalesce(Delivery.completed_at, Delivery.bonus_snapshot_date)
    window = and_(terminal_at >= start, terminal_at < end)
    completed = Delivery.status == DeliveryStatus.COMPLETADA
    failed = and_(
        Delivery.status == DeliveryStatus.FALLIDA,
        Delivery.locked_bonus_type == "FAILED_ATTEMPT",
    )
    successful = and_(completed, Delivery.locked_bonus_type == "SUCCESS")
    undated = and_(or_(completed, failed), terminal_at.is_(None))
    invalid = or_(
        and_(
            completed,
            or_(
                Delivery.locked_bonus_type.is_(None),
                Delivery.locked_bonus_type != "SUCCESS",
            ),
        ),
        and_(
            Delivery.status == DeliveryStatus.FALLIDA,
            Delivery.locked_bonus_type == "SUCCESS",
        ),
        and_(
            or_(successful, failed),
            or_(
                Delivery.locked_bonus_amount.is_(None),
                Delivery.locked_bonus_amount < 0,
            ),
        ),
    )
    # A single statement gives all counts and sums the same PostgreSQL snapshot.
    statement = select(
        func.count(Delivery.id).filter(and_(window, successful)).label("completed"),
        func.count(Delivery.id).filter(and_(window, failed)).label("failed"),
        func.sum(Delivery.locked_bonus_amount)
        .filter(and_(window, successful))
        .label("success_amount"),
        func.sum(Delivery.locked_bonus_amount)
        .filter(and_(window, failed))
        .label("failed_amount"),
        func.count(Delivery.id).filter(and_(window, invalid)).label("invalid"),
        func.count(Delivery.id).filter(undated).label("undated"),
    ).where(or_(window, undated))
    row = (await db.execute(statement)).one()
    if row.invalid:
        raise ValueError("El histórico contiene entregas sin un bono congelado válido.")
    recorded_success = Decimal(
        str(row.success_amount if row.success_amount is not None else 0)
    )
    recorded_failed = Decimal(
        str(row.failed_amount if row.failed_amount is not None else 0)
    )
    if any(
        not amount.is_finite() or amount < 0
        for amount in (recorded_success, recorded_failed)
    ):
        raise ValueError("El histórico contiene importes de bono no válidos.")
    applied = proposed.quantize(CENT, rounding=ROUND_HALF_UP)
    recorded = recorded_success + recorded_failed
    scenario = applied * row.completed + recorded_failed
    difference = scenario - recorded
    percentage = (
        ((difference / recorded) * 100).quantize(CENT, rounding=ROUND_HALF_UP)
        if recorded
        else None
    )
    return {
        "comparison_basis": "flat_bonus_same_deliveries",
        "history_days": days,
        "period_start": start.isoformat() + "Z",
        "period_end": end.isoformat() + "Z",
        "completed_deliveries": row.completed,
        "failed_bonus_deliveries": row.failed,
        "undated_bonus_deliveries": row.undated,
        "recorded_completed_bonus": float(recorded_success),
        "recorded_failed_bonus": float(recorded_failed),
        "historical_cost": float(recorded),
        "scenario_cost": float(scenario),
        "applied_bonus": float(applied),
        "difference": float(difference),
        "percentage_change": float(percentage) if percentage is not None else None,
        # Keep old wire fields as aliases of this period, never monthly projections.
        "current_monthly_cost": float(recorded),
        "projected_monthly_cost": float(scenario),
        "percentage_increase": float(percentage) if percentage is not None else 0,
        "currency": None,
        "message": "Escenario de bono uniforme sobre las mismas entregas históricas; no es una proyección mensual ni confirma pagos.",
    }
