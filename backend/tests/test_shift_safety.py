"""Operator HTTP contracts with real persistence; no production resources."""

from datetime import datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import MetaData, func, select, update

from app.api.v1 import shifts as api
from app.core.database import get_db
from app.core.security import get_current_active_user
from app.core.shift_rules import transition_shift
from app.models.rider import Rider
from app.models.shift import CheckInOut, Shift, ShiftStatus
from app.models.user import UserRole
from app.models.zone import Zone


@pytest.fixture
async def shift_context(test_engine, db_session, test_user):
    # Copy only the unrelated Zone DDL for SQLite; keep production metadata intact.
    zone_table = Zone.__table__.to_metadata(MetaData())
    zone_table.c.id.server_default = None
    async with test_engine.begin() as connection:
        await connection.run_sync(zone_table.create)
        for model in (Shift, CheckInOut):
            await connection.run_sync(model.__table__.create)
    rider = Rider(user_id=test_user.id)
    db_session.add(rider)
    await db_session.commit()
    current = [SimpleNamespace(id=test_user.id, role=test_user.role)]
    app = FastAPI()
    app.include_router(api.router, prefix="/shifts")

    async def database():
        try:
            yield db_session
        except Exception:
            await db_session.rollback()
            raise

    async def identity():
        return current[0]

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_active_user] = identity
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, db_session, rider.id, current


async def create(client, rider_id, **overrides):
    body = {
        "rider_id": str(rider_id),
        "start_time": "2026-10-24T09:00:00",
        "end_time": "2026-10-24T17:00:00",
    }
    body.update(overrides)
    return await client.post("/shifts", json=body)


@pytest.mark.asyncio
async def test_retry_start_and_end_do_not_duplicate_events_or_change_times(
    shift_context,
):
    client, db, rider_id, _ = shift_context
    response = await create(client, rider_id)
    assert response.status_code == 201, response.text
    shift_id = response.json()["id"]
    first_start = await client.patch(f"/shifts/{shift_id}/start")
    second_start = await client.patch(f"/shifts/{shift_id}/start")
    assert first_start.status_code == second_start.status_code == 200
    assert first_start.json()["check_in_at"] == second_start.json()["check_in_at"]
    first_end = await client.patch(f"/shifts/{shift_id}/end")
    second_end = await client.patch(f"/shifts/{shift_id}/end")
    assert first_end.status_code == second_end.status_code == 200
    assert first_end.json()["check_out_at"] == second_end.json()["check_out_at"]
    events = (
        (await db.execute(select(CheckInOut.check_type).order_by(CheckInOut.timestamp)))
        .scalars()
        .all()
    )
    assert events == ["IN", "OUT"]
    # The schedule is not overwritten by real attendance.
    assert await db.scalar(select(Shift.end_time)) == time(17)
    for action in ("start", "cancel"):
        assert (await client.patch(f"/shifts/{shift_id}/{action}")).status_code == 400


@pytest.mark.asyncio
async def test_one_active_shift_and_active_cancellation_requires_end(shift_context):
    client, db, rider_id, _ = shift_context
    first = (await create(client, rider_id)).json()["id"]
    second = (await create(client, rider_id)).json()["id"]
    assert (await client.patch(f"/shifts/{first}/start")).status_code == 200
    assert (await client.patch(f"/shifts/{second}/start")).status_code == 409
    assert (await client.patch(f"/shifts/{first}/cancel")).status_code == 409
    assert await db.scalar(select(func.count()).select_from(CheckInOut)) == 1
    assert (await client.patch(f"/shifts/{first}/end")).status_code == 200
    assert (await client.patch(f"/shifts/{second}/start")).status_code == 200


