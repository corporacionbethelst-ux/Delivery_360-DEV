"""Exercise enum upgrade/downgrade on disposable native PostgreSQL schemas."""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

spec = importlib.util.spec_from_file_location(
    "cancel58_migration",
    Path(__file__).parents[1] / "alembic/versions/20261030_delivery_cancellation.py",
)
revision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(revision)


@pytest.fixture
async def migration_db():
    raw = os.environ.get("TEST_DATABASE_URL")
    if not raw:
        pytest.skip("TEST_DATABASE_URL required")
    url = make_url(raw)
    assert url.get_backend_name() == "postgresql" and (url.database or "").startswith(
        "test_"
    )
    admin = create_async_engine(
        url.set(drivername="postgresql+asyncpg"), poolclass=NullPool
    )
    schema = "cancel_enum_" + uuid4().hex
    async with admin.begin() as db:
        await db.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        url.set(drivername="postgresql+asyncpg"),
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": schema + ",public"}},
    )
    try:
        async with engine.begin() as db:
            labels = ",".join("'" + label + "'" for label in revision.BEFORE)
            await db.execute(
                text("CREATE TYPE deliverystatus AS ENUM (" + labels + ")")
            )
            await db.execute(
                text(
                    "CREATE TABLE deliveries(id INTEGER PRIMARY KEY, status deliverystatus NOT NULL DEFAULT 'PENDIENTE')"
                )
            )
            await db.execute(
                text(
                    "INSERT INTO deliveries(id,status) VALUES(1,'EN_ROUTE'),(2,'COMPLETADA')"
                )
            )
        yield engine
    finally:
        await engine.dispose()
        async with admin.begin() as db:
            await db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


async def run(engine, direction):
    def migrate(conn):
        with Operations.context(MigrationContext.configure(conn)):
            getattr(revision, direction)()

    async with engine.begin() as db:
        await db.run_sync(migrate)


async def labels(engine):
    async with engine.connect() as db:
        return list(
            (
                await db.execute(
                    text(
                        "SELECT enumlabel FROM pg_enum WHERE enumtypid='deliverystatus'::regtype ORDER BY enumsortorder"
                    )
                )
            ).scalars()
        )


@pytest.mark.asyncio
async def test_upgrade_is_additive_idempotent_and_downgrade_preserves_defaults_and_rows(
    migration_db,
):
    engine = migration_db
    await run(engine, "upgrade")
    await run(engine, "upgrade")
    assert await labels(engine) == revision.AFTER
    async with engine.begin() as db:
        assert list(
            (
                await db.execute(
                    text("SELECT id,status::text FROM deliveries ORDER BY id")
                )
            ).all()
        ) == [(1, "EN_ROUTE"), (2, "COMPLETADA")]
    await run(engine, "downgrade")
    await run(engine, "downgrade")
    assert await labels(engine) == revision.BEFORE
    async with engine.begin() as db:
        await db.execute(text("INSERT INTO deliveries(id) VALUES(3)"))
        assert list(
            (
                await db.execute(
                    text("SELECT id,status::text FROM deliveries ORDER BY id")
                )
            ).all()
        ) == [(1, "EN_ROUTE"), (2, "COMPLETADA"), (3, "PENDIENTE")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "conflict", ["cancelled", "consumer", "unknown_label", "temporary_type"]
)
async def test_downgrade_refuses_loss_or_ambiguous_dependencies(migration_db, conflict):
    engine = migration_db
    await run(engine, "upgrade")
    async with engine.begin() as db:
        statements = {
            "cancelled": "INSERT INTO deliveries(id,status) VALUES(3,'CANCELADA')",
            "consumer": "CREATE TABLE other_delivery(status deliverystatus)",
            "unknown_label": "ALTER TYPE deliverystatus ADD VALUE 'EXTERNAL'",
            "temporary_type": "CREATE TYPE deliverystatus_before_cancel58 AS ENUM ('OTHER')",
        }
        await db.execute(text(statements[conflict]))
    before = await labels(engine)
    with pytest.raises(RuntimeError):
        await run(engine, "downgrade")
    assert await labels(engine) == before
    async with engine.connect() as db:
        assert (
            await db.scalar(text("SELECT status::text FROM deliveries WHERE id=1"))
            == "EN_ROUTE"
        )


@pytest.mark.asyncio
async def test_upgrade_refuses_unexpected_existing_labels(migration_db):
    engine = migration_db
    async with engine.begin() as db:
        await db.execute(text("ALTER TYPE deliverystatus ADD VALUE 'EXTERNAL'"))
    with pytest.raises(RuntimeError):
        await run(engine, "upgrade")
    assert await labels(engine) == revision.BEFORE + ["EXTERNAL"]


@pytest.mark.asyncio
async def test_new_enum_value_requires_committing_migration_before_first_write(
    migration_db,
):
    engine = migration_db

    def migrate(conn):
        with Operations.context(MigrationContext.configure(conn)):
            revision.upgrade()

    async with engine.begin() as db:
        await db.run_sync(migrate)
        with pytest.raises(DBAPIError, match="UnsafeNewEnumValueUsage|unsafe use"):
            async with db.begin_nested():
                await db.execute(
                    text("INSERT INTO deliveries(id,status) VALUES(3,'CANCELADA')")
                )
    async with engine.begin() as db:
        await db.execute(
            text("INSERT INTO deliveries(id,status) VALUES(3,'CANCELADA')")
        )
        assert (
            await db.scalar(text("SELECT status::text FROM deliveries WHERE id=3"))
            == "CANCELADA"
        )
