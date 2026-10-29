"""Native row locks, stale identity maps, transaction rollback and migration safety."""

import asyncio
import importlib.util
from pathlib import Path
import secrets
from datetime import timedelta
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from app.api.v1 import auth, users
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_active_user,
    hash_password,
)
from app.models.user import User, UserRole, utc_now_naive
from app.services.password_reset import consume_password_reset, reset_token_digest
from app.services.token_revocation import revoke_user_tokens


@pytest.fixture
async def account(pg_wallets):
    sessions, _, _ = pg_wallets
    async with sessions() as db:
        uid = await db.scalar(select(User.id).limit(1))
        user = await db.get(User, uid)
        user.role = UserRole.OPERADOR
        await db.commit()
    return sessions, uid


async def epoch(sessions, uid):
    async with sessions() as db:
        return await db.scalar(select(User.token_version).where(User.id == uid))


@pytest.mark.asyncio
async def test_only_one_of_four_concurrent_logouts_can_retire_same_epoch(account):
    sessions, uid = account
    token = create_access_token(uid)

    async def logout():
        async with sessions() as db:
            try:
                return await auth.logout(token=token, db=db)
            except HTTPException as e:
                return e.status_code

    results = await asyncio.gather(*(logout() for _ in range(4)))
    assert sum(isinstance(r, dict) for r in results) == 1 and results.count(401) == 3
    assert await epoch(sessions, uid) == 1
    async with sessions() as db:
        fresh = create_access_token(uid, token_version=1)
        assert (await get_current_active_user(token=fresh, db=db)).id == uid
        with pytest.raises(HTTPException):
            await auth.logout(token=token, db=db)
        assert (await get_current_active_user(token=fresh, db=db)).id == uid


@pytest.mark.asyncio
async def test_unconditional_concurrent_security_changes_do_not_lose_increments(
    account,
):
    sessions, uid = account

    async def revoke():
        async with sessions() as db:
            value = await revoke_user_tokens(db, uid)
            await db.commit()
            return value

    versions = []
    for _ in range(5):
        versions.extend(await asyncio.gather(*(revoke() for _ in range(4))))
    assert sorted(versions) == list(range(1, 21))
    assert await epoch(sessions, uid) == 20


@pytest.mark.asyncio
@pytest.mark.parametrize("dependency", [auth.get_current_user, get_current_active_user])
async def test_other_worker_revocation_overrides_preloaded_identity_map(
    account, dependency
):
    sessions, uid = account
    token = create_access_token(uid)
    async with sessions() as reader:
        cached = await reader.get(User, uid)
        assert (await dependency(token=token, db=reader)).id == uid
        async with sessions() as writer:
            await revoke_user_tokens(writer, uid)
            await writer.commit()
        assert cached.token_version == 0
        with pytest.raises(HTTPException) as e:
            await dependency(token=token, db=reader)
        assert e.value.status_code == 401 and cached.token_version == 1


@pytest.mark.asyncio
async def test_refresh_in_flight_at_logout_cannot_issue_usable_old_epoch(
    account, monkeypatch
):
    sessions, uid = account
    entered, resume = asyncio.Event(), asyncio.Event()
    original = auth.ensure_session_allowed

    async def pause(db, user):
        await original(db, user)
        entered.set()
        await asyncio.wait_for(resume.wait(), 5)

    monkeypatch.setattr(auth, "ensure_session_allowed", pause)

    async def refresh():
        async with sessions() as db:
            return await auth.refresh_token(
                auth.RefreshRequest(refresh_token=create_refresh_token(uid)), db
            )

    task = asyncio.create_task(refresh())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        async with sessions() as db:
            await auth.logout(token=create_access_token(uid), db=db)
    finally:
        resume.set()
    result = await asyncio.wait_for(task, 5)
    assert decode_token(result.access_token)["ver"] == 0
    async with sessions() as db:
        with pytest.raises(HTTPException) as e:
            await get_current_active_user(token=result.access_token, db=db)
        assert e.value.status_code == 401
    async with sessions() as db:
        with pytest.raises(HTTPException) as e:
            await auth.refresh_token(
                auth.RefreshRequest(refresh_token=result.refresh_token), db
            )
        assert e.value.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["logout", "reset", "admin_password"])
