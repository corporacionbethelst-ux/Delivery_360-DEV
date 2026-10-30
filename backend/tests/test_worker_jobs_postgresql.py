"""Real PostgreSQL metrics, SLA evidence, replay and isolated task sessions."""

import asyncio
from datetime import date, datetime, timedelta
from uuid import uuid4
from unittest.mock import patch
import pytest
from sqlalchemy import select, text, func, update, insert
from app.core.config import settings
from app.models.order import Order, OrderStatus
from app.models.delivery import Delivery, DeliveryStatus
from app.models.productivity import ProductivityMetrics, SLARecord, ProductivityRecord
from app.models.notification import (
    Alert,
    NotificationLog,
    NotificationPreference,
    NotificationChannel,
)
from app.services.worker_jobs import WorkerJobs
from tests.test_route_persistence import routes_db  # noqa: F401
from tests.test_wallet_postgresql import pg_wallets  # noqa: F401

DAY = date(2026, 10, 28)
START = datetime(2026, 10, 28)


@pytest.fixture
async def jobs_db(routes_db, monkeypatch):
    ctx = routes_db
    monkeypatch.setattr(settings, "CELERY_TIMEZONE", "UTC")
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True)
    async with ctx["sessions"]() as db:
        conn = await db.connection()
        await conn.run_sync(
            lambda c: Order.__table__.c.status.type.create(c, checkfirst=True)
        )
        await db.execute(
            text(
                "ALTER TABLE orders ADD COLUMN status orderstatus, ADD COLUMN created_at TIMESTAMP"
            )
        )
        await db.execute(text("CREATE TABLE shifts(id UUID PRIMARY KEY)"))
        await db.execute(text("CREATE TABLE payouts(id UUID PRIMARY KEY)"))
        for model in (
            ProductivityMetrics,
            SLARecord,
            ProductivityRecord,
            Alert,
            NotificationLog,
            NotificationPreference,
        ):
            for col in model.__table__.columns:
                if getattr(col.type, "create_type", True) is False:
                    await conn.run_sync(
                        lambda c, t=col.type: t.create(c, checkfirst=True)
                    )
            await conn.run_sync(model.__table__.create)
        await db.commit()
    return ctx


async def add_delivery(ctx, rider_index=0, **values):
    async with ctx["sessions"]() as db:
        oid = uuid4()
        await db.execute(
            text(
                "INSERT INTO orders(id,status,created_at) VALUES (:id,'ENTREGADO',:now)"
            ),
            {"id": oid, "now": START + timedelta(hours=1)},
        )
        obj = Delivery(order_id=oid, rider_id=ctx["riders"][rider_index], **values)
        db.add(obj)
        await db.commit()
        return obj.id


@pytest.mark.asyncio
async def test_closed_day_metrics_use_completion_time_and_preserve_unknowns(jobs_db):
    ctx = jobs_db
    for minute, sla, distance in [
        (60, True, 2.5),
        (120, False, 1.5),
        (180, None, None),
    ]:
        await add_delivery(
            ctx,
            status=DeliveryStatus.COMPLETADA,
            started_at=START + timedelta(minutes=minute - 10),
            completed_at=START + timedelta(minutes=minute),
            sla_compliant=sla,
            distance_total=distance,
        )
    await add_delivery(
        ctx,
        status=DeliveryStatus.FALLIDA,
        started_at=START,
        completed_at=START + timedelta(minutes=5),
    )
    await add_delivery(
        ctx,
        status=DeliveryStatus.COMPLETADA,
        started_at=START,
        completed_at=START + timedelta(days=1),
    )
    async with ctx["sessions"]() as db:
        result = await WorkerJobs(db).rider_metrics(ctx["riders"][0], DAY)
        row = await db.get(ProductivityMetrics, result["metric_id"])
        assert (
            row.total_deliveries == 3
            and row.on_time_deliveries == 1
            and row.late_deliveries == 1
        )
        assert row.sla_compliance_rate == 50 and row.avg_delivery_time_minutes == 10
        assert row.total_distance_km is None and row.total_earnings is None
        assert row.customer_rating_avg is None and row.customer_rating_count is None
        assert (
            result["unknown_sla_count"] == 1 and result["missing_distance_count"] == 1
        )


@pytest.mark.asyncio
async def test_daily_metrics_include_riders_who_became_inactive(jobs_db):
    from app.models.rider import Rider, RiderStatus

    ctx = jobs_db
    await add_delivery(
        ctx, status=DeliveryStatus.COMPLETADA, completed_at=START + timedelta(hours=1)
    )
    async with ctx["sessions"]() as db:
        await db.execute(
            update(Rider)
            .where(Rider.id == ctx["riders"][0])
            .values(status=RiderStatus.INACTIVO)
        )
        await db.commit()
        assert await WorkerJobs(db).daily_riders(DAY) == [ctx["riders"][0]]


