"""GPS persistence and concurrency against real parent/document locks."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update, text, func

from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from tests.test_document_uploads_postgresql import pg_documents  # noqa: F401
from tests.test_document_review_postgresql import complete_set, revision
from app.models.rider import Rider, RiderStatus
from app.models.location import RiderLiveLocation
from app.services.document_review import lock_rider, delete_reviewed_document
from app.services.tracking_service import TrackingService


@pytest.fixture
async def reporting(pg_documents):
    sessions, riders, doc_id, root = pg_documents
    await complete_set(sessions, riders[0], doc_id, root, status=RiderStatus.ACTIVO)
    async with sessions() as db:
        await db.execute(
            text(
                "ALTER TABLE riders ADD COLUMN last_lat DOUBLE PRECISION, ADD COLUMN last_lng DOUBLE PRECISION, ADD COLUMN last_location_at TIMESTAMP"
            )
        )
        connection = await db.connection()
        await connection.run_sync(RiderLiveLocation.__table__.create)
        await db.commit()
    return sessions, riders[0], doc_id


async def report(sessions, rider_id):
    async with sessions() as db:
        service = TrackingService(db)
        service.broadcast_location_update = AsyncMock()
        location = await service.record_location_update(rider_id, 10, -66)
        service.broadcast_location_update.assert_awaited_once()
        return location


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [RiderStatus.ACTIVO, RiderStatus.OCUPADO])
async def test_ready_tracking_persists_snapshot_history_and_broadcast(
    reporting, status
):
    sessions, rider_id, _ = reporting
    async with sessions() as db:
        await db.execute(
            update(Rider).where(Rider.id == rider_id).values(status=status)
        )
        await db.commit()
    result = await report(sessions, rider_id)
    assert result.latitude == 10 and result.longitude == -66
    async with sessions() as db:
        assert (
            await db.execute(
                select(
                    Rider.status, Rider.is_online, Rider.last_lat, Rider.last_lng
                ).where(Rider.id == rider_id)
            )
        ).one() == (status, True, 10, -66)
        assert await db.scalar(select(func.count()).select_from(RiderLiveLocation)) == 1


@pytest.mark.asyncio
async def test_suspension_committed_while_report_waits_cannot_be_overwritten(reporting):
    sessions, rider_id, _ = reporting
    async with sessions() as admin:
        await lock_rider(admin, rider_id)
        pending = asyncio.create_task(report(sessions, rider_id))
        await asyncio.sleep(0.1)
        assert not pending.done()
        await admin.execute(
            update(Rider)
            .where(Rider.id == rider_id)
            .values(status=RiderStatus.SUSPENDIDO, is_online=False)
        )
        await admin.commit()
    with pytest.raises(HTTPException) as error:
        await asyncio.wait_for(pending, 10)
    assert error.value.status_code == 403
    async with sessions() as db:
        assert (
            await db.execute(
                select(Rider.status, Rider.is_online).where(Rider.id == rider_id)
            )
        ).one() == (RiderStatus.SUSPENDIDO, False)
        assert await db.scalar(select(func.count()).select_from(RiderLiveLocation)) == 0


@pytest.mark.asyncio
async def test_delete_and_report_never_leave_documentless_rider_online(reporting):
    sessions, rider_id, doc_id = reporting
    token = await revision(sessions, doc_id)

    async def delete():
        async with sessions() as db:
            await delete_reviewed_document(db, doc_id, token)
            await db.commit()

    results = await asyncio.gather(
        delete(), report(sessions, rider_id), return_exceptions=True
    )
    assert results[0] is None
    assert (
        not isinstance(results[1], Exception)
        or isinstance(results[1], HTTPException)
        and results[1].status_code == 403
    )
    async with sessions() as db:
        assert (
            await db.execute(
                select(Rider.status, Rider.is_online).where(Rider.id == rider_id)
            )
        ).one() == (RiderStatus.PENDIENTE, False)


@pytest.mark.asyncio
async def test_suspension_waits_for_inflight_report_then_forces_offline(
    reporting, monkeypatch
):
    from app.services import tracking_service

    sessions, rider_id, _ = reporting
    checked = asyncio.Event()
    release = asyncio.Event()
    original = tracking_service.ensure_rider_can_report_online

    async def pause_after_check(*args, **kwargs):
        await original(*args, **kwargs)
        checked.set()
        await release.wait()

    monkeypatch.setattr(
        tracking_service, "ensure_rider_can_report_online", pause_after_check
    )
    reporting_task = asyncio.create_task(report(sessions, rider_id))
    await asyncio.wait_for(checked.wait(), 10)

    async def suspend():
        async with sessions() as db:
            await lock_rider(db, rider_id)
            await db.execute(
                update(Rider)
                .where(Rider.id == rider_id)
                .values(status=RiderStatus.SUSPENDIDO, is_online=False)
            )
            await db.commit()

    suspension_task = asyncio.create_task(suspend())
    try:
        await asyncio.sleep(0.1)
        assert not suspension_task.done()
    finally:
        release.set()
    await asyncio.wait_for(asyncio.gather(reporting_task, suspension_task), 10)
    async with sessions() as db:
        assert (
            await db.execute(
                select(Rider.status, Rider.is_online).where(Rider.id == rider_id)
            )
        ).one() == (RiderStatus.SUSPENDIDO, False)
        assert await db.scalar(select(func.count()).select_from(RiderLiveLocation)) == 1