async def test_commit_failure_rolls_back_epoch_and_password_together(
    account, monkeypatch, operation
):
    sessions, uid = account
    token = secrets.token_urlsafe(32)
    old_hash = hash_password("OriginalPassword123!")
    async with sessions() as db:
        u = await db.get(User, uid)
        u.hashed_password = old_hash
        u.reset_token = reset_token_digest(token)
        u.reset_token_expires = utc_now_naive() + timedelta(hours=1)
        manager = User(
            email="manager@example.test",
            hashed_password="unused",
            first_name="Manager",
            last_name="Test",
            role=UserRole.GERENTE,
        )
        db.add(manager)
        await db.commit()
        manager_id = manager.id
    async with sessions() as db:

        async def failed_commit():
            raise RuntimeError("injected commit failure")

        monkeypatch.setattr(db, "commit", failed_commit)
        with pytest.raises(RuntimeError, match="injected commit failure"):
            if operation == "logout":
                await auth.logout(token=create_access_token(uid), db=db)
            elif operation == "reset":
                await consume_password_reset(db, token, "ChangedPassword123!")
            else:
                manager = await db.get(User, manager_id)
                await users.update_user_password(
                    str(uid),
                    users.UserPasswordBody(password="ChangedPassword123!"),
                    db,
                    manager,
                )
        await db.rollback()
    async with sessions() as db:
        u = await db.get(User, uid)
        assert (
            u.token_version == 0
            and u.hashed_password == old_hash
            and u.reset_token == reset_token_digest(token)
        )


@pytest.mark.asyncio
async def test_revocation_is_account_scoped_and_persists_across_new_sessions(account):
    sessions, uid = account
    async with sessions() as db:
        other = await db.scalar(select(User.id).where(User.id != uid))
        await revoke_user_tokens(db, uid)
        await db.commit()
    async with sessions() as db:
        assert await db.scalar(select(User.token_version).where(User.id == other)) == 0
        assert await db.scalar(select(User.token_version).where(User.id == uid)) == 1


def migration():
    path = (
        Path(__file__).parents[1]
        / "alembic/versions/20261028_add_user_token_version.py"
    )
    spec = importlib.util.spec_from_file_location("epoch_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_migration_populates_existing_rows_and_keeps_server_default(account):
    sessions, _ = account
    async with sessions() as db:
        conn = await db.connection()

        def migrate(connection):
            module = migration()
            module.op = Operations(MigrationContext.configure(connection))
            module.downgrade()
            module.upgrade()
            assert (
                connection.execute(
                    text("SELECT count(*) FROM users WHERE token_version = 0")
                ).scalar_one()
                == 2
            )
            default = connection.execute(
                text(
                    "SELECT column_default FROM information_schema.columns WHERE table_schema = current_schema() AND table_name='users' AND column_name='token_version'"
                )
            ).scalar_one()
            assert default is not None and "0" in default

        await conn.run_sync(migrate)
        await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [-1, None])
async def test_database_refuses_negative_or_null_epochs(account, invalid):
    sessions, uid = account
    async with sessions() as db:
        with pytest.raises(IntegrityError):
            await db.execute(
                text("UPDATE users SET token_version = :value WHERE id = :uid"),
                {"value": invalid, "uid": uid},
            )
        await db.rollback()
    assert await epoch(sessions, uid) == 0


@pytest.mark.asyncio
async def test_downgrade_cannot_resurrect_revoked_credentials(account):
    sessions, uid = account
    async with sessions() as db:
        await revoke_user_tokens(db, uid)
        await db.commit()
    async with sessions() as db:
        conn = await db.connection()

        def downgrade(connection):
            module = migration()
            module.op = Operations(MigrationContext.configure(connection))
            with pytest.raises(RuntimeError, match="Cannot remove credential epochs"):
                module.downgrade()

        await conn.run_sync(downgrade)
    assert await epoch(sessions, uid) == 1


@pytest.mark.asyncio
async def test_epoch_exhaustion_cannot_commit_password_without_revocation(account):
    from app.core.token_version import MAX_TOKEN_VERSION

    sessions, uid = account
    async with sessions() as db:
        u = await db.get(User, uid)
        u.token_version = MAX_TOKEN_VERSION
        old_hash = u.hashed_password
        manager = User(
            email="max-manager@example.test",
            hashed_password="unused",
            first_name="Manager",
            last_name="Test",
            role=UserRole.GERENTE,
        )
        db.add(manager)
        await db.commit()
        mid = manager.id
    async with sessions() as db:
        manager = await db.get(User, mid)
        with pytest.raises(HTTPException) as e:
            await users.update_user_password(
                str(uid),
                users.UserPasswordBody(password="ChangedPassword123!"),
                db,
                manager,
            )
        assert e.value.status_code == 409
        await db.rollback()
    async with sessions() as db:
        u = await db.get(User, uid)
        assert u.token_version == MAX_TOKEN_VERSION and u.hashed_password == old_hash


@pytest.mark.asyncio
async def test_revocation_in_shared_transaction_rolls_back_other_security_changes(
    account,
):
    sessions, uid = account
    async with sessions() as db:
        u = await db.get(User, uid)
        u.role = UserRole.AUDITOR
        await revoke_user_tokens(db, uid)
        await db.rollback()
    async with sessions() as db:
        u = await db.get(User, uid)
        assert u.token_version == 0 and u.role == UserRole.OPERADOR