@pytest.mark.asyncio
async def test_parallel_metrics_create_one_row_and_replay_keeps_unrelated_evidence(
    jobs_db,
):
    ctx = jobs_db
    await add_delivery(
        ctx,
        status=DeliveryStatus.COMPLETADA,
        started_at=START,
        completed_at=START + timedelta(hours=1),
        distance_total=4,
    )

    async def calculate():
        async with ctx["sessions"]() as db:
            return await WorkerJobs(db).rider_metrics(ctx["riders"][0], DAY)

    results = await asyncio.gather(calculate(), calculate(), calculate())
    assert len({r["metric_id"] for r in results}) == 1
    async with ctx["sessions"]() as db:
        await db.execute(
            update(ProductivityMetrics).values(
                total_earnings=123.5, customer_rating_avg=4.8
            )
        )
        await db.commit()
        await WorkerJobs(db).rider_metrics(ctx["riders"][0], DAY)
        row = await db.scalar(select(ProductivityMetrics))
        assert row.total_earnings == 123.5 and row.customer_rating_avg == 4.8
        assert (
            await db.scalar(select(func.count()).select_from(ProductivityMetrics)) == 1
        )


@pytest.mark.asyncio
async def test_duplicate_historical_metrics_require_review_without_repair(jobs_db):
    ctx = jobs_db
    async with ctx["sessions"]() as db:
        for _ in range(2):
            db.add(
                ProductivityMetrics(
                    rider_id=ctx["riders"][0],
                    period_start=START,
                    period_end=START + timedelta(days=1),
                )
            )
        await db.commit()
        with pytest.raises(ValueError, match="Duplicate"):
            await WorkerJobs(db).rider_metrics(ctx["riders"][0], DAY)
        assert (
            await db.scalar(select(func.count()).select_from(ProductivityMetrics)) == 2
        )


