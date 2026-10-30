"""Read-only operational metrics with explicit cohorts and truthful missing data."""

from datetime import datetime, timedelta, date as CalendarDate, timezone
from uuid import UUID
from zoneinfo import ZoneInfo
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.reporting_period import (
    ReportingWindow,
    calendar_window,
    explicit_window,
    aware_utc,
    utc_naive,
)
from app.core.config import settings
from app.models.order import Order, OrderStatus
from app.models.delivery import Delivery, DeliveryStatus
from app.models.rider import Rider, RiderStatus
from app.models.user import User
from app.models.shift import Shift, ShiftStatus
from app.models.notification import Alert
from app.models.productivity import ProductivityMetrics
from app.schemas.operational_dashboard import (
    DashboardSnapshot,
    DashboardSummary,
    DailyActivity,
    PendingOrderPreview,
    RiderPositionPreview,
)

ACTIVE_DELIVERIES = (
    DeliveryStatus.INICIADA,
    DeliveryStatus.EN_PICKUP,
    DeliveryStatus.EN_ROUTE,
    DeliveryStatus.EN_DESTINO,
)
ACTIVE_ORDERS = (
    OrderStatus.ASIGNADO,
    OrderStatus.EN_RECOLECCION,
    OrderStatus.RECOLECTADO,
    OrderStatus.EN_RUTA,
)


def local_date(column, zone: str):
    # Columns persist UTC WITHOUT TIME ZONE. Convert UTC->timestamptz->local.
    return func.date(func.timezone(zone, func.timezone("UTC", column)))


