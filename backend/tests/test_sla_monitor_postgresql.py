"""Native lock interleavings, durable warnings and cancellation compatibility."""

import asyncio
import json
from concurrent.futures import Future
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4
import pytest
from sqlalchemy import MetaData, select, update, delete, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.test_delivery_financial_postgresql import payment_db  # noqa: F401
from tests.test_order_cancellation_postgresql import (
    cancel_db,
    cancel_request,
)  # noqa: F401
from app.core.config import settings
from app.models.notification import (
    Notification,
    NotificationLog,
    NotificationPreference,
    NotificationChannel,
    Alert,
)
from app.models.order import Order, OrderStatus
from app.models.delivery import Delivery, DeliveryStatus
from app.models.audit_log import AuditLog
from app.models.user import User, UserRole
from app.services.worker_jobs import WorkerJobs
from app.services.alert_service import AlertService
from app.services.order_cancellation import cancel_order

NOW = datetime(2026, 10, 30, 12)
REASON = "Cliente solicita cancelar la entrega"


@pytest.fixture
async def sla_db(cancel_db, monkeypatch):
    client, sessions, ids = cancel_db
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True)
    tables = {
        m.__table__ for m in (Notification, NotificationLog, NotificationPreference)
    }
    while True:
        expanded = tables | {
            fk.column.table for table in tables for fk in table.foreign_keys
        }
        if expanded == tables:
            break
        tables = expanded
    ddl = MetaData()
    for table in tables:
        table.to_metadata(ddl)
    async with sessions() as db:
        conn = await db.connection()
        for table in ddl.tables.values():
            for column in table.columns:
                if hasattr(column.type, "create"):
                    await conn.run_sync(
                        lambda c, t=column.type: t.create(c, checkfirst=True)
                    )
        await conn.run_sync(ddl.create_all)
        await db.execute(delete(Alert))
        await db.execute(
            update(Delivery).values(
                started_at=NOW - timedelta(minutes=30), sla_expected_minutes=10
            )
        )
        await db.commit()

    class Clock:
        @staticmethod
        def utcnow():
            return NOW

    monkeypatch.setattr("app.services.alert_service.datetime", Clock)
    return client, sessions, ids


@pytest.mark.asyncio
async def test_monitor_then_cancel_cannot_form_the_order_delivery_fk_deadlock(
    sla_db, monkeypatch
):
    _, sessions, ids = sla_db
    entered, release = Future(), Future()
    original = AsyncSession.commit

    async def pause(db):
        if db.info.get("pause_monitor"):
            entered.set_result(None)
            await asyncio.wrap_future(release)
        return await original(db)

    monkeypatch.setattr(AsyncSession, "commit", pause)
    worker_pid, cancel_pid = Future(), Future()

    async def monitor():
        async with sessions() as db:
            db.info["pause_monitor"] = True
            worker_pid.set_result(await db.scalar(text("SELECT pg_backend_pid()")))
            return await WorkerJobs(db).monitor_sla(NOW)

    async def cancel():
        async with sessions() as db:
            cancel_pid.set_result(await db.scalar(text("SELECT pg_backend_pid()")))
            return await cancel_order(
                db, ids["order"], ids["staff"], REASON, commit=True
            )

    async with asyncio.timeout(20):
        monitoring = asyncio.create_task(monitor())
        cancelling = None
        try:
            await asyncio.wait_for(asyncio.wrap_future(entered), 5)
            cancelling = asyncio.create_task(cancel())
            wid, cid = await asyncio.wrap_future(worker_pid), await asyncio.wrap_future(
                cancel_pid
            )
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 5
            async with sessions() as observer:
                while not await observer.scalar(
                    text("SELECT :worker = ANY(pg_blocking_pids(:cancel))"),
                    {"worker": wid, "cancel": cid},
                ):
                    assert (
                        loop.time() < deadline
                    ), "Cancellation must wait for the monitor's lock"
                    await asyncio.sleep(0.02)
        finally:
            release.set_result(None)
        result, order = await asyncio.gather(monitoring, cancelling)
    assert result["alerts_created"] == 1
    assert order.status == OrderStatus.CANCELADO
    async with sessions() as db:
        alerts = list((await db.scalars(select(Alert))).all())
        assert len(alerts) == 1 and alerts[0].status == "RESOLVED"
        assert alerts[0].resolved_by == ids["staff"]
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 1
        assert (
            await db.get(Delivery, ids["delivery"])
        ).status == DeliveryStatus.CANCELADA


