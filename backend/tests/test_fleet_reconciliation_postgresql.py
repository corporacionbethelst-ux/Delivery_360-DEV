"""Native enum comparisons, read-only snapshots and committed assignments."""

import asyncio
from datetime import date
import pytest
from sqlalchemy import select, text, update
from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from tests.test_document_uploads_postgresql import pg_documents  # noqa: F401
from tests.test_fleet_assignment_postgresql import pg_fleet, assign  # noqa: F401
from app.models.rider import Rider
from app.models.vehicle import Vehicle
from app.services.fleet_assignment import available_vehicle_condition
from app.services.fleet_reconciliation import reconcile_fleet, FleetFindingCode


@pytest.fixture
async def insured_fleet(pg_fleet):
    sessions, _, _ = pg_fleet
    async with sessions() as db:
        await db.execute(update(Vehicle).values(insurance_expiry=date.max))
        await db.commit()
    return pg_fleet


@pytest.mark.asyncio
async def test_report_succeeds_inside_postgresql_read_only_transaction(insured_fleet):
    sessions, riders, _ = insured_fleet
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
async def test_native_enum_metadata_and_duplicate_checks_and_pagination(insured_fleet):
    sessions, riders, vehicles = insured_fleet
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
    insured_fleet,
):
    sessions, riders, vehicles = insured_fleet
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
async def test_cursor_returns_new_current_page_after_committed_repair(insured_fleet):
    sessions, riders, _ = insured_fleet
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


@pytest.mark.asyncio
async def test_native_duplicate_plate_report_is_read_only_and_pages_all_members(
    insured_fleet,
):
    sessions, _, vehicles = insured_fleet
    async with sessions() as db:
        await db.execute(
            update(Vehicle)
            .where(Vehicle.id == vehicles[0])
            .values(plate=" \tlegacy-1\r\n", status="BAJA")
        )
        await db.execute(
            update(Vehicle).where(Vehicle.id == vehicles[1]).values(plate="LEGACY-1")
        )
        await db.commit()
    async with sessions() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        first = await reconcile_fleet(
            db, code=FleetFindingCode.DUPLICATE_PLATE, limit=1
        )
        assert first.has_more and first.next_cursor
        second = await reconcile_fleet(
            db, code=FleetFindingCode.DUPLICATE_PLATE, limit=1, cursor=first.next_cursor
        )
        assert not second.has_more
        findings = first.findings + second.findings
        assert {item.entity_id for item in findings} == set(vehicles)
        assert all(
            item.entity_type == "vehicle" and item.related_id is None
            for item in findings
        )
        assert set((await db.scalars(select(Vehicle.plate))).all()) == {
            " \tlegacy-1\r\n",
            "LEGACY-1",
        }
        assert not db.dirty and not db.new and not db.deleted


@pytest.mark.asyncio
async def test_duplicate_plate_report_ignores_uncommitted_edits_and_observes_commit(
    insured_fleet,
):
    sessions, _, vehicles = insured_fleet

    async def read():
        async with sessions() as db:
            return await reconcile_fleet(db, code=FleetFindingCode.DUPLICATE_PLATE)

    async with sessions() as writer:
        await writer.execute(
            update(Vehicle).where(Vehicle.id == vehicles[0]).values(plate=" fleet-1 ")
        )
        before = await asyncio.wait_for(read(), 10)
        assert not before.findings
        await writer.commit()
    after = await read()
    assert {item.entity_id for item in after.findings} == set(vehicles)


@pytest.mark.asyncio
async def test_insurance_diagnostics_native_dates_in_read_only_transaction(
    insured_fleet,
):
    from datetime import datetime, timezone
    from unittest.mock import patch

    sessions, _, vehicles = insured_fleet
    async with sessions() as db:
        await db.execute(
            update(Vehicle)
            .where(Vehicle.id == vehicles[0])
            .values(insurance_expiry=date(2026, 10, 24))
        )
        await db.execute(
            update(Vehicle)
            .where(Vehicle.id == vehicles[1])
            .values(insurance_expiry=None)
        )
        await db.commit()
    async with sessions() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        with patch("app.services.fleet_reconciliation.datetime") as clock:
            clock.now.return_value = datetime(2026, 10, 25, tzinfo=timezone.utc)
            report = await reconcile_fleet(db)
        assert report.insurance_reference_date == date(2026, 10, 25)
        assert {(f.code, f.entity_id) for f in report.findings} == {
            (FleetFindingCode.INSURANCE_EXPIRED, vehicles[0]),
            (FleetFindingCode.INSURANCE_EXPIRY_MISSING, vehicles[1]),
        }
        assert not db.new and not db.dirty and not db.deleted
        await db.rollback()
