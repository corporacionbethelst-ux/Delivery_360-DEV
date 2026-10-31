"""Assignment replays preserve clocks, receipts, permissions and real first audits."""

import asyncio
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select, update, func
from tests.test_delivery_financial_postgresql import payment_db  # noqa: F401
from tests.test_order_cancellation_postgresql import cancel_db  # noqa: F401
from tests.test_sla_monitor_postgresql import sla_db  # noqa: F401
from tests.test_runtime_contracts_postgresql import runtime_db  # noqa: F401
from tests.test_assignment_eligibility_postgresql import (
    assignment_db,
    request,
)  # noqa: F401
from tests.test_assignment_concurrency_postgresql import second_rider
from app.core.security import create_access_token
from app.models.order import Order, OrderStatus
from app.models.delivery import Delivery, DeliveryStatus
from app.models.audit_log import AuditLog, ActionType
from app.models.notification import Notification
from app.models.user import User
from app.models.rider_document import RiderDocument, DocumentStatus
from app.schemas.order import OrderCreate
from app.services.order_service import OrderService
from app.services import order_assignment as assignments
from app.services.worker_jobs import WorkerJobs

NOW = datetime(2026, 10, 31, 12)
EARLIER = NOW - timedelta(minutes=30)


@pytest.fixture
async def confirmed(assignment_db, monkeypatch):
    client, sessions, ids = assignment_db
    monkeypatch.setattr(assignments, "utc_now_naive", lambda: NOW)
    response = request(client, ids, "manual")
    assert response.status_code == 200, response.text
    async with sessions() as db:
        await db.execute(update(Order).values(accepted_at=EARLIER))
        await db.execute(
            update(Delivery).values(started_at=EARLIER, sla_expected_minutes=10)
        )
        await db.commit()
    return client, sessions, ids


async def receipt(sessions, ids):
    async with sessions() as db:
        order = await db.get(Order, ids["order"])
        delivery = await db.get(Delivery, ids["delivery"])
        return {
            "accepted_at": order.accepted_at,
            "started_at": delivery.started_at,
            "order_updated_at": order.updated_at,
            "delivery_updated_at": delivery.updated_at,
            "rider": delivery.rider_id,
            "audits": await db.scalar(select(func.count()).select_from(AuditLog)),
            "notices": await db.scalar(select(func.count()).select_from(Notification)),
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["manual", "delivery", "service"])
@pytest.mark.parametrize("unknown_clock", [False, True])
async def test_replaying_an_unchanged_assignment_preserves_all_clocks_and_receipts(
    confirmed, monkeypatch, path, unknown_clock
):
    client, sessions, ids = confirmed
    if unknown_clock:
        async with sessions() as db:
            await db.execute(update(Order).values(accepted_at=None))
            await db.execute(update(Delivery).values(started_at=None))
            await db.commit()
    before = await receipt(sessions, ids)
    redis = SimpleNamespace(connected=True, log_order_assigned=AsyncMock())
    monkeypatch.setattr("app.api.v1.orders.get_redis_audit_logger", lambda: redis)
    hook = AsyncMock()
    monkeypatch.setattr("app.api.v1.deliveries.notify_event", hook)
    for _ in range(2):
        if path == "service":
            async with sessions() as db:
                await OrderService().assign_rider_to_order(
                    db, ids["order"], ids["rider"], ids["staff"]
                )
        else:
            response = request(client, ids, path)
            assert response.status_code == 200, response.text
    assert await receipt(sessions, ids) == before
    redis.log_order_assigned.assert_not_awaited()
    hook.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["manual", "delivery"])
async def test_assignment_replay_does_not_postpone_a_real_sla_breach(confirmed, path):
    client, sessions, ids = confirmed
    response = request(client, ids, path)
    assert response.status_code == 200, response.text
    async with sessions() as db:
        result = await WorkerJobs(db).monitor_sla(NOW)
        assert result["alerts_created"] == 1
    async with sessions() as db:
        assert (await db.get(Delivery, ids["delivery"])).started_at == EARLIER


