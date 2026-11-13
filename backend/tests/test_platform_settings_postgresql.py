"""Native concurrent transactions in a private schema of an explicit test_* DB."""

import asyncio
import os
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.v1.settings import (
    PlatformSettingsUpdate,
    _coerce_settings,
    _ensure_default_settings,
    update_platform_settings,
)
from app.models.audit_log import AuditLog
from app.models.platform_setting import PlatformSetting
from app.models.user import User, UserRole


@pytest.fixture
async def settings_pg():
    raw_url = os.environ.get("TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL row-lock tests")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or not (url.database or "").startswith(
        "test_"
    ):
        pytest.fail(
            "Settings integration tests require an explicit PostgreSQL test_* DB"
        )
    url = url.set(drivername="postgresql+asyncpg")
    schema = "settings_test_" + uuid4().hex
    admin = create_async_engine(url, poolclass=NullPool)
    engine = None
    try:
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(
            url,
            poolclass=NullPool,
            connect_args={"server_settings": {"search_path": schema}},
        )
        async with engine.begin() as connection:
            for model in (User, PlatformSetting, AuditLog):
                await connection.run_sync(model.__table__.create)
        sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with sessions() as db:
            actor = User(
                email="settings-pg@example.test",
                hashed_password="unused-synthetic",
                first_name="Settings",
                last_name="Test",
                role=UserRole.SUPERADMIN,
            )
            db.add(actor)
            await db.commit()
        yield sessions, actor
    finally:
        if engine is not None:
            await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()


async def snapshot(sessions):
    async with sessions() as db:
        return _coerce_settings(await _ensure_default_settings(db))


async def test_simultaneous_initial_reads_create_one_row_per_key(settings_pg):
    sessions, _ = settings_pg
    results = await asyncio.gather(*(snapshot(sessions) for _ in range(8)))
    assert len({row["revision"] for row in results}) == 1
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(PlatformSetting)) == 8


async def test_same_revision_has_exactly_one_winner_and_one_audit(settings_pg):
    sessions, actor = settings_pg
    before = await snapshot(sessions)
    ready, start = asyncio.Queue(), asyncio.Event()

    async def writer(amount):
        async with sessions() as db:
            ready.put_nowait(True)
            await start.wait()
            try:
                return await update_platform_settings(
                    PlatformSettingsUpdate(delivery_fee_base=amount),
                    db,
                    actor,
                    '"' + before["revision"] + '"',
                )
            except HTTPException as error:
                await db.rollback()
                return error.status_code

    tasks = [asyncio.create_task(writer(amount)) for amount in (4, 9)]
    await asyncio.wait_for(ready.get(), timeout=5)
    await asyncio.wait_for(ready.get(), timeout=5)
    start.set()
    results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=15)
    winners = [result for result in results if isinstance(result, dict)]
    assert len(winners) == 1
    assert results.count(412) == 1
    assert await snapshot(sessions) == winners[0]
    async with sessions() as db:
        audits = list(await db.scalars(select(AuditLog)))
        assert len(audits) == 1
        assert audits[0].new_values == {
            "delivery_fee_base": winners[0]["delivery_fee_base"]
        }


async def test_lock_refreshes_a_preloaded_identity_map(settings_pg):
    sessions, actor = settings_pg
    before = await snapshot(sessions)
    async with sessions() as stale:
        cached = await _ensure_default_settings(stale)
        assert cached["delivery_fee_base"].value is None
        async with sessions() as other:
            await update_platform_settings(
                PlatformSettingsUpdate(delivery_fee_base=9),
                other,
                actor,
                '"' + before["revision"] + '"',
            )
        with pytest.raises(HTTPException) as error:
            await update_platform_settings(
                PlatformSettingsUpdate(delivery_fee_base=4),
                stale,
                actor,
                '"' + before["revision"] + '"',
            )
        assert error.value.status_code == 412
        await stale.rollback()
    assert (await snapshot(sessions))["delivery_fee_base"] == 9


async def test_audit_failure_rolls_back_values_and_revision(settings_pg, monkeypatch):
    sessions, actor = settings_pg
    before = await snapshot(sessions)
    async with sessions() as db:
        original = db.add

        def fail_audit(row):
            if isinstance(row, AuditLog):
                raise RuntimeError("synthetic audit failure")
            original(row)

        monkeypatch.setattr(db, "add", fail_audit)
        with pytest.raises(RuntimeError, match="synthetic audit failure"):
            await update_platform_settings(
                PlatformSettingsUpdate(delivery_fee_base=9),
                db,
                actor,
                '"' + before["revision"] + '"',
            )
        await db.rollback()
    assert await snapshot(sessions) == before
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 0