@pytest.mark.asyncio
async def test_empty_or_invalid_measurements_do_not_invent_sla_or_duration(jobs_db):
    ctx = jobs_db
    await add_delivery(
        ctx,
        status=DeliveryStatus.COMPLETADA,
        started_at=START + timedelta(hours=2),
        completed_at=START + timedelta(hours=1),
        distance_total=float("nan"),
    )
    async with ctx["sessions"]() as db:
        result = await WorkerJobs(db).rider_metrics(ctx["riders"][0], DAY)
        row = await db.scalar(select(ProductivityMetrics))
        assert (
            row.sla_compliance_rate is None
            and row.avg_delivery_time_minutes is None
            and row.total_distance_km is None
        )
        assert result["missing_duration_count"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("age,expected", [(599, 0), (600, 0), (601, 1)])
async def test_sla_uses_exact_deadline_and_local_addressed_evidence(
    jobs_db, age, expected
):
    ctx = jobs_db
    now = START + timedelta(hours=12)
    did = await add_delivery(
        ctx,
        status=DeliveryStatus.EN_ROUTE,
        started_at=now - timedelta(seconds=age),
        sla_expected_minutes=10,
    )
    async with ctx["sessions"]() as db:
        result = await WorkerJobs(db).monitor_sla(now)
        assert result["alerts_created"] == expected
        assert await db.scalar(select(func.count()).select_from(Alert)) == expected
        assert (
            await db.scalar(select(func.count()).select_from(NotificationLog))
            == expected * 2
        )
        delivery = await db.get(Delivery, did)
        assert delivery.sla_compliant is None and delivery.sla_actual_minutes is None
        assert (
            delivery.locked_bonus_amount is None
            and delivery.status is DeliveryStatus.EN_ROUTE
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,expected",
    [
        (DeliveryStatus.EN_PICKUP, 1),
        (DeliveryStatus.PENDIENTE, 0),
        (DeliveryStatus.COMPLETADA, 0),
        (DeliveryStatus.FALLIDA, 0),
    ],
)
async def test_sla_does_not_modify_terminal_or_unstarted_delivery(
    jobs_db, status, expected
):
    ctx = jobs_db
    now = START + timedelta(hours=12)
    await add_delivery(ctx, status=status, started_at=START, sla_expected_minutes=10)
    async with ctx["sessions"]() as db:
        assert (await WorkerJobs(db).monitor_sla(now))["alerts_created"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("sla", [None, 0, -1])
async def test_missing_or_invalid_sla_target_is_not_assumed_to_be_sixty_minutes(
    jobs_db, sla
):
    ctx = jobs_db
    await add_delivery(
        ctx, status=DeliveryStatus.EN_ROUTE, started_at=START, sla_expected_minutes=sla
    )
    async with ctx["sessions"]() as db:
        assert (await WorkerJobs(db).monitor_sla(START + timedelta(hours=1)))[
            "alerts_created"
        ] == 0


@pytest.mark.asyncio
async def test_competing_sla_monitors_and_replay_do_not_duplicate_alert_or_inbox(
    jobs_db,
):
    ctx = jobs_db
    await add_delivery(
        ctx, status=DeliveryStatus.EN_ROUTE, started_at=START, sla_expected_minutes=10
    )

    async def run():
        async with ctx["sessions"]() as db:
            return await WorkerJobs(db).monitor_sla(START + timedelta(hours=1))

    results = await asyncio.gather(run(), run(), run(), run())
    assert sum(r["alerts_created"] for r in results) == 1
    assert (await run())["alerts_created"] == 0
    async with ctx["sessions"]() as db:
        assert await db.scalar(select(func.count()).select_from(Alert)) == 1
        assert await db.scalar(select(func.count()).select_from(NotificationLog)) == 2


@pytest.mark.asyncio
async def test_failed_commit_rolls_back_alert_and_every_recipient(jobs_db):
    ctx = jobs_db
    await add_delivery(
        ctx, status=DeliveryStatus.EN_ROUTE, started_at=START, sla_expected_minutes=10
    )
    async with ctx["sessions"]() as db:
        with patch.object(db, "commit", side_effect=RuntimeError("commit failed")):
            with pytest.raises(RuntimeError):
                await WorkerJobs(db).monitor_sla(START + timedelta(hours=1))
    async with ctx["sessions"]() as db:
        assert await db.scalar(select(func.count()).select_from(Alert)) == 0
        assert await db.scalar(select(func.count()).select_from(NotificationLog)) == 0


@pytest.mark.asyncio
async def test_operations_report_counts_database_without_financial_claims(jobs_db):
    ctx = jobs_db
    await add_delivery(
        ctx, status=DeliveryStatus.COMPLETADA, completed_at=START + timedelta(hours=1)
    )
    await add_delivery(
        ctx, status=DeliveryStatus.EN_ROUTE, completed_at=START + timedelta(hours=1)
    )
    async with ctx["sessions"]() as db:
        result = await WorkerJobs(db).operations_report(DAY)
        assert result["orders_created_by_status"] == {"ENTREGADO": 2}
        assert result["deliveries_closed_by_status"] == {"COMPLETADA": 1}
        assert (
            result["source"] == "database_snapshot"
            and result["financial_report"] is False
        )


@pytest.mark.asyncio
async def test_worker_session_runs_on_separate_event_loops_without_pooled_connections(
    jobs_db, monkeypatch
):
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.workers import runtime, productivity_worker

    ctx = jobs_db
    await add_delivery(
        ctx, status=DeliveryStatus.COMPLETADA, completed_at=START + timedelta(hours=1)
    )
    async with ctx["sessions"]() as db:
        url = db.bind.url
        schema = await db.scalar(text("SELECT current_schema()"))

    def factory(_url, **kwargs):
        return create_async_engine(
            url, connect_args={"server_settings": {"search_path": schema}}, **kwargs
        )

    monkeypatch.setattr(runtime, "create_async_engine", factory)
    monkeypatch.setattr(settings, "WORKER_PRODUCTIVITY_ENABLED", True)
    results = []
    for _ in range(2):
        result = await asyncio.to_thread(
            productivity_worker.calculate_rider_productivity.run,
            str(ctx["riders"][0]),
            DAY.isoformat(),
        )
        assert result["success"], result
        results.append(result)
    assert results[0]["metric_id"] == results[1]["metric_id"]


@pytest.mark.asyncio
async def test_metrics_refuse_oversized_period_without_partial_row(jobs_db):
    ctx = jobs_db
    async with ctx["sessions"]() as db:
        # Populate explicit orders/deliveries with set-based SQL, in this test schema only.
        await db.execute(
            text(
                "INSERT INTO orders(id) SELECT gen_random_uuid() FROM generate_series(1,10001)"
            )
        )
        await db.execute(
            text(
                "INSERT INTO deliveries(id,order_id,rider_id,status,completed_at) SELECT gen_random_uuid(),id,:rider,'COMPLETADA',:finished FROM orders WHERE created_at IS NULL AND id NOT IN (SELECT order_id FROM deliveries)"
            ),
            {"rider": ctx["riders"][0], "finished": START + timedelta(hours=1)},
        )
        await db.commit()
        with pytest.raises(ValueError, match="limit"):
            await WorkerJobs(db).rider_metrics(ctx["riders"][0], DAY)
        assert (
            await db.scalar(select(func.count()).select_from(ProductivityMetrics)) == 0
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["pause", "preference"])
async def test_sla_inbox_respects_global_pause_and_user_preference(
    jobs_db, monkeypatch, mode
):
    ctx = jobs_db
    await add_delivery(
        ctx, status=DeliveryStatus.EN_ROUTE, started_at=START, sla_expected_minutes=10
    )
    if mode == "pause":
        monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", False)
    async with ctx["sessions"]() as db:
        if mode == "preference":
            db.add(
                NotificationPreference(
                    user_id=ctx["owners"][ctx["riders"][0]],
                    event_code="sla_warning",
                    channel=NotificationChannel.IN_APP,
                    enabled=False,
                )
            )
            await db.commit()
        assert (await WorkerJobs(db).monitor_sla(START + timedelta(hours=1)))[
            "alerts_created"
        ] == 1
        assert await db.scalar(select(func.count()).select_from(NotificationLog)) == (
            0 if mode == "pause" else 1
        )