@pytest.mark.asyncio
async def test_cancel_retry_and_terminal_state_reject_reopening(shift_context):
    client, db, rider_id, _ = shift_context
    shift_id = (await create(client, rider_id)).json()["id"]
    for _ in range(2):
        response = await client.patch(f"/shifts/{shift_id}/cancel")
        assert response.status_code == 200
        assert response.json()["status"] == "CANCELADO"
    for action in ("start", "end"):
        assert (await client.patch(f"/shifts/{shift_id}/{action}")).status_code == 400
    assert await db.scalar(select(func.count()).select_from(CheckInOut)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role", [UserRole.REPARTIDOR, UserRole.CLIENTE, UserRole.AUDITOR, None]
)
async def test_non_operator_cannot_access_any_shift_endpoint(shift_context, role):
    client, db, rider_id, current = shift_context
    current[0] = SimpleNamespace(role=role)
    shift_id = str(uuid4())
    with patch.object(db, "execute", wraps=db.execute) as execute:
        assert (await client.get("/shifts")).status_code == 403
        assert (await client.get(f"/shifts/{shift_id}")).status_code == 403
        assert (await create(client, rider_id)).status_code == 403
        for action in ("start", "end", "cancel"):
            assert (
                await client.patch(f"/shifts/{shift_id}/{action}")
            ).status_code == 403
        execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role", [UserRole.SUPERADMIN, UserRole.GERENTE, UserRole.OPERADOR]
)
async def test_operator_roles_keep_access(shift_context, role):
    client, _, rider_id, current = shift_context
    current[0] = SimpleNamespace(role=role)
    assert (await create(client, rider_id)).status_code == 201


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "start,end",
    [
        ("2026-10-24T22:00:00-04:00", "2026-10-25T06:00:00-04:00"),
        ("2026-10-24T22:00:00", "2026-10-25T06:00:00"),
        ("2026-10-24T09:00:00", "2026-10-25T09:00:00"),
    ],
)
async def test_schedule_roundtrip_keeps_utc_instant_and_next_day(
    shift_context, start, end
):
    from app.core.shift_rules import utc_naive

    client, _, rider_id, _ = shift_context
    response = await create(client, rider_id, start_time=start, end_time=end)
    assert response.status_code == 201, response.text
    body = response.json()
    assert datetime.fromisoformat(body["start_time"]) == utc_naive(
        datetime.fromisoformat(start)
    )
    assert datetime.fromisoformat(body["end_time"]) == utc_naive(
        datetime.fromisoformat(end)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "end", ["2026-10-24T08:00:00", "2026-10-24T09:00:00", "2026-10-25T09:00:01"]
)
async def test_unrepresentable_or_nonpositive_schedule_never_persists(
    shift_context, end
):
    client, db, rider_id, _ = shift_context
    assert (await create(client, rider_id, end_time=end)).status_code == 422
    assert await db.scalar(select(func.count()).select_from(Shift)) == 0


@pytest.mark.asyncio
async def test_legacy_active_without_valid_checkin_requires_review(shift_context):
    client, db, rider_id, _ = shift_context
    shift_id = (await create(client, rider_id)).json()["id"]
    for check_in in (None, datetime.utcnow() + timedelta(hours=1)):
        await db.execute(
            update(Shift).values(status=ShiftStatus.EN_CURSO, check_in_at=check_in)
        )
        await db.commit()
        assert (await client.patch(f"/shifts/{shift_id}/end")).status_code == 409
    assert await db.scalar(select(func.count()).select_from(CheckInOut)) == 0


@pytest.mark.asyncio
async def test_attendance_failure_rolls_back_transition(shift_context):
    client, db, rider_id, _ = shift_context
    shift_id = (await create(client, rider_id)).json()["id"]
    from uuid import UUID

    with patch.object(
        db, "flush", side_effect=RuntimeError("simulated attendance insert failure")
    ):
        with pytest.raises(RuntimeError):
            await transition_shift(db, UUID(shift_id), ShiftStatus.EN_CURSO)
    await db.rollback()
    assert await db.scalar(select(Shift.status)) == ShiftStatus.PROGRAMADO
    assert await db.scalar(select(func.count()).select_from(CheckInOut)) == 0


@pytest.mark.asyncio
async def test_unauthenticated_request_is_rejected_before_database():
    from unittest.mock import AsyncMock

    app = FastAPI()
    app.include_router(api.router, prefix="/shifts")
    database = AsyncMock()
    app.dependency_overrides[get_db] = database
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/shifts")).status_code == 401
    database.assert_not_awaited()


@pytest.mark.asyncio
async def test_bad_or_unknown_uuid_does_not_write(shift_context):
    client, db, _, _ = shift_context
    for action in ("start", "end", "cancel"):
        assert (await client.patch(f"/shifts/invalid/{action}")).status_code == 400
        assert (await client.patch(f"/shifts/{uuid4()}/{action}")).status_code == 404
    assert await db.scalar(select(func.count()).select_from(CheckInOut)) == 0


@pytest.mark.asyncio
async def test_creation_response_failure_does_not_leave_a_committed_shift(
    shift_context,
):
    client, db, rider_id, _ = shift_context
    with patch.object(
        api,
        "_serialize_shift",
        side_effect=RuntimeError("simulated serialization failure"),
    ):
        with pytest.raises(RuntimeError):
            await create(client, rider_id)
    assert await db.scalar(select(func.count()).select_from(Shift)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,action", [(ShiftStatus.EN_CURSO, "start"), (ShiftStatus.COMPLETADO, "end")]
)
async def test_retry_cannot_confirm_historical_state_with_missing_attendance(
    shift_context, status, action
):
    client, db, rider_id, _ = shift_context
    shift_id = (await create(client, rider_id)).json()["id"]
    await db.execute(
        update(Shift).values(status=status, check_in_at=None, check_out_at=None)
    )
    await db.commit()
    assert (await client.patch(f"/shifts/{shift_id}/{action}")).status_code == 409
    assert await db.scalar(select(func.count()).select_from(CheckInOut)) == 0
