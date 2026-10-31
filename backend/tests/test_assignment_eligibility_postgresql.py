"""Assignments on real PostgreSQL/PostGIS: live policy, atomicity and races."""

import asyncio
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sqlalchemy import select, update, delete, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.test_delivery_financial_postgresql import payment_db  # noqa: F401
from tests.test_order_cancellation_postgresql import cancel_db  # noqa: F401
from tests.test_sla_monitor_postgresql import sla_db  # noqa: F401
from tests.test_runtime_contracts_postgresql import runtime_db  # noqa: F401
from app.core.security import create_access_token
from app.core.exceptions import ValidationError, AppException
from app.models.user import User, UserRole
from app.models.rider import Rider, RiderStatus
from app.models.rider_document import RiderDocument, DocumentType, DocumentStatus
from app.models.order import Order, OrderStatus
from app.models.delivery import Delivery, DeliveryStatus
from app.models.route import Route, RouteStatus
from app.models.audit_log import AuditLog, ActionType
from app.models.notification import Notification
from app.schemas.rider import RiderApprovalRequest
from app.schemas.order import OrderCreate, OrderUpdate
from app.services.rider_service import RiderService
from app.services.order_service import OrderService
from app.services import order_assignment as assignments

PATHS = ("manual", "auto", "delivery", "create")


@pytest.fixture
async def assignment_db(runtime_db, monkeypatch):
    client, sessions, ids = runtime_db
    monkeypatch.setattr(
        "app.api.v1.deliveries.notify_event", AsyncMock(return_value=None)
    )
    async with sessions() as db:
        await db.execute(
            update(Order).values(pickup_latitude=0.0, pickup_longitude=0.0)
        )
        await db.execute(
            update(Delivery).values(status=DeliveryStatus.PENDIENTE, started_at=None)
        )
        await db.execute(
            update(Rider).values(is_online=True, last_lat=0.0, last_lng=0.0)
        )
        await db.execute(
            text("UPDATE riders SET last_location=ST_SetSRID(ST_MakePoint(0,0),4326)")
        )
        await db.commit()
    return client, sessions, ids


def request(client, ids, path, *, epoch=0):
    headers = {
        "Authorization": "Bearer "
        + create_access_token(ids["staff"], token_version=epoch)
    }
    if path == "create":
        return client.post(
            "/api/v1/orders",
            headers=headers,
            json={
                "customer_name": "Assignment customer",
                "customer_phone": "123",
                "pickup_address": "A",
                "delivery_address": "B",
                "delivery_contact": "Customer",
                "rider_id": str(ids["rider"]),
                "total": 0,
            },
        )
    if path == "delivery":
        return client.post(
            f"/api/v1/deliveries/{ids['delivery']}/assign",
            headers=headers,
            json={"rider_id": str(ids["rider"])},
        )
    if path == "auto":
        return client.post(
            f"/api/v1/orders/{ids['order']}/assign-auto", headers=headers
        )
    return client.patch(
        f"/api/v1/orders/{ids['order']}/assign",
        headers=headers,
        json={"rider_id": str(ids["rider"])},
    )


