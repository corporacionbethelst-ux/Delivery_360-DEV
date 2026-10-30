"""Read consolidated daily metrics; volume ranking does not invent performance scores."""

import math
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.auth import get_current_user, require_role
from app.core.database import get_db
from app.core.reporting_period import calendar_window, aware_utc
from app.models.user import User, UserRole
from app.models.delivery import Delivery, DeliveryStatus
from app.models.productivity import ProductivityMetrics
from app.services.tracking_access import authorize_rider_tracking

router = APIRouter()


def finite(value: float | None) -> float | None:
    return value if value is not None and math.isfinite(value) and value >= 0 else None


@router.get("/rider/{rider_id}")
@router.get("/productivity/rider/{rider_id}", include_in_schema=False)
async def rider_productivity(
    rider_id: UUID,
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await authorize_rider_tracking(db, current_user, rider_id)
    rows = (
        await db.execute(
            select(
                ProductivityMetrics,
                func.count()
                .over(
                    partition_by=(
                        ProductivityMetrics.period_start,
                        ProductivityMetrics.period_end,
                    )
                )
                .label("period_count"),
            )
            .where(
                ProductivityMetrics.rider_id == rider_id,
                ProductivityMetrics.shift_id.is_(None),
            )
            .order_by(ProductivityMetrics.period_start.desc(), ProductivityMetrics.id)
            .limit(limit)
        )
    ).all()
    result = []
    for row, period_count in rows:
        # Window aggregation runs before LIMIT: a duplicate cannot disappear
        # just because the caller asks for a single historical result.
        if period_count > 1:
            raise HTTPException(
                status_code=409,
                detail="Métricas históricas duplicadas requieren revisión",
            )
        if row.period_end <= row.period_start:
            raise HTTPException(status_code=409, detail="Período histórico incoherente")
        total, on_time, late = (
            row.total_deliveries,
            row.on_time_deliveries,
            row.late_deliveries,
        )
        if any(value is not None and value < 0 for value in (total, on_time, late)):
            raise HTTPException(
                status_code=409, detail="Conteos históricos incoherentes"
            )
        if (
            total is not None
            and on_time is not None
            and late is not None
            and on_time + late > total
        ):
            raise HTTPException(
                status_code=409, detail="Conteos históricos incoherentes"
            )
        known = on_time + late if on_time is not None and late is not None else None
        rate = (
            round(on_time / known * 100, 2) if on_time is not None and known else None
        )
        result.append(
            {
                "id": str(row.id),
                "rider_id": str(row.rider_id),
                "period_start": aware_utc(row.period_start),
                "period_end": aware_utc(row.period_end),
                "completed_deliveries": total,
                "on_time_deliveries": on_time,
                "late_deliveries": late,
                "unknown_sla_count": (
                    total - known if total is not None and known is not None else None
                ),
                "sla_percent": rate,
                "avg_delivery_minutes": finite(row.avg_delivery_time_minutes),
                "total_distance_km": finite(row.total_distance_km),
                "total_earnings": finite(row.total_earnings),
                "source": "consolidated_metrics",
                "performance_score": None,
            }
        )
    return result


@router.get("/ranking")
@router.get("/productivity/ranking", include_in_schema=False)
async def performance_ranking(
    days: int = Query(7, ge=1, le=31),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.SUPERADMIN, UserRole.GERENTE, UserRole.OPERADOR)
    ),
):
    window = calendar_window(days)
    valid_duration = Delivery.started_at.is_not(None) & (
        Delivery.completed_at >= Delivery.started_at
    )
    rows = (
        await db.execute(
            select(
                Delivery.rider_id,
                func.count().label("total"),
                func.sum(case((Delivery.sla_compliant.is_(True), 1), else_=0)).label(
                    "on_time"
                ),
                func.sum(case((Delivery.sla_compliant.is_not(None), 1), else_=0)).label(
                    "known"
                ),
                func.avg(
                    case(
                        (
                            valid_duration,
                            func.extract(
                                "epoch", Delivery.completed_at - Delivery.started_at
                            )
                            / 60,
                        ),
                        else_=None,
                    )
                ).label("average"),
            )
            .where(
                Delivery.status == DeliveryStatus.COMPLETADA,
                Delivery.completed_at >= window.start,
                Delivery.completed_at < window.end,
            )
            .group_by(Delivery.rider_id)
            .order_by(func.count().desc(), Delivery.rider_id)
            .limit(limit)
        )
    ).all()
    return [
        {
            "rank": index + 1,
            "rider_id": str(row.rider_id),
            "completed_deliveries": row.total,
            "sla_percent": (
                round(row.on_time / row.known * 100, 2) if row.known else None
            ),
            "avg_delivery_minutes": (
                float(row.average) if row.average is not None else None
            ),
            "ranking_basis": "completed_deliveries",
            "performance_score": None,
        }
        for index, row in enumerate(rows)
    ]
