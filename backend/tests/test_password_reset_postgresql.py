"""Native PostgreSQL races, conditional writes and transactional reset rollback."""

import asyncio
import secrets
from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update, func

from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from app.api.v1 import auth
from app.core.security import hash_password, verify_password
from app.models.user import User, utc_now_naive
from app.schemas.auth import ResetPasswordRequest
from app.services import password_reset as service


@pytest.fixture
async def pg_reset(pg_wallets):
    sessions, _, _ = pg_wallets
    token = secrets.token_urlsafe(32)
    original_hash = hash_password("OriginalPassword123!")
    async with sessions() as db:
        uid = await db.scalar(select(User.id).order_by(User.id).limit(1))
        await db.execute(
            update(User)
            .where(User.id == uid)
            .values(
                hashed_password=original_hash,
                reset_token=service.reset_token_digest(token),
                reset_token_expires=utc_now_naive() + timedelta(hours=1),
            )
        )
        await db.commit()
    return sessions, uid, token, original_hash


async def consume(sessions, token, password="ChangedPassword123!"):
    async with sessions() as db:
        return await auth.reset_password(
            ResetPasswordRequest(token=token, new_password=password), db
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("workers", [2, 4])
async def test_only_one_concurrent_request_can_commit(pg_reset, monkeypatch, workers):
    sessions, uid, token, _ = pg_reset
    ready = asyncio.Event()
    entered = 0
    real_hash = service.run_in_threadpool

    async def rendezvous(*args):
        nonlocal entered
        entered += 1
        if entered == workers:
            ready.set()
        await asyncio.wait_for(ready.wait(), 5)
        return await real_hash(*args)

    monkeypatch.setattr(service, "run_in_threadpool", rendezvous)
    passwords = [f"WinnerCandidate{i}!" for i in range(workers)]
    results = await asyncio.wait_for(
        asyncio.gather(
            *(consume(sessions, token, password) for password in passwords),
            return_exceptions=True,
        ),
        15,
    )
    assert sum(isinstance(result, dict) for result in results) == 1, results
    assert (
        sum(
            isinstance(result, HTTPException) and result.status_code == 400
            for result in results
        )
        == workers - 1
    )
    winner = next(i for i, result in enumerate(results) if isinstance(result, dict))
    async with sessions() as db:
        row = await db.get(User, uid)
        assert verify_password(passwords[winner], row.hashed_password)
        assert all(
            not verify_password(password, row.hashed_password)
            for i, password in enumerate(passwords)
            if i != winner
        )
        assert row.reset_token is None and row.reset_token_expires is None


@pytest.fixture
async def hashing_pause(monkeypatch):
    entered, resume = asyncio.Event(), asyncio.Event()
    original = service.run_in_threadpool

    async def pause(*args):
        entered.set()
        await asyncio.wait_for(resume.wait(), 5)
        return await original(*args)

    monkeypatch.setattr(service, "run_in_threadpool", pause)
    return entered, resume


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["deactivate", "email", "password", "token"])
async def test_intervening_account_change_prevents_stale_consumption(
    pg_reset, hashing_pause, change
):
    sessions, uid, token, original_hash = pg_reset
    entered, resume = hashing_pause
    task = asyncio.create_task(consume(sessions, token))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        replacement = secrets.token_urlsafe(32)
        values = {
            "deactivate": {"is_active": False},
            "email": {"email": "updated@example.com"},
            "password": {"hashed_password": hash_password("AdministrativePassword!")},
            "token": {"reset_token": service.reset_token_digest(replacement)},
        }[change]
        async with sessions() as db:
            await db.execute(update(User).where(User.id == uid).values(**values))
            await db.commit()
        resume.set()
        with pytest.raises(HTTPException) as rejected:
            await asyncio.wait_for(task, 10)
        assert rejected.value.status_code == 400
        async with sessions() as db:
            row = await db.get(User, uid)
            assert row.hashed_password == values.get("hashed_password", original_hash)
            assert row.reset_token == values.get(
                "reset_token", service.reset_token_digest(token)
            )
            assert row.reset_token_expires is not None
    finally:
        resume.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_expiration_is_rechecked_after_hashing_against_db_wall_clock(
    pg_reset, hashing_pause, monkeypatch
):
    sessions, uid, token, original_hash = pg_reset
    entered, resume = hashing_pause
    task = asyncio.create_task(consume(sessions, token))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        async with sessions() as db:
            # Transaction started while the token was valid; now() would stay old.
            now = await db.scalar(select(func.timezone("UTC", func.clock_timestamp())))
            expiry = now + timedelta(milliseconds=50)
            await db.execute(
                update(User).where(User.id == uid).values(reset_token_expires=expiry)
            )
            await db.commit()
            for _ in range(100):
                current = await db.scalar(
                    select(func.timezone("UTC", func.clock_timestamp()))
                )
                if current >= expiry:
                    break
                await asyncio.sleep(0.01)
            assert current >= expiry
        # An old application clock must not make an expired DB token acceptable.
        monkeypatch.setattr(service, "utc_now_naive", lambda: now - timedelta(days=1))
        resume.set()
        with pytest.raises(HTTPException) as rejected:
            await asyncio.wait_for(task, 10)
        assert rejected.value.status_code == 400
        async with sessions() as db:
            row = await db.get(User, uid)
            assert row.hashed_password == original_hash
            assert row.reset_token == service.reset_token_digest(token)
    finally:
        resume.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["reset", "email", "deactivate"])