async def unchanged(sessions, ids):
    async with sessions() as db:
        order = await db.get(Order, ids["order"])
        delivery = await db.get(Delivery, ids["delivery"])
        assert order.status == OrderStatus.PENDIENTE and order.assigned_rider_id is None
        assert delivery.rider_id == ids["rider"]
        assert await db.scalar(select(func.count()).select_from(Order)) == 1
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 0
        assert await db.scalar(select(func.count()).select_from(Notification)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize(
    "denial",
    [
        "inactive_user",
        "wrong_role",
        "suspended",
        "missing_document",
        "rejected_document",
        "empty_file",
    ],
)
async def test_all_assignment_paths_reject_ineligible_riders_without_partial_writes(
    assignment_db, path, denial
):
    client, sessions, ids = assignment_db
    async with sessions() as db:
        if denial == "inactive_user":
            await db.execute(
                update(User).where(User.id == ids["owner"]).values(is_active=False)
            )
        elif denial == "wrong_role":
            await db.execute(
                update(User)
                .where(User.id == ids["owner"])
                .values(role=UserRole.CLIENTE)
            )
        elif denial == "suspended":
            await db.execute(update(Rider).values(status=RiderStatus.SUSPENDIDO))
        elif denial == "missing_document":
            await db.execute(
                delete(RiderDocument).where(
                    RiderDocument.type == DocumentType.DOCUMENTO_IDENTIDAD
                )
            )
        elif denial == "rejected_document":
            await db.execute(
                update(RiderDocument).values(status=DocumentStatus.RECHAZADO)
            )
        else:
            file = await db.scalar(select(RiderDocument.file_url).limit(1))
            Path(file.lstrip("/")).write_bytes(b"")
        await db.commit()
    response = request(client, ids, path)
    assert response.status_code == (404 if path == "auto" else 400), response.text
    await unchanged(sessions, ids)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", PATHS)
async def test_all_assignment_paths_commit_order_delivery_and_audit_together(
    assignment_db, path
):
    client, sessions, ids = assignment_db
    # Administrative assignment retains support for an offline rider without GPS.
    async with sessions() as db:
        await db.execute(
            update(User).where(User.id == ids["owner"]).values(last_name="")
        )
        if path != "auto":
            await db.execute(
                update(Rider).values(
                    is_online=False, last_location=None, last_lat=None, last_lng=None
                )
            )
        await db.commit()
    response = request(client, ids, path)
    assert response.status_code in (200, 201), response.text
    oid = ids["order"] if path != "create" else response.json()["id"]
    async with sessions() as db:
        order = await db.get(Order, oid)
        delivery = await db.scalar(select(Delivery).where(Delivery.order_id == oid))
        audit = await db.scalar(select(AuditLog))
        assert (
            order.status == OrderStatus.ASIGNADO
            and order.assigned_rider_id == ids["rider"]
        )
        assert (
            delivery.status == DeliveryStatus.INICIADA
            and delivery.rider_id == ids["rider"]
        )
        assert order.accepted_at == delivery.started_at
        assert audit.action_type == ActionType.ASSIGN and audit.resource_id == str(
            order.id
        )
        assert audit.new_values["delivery_id"] == str(delivery.id)
        if path == "auto":
            assert response.json()["assigned_rider"]["name"] == "Owner"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", PATHS)
async def test_audit_commit_failure_rolls_back_every_assignment_entry_point(
    assignment_db, monkeypatch, path
):
    client, sessions, ids = assignment_db
    original = AsyncSession.commit

    async def broken(db):
        if db.info.get("workflow_request") and any(
            isinstance(row, AuditLog) for row in db.new
        ):
            raise RuntimeError("Injected assignment audit failure")
        return await original(db)

    monkeypatch.setattr(AsyncSession, "commit", broken)
    response = request(client, ids, path)
    assert response.status_code == 500, response.text
    await unchanged(sessions, ids)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["manual", "auto", "delivery"])
@pytest.mark.parametrize(
    "evidence", ["delivery_progress", "delivery_issue", "route_progress"]
)
async def test_assignment_does_not_erase_existing_operational_evidence(
    assignment_db, path, evidence
):
    client, sessions, ids = assignment_db
    async with sessions() as db:
        if evidence == "delivery_progress":
            await db.execute(update(Delivery).values(status=DeliveryStatus.EN_PICKUP))
        elif evidence == "delivery_issue":
            await db.execute(
                update(Delivery).values(issue_description="Keep this incident")
            )
        else:
            await db.execute(update(Route).values(status=RouteStatus.EN_PROGRESO))
        await db.commit()
    response = request(client, ids, path)
    assert response.status_code in (400, 409), response.text
    await unchanged(sessions, ids)
    async with sessions() as db:
        if evidence == "delivery_progress":
            assert (
                await db.get(Delivery, ids["delivery"])
            ).status == DeliveryStatus.EN_PICKUP
        elif evidence == "delivery_issue":
            assert (
                await db.get(Delivery, ids["delivery"])
            ).issue_description == "Keep this incident"
        else:
            assert (await db.get(Route, ids["route"])).status == RouteStatus.EN_PROGRESO


@pytest.mark.asyncio
@pytest.mark.parametrize("approved", [True, False])
@pytest.mark.parametrize("length", [500, 501, 2000])
async def test_approval_audit_keeps_full_reason_and_respects_physical_summary_capacity(
    assignment_db, approved, length
):
    _, sessions, ids = assignment_db
    reason = "á" * length
    async with sessions() as db:
        await RiderService(db).approve_rider(
            ids["rider"],
            RiderApprovalRequest(
                approved=approved, notes=reason, rejection_reason=reason
            ),
            ids["staff"],
        )
    async with sessions() as db:
        audit = await db.scalar(select(AuditLog))
        assert audit.changes_summary == reason[:500]
        assert audit.new_values["reason"] == reason
        assert (await db.get(Rider, ids["rider"])).status == (
            RiderStatus.ACTIVO if approved else RiderStatus.SUSPENDIDO
        )


