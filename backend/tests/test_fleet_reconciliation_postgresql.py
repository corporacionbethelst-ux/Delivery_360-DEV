"""Native enum comparisons, read-only snapshots and committed assignments."""

import asyncio
import pytest
from sqlalchemy import select, text, update
from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from tests.test_document_uploads_postgresql import pg_documents  # noqa: F401
from tests.test_fleet_assignment_postgresql import pg_fleet, assign  # noqa: F401
from app.models.rider import Rider
from app.models.vehicle import Vehicle
from app.services.fleet_assignment import available_vehicle_condition
from app.services.fleet_reconciliation import reconcile_fleet, FleetFindingCode


@pytest.mark.asyncio
async def test_report_succeeds_inside_postgresql_read_only_transaction(pg_fleet):
    sessions, riders, _ = pg_fleet
    async with sessions() as db:
        await db.execute(
            update(Rider)
            .where(Rider.id == riders[0])
            .values(vehicle_ownership_type="EMPRESA")
        )
        await db.commit()
    async with sessions() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        result = await reconcile_fleet(db)
        assert [item.code for item in result.findings] == [
            FleetFindingCode.COMPANY_WITHOUT_VEHICLE
        ]
        assert result.findings[0].entity_id == riders[0]
        assert (
            await db.execute(text("SHOW transaction_read_only"))
        ).scalar_one() == "on"
        assert not db.new and not db.dirty and not db.deleted
        await db.rollback()


@pytest.mark.asyncio
async def test_native_enum_metadata_and_duplicate_checks_and_pagination(pg_fleet):
    sessions, riders, vehicles = pg_fleet
    await assign(sessions, riders[0], vehicles[0])
    async with sessions() as db:
        assert (await reconcile_fleet(db)).findings == []
        await db.execute(
            update(Rider)
            .where(Rider.id == riders[1])
            .values(
                vehicle_ownership_type="EMPRESA",
                assigned_vehicle_id=vehicles[0],
                vehicle_type="AUTO",
                vehicle_plate="OLD",
                vehicle_model=None,
            )
        )
        await db.execute(
            update(Vehicle)
            .where(Vehicle.id == vehicles[0])
            .values(status="MANTENIMIENTO")
        )
        await db.commit()
    async with sessions() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        expected = await reconcile_fleet(db, limit=500)
        codes = {item.code for item in expected.findings}
        assert {
            FleetFindingCode.METADATA_MISMATCH,
            FleetFindingCode.MULTIPLE_RIDERS,
            FleetFindingCode.OWNER_MISMATCH,
            FleetFindingCode.INACTIVE_VEHICLE,
        }.issubset(codes)
        found, cursor = [], None
        for _ in range(20):
            page = await reconcile_fleet(db, limit=1, cursor=cursor)
            found.extend(page.findings)
            if not page.has_more:
                break
            assert cursor != page.next_cursor
            cursor = page.next_cursor
        assert found == expected.findings
        assert (
            len(
                [
                    item
                    for item in found
                    if item.code == FleetFindingCode.MULTIPLE_RIDERS
                ]
            )
            == 2
        )


@pytest.mark.asyncio
async def test_report_and_catalog_ignore_uncommitted_assignment_then_observe_commit(
    pg_fleet,
):
    sessions, riders, vehicles = pg_fleet
    async with sessions() as writer:
        await writer.execute(
            update(Rider)
            .where(Rider.id == riders[0])
            .values(vehicle_ownership_type="EMPRESA", assigned_vehicle_id=vehicles[0])
        )

        async def read():
            async with sessions() as db:
                report = await reconcile_fleet(db)
                available = list(
                    (
                        await db.scalars(
                            select(Vehicle.id).where(available_vehicle_condition())
                        )
                    ).all()
                )
                return report, available

        before, available = await asyncio.wait_for(read(), 10)
        assert before.findings == []
        assert vehicles[0] in available
        await writer.commit()
    after, available = await read()
    assert FleetFindingCode.OWNER_MISMATCH in {item.code for item in after.findings}
    assert vehicles[0] not in available


@pytest.mark.asyncio
async def test_cursor_returns_new_current_page_after_committed_repair(pg_fleet):
    sessions, riders, _ = pg_fleet
    async with sessions() as db:
        await db.execute(update(Rider).values(vehicle_ownership_type="EMPRESA"))
        await db.commit()
        first = await reconcile_fleet(db, limit=1)
        assert first.has_more and first.next_cursor
        remaining = next(
            rider for rider in riders if rider != first.findings[0].entity_id
        )
        await db.execute(
            update(Rider)
            .where(Rider.id == remaining)
            .values(vehicle_ownership_type="PROPIO")
        )
        await db.commit()
        second = await reconcile_fleet(db, limit=1, cursor=first.next_cursor)
        assert second.findings == [] and not second.has_more
