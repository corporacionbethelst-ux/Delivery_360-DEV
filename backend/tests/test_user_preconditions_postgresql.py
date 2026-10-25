"""User row locks serialize metadata writes across user and rider protocols."""

import asyncio
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from tests.test_document_uploads_postgresql import pg_documents  # noqa: F401
from tests.test_fleet_assignment_postgresql import pg_fleet  # noqa: F401
from tests.test_rider_profile_postgresql import (
    profiles,
    load,
    write as write_rider,
)  # noqa: F401
from app.api.v1 import users as api
from app.models.user import User, UserRole
from app.services.user_revision import lock_user, user_revision
from app.services.rider_profile_revision import profile_revision


async def edit(sessions, uid, expected, phone):
    async with sessions() as db:
        actor = await db.get(User, uid)
        return await api.update_me(
            api.UserSelfUpdateBody(phone=phone, expected_user_revision=expected),
            db,
            actor,
        )


@pytest.mark.asyncio
async def test_two_user_editors_confirm_only_one(profiles):
    sessions, riders, _ = profiles
    async with sessions() as db:
        rider = await load(db, riders[0])
        uid, revision = rider.user_id, user_revision(rider.user)
    results = await asyncio.wait_for(
        asyncio.gather(
            *(edit(sessions, uid, revision, p) for p in ["+111111111", "+222222222"]),
            return_exceptions=True,
        ),
        15,
    )
    assert sum(isinstance(r, dict) for r in results) == 1
    failure = next(r for r in results if isinstance(r, Exception))
    assert isinstance(failure, HTTPException) and failure.status_code == 409


@pytest.mark.asyncio
async def test_user_and_rider_edit_cannot_both_overwrite_shared_phone(profiles):
    sessions, riders, _ = profiles
    async with sessions() as db:
        rider = await load(db, riders[0])
        uid, urev, prev = (
            rider.user_id,
            user_revision(rider.user),
            profile_revision(rider),
        )
    results = await asyncio.wait_for(
        asyncio.gather(
            edit(sessions, uid, urev, "+111111111"),
            write_rider(sessions, riders[0], prev, "+222222222"),
            return_exceptions=True,
        ),
        15,
    )
    failures = [r for r in results if isinstance(r, Exception)]
    assert (
        len(failures) == 1
        and isinstance(failures[0], HTTPException)
        and failures[0].status_code == 409
    )
    winner = next(r for r in results if not isinstance(r, Exception))
    async with sessions() as db:
        assert (await db.get(User, uid)).phone == (
            winner["phone"] if isinstance(winner, dict) else winner
        )


@pytest.mark.asyncio
async def test_edit_and_deactivation_cannot_accept_the_same_old_revision(profiles):
    sessions, riders, _ = profiles
    async with sessions() as db:
        rider = await load(db, riders[0])
        uid, revision = rider.user_id, user_revision(rider.user)
        actor_id = (await load(db, riders[1])).user_id

    async def deactivate():
        async with sessions() as db:
            return await api.delete_user(
                str(uid),
                db,
                SimpleNamespace(id=actor_id, role=UserRole.GERENTE),
                if_match=revision,
            )

    results = await asyncio.wait_for(
        asyncio.gather(
            edit(sessions, uid, revision, "+111111111"),
            deactivate(),
            return_exceptions=True,
        ),
        15,
    )
    failures = [r for r in results if isinstance(r, Exception)]
    assert (
        len(failures) == 1
        and isinstance(failures[0], HTTPException)
        and failures[0].status_code == 409
    )
    async with sessions() as db:
        user = await db.get(User, uid)
        assert (user.phone == "+111111111") is (user.is_active is True)


@pytest.mark.asyncio
async def test_waiting_manager_rechecks_new_target_role_under_lock(profiles):
    sessions, riders, _ = profiles
    async with sessions() as holder:
        rider = await load(holder, riders[0])
        uid, revision = rider.user_id, user_revision(rider.user)
        actor_id = (await load(holder, riders[1])).user_id
        user = await lock_user(holder, uid)

        async def edit_as_manager():
            async with sessions() as db:
                return await api.update_user(
                    str(uid),
                    api.UserUpdateBody(
                        phone="+111111111", expected_user_revision=revision
                    ),
                    db,
                    SimpleNamespace(id=actor_id, role=UserRole.GERENTE),
                )

        task = asyncio.create_task(edit_as_manager())
        await asyncio.sleep(0.1)
        assert not task.done()
        user.role = UserRole.SUPERADMIN
        await holder.commit()
    with pytest.raises(HTTPException) as error:
        await asyncio.wait_for(task, 10)
    assert error.value.status_code == 403
