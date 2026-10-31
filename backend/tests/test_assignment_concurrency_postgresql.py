"""Real lock waits, candidate fallback and administrative assignment boundaries."""

import asyncio
from concurrent.futures import Future
from pathlib import Path
import pytest
from sqlalchemy import select, update, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.test_delivery_financial_postgresql import payment_db  # noqa: F401
from tests.test_order_cancellation_postgresql import cancel_db  # noqa: F401
from tests.test_sla_monitor_postgresql import sla_db  # noqa: F401
from tests.test_runtime_contracts_postgresql import runtime_db  # noqa: F401
from tests.test_assignment_eligibility_postgresql import (
    assignment_db,
    request,
    unchanged,
)  # noqa: F401
from app.core.security import create_access_token
from app.models.user import User, UserRole
from app.models.rider import Rider, RiderStatus
from app.models.rider_document import RiderDocument, DocumentType, DocumentStatus
from app.models.order import Order, OrderStatus
from app.models.delivery import Delivery
from app.models.audit_log import AuditLog, ActionType
from app.services import order_assignment as assignments


async def wait_for_blocker(sessions, waiter, blocker):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 5
    async with sessions() as db:
        while not await db.scalar(
            text("SELECT :blocker = ANY(pg_blocking_pids(:waiter))"),
            {"blocker": blocker, "waiter": waiter},
        ):
            assert loop.time() < deadline, "Expected a real PostgreSQL lock wait"
            await asyncio.sleep(0.02)


