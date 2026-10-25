"""Real parent/User locking prevents lost personal/tier updates."""

import asyncio
import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import load_only, raiseload
from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from tests.test_document_uploads_postgresql import pg_documents  # noqa: F401
from tests.test_fleet_assignment_postgresql import pg_fleet, assign  # noqa: F401
from app.models.rider import Rider
from app.models.user import User
from app.services.rider_profile_revision import (
    ensure_profile_revision,
    profile_revision,
)


@pytest.fixture
async def profiles(pg_fleet):
    sessions, riders, vehicles = pg_fleet
    async with sessions() as db:
        connection = await db.connection()
        await connection.run_sync(
            lambda conn: Rider.__table__.c.tier.type.create(conn, checkfirst=True)
        )
        await db.execute(
            text(
                "ALTER TABLE riders ADD COLUMN operating_zone VARCHAR(100), ADD COLUMN cpf VARCHAR(20), ADD COLUMN cnh VARCHAR(20), ADD COLUMN tier rider_tier DEFAULT 'BRONCE'"
            )
        )
        await db.commit()
    return sessions, riders, vehicles


async def load(db, rid):
    rider = await db.scalar(
        select(Rider)
        .options(
            raiseload("*"),
            load_only(
                Rider.id,
                Rider.user_id,
                Rider.operating_zone,
                Rider.cpf,
                Rider.cnh,
                Rider.tier,
            ),
        )
        .where(Rider.id == rid)
    )
    rider.user = await db.scalar(
        select(User).options(raiseload("*")).where(User.id == rider.user_id)
    )
    return rider


async def write(sessions, rid, expected, phone):
    async with sessions() as db:
        rider = await load(db, rid)
        await ensure_profile_revision(db, rider, expected)
        rider.user.phone = phone
        await db.commit()
        return phone


@pytest.mark.asyncio
async def test_two_personal_editors_only_one_commits(profiles):
    sessions, riders, _ = profiles
    async with sessions() as db:
        expected = profile_revision(await load(db, riders[0]))
    results = await asyncio.wait_for(
        asyncio.gather(
            *(
                write(sessions, riders[0], expected, phone)
                for phone in ["+111111111", "+222222222"]
            ),
            return_exceptions=True,
        ),
        15,
    )
    assert sum(isinstance(r, str) for r in results) == 1
    failure = next(r for r in results if isinstance(r, Exception))
    assert isinstance(failure, HTTPException) and failure.status_code == 409
    async with sessions() as db:
        assert (await load(db, riders[0])).user.phone == next(
            r for r in results if isinstance(r, str)
        )


@pytest.mark.asyncio
async def test_waiting_editor_refreshes_user_instead_of_trusting_identity_map(profiles):
    sessions, riders, _ = profiles
    async with sessions() as holder:
        rider = await load(holder, riders[0])
        expected = profile_revision(rider)
        await ensure_profile_revision(holder, rider, expected)
        task = asyncio.create_task(write(sessions, riders[0], expected, "+222222222"))
        await asyncio.sleep(0.1)
        assert not task.done()
        rider.user.phone = "+111111111"
        await holder.commit()
    with pytest.raises(HTTPException) as error:
        await asyncio.wait_for(task, 10)
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_personal_and_fleet_edits_finish_without_reverse_lock_order(profiles):
    sessions, riders, vehicles = profiles
    async with sessions() as editor:
        rider = await load(editor, riders[0])
        expected = profile_revision(rider)
        await ensure_profile_revision(editor, rider, expected)
        task = asyncio.create_task(assign(sessions, riders[0], vehicles[0]))
        await asyncio.sleep(0.1)
        assert not task.done()
        rider.user.phone = "+111111111"
        await editor.commit()
    await asyncio.wait_for(task, 10)
    async with sessions() as db:
        result = await load(db, riders[0])
        assert result.user.phone == "+111111111"
        assert (
            await db.scalar(
                select(Rider.assigned_vehicle_id).where(Rider.id == riders[0])
            )
            == vehicles[0]
        )