async def test_stale_issuance_cannot_restore_token_after_account_change(
    pg_reset, change
):
    sessions, uid, token, _ = pg_reset
    async with sessions() as stale:
        account = await stale.get(User, uid)
        if change == "reset":
            assert isinstance(await consume(sessions, token), dict)
        else:
            async with sessions() as db:
                values = (
                    {"email": "changed@example.com"}
                    if change == "email"
                    else {"is_active": False}
                )
                await db.execute(update(User).where(User.id == uid).values(**values))
                await db.commit()
        assert not await service.issue_password_reset(
            stale, account, secrets.token_urlsafe(32)
        )
    async with sessions() as db:
        row = await db.get(User, uid)
        assert (
            row.reset_token is None
            if change == "reset"
            else row.reset_token == service.reset_token_digest(token)
        )


@pytest.mark.asyncio
async def test_commit_failure_rolls_back_password_and_token_together(
    pg_reset, monkeypatch
):
    sessions, uid, token, original_hash = pg_reset
    async with sessions() as db:

        async def failed_commit():
            raise RuntimeError("injected transaction failure")

        monkeypatch.setattr(db, "commit", failed_commit)
        with pytest.raises(RuntimeError, match="injected transaction failure"):
            await auth.reset_password(
                ResetPasswordRequest(token=token, new_password="WillNotCommit123!"), db
            )
        await db.rollback()
    async with sessions() as db:
        row = await db.get(User, uid)
        assert row.hashed_password == original_hash
        assert row.reset_token == service.reset_token_digest(token)
        assert row.reset_token_expires is not None
    assert isinstance(await consume(sessions, token), dict)


@pytest.mark.asyncio
async def test_ambiguous_stored_digests_do_not_change_either_account(pg_reset):
    sessions, uid, token, original_hash = pg_reset
    async with sessions() as db:
        await db.execute(
            update(User).values(
                hashed_password=original_hash,
                reset_token=service.reset_token_digest(token),
                reset_token_expires=utc_now_naive() + timedelta(hours=1),
            )
        )
        await db.commit()
    with pytest.raises(HTTPException) as rejected:
        await consume(sessions, token)
    assert rejected.value.status_code == 400
    async with sessions() as db:
        rows = list((await db.scalars(select(User))).all())
        assert len(rows) == 2
        assert all(
            row.hashed_password == original_hash
            and row.reset_token == service.reset_token_digest(token)
            for row in rows
        )


@pytest.mark.asyncio
async def test_issuance_uses_db_clock_and_never_stores_raw_secret(
    pg_reset, monkeypatch
):
    sessions, uid, _, _ = pg_reset
    raw = secrets.token_urlsafe(32)
    monkeypatch.setattr(
        service, "utc_now_naive", lambda: utc_now_naive() - timedelta(days=1)
    )
    async with sessions() as db:
        account = await db.get(User, uid)
        assert await service.issue_password_reset(db, account, raw)
    async with sessions() as db:
        account = await db.get(User, uid)
        now = await db.scalar(select(func.timezone("UTC", func.clock_timestamp())))
        assert account.reset_token == service.reset_token_digest(raw)
        assert account.reset_token != raw
        assert (
            now + timedelta(minutes=59)
            < account.reset_token_expires
            <= now + timedelta(hours=1)
        )
    assert isinstance(await consume(sessions, raw), dict)
