"""
Delivery360 - Productivity Service
Productivity metrics, SLA calculation, performance rankings
"""

from datetime import datetime
from typing import List, Dict, TypedDict
from uuid import UUID
from app.core.shift_rules import utc_naive
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func
from app.models.delivery import Delivery, DeliveryStatus
from app.models.shift import Shift, ShiftStatus
from app.models.rider import Rider
from sqlalchemy import select
from fastapi import HTTPException


class RiderProductivityData(TypedDict):
    """Tipo de retorno para productividad de repartidor"""

    rider_id: UUID
    period: Dict[str, datetime]
    total_deliveries: int
    on_time_deliveries: int
    sla_percentage: float
    avg_delivery_time_minutes: float
    deliveries_per_hour: float
    total_hours_worked: float


class ShiftProductivityData(TypedDict):
    """Tipo de retorno para productividad de turno"""

    shift_id: UUID
    rider_id: UUID
    start_time: datetime
    end_time: datetime
    total_deliveries: int
    duration_hours: float
    deliveries_per_hour: float


class PerformanceRankingItem(TypedDict):
    """Tipo para item de ranking de rendimiento"""

    rank: int
    rider_id: UUID
    user_id: UUID
    total_deliveries: int
    avg_delivery_time_minutes: float


class SLAComplianceReport(TypedDict):
    """Tipo para reporte de cumplimiento de SLA"""

    period: Dict[str, datetime]
    total_deliveries: int
    met_sla_count: int
    missed_sla_count: int
    sla_percentage: float
    compliance_level: str


