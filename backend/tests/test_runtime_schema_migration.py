"""Native upgrade compatibility and loss-avoiding rollback of the runtime delta."""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4
from datetime import datetime

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

spec = importlib.util.spec_from_file_location(
    "runtime88",
    Path(__file__).parents[1]
    / "alembic/versions/20261113_runtime_schema_completion.py",
)
revision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(revision)


@pytest.fixture
async def runtime_schema():
    raw = os.environ.get("TEST_DATABASE_URL")
    if not raw:
        pytest.skip("Explicit PostgreSQL TEST_DATABASE_URL required")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql" or not (url.database or "").startswith(
        "test_"
    ):
        pytest.fail("Explicit test_* PostgreSQL DB required")
    url = url.set(drivername="postgresql+asyncpg")
    schema = "runtime88_" + uuid4().hex
    admin = create_async_engine(url, poolclass=NullPool)
    async with admin.begin() as db:
        await db.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": schema}},
    )
    try:
        async with engine.begin() as db:
            await db.execute(
                sa.text(
                    "CREATE TYPE userrole AS ENUM ('SUPERADMIN','GERENTE','OPERADOR','REPARTIDOR','CLIENTE')"
                )
            )
            await db.execute(
                sa.text("CREATE TABLE users (id UUID PRIMARY KEY, role userrole)")
            )
            for table in ("riders", "shifts", "orders", "deliveries", "integrations"):
                await db.execute(
                    sa.text("CREATE TABLE " + table + " (id UUID PRIMARY KEY)")
                )
        yield engine
    finally:
        await engine.dispose()
        async with admin.begin() as db:
            await db.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


async def migrate(engine, direction="upgrade"):
    def run(connection):
        with Operations.context(MigrationContext.configure(connection)):
            getattr(revision, direction)()

    async with engine.begin() as db:
        await db.run_sync(run)


async def test_upgrade_completes_tables_and_auditor_without_changing_existing_accounts(
    runtime_schema,
):
    engine = runtime_schema
    identity = uuid4()
    async with engine.begin() as db:
        await db.execute(
            sa.text("INSERT INTO users VALUES (:id,'SUPERADMIN')"), {"id": identity}
        )
    await migrate(engine)
    async with engine.begin() as db:
        for table, expected in revision.EXPECTED_COLUMNS.items():
            names = await db.run_sync(
                lambda conn: {
                    column["name"] for column in sa.inspect(conn).get_columns(table)
                }
            )
            assert names == expected
        assert (
            await db.scalar(
                sa.text("SELECT role::text FROM users WHERE id=:id"), {"id": identity}
            )
            == "SUPERADMIN"
        )
        await db.execute(
            sa.text("INSERT INTO users VALUES (:id,'AUDITOR')"), {"id": uuid4()}
        )


async def test_repeated_upgrade_preserves_preexisting_runtime_rows(runtime_schema):
    engine = runtime_schema
    await migrate(engine)
    identity = uuid4()
    event = uuid4()
    async with engine.begin() as db:
        await db.execute(
            sa.text("INSERT INTO integrations VALUES (:id)"), {"id": identity}
        )
        await db.execute(
            sa.text(
                "INSERT INTO webhook_events(id,integration_id,event_type,payload) VALUES (:id,:integration,'ORDER_CREATED','{}')"
            ),
            {"id": event, "integration": identity},
        )
    await migrate(engine)
    async with engine.connect() as db:
        assert await db.scalar(sa.text("SELECT count(*) FROM webhook_events")) == 1


async def test_downgrade_refuses_to_delete_runtime_history(runtime_schema):
    engine = runtime_schema
    await migrate(engine)
    async with engine.begin() as db:
        rider = uuid4()
        await db.execute(sa.text("INSERT INTO riders VALUES (:id)"), {"id": rider})
        await db.execute(
            sa.text(
                "INSERT INTO productivity_metrics(id,rider_id,period_start,period_end) VALUES (:id,:rider,:date,:date)"
            ),
            {"id": uuid4(), "rider": rider, "date": datetime(2026, 11, 13)},
        )
    with pytest.raises(RuntimeError, match="preserve/export"):
        await migrate(engine, "downgrade")
    async with engine.connect() as db:
        assert (
            await db.scalar(sa.text("SELECT count(*) FROM productivity_metrics")) == 1
        )


async def test_empty_downgrade_keeps_auditor_meaning(runtime_schema):
    engine = runtime_schema
    await migrate(engine)
    await migrate(engine, "downgrade")
    async with engine.begin() as db:
        tables = await db.run_sync(lambda conn: set(sa.inspect(conn).get_table_names()))
        assert not (tables & revision.EXPECTED_COLUMNS.keys())
        await db.execute(
            sa.text("INSERT INTO users VALUES (:id,'AUDITOR')"), {"id": uuid4()}
        )


async def test_unexpected_existing_table_is_not_silently_accepted(runtime_schema):
    engine = runtime_schema
    async with engine.begin() as db:
        await db.execute(sa.text("CREATE TABLE sla_records(id UUID PRIMARY KEY)"))
    with pytest.raises(RuntimeError, match="unexpected shape"):
        await migrate(engine)
    async with engine.connect() as db:
        assert await db.scalar(sa.text("SELECT to_regclass('webhook_events')")) is None