@pytest.mark.asyncio
async def test_pending_cancellation_is_skipped_before_monitor_locks_its_delivery(
    sla_db, monkeypatch
):
    client, sessions, ids = sla_db
    entered, release = Future(), Future()
    original = AsyncSession.scalars

    async def pause(db, statement, *args, **kwargs):
        if (
            db.info.get("workflow_request")
            and "FROM deliveries" in str(statement)
            and "FOR UPDATE" in str(statement)
        ):
            entered.set_result(None)
            await asyncio.wrap_future(release)
        return await original(db, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "scalars", pause)
    async with asyncio.timeout(20):
        pending = asyncio.create_task(
            asyncio.to_thread(cancel_request, client, ids, REASON)
        )
        try:
            await asyncio.wait_for(asyncio.wrap_future(entered), 5)
            async with sessions() as db:
                result = await asyncio.wait_for(WorkerJobs(db).monitor_sla(NOW), 5)
                assert result["alerts_created"] == 0
                assert await db.scalar(select(func.count()).select_from(Alert)) == 0
        finally:
            release.set_result(None)
        response = await asyncio.wait_for(pending, 10)
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_bounded_monitor_skips_busy_parent_and_processes_another_order(sla_db):
    _, sessions, ids = sla_db
    async with sessions() as db:
        other = Order(
            id=UUID(int=1),
            customer_name="Other",
            customer_phone="123",
            pickup_address="A",
            delivery_address="B",
            status=OrderStatus.EN_RUTA,
            assigned_rider_id=ids["rider"],
        )
        db.add(other)
        await db.flush()
        second = Delivery(
            order_id=other.id,
            rider_id=ids["rider"],
            status=DeliveryStatus.EN_ROUTE,
            started_at=NOW - timedelta(hours=1),
            sla_expected_minutes=10,
        )
        db.add(second)
        await db.commit()
    async with sessions() as owner:
        await owner.execute(
            select(Order.id).where(Order.id == UUID(int=1)).with_for_update()
        )
        async with sessions() as monitor:
            result = await asyncio.wait_for(
                WorkerJobs(monitor).monitor_sla(NOW, batch_size=1), 5
            )
            assert result["alerts_created"] == 1
            assert await monitor.scalar(select(Alert.delivery_id)) == ids["delivery"]
        await owner.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "remaining,expected", [(-1, 0), (0, 0), (1, 2), (300, 2), (301, 0)]
)
async def test_warning_window_is_future_only_with_inclusive_upper_boundary(
    sla_db, remaining, expected
):
    _, sessions, ids = sla_db
    async with sessions() as db:
        await db.execute(
            update(Delivery).values(
                started_at=NOW + timedelta(seconds=remaining) - timedelta(minutes=10)
            )
        )
        await db.commit()
        notifications = await AlertService().check_sla_alerts(db)
        assert len(notifications) == expected
        assert await db.scalar(select(func.count()).select_from(Alert)) == (
            1 if expected else 0
        )
        for notification in notifications:
            assert notification.user_id in (ids["staff"], ids["owner"])
            assert notification.related_id == str(ids["delivery"])
            assert notification.data["related_order_id"] == str(ids["order"])
            assert notification.is_sent is False


@pytest.mark.asyncio
async def test_warning_receipt_survives_inbox_deletion_and_cancellation_resolves_it(
    sla_db,
):
    client, sessions, ids = sla_db
    async with sessions() as db:
        await db.execute(update(Delivery).values(started_at=NOW - timedelta(minutes=6)))
        await db.commit()
        assert len(await AlertService().check_sla_alerts(db)) == 2
        await db.execute(delete(Notification))
        await db.commit()
        assert await AlertService().check_sla_alerts(db) == []
    response = cancel_request(client, ids)
    assert response.status_code == 200, response.text
    async with sessions() as db:
        alert = await db.scalar(select(Alert))
        assert alert.alert_type == "SLA_WARNING" and alert.status == "RESOLVED"
        assert alert.resolved_by == ids["staff"]
        assert await AlertService().check_sla_alerts(db) == []