@pytest.mark.asyncio
async def test_overlong_decision_reason_is_rejected_before_database_io():
    db = AsyncMock()
    with pytest.raises(ValidationError):
        await RiderService(db).approve_rider(
            uuid4(), RiderApprovalRequest(notes="x" * 2001), uuid4()
        )
    db.scalar.assert_not_awaited()
    db.commit.assert_not_awaited()
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["actor_role", "actor_epoch", "owner_active", "rider_status", "document"]
)
@pytest.mark.parametrize("path", ["manual", "auto"])
async def test_assignment_rechecks_live_policy_after_resource_wait(
    assignment_db, monkeypatch, change, path
):
    client, sessions, ids = assignment_db
    entered, release = Future(), Future()
    original = assignments.assignment_candidate

    async def paused(*args, **kwargs):
        if not entered.done():
            entered.set_result(None)
        await asyncio.wrap_future(release)
        return await original(*args, **kwargs)

    # API keeps a direct import, while manual coordinator calls its module global.
    monkeypatch.setattr(assignments, "assignment_candidate", paused)
    monkeypatch.setattr("app.api.v1.orders.assignment_candidate", paused)
    async with asyncio.timeout(20):
        pending = asyncio.create_task(asyncio.to_thread(request, client, ids, path))
        try:
            await asyncio.wait_for(asyncio.wrap_future(entered), 5)
            async with sessions() as db:
                if change == "actor_role":
                    await db.execute(
                        update(User)
                        .where(User.id == ids["staff"])
                        .values(role=UserRole.AUDITOR)
                    )
                elif change == "actor_epoch":
                    await db.execute(
                        update(User)
                        .where(User.id == ids["staff"])
                        .values(token_version=1)
                    )
                elif change == "owner_active":
                    await db.execute(
                        update(User)
                        .where(User.id == ids["owner"])
                        .values(is_active=False)
                    )
                elif change == "rider_status":
                    await db.execute(
                        update(Rider).values(status=RiderStatus.SUSPENDIDO)
                    )
                else:
                    await db.execute(
                        update(RiderDocument).values(status=DocumentStatus.RECHAZADO)
                    )
                await db.commit()
        finally:
            release.set_result(None)
        response = await pending
    assert response.status_code == (
        {"actor_role": 403, "actor_epoch": 401}.get(
            change, 404 if path == "auto" else 400
        )
    ), response.text
    await unchanged(sessions, ids)


@pytest.mark.asyncio
async def test_auto_assignment_skips_locked_rider_and_returns_without_waiting(
    assignment_db,
):
    client, sessions, ids = assignment_db
    async with sessions() as locker:
        await locker.execute(
            select(Rider).where(Rider.id == ids["rider"]).with_for_update()
        )
        response = await asyncio.wait_for(
            asyncio.to_thread(request, client, ids, "auto"), 3
        )
        assert response.status_code == 404, response.text
        await locker.rollback()
    await unchanged(sessions, ids)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["assign", "create", "edit", "status"])
async def test_legacy_order_service_cannot_bypass_guarded_assignment(
    assignment_db, operation
):
    _, sessions, ids = assignment_db
    async with sessions() as db:
        await db.execute(
            update(User).where(User.id == ids["owner"]).values(is_active=False)
        )
        await db.commit()
        service = OrderService()
        with pytest.raises((HTTPException, AppException)) as error:
            if operation == "assign":
                await service.assign_rider_to_order(
                    db, ids["order"], ids["rider"], ids["staff"]
                )
            elif operation == "create":
                await service.create_order(
                    db,
                    OrderCreate(
                        customer_name="C",
                        customer_phone="123",
                        pickup_address="A",
                        delivery_address="B",
                        assigned_rider_id=ids["rider"],
                    ),
                    ids["staff"],
                )
            elif operation == "edit":
                await service.update_order(
                    db,
                    ids["order"],
                    OrderUpdate(assigned_rider_id=ids["rider"]),
                    ids["staff"],
                )
            else:
                await service.update_status(
                    db, ids["order"], OrderStatus.ASIGNADO, ids["staff"]
                )
        assert error.value.status_code in (400, 409)
        if operation in ("create", "assign"):
            assert not db.in_transaction()
        await db.rollback()
    await unchanged(sessions, ids)
