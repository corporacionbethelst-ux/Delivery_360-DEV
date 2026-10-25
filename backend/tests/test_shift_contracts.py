"""Persisted contracts and shared internal workflows; no alternative HTTP API."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select, update

from tests.test_shift_safety import shift_context  # noqa: F401
from tests.orm_contract import detailed_mapping_contract
from app.crud.shift import shift as crud
from app.models.rider import Rider
from app.models.shift import CheckInOut, Shift, ShiftStatus
from app.schemas.shift import (
    ShiftCreate,
    ShiftUpdate,
    CheckInRequest,
    CheckOutRequest,
    ShiftResponse,
    CheckInOutResponse,
)
from app.services.shift_service import ShiftService


def test_postgresql_mapping_contract_is_unchanged():
    expected = json.loads(
        (Path(__file__).parent / "fixtures/orm_shift_contract.json").read_text()
    )
    assert detailed_mapping_contract(("shifts", "check_in_out")) == expected


def test_only_canonical_operator_shift_router_is_available():
    from app.main import app
    from app.api.v1 import shifts, routers_combined

    assert routers_combined.shifts_router is shifts.router
    assert not hasattr(routers_combined, "checkin")
    assert not hasattr(routers_combined, "checkout")
    paths = [
        route.path for route in app.routes if route.path.startswith("/api/v1/shifts")
    ]
    assert len(paths) == 6 and len(set(paths)) == 5  # GET + POST at the collection
    assert not any(
        "checkin" in path or "checkout" in path or "/shifts/shifts" in path
        for path in paths
    )


async def scheduled(db, rider_id, **overrides):
    data = dict(
        rider_id=rider_id,
        scheduled_start=datetime(2026, 10, 24, 9),
        scheduled_end=datetime(2026, 10, 24, 17),
    )
    data.update(overrides)
    return await ShiftService(db).create_shift(rider_id, ShiftCreate(**data))


@pytest.mark.asyncio
async def test_service_uses_requested_shift_and_returns_original_attendance(
    shift_context,
):
    _, db, rider_id, _ = shift_context
    first = await scheduled(db, rider_id)
    second = await scheduled(db, rider_id)
    service = ShiftService(db)
    before = (
        await db.execute(
            select(Rider.status, Rider.is_online).where(Rider.id == rider_id)
        )
    ).one()
    request = CheckInRequest(
        shift_id=second.id, latitude=10, longitude=-66, notes="Original"
    )
    with patch.object(db, "commit", wraps=db.commit) as commit:
        started, event = await service.check_in(rider_id, request)
        commit.assert_awaited_once()
    assert started.id == second.id and event.rider_id == rider_id
    assert started.check_in_latitude == event.latitude == 10
    assert started.check_in_longitude == event.longitude == -66
    _, retried = await service.check_in(
        rider_id,
        CheckInRequest(shift_id=second.id, latitude=11, longitude=-67, notes="Changed"),
    )
    assert (
        retried.id == event.id
        and retried.notes == "Original"
        and retried.latitude == 10
    )
    ended, out = await service.check_out(
        rider_id, CheckOutRequest(shift_id=second.id, latitude=12, longitude=-68)
    )
    _, repeated_out = await service.check_out(
        rider_id, CheckOutRequest(shift_id=second.id)
    )
    assert out.id == repeated_out.id and ended.status == ShiftStatus.COMPLETADO
    assert ended.check_out_latitude == 12
    assert (await crud.get(db, first.id)).status == ShiftStatus.PROGRAMADO
    assert await db.scalar(select(func.count()).select_from(Shift)) == 2
    assert await db.scalar(select(func.count()).select_from(CheckInOut)) == 2
    after = (
        await db.execute(
            select(Rider.status, Rider.is_online).where(Rider.id == rider_id)
        )
    ).one()
    assert after == before
    assert isinstance(ShiftResponse.model_validate(ended).id, UUID)
    assert CheckInOutResponse.model_validate(out).check_type == "OUT"


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["check_in", "check_out"])
async def test_service_does_not_operate_on_another_riders_shift(shift_context, action):
    _, db, rider_id, _ = shift_context
    row = await scheduled(db, rider_id)
    request_type = CheckInRequest if action == "check_in" else CheckOutRequest
    with pytest.raises(HTTPException) as error:
        await getattr(ShiftService(db), action)(uuid4(), request_type(shift_id=row.id))
    assert error.value.status_code == 403
    assert await db.scalar(select(Shift.status)) == ShiftStatus.PROGRAMADO
    assert await db.scalar(select(func.count()).select_from(CheckInOut)) == 0


@pytest.mark.asyncio
async def test_create_rejects_mismatched_rider(shift_context):
    _, db, rider_id, _ = shift_context
    with pytest.raises(HTTPException) as error:
        await ShiftService(db).create_shift(
            rider_id,
            ShiftCreate(rider_id=uuid4(), scheduled_start=datetime(2026, 10, 24, 9)),
        )
    assert error.value.status_code == 422
    assert await db.scalar(select(func.count()).select_from(Shift)) == 0


@pytest.mark.asyncio
async def test_crud_reuses_canonical_attendance_and_rejects_reopening(shift_context):
    _, db, rider_id, _ = shift_context
    row = await crud.create(
        db,
        rider_id,
        datetime(2026, 10, 24, 22),
        scheduled_end=datetime(2026, 10, 25, 6),
    )
    row = await crud.start_shift(db, row, (10, -66))
    row = await crud.start_shift(db, row, (11, -67))
    assert row.check_in_latitude == 10
    row = await crud.end_shift(db, row, (12, -68))
    row = await crud.end_shift(db, row, (13, -69))
    assert row.check_out_latitude == 12
    assert await db.scalar(select(func.count()).select_from(CheckInOut)) == 2
    with pytest.raises(HTTPException):
        await crud.start_shift(db, row, (10, -66))


@pytest.mark.asyncio
async def test_partial_schedule_update_persists_real_columns_and_freezes_active_schedule(
    shift_context,
):
    _, db, rider_id, _ = shift_context
    row = await scheduled(db, rider_id)
    service = ShiftService(db)
    updated = await service.update_shift(
        row.id,
        ShiftUpdate(scheduled_end=datetime(2026, 10, 24, 18), notes="Reprogramado"),
    )
    assert updated.start_time.hour == 9 and updated.end_time.hour == 18
    await service.check_in(rider_id, CheckInRequest(shift_id=row.id))
    with pytest.raises(HTTPException) as error:
        await service.update_shift(
            row.id,
            ShiftUpdate(
                scheduled_end=datetime(2026, 10, 24, 19), notes="Must not persist"
            ),
        )
    assert error.value.status_code == 409
    await db.refresh(updated)
    assert updated.end_time.hour == 18 and updated.notes == "Reprogramado"
    await service.update_shift(row.id, ShiftUpdate(notes=None))
    assert updated.notes is None
    await service.check_out(rider_id, CheckOutRequest(shift_id=row.id))
    with pytest.raises(HTTPException):
        await service.update_shift(row.id, ShiftUpdate(notes="Terminal mutation"))


@pytest.mark.asyncio
async def test_service_cancel_preserves_original_reason_and_cannot_cancel_active(
    shift_context,
):
    _, db, rider_id, _ = shift_context
    service = ShiftService(db)
    row = await scheduled(db, rider_id)
    cancelled = await service.cancel_shift(row.id, "Cambio de planificación")
    again = await service.cancel_shift(row.id, "Different retry")
    assert (
        cancelled.cancellation_reason
        == again.cancellation_reason
        == "Cambio de planificación"
    )
    second = await scheduled(db, rider_id)
    await service.check_in(rider_id, CheckInRequest(shift_id=second.id))
    with pytest.raises(HTTPException) as error:
        await service.cancel_shift(second.id, "Do not cancel attendance")
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_duplicate_historical_active_shifts_require_review(shift_context):
    _, db, rider_id, _ = shift_context
    await scheduled(db, rider_id)
    await scheduled(db, rider_id)
    await db.execute(update(Shift).values(status=ShiftStatus.EN_CURSO))
    await db.commit()
    with pytest.raises(HTTPException) as error:
        await ShiftService(db).get_active_shift(rider_id)
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_service_commit_false_leaves_transaction_to_caller(shift_context):
    _, db, rider_id, _ = shift_context
    row = await scheduled(db, rider_id)
    shift_id = row.id
    with patch.object(db, "commit", wraps=db.commit) as commit:
        await ShiftService(db).check_in(
            rider_id, CheckInRequest(shift_id=shift_id), commit=False
        )
        commit.assert_not_awaited()
    await db.rollback()
    assert (
        await db.scalar(select(Shift.status).where(Shift.id == shift_id))
        == ShiftStatus.PROGRAMADO
    )
    assert await db.scalar(select(func.count()).select_from(CheckInOut)) == 0


@pytest.mark.asyncio
async def test_date_filters_use_date_and_time_and_preserve_pagination(shift_context):
    _, db, rider_id, _ = shift_context
    first = await scheduled(
        db,
        rider_id,
        scheduled_start=datetime(2026, 10, 23, 9),
        scheduled_end=datetime(2026, 10, 23, 17),
    )
    second = await scheduled(db, rider_id)
    third = await scheduled(
        db,
        rider_id,
        scheduled_start=datetime(2026, 10, 25, 9),
        scheduled_end=datetime(2026, 10, 25, 17),
    )
    # Older rows can keep midnight in shift_date; Time is authoritative for schedule.
    await db.execute(
        update(Shift)
        .where(Shift.id == second.id)
        .values(shift_date=datetime(2026, 10, 24))
    )
    await db.commit()
    assert [
        row.id for row in await crud.get_multi(db, date=datetime(2026, 10, 24))
    ] == [second.id]
    assert [
        row.id for row in await crud.get_by_rider(db, rider_id, skip=1, limit=1)
    ] == [second.id]
    service = ShiftService(db)
    assert [
        row.id
        for row in await service.get_shifts_by_date_range(
            datetime(2026, 10, 24, 8), datetime(2026, 10, 24, 10)
        )
    ] == [second.id]
    assert (
        await service.get_shifts_by_date_range(
            datetime(2026, 10, 24, 10), datetime(2026, 10, 24, 11)
        )
        == []
    )
    assert first.id != third.id


@pytest.mark.asyncio
async def test_statistics_use_real_attendance_and_report_missing_marks(shift_context):
    _, db, rider_id, _ = shift_context
    now = datetime.utcnow()
    good = await scheduled(
        db,
        rider_id,
        scheduled_start=now - timedelta(hours=3),
        scheduled_end=now + timedelta(hours=5),
    )
    bad = await scheduled(
        db,
        rider_id,
        scheduled_start=now - timedelta(hours=2),
        scheduled_end=now + timedelta(hours=6),
    )
    await db.execute(
        update(Shift)
        .where(Shift.id == good.id)
        .values(
            status=ShiftStatus.COMPLETADO,
            check_in_at=now - timedelta(hours=2),
            check_out_at=now - timedelta(minutes=30),
        )
    )
    await db.execute(
        update(Shift)
        .where(Shift.id == bad.id)
        .values(status=ShiftStatus.COMPLETADO, check_in_at=None, check_out_at=None)
    )
    await db.commit()
    stats = await ShiftService(db).get_shift_statistics(rider_id)
    assert stats["total_shifts"] == 2 and stats["shifts_requiring_review"] == 1
    assert stats["total_hours"] == stats["avg_hours"] == 1.5
    assert await ShiftService(db).get_active_shifts_count() == 0


@pytest.mark.asyncio
async def test_historical_nullable_values_remain_null_in_response(shift_context):
    _, db, rider_id, _ = shift_context
    row = await scheduled(db, rider_id)
    await db.execute(
        update(Shift).values(
            status=None,
            created_at=None,
            updated_at=None,
            total_deliveries=None,
            completed_deliveries=None,
            total_earnings=None,
        )
    )
    await db.commit()
    await db.refresh(row)
    response = ShiftResponse.model_validate(row)
    assert response.status is None and response.created_at is None
    assert response.total_deliveries is None and response.total_earnings is None


@pytest.mark.parametrize(
    "fields",
    [
        {"rider_id": 1},
        {"status": "ACTIVE"},
        {"status": "PAUSADO"},
        {"metadata_json": {}},
        {"start_time": "09:00:00"},
    ],
)
def test_creation_rejects_unsupported_legacy_contract(fields):
    data = dict(rider_id=uuid4(), scheduled_start=datetime(2026, 10, 24, 9))
    data.update(fields)
    with pytest.raises(ValidationError):
        ShiftCreate(**data)


@pytest.mark.parametrize(
    "fields",
    [
        {"status": "COMPLETADO"},
        {"scheduled_start": None},
        {"scheduled_end": None},
        {"metadata_json": {}},
        {"notes": "x" * 501},
    ],
)
def test_generic_update_cannot_bypass_transitions_or_clear_schedule(fields):
    with pytest.raises(ValidationError):
        ShiftUpdate(**fields)


@pytest.mark.parametrize(
    "fields",
    [
        {"shift_id": 1},
        {"latitude": 91, "longitude": 0},
        {"latitude": 0},
        {"latitude": True, "longitude": 0},
        {"latitude": float("nan"), "longitude": 0},
        {"photo_url": "unsupported"},
    ],
)
def test_attendance_requests_reject_invalid_ids_evidence_or_coordinates(fields):
    data = dict(shift_id=uuid4())
    data.update(fields)
    with pytest.raises(ValidationError):
        CheckInRequest(**data)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["check_in", "check_out"])
async def test_missing_attendance_event_is_not_fabricated_by_retry(
    shift_context, action
):
    from sqlalchemy import delete

    _, db, rider_id, _ = shift_context
    row = await scheduled(db, rider_id)
    service = ShiftService(db)
    await service.check_in(rider_id, CheckInRequest(shift_id=row.id))
    check_type = "IN"
    request = CheckInRequest(shift_id=row.id)
    if action == "check_out":
        await service.check_out(rider_id, CheckOutRequest(shift_id=row.id))
        check_type = "OUT"
        request = CheckOutRequest(shift_id=row.id)
    await db.execute(delete(CheckInOut).where(CheckInOut.check_type == check_type))
    await db.commit()
    before = await db.scalar(select(func.count()).select_from(CheckInOut))
    with pytest.raises(HTTPException) as error:
        await getattr(service, action)(rider_id, request)
    assert error.value.status_code == 409
    assert await db.scalar(select(func.count()).select_from(CheckInOut)) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "coordinates", [(float("inf"), 0), (True, 0), (10, None), (-91, 0)]
)
async def test_crud_does_not_persist_invalid_coordinates(shift_context, coordinates):
    _, db, rider_id, _ = shift_context
    row = await scheduled(db, rider_id)
    with pytest.raises(HTTPException) as error:
        await crud.start_shift(db, row, coordinates)
    assert error.value.status_code == 422
    assert await db.scalar(select(Shift.status)) == ShiftStatus.PROGRAMADO
    assert await db.scalar(select(func.count()).select_from(CheckInOut)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("days", [0, 367])
async def test_statistics_reject_invalid_period(shift_context, days):
    _, db, rider_id, _ = shift_context
    with pytest.raises(HTTPException) as error:
        await ShiftService(db).get_shift_statistics(rider_id, days)
    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_productivity_uses_actual_cross_midnight_attendance_not_schedule(
    shift_context, test_engine
):
    from app.models.order import Order
    from app.models.delivery import Delivery, DeliveryStatus
    from app.services.productivity_service import ProductivityService

    _, db, rider_id, _ = shift_context
    async with test_engine.begin() as connection:
        for model in (Order, Delivery):
            await connection.run_sync(model.__table__.create)
    row = await scheduled(db, rider_id)
    start, end = datetime(2026, 10, 24, 23), datetime(2026, 10, 25, 1)
    await db.execute(
        update(Shift).values(
            status=ShiftStatus.COMPLETADO, check_in_at=start, check_out_at=end
        )
    )
    orders = [
        Order(
            customer_name="Cliente",
            customer_phone="123",
            pickup_address="A",
            delivery_address="B",
        )
        for _ in range(3)
    ]
    db.add_all(orders)
    await db.flush()
    db.add_all(
        [
            Delivery(
                order_id=orders[0].id,
                rider_id=rider_id,
                status=DeliveryStatus.COMPLETADA,
                started_at=start + timedelta(minutes=5),
                completed_at=start + timedelta(minutes=35),
                sla_compliant=True,
            ),
            Delivery(
                order_id=orders[1].id,
                rider_id=rider_id,
                status=DeliveryStatus.COMPLETADA,
                started_at=start + timedelta(minutes=40),
                completed_at=start + timedelta(minutes=70),
                sla_compliant=False,
            ),
            Delivery(
                order_id=orders[2].id,
                rider_id=rider_id,
                status=DeliveryStatus.COMPLETADA,
                started_at=start - timedelta(hours=2),
                completed_at=start - timedelta(hours=1),
            ),
        ]
    )
    await db.commit()
    await db.refresh(row)
    service = ProductivityService(db)
    report = await service.calculate_shift_productivity(row.id)
    assert report["start_time"] == start and report["end_time"] == end
    assert report["rider_id"] == rider_id
    assert report["total_deliveries"] == 2 and report["duration_hours"] == 2
    assert report["deliveries_per_hour"] == 1
    summary = await service.calculate_rider_productivity(rider_id, start, end)
    assert summary["total_hours_worked"] == 2
    assert summary["total_deliveries"] == 2 and summary["sla_percentage"] == 50
    assert summary["avg_delivery_time_minutes"] == 30


@pytest.mark.asyncio
@pytest.mark.parametrize("complete", [False, True])
async def test_productivity_does_not_invent_actual_hours_for_unclosed_shifts(
    shift_context, complete
):
    from app.services.productivity_service import ProductivityService

    _, db, rider_id, _ = shift_context
    row = await scheduled(db, rider_id)
    if complete:
        await db.execute(
            update(Shift).values(
                status=ShiftStatus.COMPLETADO, check_in_at=None, check_out_at=None
            )
        )
        await db.commit()
        await db.refresh(row)
    with pytest.raises(HTTPException) as error:
        await ProductivityService(db).calculate_shift_productivity(row.id)
    assert error.value.status_code == 409