@pytest.mark.asyncio
async def test_competing_warning_scans_create_one_durable_receipt(sla_db):
    _, sessions, _ = sla_db
    async with sessions() as db:
        await db.execute(update(Delivery).values(started_at=NOW - timedelta(minutes=6)))
        await db.commit()

    async def scan():
        async with sessions() as db:
            return await AlertService().check_sla_alerts(db)

    results = await asyncio.gather(scan(), scan(), scan())
    assert sum(map(len, results)) == 2
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Alert)) == 1
        assert await db.scalar(select(func.count()).select_from(Notification)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("mute", ["pause", "preference"])
async def test_warning_receipt_does_not_depend_on_inbox_delivery(
    sla_db, monkeypatch, mute
):
    _, sessions, ids = sla_db
    async with sessions() as db:
        await db.execute(update(Delivery).values(started_at=NOW - timedelta(minutes=6)))
        if mute == "pause":
            monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", False)
        else:
            db.add(
                NotificationPreference(
                    user_id=ids["owner"],
                    event_code="sla_warning",
                    channel=NotificationChannel.IN_APP,
                    enabled=False,
                )
            )
        await db.commit()
        result = await AlertService().check_sla_alerts(db)
        assert len(result) == (0 if mute == "pause" else 1)
        assert await db.scalar(select(func.count()).select_from(Alert)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["flush", "commit"])
async def test_warning_failure_rolls_back_receipt_and_all_inbox_rows(
    sla_db, monkeypatch, failure
):
    _, sessions, _ = sla_db
    async with sessions() as db:
        await db.execute(update(Delivery).values(started_at=NOW - timedelta(minutes=6)))
        await db.commit()

        async def broken(*args, **kwargs):
            raise RuntimeError("injected warning failure")

        monkeypatch.setattr(db, failure, broken)
        with pytest.raises(RuntimeError):
            await AlertService().check_sla_alerts(db)
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Alert)) == 0
        assert await db.scalar(select(func.count()).select_from(Notification)) == 0


def test_legacy_notification_mapping_matches_unmodified_base():
    from tests.orm_contract import detailed_mapping_contract

    expected = json.loads(
        (
            Path(__file__).parent / "fixtures/legacy_notification_contract.json"
        ).read_text()
    )
    assert detailed_mapping_contract(["notifications"]) == expected


@pytest.mark.asyncio
async def test_existing_worker_runs_warning_and_breach_scans_with_one_clock(
    sla_db, monkeypatch
):
    from contextlib import asynccontextmanager
    from app.workers import sla_monitor_worker

    _, sessions, ids = sla_db
    async with sessions() as db:
        await db.execute(update(Delivery).values(started_at=NOW - timedelta(minutes=6)))
        await db.commit()

    @asynccontextmanager
    async def own_session():
        async with sessions() as db:
            yield db

    class Clock:
        @staticmethod
        def now(zone):
            return NOW.replace(tzinfo=zone)

    monkeypatch.setattr(sla_monitor_worker, "worker_session", own_session)
    monkeypatch.setattr(sla_monitor_worker, "datetime", Clock)
    result = await sla_monitor_worker.run_monitor(ids["delivery"])
    assert result["warning_inbox_created"] == 2 and result["alerts_created"] == 0
    again = await sla_monitor_worker.run_monitor(ids["delivery"])
    assert again["warning_inbox_created"] == 0 and again["alerts_created"] == 0


@pytest.mark.asyncio
async def test_assignment_records_notification_for_user_without_lazy_rider_relationship(
    sla_db,
    tmp_path,
    monkeypatch,
):
    from app.core.security import create_access_token
    from app.models.rider_document import RiderDocument, DocumentType, DocumentStatus
    from app.models.route import Route, RouteStatus

    client, sessions, ids = sla_db
    monkeypatch.chdir(tmp_path)
    async with sessions() as db:
        conn = await db.connection()
        await conn.run_sync(RiderDocument.__table__.create)
        folder = tmp_path / "uploads/documents" / str(ids["rider"])
        folder.mkdir(parents=True)
        for kind in DocumentType:
            path = folder / (kind.value + ".pdf")
            path.write_bytes(b"%PDF assignment evidence")
            db.add(
                RiderDocument(
                    rider_id=ids["rider"],
                    type=kind,
                    status=DocumentStatus.APROBADO,
                    file_url=f"/uploads/documents/{ids['rider']}/{path.name}",
                )
            )
        await db.execute(update(Order).values(status=OrderStatus.ASIGNADO))
        await db.execute(update(Delivery).values(status=DeliveryStatus.INICIADA))
        await db.execute(update(Route).values(status=RouteStatus.PLANIFICADA))
        await db.commit()
    response = client.patch(
        f"/api/v1/orders/{ids['order']}/assign",
        json={"rider_id": str(ids["rider"])},
        headers={"Authorization": "Bearer " + create_access_token(ids["staff"])},
    )
    assert response.status_code == 200, response.text
    async with sessions() as db:
        records = list((await db.scalars(select(Notification))).all())
        assert len(records) == 1
        assert records[0].user_id == ids["owner"]
        assert records[0].notification_type.value == "ASIGNACION_PEDIDO"
        assert records[0].is_sent is False and records[0].sent_at is None
