"""Database checks for GPS writers and document eligibility."""

from unittest.mock import AsyncMock
from uuid import uuid4
from datetime import datetime
import pytest
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import load_only
from tests.test_document_review import ready_set, state
from tests.test_document_uploads import submissions  # noqa: F401
from tests.test_private_documents import documents  # noqa: F401
from app.api.v1.telemetry import rider_heartbeat
from app.models.rider import Rider, RiderStatus
from app.models.rider_document import RiderDocument, DocumentStatus
from app.schemas.rider_location import HeartbeatRequest
from app.services.tracking_service import TrackingService
from app.services.document_review import ensure_rider_can_report_online


@pytest.mark.asyncio
@pytest.mark.parametrize("writer", ["telemetry", "tracking"])
@pytest.mark.parametrize(
    "status",
    [
        RiderStatus.PENDIENTE,
        RiderStatus.SUSPENDIDO,
        RiderStatus.INACTIVO,
        RiderStatus.ACTIVO,
        RiderStatus.OCUPADO,
    ],
)
async def test_invalid_reports_have_no_position_or_broadcast(
    submissions, writer, status
):
    _, db, ctx = submissions
    await db.execute(
        update(Rider)
        .where(Rider.id == ctx["rider_id"])
        .values(status=status, is_online=True)
    )
    await db.commit()
    service = TrackingService(db)
    service.broadcast_location_update = AsyncMock()
    with pytest.raises(HTTPException) as error:
        if writer == "telemetry":
            await rider_heartbeat(
                str(ctx["rider_id"]),
                HeartbeatRequest(lat=10, lng=-66),
                db,
                ctx["current"][0],
            )
        else:
            await service.record_location_update(ctx["rider_id"], 10, -66)
    assert error.value.status_code == 403
    expected = (
        RiderStatus.PENDIENTE
        if status in (RiderStatus.ACTIVO, RiderStatus.OCUPADO)
        else status
    )
    assert await state(db, ctx) == (expected, False)
    assert (
        await db.scalar(select(Rider.last_lat).where(Rider.id == ctx["rider_id"]))
        is None
    )
    service.broadcast_location_update.assert_not_awaited()
    assert not db.new


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [RiderStatus.ACTIVO, RiderStatus.OCUPADO])
async def test_ready_riders_can_report_during_delivery(submissions, status):
    _, db, ctx = submissions
    await ready_set(db, ctx, rider_status=status)
    await db.execute(
        update(RiderDocument).values(
            status=DocumentStatus.APROBADO, updated_at=datetime.utcnow()
        )
    )
    await db.commit()
    rider = await db.scalar(
        select(Rider)
        .options(load_only(Rider.id, Rider.status, Rider.is_online, Rider.approved_at))
        .where(Rider.id == ctx["rider_id"])
    )
    await ensure_rider_can_report_online(db, rider, allow_busy=True)
    assert rider.status == status
    await db.rollback()


@pytest.mark.asyncio
async def test_foreign_report_cannot_disconnect_owner(submissions):
    _, db, ctx = submissions
    ctx["current"][0].id = uuid4()
    await db.execute(
        update(Rider).where(Rider.id == ctx["rider_id"]).values(is_online=True)
    )
    await db.commit()
    with pytest.raises(HTTPException) as error:
        await rider_heartbeat(
            str(ctx["rider_id"]),
            HeartbeatRequest(lat=10, lng=-66),
            db,
            ctx["current"][0],
        )
    assert error.value.status_code == 403
    assert (await state(db, ctx))[1] is True


@pytest.mark.asyncio
async def test_unknown_rider_no_location_or_broadcast(submissions):
    _, db, _ = submissions
    service = TrackingService(db)
    service.broadcast_location_update = AsyncMock()
    with pytest.raises(HTTPException) as error:
        await service.record_location_update(uuid4(), 10, -66)
    assert error.value.status_code == 404
    assert not db.new
    service.broadcast_location_update.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        RiderStatus.ACTIVO,
        RiderStatus.OCUPADO,
        RiderStatus.SUSPENDIDO,
        RiderStatus.INACTIVO,
    ],
)
async def test_vehicle_change_preserves_closed_status(submissions, status):
    from app.api.v1.riders import update_my_rider_profile, RiderUpdate
    from app.models.audit_log import AuditLog
    from app.models.user import User

    _, db, ctx = submissions
    connection = await db.connection()
    await connection.run_sync(
        lambda conn: conn.connection.dbapi_connection.create_function(
            "AsEWKB", 1, lambda value: None
        )
    )
    default = AuditLog.__table__.c.id.server_default
    try:
        AuditLog.__table__.c.id.server_default = None
        await connection.run_sync(AuditLog.__table__.create)
    finally:
        AuditLog.__table__.c.id.server_default = default
    user = await db.get(User, ctx["current"][0].id)
    await ready_set(db, ctx, rider_status=status, online=True)
    await db.execute(
        update(RiderDocument).values(
            status=DocumentStatus.APROBADO, updated_at=datetime.utcnow()
        )
    )
    await db.commit()
    result = await update_my_rider_profile(
        RiderUpdate(vehicle_plate="NEW-123"), db, user
    )
    expected = (
        RiderStatus.PENDIENTE
        if status in (RiderStatus.ACTIVO, RiderStatus.OCUPADO)
        else status
    )
    assert await state(db, ctx) == (expected, False)
    assert result["status"] == expected.value
    assert result["is_online"] is False
    assert set((await db.scalars(select(RiderDocument.status))).all()) == {
        DocumentStatus.RECHAZADO
    }
    audit = await db.scalar(select(AuditLog))
    assert audit.new_values["status_changed_to"] == expected.value


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [RiderStatus.ACTIVO, RiderStatus.OCUPADO])
@pytest.mark.parametrize("legacy", [False, True])
async def test_ready_telemetry_updates_coordinates_without_changing_job_status(
    submissions, status, legacy
):
    _, db, ctx = submissions
    await ready_set(db, ctx, rider_status=status)
    await db.execute(
        update(RiderDocument).values(
            status=DocumentStatus.APROBADO, updated_at=datetime.utcnow()
        )
    )
    connection = await db.connection()

    def geo_functions(conn):
        conn.connection.dbapi_connection.create_function(
            "AsEWKB", 1, lambda value: None
        )
        conn.connection.dbapi_connection.create_function(
            "ST_MakePoint", 2, lambda lng, lat: None
        )
        conn.connection.dbapi_connection.create_function(
            "ST_SetSRID", 2, lambda point, srid: None
        )

    await connection.run_sync(geo_functions)
    await db.commit()
    if legacy:
        from app.api.v1.riders import update_heartbeat

        result = await update_heartbeat(
            str(ctx["rider_id"]),
            HeartbeatRequest(lat=10, lng=-66),
            db,
            ctx["current"][0],
        )
    else:
        result = await rider_heartbeat(
            str(ctx["rider_id"]),
            HeartbeatRequest(lat=10, lng=-66),
            db,
            ctx["current"][0],
        )
    assert result["status"] == "ok"
    assert await state(db, ctx) == (status, True)
    assert (
        await db.execute(
            select(Rider.last_lat, Rider.last_lng).where(Rider.id == ctx["rider_id"])
        )
    ).one() == (10, -66)