@pytest.mark.asyncio
async def test_service_creation_records_a_true_first_assignment_and_leaves_input_unchanged(
    assignment_db,
):
    _, sessions, ids = assignment_db
    data = OrderCreate(
        customer_name="New customer",
        customer_phone="123",
        pickup_address="A",
        delivery_address="B",
        assigned_rider_id=ids["rider"],
    )
    async with sessions() as db:
        created = await OrderService().create_order(db, data, ids["staff"])
        oid = created.id
        assert data.assigned_rider_id == ids["rider"]
    async with sessions() as db:
        audit = await db.scalar(
            select(AuditLog).where(AuditLog.resource_id == str(oid))
        )
        delivery = await db.scalar(select(Delivery).where(Delivery.order_id == oid))
        assert audit.action_type == ActionType.ASSIGN
        assert (
            audit.old_values["rider_id"] is None
            and audit.old_values["order_status"] == "PENDIENTE"
        )
        assert audit.new_values["rider_id"] == str(ids["rider"])
        assert audit.new_values["delivery_id"] == str(delivery.id)
        assert delivery.started_at == (await db.get(Order, oid)).accepted_at


@pytest.mark.asyncio
async def test_a_real_rider_change_still_has_new_clock_and_previous_clock_evidence(
    confirmed,
):
    client, sessions, ids = confirmed
    other = await second_rider(sessions)
    response = request(client, {**ids, "rider": other}, "manual")
    assert response.status_code == 200, response.text
    async with sessions() as db:
        audit = await db.scalar(
            select(AuditLog).where(AuditLog.action_type == ActionType.REASSIGN)
        )
        assert audit.old_values["started_at"] == EARLIER.isoformat()
        assert audit.new_values["started_at"] == NOW.isoformat()
        assert (await db.get(Delivery, ids["delivery"])).rider_id == other
    before = await receipt(sessions, ids)
    assert request(client, {**ids, "rider": other}, "manual").status_code == 200
    assert await receipt(sessions, ids) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("denial", ["credentials", "owner", "documents"])
async def test_replay_does_not_bypass_current_credentials_or_eligibility(
    confirmed, denial
):
    client, sessions, ids = confirmed
    async with sessions() as db:
        if denial == "credentials":
            await db.execute(
                update(User).where(User.id == ids["staff"]).values(token_version=1)
            )
        elif denial == "owner":
            await db.execute(
                update(User).where(User.id == ids["owner"]).values(is_active=False)
            )
        else:
            await db.execute(
                update(RiderDocument).values(status=DocumentStatus.RECHAZADO)
            )
        await db.commit()
    before = await receipt(sessions, ids)
    response = request(client, ids, "manual")
    assert response.status_code == (
        401 if denial == "credentials" else 400
    ), response.text
    assert await receipt(sessions, ids) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("paths", [("manual", "manual"), ("manual", "delivery")])
async def test_concurrent_first_assignments_emit_one_receipt_and_one_notice(
    assignment_db, monkeypatch, paths
):
    client, sessions, ids = assignment_db
    redis = SimpleNamespace(connected=True, log_order_assigned=AsyncMock())
    monkeypatch.setattr("app.api.v1.orders.get_redis_audit_logger", lambda: redis)
    hook = AsyncMock()
    monkeypatch.setattr("app.api.v1.deliveries.notify_event", hook)
    async with asyncio.timeout(20):
        responses = await asyncio.gather(
            *(asyncio.to_thread(request, client, ids, path) for path in paths)
        )
    assert all(response.status_code == 200 for response in responses), [
        r.text for r in responses
    ]
    saved = await receipt(sessions, ids)
    assert saved["audits"] == 1 and saved["notices"] + hook.await_count == 1
    assert redis.log_order_assigned.await_count <= 1


@pytest.mark.asyncio
async def test_assignment_http_contract_contains_the_canonical_rider_summary(
    assignment_db,
):
    client, _, ids = assignment_db
    response = request(client, ids, "manual")
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["assigned_rider"]["id"] == str(ids["rider"])
    assert value["delivery"]["order_id"] == str(ids["order"])
    assert value["delivery"]["rider_id"] == str(ids["rider"])
    assert value["status"] == "ASIGNADO" and value["delivery"]["status"] == "INICIADA"
    export = os.environ.get("EXPORT_ASSIGNMENT_CONTRACT_PATH")
    if export:
        Path(export).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
