"""Canonical PostgreSQL claims, real UNIQUE errors and global lock ordering."""

import asyncio
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from sqlalchemy import select, func, text
from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from tests.test_document_uploads_postgresql import pg_documents  # noqa: F401
from tests.test_fleet_assignment_postgresql import pg_fleet  # noqa: F401
from tests.test_rider_profile_postgresql import profiles, load  # noqa: F401
from app.api.v1 import users as api
from app.models.user import User, UserRole
from app.services.user_emails import claim_email, normalize_email
from app.services.user_revision import user_revision
from app.services.rider_profile_revision import (
    ensure_profile_revision,
    profile_revision,
)
from app.services.fleet_assignment import lock_vehicles

ACTOR = SimpleNamespace(id=None, role=UserRole.GERENTE)


async def create(sessions, email):
    async with sessions() as db:
        return await api.create_user(
            api.UserCreateBody(
                email=email,
                password="ValidPassword123!",
                first_name="New",
                last_name="User",
            ),
            db,
            ACTOR,
        )


async def edit(sessions, uid, revision, email):
    async with sessions() as db:
        return await api.update_user(
            str(uid),
            api.UserUpdateBody(
                email=email, phone="+111111111", expected_user_revision=revision
            ),
            db,
            ACTOR,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("operations", ["create-create", "edit-edit", "create-edit"])
async def test_only_one_concurrent_email_claim_is_committed(profiles, operations):
    sessions, riders, _ = profiles
    async with sessions() as db:
        rows = [(await load(db, r)).user for r in riders]
        ids, revisions = [u.id for u in rows], [user_revision(u) for u in rows]
    first = (
        create(sessions, " Race@Example.com ")
        if operations.startswith("create")
        else edit(sessions, ids[0], revisions[0], " Race@Example.com ")
    )
    second = (
        create(sessions, "race@example.com")
        if operations.endswith("create")
        else edit(sessions, ids[1], revisions[1], "race@example.com")
    )
    results = await asyncio.wait_for(
        asyncio.gather(first, second, return_exceptions=True), 15
    )
    assert sum(isinstance(r, dict) for r in results) == 1, results
    error = next(r for r in results if isinstance(r, Exception))
    assert isinstance(error, HTTPException) and error.status_code == 409
    assert error.detail["code"] == "USER_EMAIL_CONFLICT"
    async with sessions() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(User)
                .where(User.email == "race@example.com")
            )
            == 1
        )
        for uid, revision in zip(ids, revisions):
            user = await db.get(User, uid)
            if user.email != "race@example.com":
                assert user_revision(user) == revision


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "edit"])
async def test_native_unique_fallback_is_precise_and_atomic(
    profiles, operation, monkeypatch
):
    sessions, riders, _ = profiles
    async with sessions() as db:
        first, second = [(await load(db, r)).user for r in riders]
        first.email = "one@example.com"
        second.email = "two@example.com"
        await db.commit()
        uid, revision = first.id, user_revision(first)

    async def bypass(db, email, **kwargs):
        return normalize_email(email)

    monkeypatch.setattr(api, "claim_email", bypass)
    with pytest.raises(HTTPException) as error:
        if operation == "create":
            await create(sessions, "two@example.com")
        else:
            await edit(sessions, uid, revision, "two@example.com")
    assert (
        error.value.status_code == 409
        and error.value.detail["code"] == "USER_EMAIL_CONFLICT"
    )
    async with sessions() as db:
        assert user_revision(await db.get(User, uid)) == revision


@pytest.mark.asyncio
async def test_email_claim_does_not_hold_user_while_waiting_for_vehicle_chain(profiles):
    sessions, riders, vehicles = profiles
    claimed = asyncio.Event()
    async with sessions() as parent:
        await lock_vehicles(parent, {vehicles[0]})
        rider = await load(parent, riders[0])
        uid, urev, prev = (
            rider.user_id,
            user_revision(rider.user),
            profile_revision(rider),
        )

        async def reservation_then_vehicle():
            async with sessions() as db:
                await claim_email(db, "chain@example.com")
                claimed.set()
                await lock_vehicles(db, {vehicles[0]})
                await db.rollback()

        reserve = asyncio.create_task(reservation_then_vehicle())
        await asyncio.wait_for(claimed.wait(), 5)
        changing = asyncio.create_task(edit(sessions, uid, urev, "chain@example.com"))
        try:
            await asyncio.sleep(0.1)
            assert not reserve.done() and not changing.done()
            await asyncio.wait_for(ensure_profile_revision(parent, rider, prev), 5)
            await parent.commit()
        finally:
            await parent.rollback()
            await asyncio.wait_for(
                asyncio.gather(reserve, changing, return_exceptions=True), 15
            )
    assert (await changing)["email"] == "chain@example.com"


@pytest.mark.asyncio
async def test_rollback_releases_canonical_email_claim(profiles):
    sessions, _, _ = profiles
    async with sessions() as first:
        await claim_email(first, " Release@Example.com ")
        task = asyncio.create_task(create(sessions, "release@example.com"))
        await asyncio.sleep(0.1)
        assert not task.done()
        await first.rollback()
    assert (await asyncio.wait_for(task, 10))["email"] == "release@example.com"


@pytest.mark.asyncio
async def test_multiple_historical_equivalents_are_a_business_conflict(profiles):
    sessions, riders, _ = profiles
    async with sessions() as db:
        rows = [(await load(db, r)).user for r in riders]
        rows[0].email = " \tHISTORY@example.com\n"
        rows[1].email = "history@example.com"
        await db.commit()
    with pytest.raises(HTTPException) as error:
        await create(sessions, "HISTORY@example.com")
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_unrelated_unique_constraint_is_not_reported_as_email(profiles):
    from sqlalchemy.exc import IntegrityError

    sessions, riders, _ = profiles
    async with sessions() as db:
        first, second = [(await load(db, r)).user for r in riders]
        second.phone = "+111111111"
        uid, revision = first.id, user_revision(first)
        await db.execute(text("CREATE UNIQUE INDEX test_unique_phone ON users(phone)"))
        await db.commit()
    with pytest.raises(IntegrityError):
        await edit(sessions, uid, revision, "free@example.com")
    async with sessions() as db:
        assert user_revision(await db.get(User, uid)) == revision