async def second_rider(sessions):
    async with sessions() as db:
        owner = User(
            email="fallback@example.com",
            hashed_password="unused",
            first_name="Second",
            last_name="Rider",
            role=UserRole.REPARTIDOR,
            is_active=True,
        )
        db.add(owner)
        await db.flush()
        rider = Rider(
            user_id=owner.id,
            status=RiderStatus.ACTIVO,
            is_online=True,
            last_lat=0.001,
            last_lng=0.0,
            last_location=func.ST_SetSRID(func.ST_MakePoint(0.0, 0.001), 4326),
        )
        db.add(rider)
        await db.flush()
        folder = Path("uploads/documents") / str(rider.id)
        folder.mkdir(parents=True)
        for kind in DocumentType:
            path = folder / (kind.value + ".pdf")
            path.write_bytes(b"%PDF fallback evidence")
            db.add(
                RiderDocument(
                    rider_id=rider.id,
                    type=kind,
                    status=DocumentStatus.APROBADO,
                    file_url=f"/uploads/documents/{rider.id}/{path.name}",
                )
            )
        await db.commit()
        return rider.id


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["manual", "auto"])
async def test_operator_revoked_during_actual_order_lock_wait_cannot_assign(
    assignment_db, monkeypatch, path
):
    client, sessions, ids = assignment_db
    waiting = Future()
    original = AsyncSession.execute

    async def observed(db, statement, *args, **kwargs):
        if (
            db.info.get("workflow_request")
            and getattr(statement, "_for_update_arg", None) is not None
            and not waiting.done()
        ):
            waiting.set_result(
                (await original(db, text("SELECT pg_backend_pid()"))).scalar_one()
            )
        return await original(db, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", observed)
    async with asyncio.timeout(20):
        async with sessions() as blocker:
            pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
            await blocker.execute(
                select(Order).where(Order.id == ids["order"]).with_for_update()
            )
            pending = asyncio.create_task(asyncio.to_thread(request, client, ids, path))
            try:
                waiter = await asyncio.wait_for(asyncio.wrap_future(waiting), 5)
                await wait_for_blocker(sessions, waiter, pid)
                async with sessions() as writer:
                    await writer.execute(
                        update(User)
                        .where(User.id == ids["staff"])
                        .values(token_version=1)
                    )
                    await writer.commit()
            finally:
                await blocker.rollback()
            response = await pending
    assert response.status_code == 401, response.text
    await unchanged(sessions, ids)


@pytest.mark.asyncio
async def test_recipient_deactivation_waits_for_the_assignment_commit(
    assignment_db, monkeypatch
):
    client, sessions, ids = assignment_db
    entered, release, writer_pid = Future(), Future(), Future()
    original = assignments.apply_order_assignment

    async def paused(db, *args, **kwargs):
        result = await original(db, *args, **kwargs)
        entered.set_result(await db.scalar(text("SELECT pg_backend_pid()")))
        await asyncio.wrap_future(release)
        return result

    monkeypatch.setattr(assignments, "apply_order_assignment", paused)

    async def deactivate():
        async with sessions() as db:
            writer_pid.set_result(await db.scalar(text("SELECT pg_backend_pid()")))
            await db.execute(
                update(User).where(User.id == ids["owner"]).values(is_active=False)
            )
            await db.commit()

    async with asyncio.timeout(20):
        pending = asyncio.create_task(asyncio.to_thread(request, client, ids, "manual"))
        writer = None
        try:
            assignment_pid = await asyncio.wait_for(asyncio.wrap_future(entered), 5)
            writer = asyncio.create_task(deactivate())
            await wait_for_blocker(
                sessions, await asyncio.wrap_future(writer_pid), assignment_pid
            )
        finally:
            release.set_result(None)
        response, _ = await asyncio.gather(pending, writer)
    assert response.status_code == 200, response.text
    async with sessions() as db:
        assert (await db.get(Order, ids["order"])).assigned_rider_id == ids["rider"]
        assert not (await db.get(User, ids["owner"])).is_active
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 1


@pytest.mark.asyncio
async def test_auto_assignment_uses_next_candidate_when_nearest_rider_is_locked(
    assignment_db,
):
    client, sessions, ids = assignment_db
    fallback = await second_rider(sessions)
    async with sessions() as blocker:
        await blocker.execute(
            select(Rider).where(Rider.id == ids["rider"]).with_for_update()
        )
        response = await asyncio.wait_for(
            asyncio.to_thread(request, client, ids, "auto"), 5
        )
        assert response.status_code == 200, response.text
        assert response.json()["assigned_rider"]["id"] == str(fallback)
        await blocker.rollback()
    async with sessions() as db:
        assert (await db.get(Delivery, ids["delivery"])).rider_id == fallback


@pytest.mark.asyncio
async def test_unstarted_reassignment_keeps_auditable_previous_rider(assignment_db):
    client, sessions, ids = assignment_db
    fallback = await second_rider(sessions)
    async with sessions() as db:
        await db.execute(
            update(Order).values(
                status=OrderStatus.ASIGNADO, assigned_rider_id=ids["rider"]
            )
        )
        await db.commit()
    response = request(client, {**ids, "rider": fallback}, "manual")
    assert response.status_code == 200, response.text
    async with sessions() as db:
        audit = await db.scalar(select(AuditLog))
        assert audit.action_type == ActionType.REASSIGN
        assert audit.old_values["rider_id"] == str(ids["rider"])
        assert audit.new_values["rider_id"] == str(fallback)
        assert (await db.get(Delivery, ids["delivery"])).rider_id == fallback


@pytest.mark.asyncio
@pytest.mark.parametrize("denial", ["inactive", "role"])
async def test_nearby_discovery_does_not_advertise_unavailable_accounts(
    assignment_db, denial
):
    client, sessions, ids = assignment_db
    async with sessions() as db:
        values = (
            {"is_active": False} if denial == "inactive" else {"role": UserRole.CLIENTE}
        )
        await db.execute(update(User).where(User.id == ids["owner"]).values(**values))
        await db.commit()
    response = client.post(
        "/api/v1/riders/nearby",
        headers={"Authorization": "Bearer " + create_access_token(ids["staff"])},
        json={"lat": 0, "lng": 0, "radius_km": 1, "limit": 5},
    )
    assert response.status_code == 200, response.text
    assert response.json()["count"] == 0 and response.json()["riders"] == []


@pytest.mark.asyncio
async def test_generic_order_status_cannot_create_an_assignment_without_a_rider_check(
    assignment_db,
):
    client, sessions, ids = assignment_db
    response = client.patch(
        f"/api/v1/orders/{ids['order']}/status",
        params={"new_status": "ASIGNADO"},
        headers={"Authorization": "Bearer " + create_access_token(ids["staff"])},
    )
    assert response.status_code == 409, response.text
    await unchanged(sessions, ids)


@pytest.mark.asyncio
@pytest.mark.parametrize("latitude", [None, float("nan")])
async def test_auto_assignment_rechecks_coordinates_after_candidate_discovery(
    assignment_db, monkeypatch, latitude
):
    client, sessions, ids = assignment_db
    entered, release = Future(), Future()
    original = assignments.assignment_candidate

    async def paused(*args, **kwargs):
        entered.set_result(None)
        await asyncio.wrap_future(release)
        return await original(*args, **kwargs)

    monkeypatch.setattr("app.api.v1.orders.assignment_candidate", paused)
    async with asyncio.timeout(20):
        pending = asyncio.create_task(asyncio.to_thread(request, client, ids, "auto"))
        try:
            await asyncio.wait_for(asyncio.wrap_future(entered), 5)
            async with sessions() as db:
                await db.execute(
                    update(Rider)
                    .where(Rider.id == ids["rider"])
                    .values(last_lat=latitude)
                )
                await db.commit()
        finally:
            release.set_result(None)
        response = await pending
    assert response.status_code == 404, response.text
    await unchanged(sessions, ids)