class DashboardService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def snapshot(
        self, days: int = 7, *, operator: bool = False, now: datetime | None = None
    ) -> DashboardSnapshot:
        return await self._snapshot(calendar_window(days, now), operator=operator)

    async def _snapshot(
        self, window: ReportingWindow, *, operator: bool = False
    ) -> DashboardSnapshot:
        start, end = window.start, window.end
        orders = (
            await self.db.execute(
                select(
                    func.count(Order.id).label("total"),
                    func.sum(
                        case((Order.status == OrderStatus.ENTREGADO, 1), else_=0)
                    ).label("legacy_delivered"),
                    func.sum(
                        case((Order.status == OrderStatus.CANCELADO, 1), else_=0)
                    ).label("cancelled"),
                ).where(Order.created_at >= start, Order.created_at < end)
            )
        ).one()
        valid_duration = (Delivery.started_at.is_not(None)) & (
            Delivery.completed_at >= Delivery.started_at
        )
        duration = (
            func.extract("epoch", Delivery.completed_at - Delivery.started_at) / 60
        )
        deliveries = (
            await self.db.execute(
                select(
                    func.count(Delivery.id).label("total"),
                    func.sum(
                        case((Delivery.sla_compliant.is_(True), 1), else_=0)
                    ).label("on_time"),
                    func.sum(
                        case((Delivery.sla_compliant.is_not(None), 1), else_=0)
                    ).label("known"),
                    func.sum(case((valid_duration, 1), else_=0)).label(
                        "valid_durations"
                    ),
                    func.avg(case((valid_duration, duration), else_=None)).label(
                        "average"
                    ),
                ).where(
                    Delivery.status == DeliveryStatus.COMPLETADA,
                    Delivery.completed_at >= start,
                    Delivery.completed_at < end,
                )
            )
        ).one()
        online = (
            (Rider.is_online.is_(True))
            & (Rider.status.in_((RiderStatus.ACTIVO, RiderStatus.OCUPADO)))
            & (User.is_active.is_(True))
        )

        def count_query(model, *conditions):
            return (
                select(func.count())
                .select_from(model)
                .where(*conditions)
                .scalar_subquery()
            )

        globals_ = (
            await self.db.execute(
                select(
                    count_query(Order, Order.status == OrderStatus.PENDIENTE).label(
                        "pending"
                    ),
                    count_query(Order, Order.status.in_(ACTIVE_ORDERS)).label(
                        "in_progress"
                    ),
                    count_query(Delivery, Delivery.status.in_(ACTIVE_DELIVERIES)).label(
                        "active_deliveries"
                    ),
                    select(func.count(Rider.id))
                    .join(User, User.id == Rider.user_id)
                    .where(online)
                    .scalar_subquery()
                    .label("online"),
                    select(func.count(Rider.id))
                    .join(User, User.id == Rider.user_id)
                    .where(online, Rider.status == RiderStatus.ACTIVO)
                    .scalar_subquery()
                    .label("available"),
                    count_query(
                        Shift,
                        Shift.status == ShiftStatus.EN_CURSO,
                        Shift.check_in_at.is_not(None),
                        Shift.check_out_at.is_(None),
                    ).label("shifts"),
                    count_query(
                        Alert, Alert.status.in_(("OPEN", "ACKNOWLEDGED"))
                    ).label("alerts"),
                    count_query(User, User.is_active.is_(True)).label("users"),
                )
            )
        ).one()
        complete = int(deliveries.total)
        known = int(deliveries.known or 0)
        summary = DashboardSummary(
            orders_created=orders.total,
            cancelled_orders=orders.cancelled or 0,
            completed_deliveries=complete,
            pending_orders=globals_.pending,
            in_progress_orders=globals_.in_progress,
            active_deliveries=globals_.active_deliveries,
            riders_online=globals_.online,
            available_riders=globals_.available,
            active_shifts=globals_.shifts,
            open_alerts=globals_.alerts,
            active_users=globals_.users,
            avg_delivery_minutes=(
                float(deliveries.average) if deliveries.average is not None else None
            ),
            valid_duration_count=int(deliveries.valid_durations or 0),
            sla_percent=(
                round(int(deliveries.on_time or 0) / known * 100, 2) if known else None
            ),
            sla_known_count=known,
            sla_unknown_count=complete - known,
        )
        grouped_orders = (
            await self.db.execute(
                select(
                    local_date(Order.created_at, window.zone).label("day"),
                    func.count(Order.id),
                )
                .where(Order.created_at >= start, Order.created_at < end)
                .group_by("day")
            )
        ).all()
        grouped_deliveries = (
            await self.db.execute(
                select(
                    local_date(Delivery.completed_at, window.zone).label("day"),
                    func.count(Delivery.id),
                )
                .where(
                    Delivery.status == DeliveryStatus.COMPLETADA,
                    Delivery.completed_at >= start,
                    Delivery.completed_at < end,
                )
                .group_by("day")
            )
        ).all()
        by_orders = {row[0]: row[1] for row in grouped_orders}
        by_deliveries = {row[0]: row[1] for row in grouped_deliveries}
        snapshot = DashboardSnapshot(
            summary=summary,
            series=[
                DailyActivity(
                    date=day,
                    orders_created=by_orders.get(day, 0),
                    completed_deliveries=by_deliveries.get(day, 0),
                )
                for day in window.dates
            ],
            period_start=aware_utc(start),
            period_end=aware_utc(end),
            timezone=window.zone,
            generated_at=aware_utc(end),
            orders_today=summary.orders_created if len(window.dates) == 1 else None,
            delivered_today=(
                int(orders.legacy_delivered or 0) if len(window.dates) == 1 else None
            ),
            sla_compliance_pct=summary.sla_percent if len(window.dates) == 1 else None,
            sla_breached=(
                (known - int(deliveries.on_time or 0))
                if len(window.dates) == 1
                else None
            ),
            active_riders=summary.riders_online,
            avg_delivery_time_min=summary.avg_delivery_minutes,
        )
        if operator:
            queue = (
                await self.db.execute(
                    select(
                        Order.id,
                        Order.external_id,
                        Order.status,
                        Order.delivery_address,
                        Order.priority,
                    )
                    .where(
                        Order.status.in_((OrderStatus.PENDIENTE, OrderStatus.ASIGNADO))
                    )
                    .order_by(Order.created_at, Order.id)
                    .limit(21)
                )
            ).all()
            snapshot.pending_orders = [
                PendingOrderPreview(
                    id=r.id,
                    number=r.external_id,
                    status=r.status.value if r.status else None,
                    address=r.delivery_address,
                    priority=r.priority.value if r.priority else None,
                )
                for r in queue[:20]
            ]
            snapshot.queue_truncated = len(queue) > 20
            positions = (
                await self.db.execute(
                    select(
                        Rider.id, Rider.last_lat, Rider.last_lng, Rider.last_location_at
                    )
                    .join(User, User.id == Rider.user_id)
                    .where(
                        online,
                        Rider.last_lat >= -90,
                        Rider.last_lat <= 90,
                        Rider.last_lng >= -180,
                        Rider.last_lng <= 180,
                        Rider.last_location_at >= end - timedelta(minutes=5),
                        Rider.last_location_at <= end,
                    )
                    .order_by(Rider.last_location_at.desc(), Rider.id)
                    .limit(51)
                )
            ).all()
            snapshot.riders_online = [
                RiderPositionPreview(
                    id=r.id,
                    lat=r.last_lat,
                    lng=r.last_lng,
                    recorded_at=aware_utc(r.last_location_at),
                )
                for r in positions[:50]
            ]
            snapshot.positions_truncated = len(positions) > 50
        return snapshot

    async def get_manager_dashboard(
        self, start_date: datetime, end_date: datetime
    ) -> dict[str, object]:
        data = await self._snapshot(explicit_window(start_date, end_date))
        return {
            "total_orders": data.summary.orders_created,
            "delivered_orders": data.summary.completed_deliveries,
            "delivery_rate": None,
            "avg_delivery_time_minutes": data.summary.avg_delivery_minutes,
            "sla_percentage": data.summary.sla_percent,
            "avg_cost_per_order": None,
            "active_riders": data.summary.riders_online,
            "period_start": data.period_start,
            "period_end": data.period_end,
        }

    async def get_operator_dashboard(
        self, shift_id: UUID | None = None
    ) -> dict[str, object]:
        data = await self.snapshot(1, operator=True)
        now = utc_naive(data.generated_at)
        at_risk = await self.db.scalar(
            select(func.count(Delivery.id)).where(
                Delivery.status.in_(ACTIVE_DELIVERIES),
                Delivery.started_at.is_not(None),
                Delivery.started_at <= now,
                Delivery.sla_expected_minutes > 0,
                func.extract("epoch", now - Delivery.started_at) / 60
                >= Delivery.sla_expected_minutes - 15,
            )
        )
        count = data.summary.active_shifts
        if shift_id is not None:
            count = (
                await self.db.scalar(
                    select(func.count(Shift.id)).where(
                        Shift.id == shift_id,
                        Shift.status == ShiftStatus.EN_CURSO,
                        Shift.check_in_at.is_not(None),
                        Shift.check_out_at.is_(None),
                    )
                )
                or 0
            )
        return {
            "pending_orders": data.summary.pending_orders,
            "in_progress_orders": data.summary.in_progress_orders,
            "available_riders": data.summary.available_riders,
            "active_shifts": count,
            "at_risk_deliveries": at_risk or 0,
            "timestamp": data.generated_at,
        }

    async def get_rider_dashboard(
        self, rider_id: UUID, date: CalendarDate | datetime | None = None
    ) -> dict[str, object]:
        from app.services.productivity_service import ProductivityService
        from app.workers.runtime import period

        day = (
            date.date()
            if isinstance(date, datetime)
            else date or datetime.now(ZoneInfo(settings.CELERY_TIMEZONE)).date()
        )
        start, end = period(day)
        # Legacy helper uses inclusive endpoints; retain its contract without including next midnight.
        result = await ProductivityService(self.db).calculate_rider_productivity(
            rider_id, start, end - timedelta(microseconds=1)
        )
        return {
            "completed_deliveries": result["total_deliveries"],
            "daily_earnings": None,
            "total_hours_worked": result["total_hours_worked"],
            "personal_sla_percentage": result["sla_percentage"],
            "date": day,
            "timestamp": aware_utc(datetime.now(timezone.utc)),
        }

    async def get_productivity_comparison(
        self, start_date: datetime, end_date: datetime, group_by: str = "day"
    ) -> list[dict[str, object]]:
        if group_by != "day":
            raise ValueError("Solo se admite agrupación por día")
        window = explicit_window(start_date, end_date)
        rows = list(
            (
                await self.db.scalars(
                    select(ProductivityMetrics)
                    .where(
                        ProductivityMetrics.shift_id.is_(None),
                        ProductivityMetrics.period_start >= window.start,
                        ProductivityMetrics.period_end <= window.end,
                    )
                    .limit(10001)
                )
            ).all()
        )
        if len(rows) > 10000:
            raise ValueError("El período requiere consulta por lotes")
        groups: dict[CalendarDate, list[ProductivityMetrics]] = {}
        seen = set()
        for row in rows:
            key = (row.rider_id, row.period_start, row.period_end)
            if key in seen:
                raise ValueError("Métricas históricas duplicadas requieren revisión")
            seen.add(key)
            day = aware_utc(row.period_start).astimezone(ZoneInfo(window.zone)).date()
            groups.setdefault(day, []).append(row)
        result: list[dict[str, object]] = []
        for day, items in sorted(groups.items()):
            total = sum(r.total_deliveries or 0 for r in items)
            on_time = sum(r.on_time_deliveries or 0 for r in items)
            known = sum(
                (r.on_time_deliveries or 0) + (r.late_deliveries or 0) for r in items
            )
            if not 0 <= on_time <= known <= total:
                raise ValueError("Conteos históricos incoherentes")
            result.append(
                {
                    "date": day,
                    "avg_deliveries_per_hour": None,
                    "avg_sla_compliance": on_time / known * 100 if known else None,
                    "total_deliveries": total,
                }
            )
        return result