class ProductivityService:
    """Service for calculating productivity metrics and SLA"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def calculate_rider_productivity(
        self, rider_id: UUID, start_date: datetime, end_date: datetime
    ) -> RiderProductivityData:
        start_date, end_date = utc_naive(start_date), utc_naive(end_date)
        if end_date < start_date:
            raise HTTPException(status_code=422, detail="Rango de fechas inválido")
        deliveries = await self.db.stream(
            select(Delivery.started_at, Delivery.completed_at, Delivery.sla_compliant)
            .where(
                Delivery.rider_id == rider_id,
                Delivery.status == DeliveryStatus.COMPLETADA,
                Delivery.completed_at >= start_date,
                Delivery.completed_at <= end_date,
            )
            .execution_options(yield_per=500)
        )
        total_deliveries = on_time_deliveries = valid_durations = 0
        duration_minutes = 0.0
        try:
            async for begin, end, sla in deliveries:
                total_deliveries += 1
                on_time_deliveries += sla is True
                if begin is not None and end is not None and end >= begin:
                    valid_durations += 1
                    duration_minutes += (end - begin).total_seconds() / 60
        finally:
            await deliveries.close()
        marks = await self.db.stream(
            select(Shift.check_in_at, Shift.check_out_at)
            .where(
                Shift.rider_id == rider_id,
                Shift.status == ShiftStatus.COMPLETADO,
                Shift.check_out_at >= start_date,
                Shift.check_out_at <= end_date,
            )
            .execution_options(yield_per=500)
        )
        total_hours = 0.0
        try:
            async for begin, end in marks:
                if begin is not None and end is not None and end >= begin:
                    total_hours += (end - begin).total_seconds() / 3600
        finally:
            await marks.close()
        return {
            "rider_id": rider_id,
            "period": {"start": start_date, "end": end_date},
            "total_deliveries": total_deliveries,
            "on_time_deliveries": on_time_deliveries,
            "sla_percentage": (
                round(on_time_deliveries / total_deliveries * 100, 2)
                if total_deliveries
                else 0.0
            ),
            "avg_delivery_time_minutes": (
                round(duration_minutes / valid_durations, 2) if valid_durations else 0.0
            ),
            "deliveries_per_hour": (
                round(total_deliveries / total_hours, 2) if total_hours > 0 else 0.0
            ),
            "total_hours_worked": round(total_hours, 2),
        }

    async def calculate_shift_productivity(
        self, shift_id: UUID
    ) -> ShiftProductivityData:
        shift = await self.db.get(Shift, shift_id)
        if shift is None:
            raise HTTPException(status_code=404, detail="Shift not found")
        start, end = shift.check_in_at, shift.check_out_at
        if (
            shift.status != ShiftStatus.COMPLETADO
            or start is None
            or end is None
            or end < start
        ):
            raise HTTPException(
                status_code=409,
                detail="Se requieren marcas reales de un turno finalizado",
            )
        total_deliveries = (
            await self.db.scalar(
                select(func.count(Delivery.id)).where(
                    Delivery.rider_id == shift.rider_id,
                    Delivery.started_at >= start,
                    Delivery.completed_at <= end,
                    Delivery.status == DeliveryStatus.COMPLETADA,
                )
            )
            or 0
        )
        duration_hours = (end - start).total_seconds() / 3600
        return {
            "shift_id": shift_id,
            "rider_id": shift.rider_id,
            "start_time": start,
            "end_time": end,
            "total_deliveries": total_deliveries,
            "duration_hours": round(duration_hours, 2),
            "deliveries_per_hour": (
                round(total_deliveries / duration_hours, 2)
                if duration_hours > 0
                else 0.0
            ),
        }

    async def get_performance_ranking(
        self, start_date: datetime, end_date: datetime, limit: int = 10
    ) -> List[PerformanceRankingItem]:
        """Get top performing riders in a period"""

        # Query riders with their metrics
        result = await self.db.execute(
            select(
                Rider.id,
                Rider.user_id,
                func.count(Delivery.id).label("total_deliveries"),
                func.avg(Delivery.completed_at - Delivery.started_at).label("avg_time"),
            )
            .join(Delivery, Delivery.rider_id == Rider.id)
            .where(
                Delivery.status == DeliveryStatus.COMPLETADA,
                Delivery.completed_at >= start_date,
                Delivery.completed_at <= end_date,
            )
            .group_by(Rider.id, Rider.user_id)
            .order_by(func.count(Delivery.id).desc())
            .limit(limit)
        )

        rankings: List[PerformanceRankingItem] = []
        for row in result.fetchall():
            rankings.append(
                {
                    "rank": len(rankings) + 1,
                    "rider_id": row.id,
                    "user_id": row.user_id,
                    "total_deliveries": row.total_deliveries,
                    "avg_delivery_time_minutes": (
                        round(row.avg_time.total_seconds() / 60, 2)
                        if row.avg_time
                        else 0
                    ),
                }
            )

        return rankings

    async def get_sla_compliance_report(
        self, start_date: datetime, end_date: datetime
    ) -> SLAComplianceReport:
        """Get SLA compliance report for a period"""

        # Total deliveries
        total_result = await self.db.execute(
            select(func.count(Delivery.id)).where(
                Delivery.status == DeliveryStatus.COMPLETADA,
                Delivery.completed_at >= start_date,
                Delivery.completed_at <= end_date,
            )
        )
        total_deliveries = total_result.scalar() or 0

        # Met SLA - using Delivery.sla_compliant
        met_sla_result = await self.db.execute(
            select(func.count(Delivery.id)).where(
                Delivery.status == DeliveryStatus.COMPLETADA,
                Delivery.sla_compliant.is_(True),
                Delivery.completed_at >= start_date,
                Delivery.completed_at <= end_date,
            )
        )
        met_sla_count = met_sla_result.scalar() or 0

        # SLA percentage
        sla_percentage = (
            (met_sla_count / total_deliveries * 100) if total_deliveries > 0 else 0
        )

        return {
            "period": {"start": start_date, "end": end_date},
            "total_deliveries": total_deliveries,
            "met_sla_count": met_sla_count,
            "missed_sla_count": total_deliveries - met_sla_count,
            "sla_percentage": round(sla_percentage, 2),
            "compliance_level": (
                "Excellent"
                if sla_percentage >= 95
                else "Good" if sla_percentage >= 85 else "Needs Improvement"
            ),
        }
