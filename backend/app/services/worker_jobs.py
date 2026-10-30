"""Bounded operational jobs; no payment, destructive retention or external delivery."""

import math
from datetime import date, datetime
from uuid import UUID, uuid4
from sqlalchemy import exists, func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.models.delivery import Delivery, DeliveryStatus
from app.models.order import Order
from app.models.rider import Rider
from app.models.user import User, UserRole
from app.models.notification import (
    Alert,
    NotificationLog,
    NotificationChannel,
    OmnichannelStatus,
    NotificationPreference,
)
from app.models.productivity import ProductivityMetrics
from app.workers.runtime import period


class WorkerJobs:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def rider_metrics(self, rider_id: UUID, day: date) -> dict[str, object]:
        start, end = period(day)
        try:
            if (
                await self.db.scalar(
                    select(Rider.id).where(Rider.id == rider_id).with_for_update()
                )
                is None
            ):
                raise ValueError("Rider not found")
            rows = list(
                (
                    await self.db.execute(
                        select(
                            Delivery.started_at,
                            Delivery.completed_at,
                            Delivery.sla_compliant,
                            Delivery.distance_total,
                        )
                        .where(
                            Delivery.rider_id == rider_id,
                            Delivery.status == DeliveryStatus.COMPLETADA,
                            Delivery.completed_at >= start,
                            Delivery.completed_at < end,
                        )
                        .limit(10001)
                    )
                ).all()
            )
            if len(rows) > 10000:
                raise ValueError("Delivery limit exceeded")
            known_sla = [r.sla_compliant for r in rows if r.sla_compliant is not None]
            durations = [
                (r.completed_at - r.started_at).total_seconds() / 60
                for r in rows
                if r.started_at is not None and r.completed_at >= r.started_at
            ]
            distances = [
                r.distance_total
                for r in rows
                if r.distance_total is not None
                and math.isfinite(r.distance_total)
                and r.distance_total >= 0
            ]
            values = dict(
                total_deliveries=len(rows),
                on_time_deliveries=sum(v is True for v in known_sla),
                late_deliveries=sum(v is False for v in known_sla),
                sla_compliance_rate=(
                    (100 * sum(v is True for v in known_sla) / len(known_sla))
                    if known_sla
                    else None
                ),
                avg_delivery_time_minutes=(
                    sum(durations) / len(durations) if durations else None
                ),
                total_distance_km=(
                    sum(distances) if len(distances) == len(rows) else None
                ),
            )
            existing = list(
                (
                    await self.db.scalars(
                        select(ProductivityMetrics)
                        .where(
                            ProductivityMetrics.rider_id == rider_id,
                            ProductivityMetrics.period_start == start,
                            ProductivityMetrics.period_end == end,
                            ProductivityMetrics.shift_id.is_(None),
                        )
                        .limit(2)
                    )
                ).all()
            )
            if len(existing) > 1:
                raise ValueError("Duplicate historical metrics require review")
            if existing:
                obj = existing[0]
                for name, value in values.items():
                    setattr(obj, name, value)
                metric_id = obj.id
            else:
                metric_id = uuid4()
                await self.db.execute(
                    insert(ProductivityMetrics).values(
                        id=metric_id,
                        rider_id=rider_id,
                        period_start=start,
                        period_end=end,
                        total_earnings=None,
                        customer_rating_avg=None,
                        customer_rating_count=None,
                        **values,
                    )
                )
            await self.db.commit()
            return {
                "success": True,
                "metric_id": str(metric_id),
                "rider_id": str(rider_id),
                "date": day.isoformat(),
                "completed_deliveries": len(rows),
                "unknown_sla_count": len(rows) - len(known_sla),
                "missing_duration_count": len(rows) - len(durations),
                "missing_distance_count": len(rows) - len(distances),
            }
        except BaseException:
            await self.db.rollback()
            raise

    async def daily_riders(self, day: date) -> list[UUID]:
        start, end = period(day)
        riders = list(
            (
                await self.db.scalars(
                    select(Delivery.rider_id)
                    .where(
                        Delivery.status == DeliveryStatus.COMPLETADA,
                        Delivery.completed_at >= start,
                        Delivery.completed_at < end,
                    )
                    .distinct()
                    .order_by(Delivery.rider_id)
                    .limit(1001)
                )
            ).all()
        )
        if len(riders) > 1000:
            raise ValueError("Rider batch requires partitioning")
        return riders

    async def monitor_sla(
        self, now: datetime, batch_size: int = 100, delivery_id: UUID | None = None
    ) -> dict[str, object]:
        if type(batch_size) is not int or not 1 <= batch_size <= 100:
            raise ValueError("Invalid batch size")
        if now.tzinfo is not None:
            raise ValueError("Expected UTC naive clock")
        previous = exists(
            select(Alert.id).where(
                Alert.delivery_id == Delivery.id, Alert.alert_type == "SLA_BREACH"
            )
        )
        query = select(Delivery).where(
            Delivery.status.in_(
                (
                    DeliveryStatus.INICIADA,
                    DeliveryStatus.EN_PICKUP,
                    DeliveryStatus.EN_ROUTE,
                    DeliveryStatus.EN_DESTINO,
                )
            ),
            Delivery.started_at.is_not(None),
            Delivery.sla_expected_minutes > 0,
            Delivery.started_at
            + Delivery.sla_expected_minutes * text("INTERVAL '1 minute'")
            < now,
            ~previous,
        )
        if delivery_id is not None:
            query = query.where(Delivery.id == delivery_id)
        try:
            deliveries = list(
                (
                    await self.db.scalars(
                        query.order_by(Delivery.id)
                        .limit(batch_size)
                        .with_for_update(skip_locked=True, of=Delivery)
                    )
                ).all()
            )
            managers = list(
                (
                    await self.db.scalars(
                        select(User.id)
                        .where(
                            User.is_active.is_(True),
                            User.role.in_((UserRole.GERENTE, UserRole.SUPERADMIN)),
                        )
                        .limit(201)
                    )
                ).all()
            )
            if len(managers) > 200:
                raise ValueError("Recipient limit exceeded")
            created = 0
            for delivery in deliveries:
                # Recheck after locking: another cooperating monitor may have committed while this query waited.
                if (
                    await self.db.scalar(
                        select(Alert.id)
                        .where(
                            Alert.delivery_id == delivery.id,
                            Alert.alert_type == "SLA_BREACH",
                        )
                        .limit(1)
                    )
                    is not None
                ):
                    continue
                owner = await self.db.scalar(
                    select(User.id)
                    .join(Rider, Rider.user_id == User.id)
                    .where(Rider.id == delivery.rider_id, User.is_active.is_(True))
                )
                recipients = set(managers)
                if owner is not None:
                    recipients.add(owner)
                self.db.add(
                    Alert(
                        alert_type="SLA_BREACH",
                        severity="HIGH",
                        title="SLA de entrega excedido",
                        description="La entrega activa superó el plazo configurado.",
                        delivery_id=delivery.id,
                        order_id=delivery.order_id,
                        rider_id=delivery.rider_id,
                        status="OPEN",
                    )
                )
                created += 1
                muted: set[UUID] = set()
                if recipients and settings.NOTIFICATIONS_ENABLED:
                    muted = set(
                        (
                            await self.db.scalars(
                                select(NotificationPreference.user_id).where(
                                    NotificationPreference.user_id.in_(recipients),
                                    NotificationPreference.event_code == "sla_warning",
                                    NotificationPreference.channel
                                    == NotificationChannel.IN_APP,
                                    NotificationPreference.enabled.is_(False),
                                )
                            )
                        ).all()
                    )
                deliverable = (
                    recipients - muted if settings.NOTIFICATIONS_ENABLED else set()
                )
                for user_id in deliverable:
                    self.db.add(
                        NotificationLog(
                            user_id=user_id,
                            delivery_id=delivery.id,
                            channel=NotificationChannel.IN_APP,
                            status=OmnichannelStatus.PENDIENTE,
                            title="SLA de entrega excedido",
                            body="Revisa la entrega asignada y su plazo operativo.",
                            dedupe_key=f"sla:{delivery.id}:{user_id}",
                        )
                    )
            await self.db.commit()
            return {
                "success": True,
                "alerts_created": created,
                "batch_limit": batch_size,
            }
        except BaseException:
            await self.db.rollback()
            raise

    async def operations_report(self, day: date) -> dict[str, object]:
        start, end = period(day)
        orders = (
            await self.db.execute(
                select(Order.status, func.count())
                .where(Order.created_at >= start, Order.created_at < end)
                .group_by(Order.status)
            )
        ).all()
        deliveries = (
            await self.db.execute(
                select(Delivery.status, func.count())
                .where(
                    Delivery.status.in_(
                        (DeliveryStatus.COMPLETADA, DeliveryStatus.FALLIDA)
                    ),
                    Delivery.completed_at >= start,
                    Delivery.completed_at < end,
                )
                .group_by(Delivery.status)
            )
        ).all()
        return {
            "success": True,
            "date": day.isoformat(),
            "period_start_utc": start.isoformat() + "Z",
            "period_end_utc": end.isoformat() + "Z",
            "orders_created_by_status": {
                status.value if status else "UNKNOWN": count for status, count in orders
            },
            "deliveries_closed_by_status": {
                status.value if status else "UNKNOWN": count
                for status, count in deliveries
            },
            "source": "database_snapshot",
            "financial_report": False,
        }
