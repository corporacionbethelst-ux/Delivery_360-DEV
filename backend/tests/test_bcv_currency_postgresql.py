"""HTTP, immutable SQL history, optimistic writes, replay and native races."""

import asyncio
from datetime import datetime, timezone, timedelta
import importlib.util
import os
from pathlib import Path
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, select, text, func
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.main import app
from app.core.database import get_db
from app.core.security import create_access_token
from app.core.rate_limiter import RateLimiter
from app.middleware import rate_limit_middleware
from app.models.user import User, UserRole
from app.models.rider import Rider, RiderStatus
from app.models.audit_log import AuditLog
from app.models.currency import BcvRate, UsdVesQuote
from app.services import bcv_currency as service

spec = importlib.util.spec_from_file_location(
    "currency90",
    Path(__file__).parents[1] / "alembic/versions/20261114_bcv_currency.py",
)
revision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(revision)


async def migrate(engine, direction):
    def operation(conn):
        with Operations.context(MigrationContext.configure(conn)):
            getattr(revision, direction)()

    async with engine.begin() as db:
        await db.run_sync(operation)


@pytest.fixture
async def currency_db(monkeypatch):
    raw = os.environ.get("TEST_DATABASE_URL")
    if not raw:
        pytest.skip("Explicit test_* PostgreSQL required")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql" or not (url.database or "").startswith(
        "test_"
    ):
        pytest.fail("Explicit test_* PostgreSQL required")
    url = url.set(drivername="postgresql+asyncpg")
    schema = "currency90_" + uuid4().hex
    admin = create_async_engine(url, poolclass=NullPool)
    async with admin.begin() as db:
        await db.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": schema + ",public"}},
    )
    old = app.dependency_overrides.copy()
    client = None
    try:
        metadata = MetaData()
        tables = {User.__table__, AuditLog.__table__, Rider.__table__}
        while True:
            expanded = tables | {
                fk.column.table for table in tables for fk in table.foreign_keys
            }
            if expanded == tables:
                break
            tables = expanded
        for table in tables:
            table.to_metadata(metadata)
        async with engine.begin() as db:
            await db.run_sync(metadata.create_all)
        await migrate(engine, "upgrade")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        ids = {}
        async with sessions() as db:
            for role in UserRole:
                row = User(
                    email=role.value.lower() + "@example.com",
                    hashed_password="unused",
                    first_name="Test",
                    last_name=role.value,
                    role=role,
                    is_active=True,
                )
                db.add(row)
                await db.flush()
                ids[role.value] = row.id
            other = User(
                email="other@example.com",
                hashed_password="unused",
                first_name="Other",
                last_name="Operator",
                role=UserRole.OPERADOR,
                is_active=True,
            )
            db.add(other)
            await db.flush()
            ids["OTHER"] = other.id
            db.add(Rider(user_id=ids["REPARTIDOR"], status=RiderStatus.ACTIVO))
            await db.commit()

        async def database():
            async with sessions() as db:
                db.info["currency_request"] = True
                try:
                    yield db
                    await db.commit()
                except BaseException:
                    await db.rollback()
                    raise

        app.dependency_overrides[get_db] = database
        monkeypatch.setattr(rate_limit_middleware, "rate_limiter", RateLimiter())
        monkeypatch.setattr(
            service, "utc_now", lambda: datetime(2026, 11, 14, 16, tzinfo=timezone.utc)
        )
        client = TestClient(app, raise_server_exceptions=False)
        yield client, sessions, ids, engine
    finally:
        if client:
            client.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(old)
        await engine.dispose()
        async with admin.begin() as db:
            await db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


def call(fixture, method, path, body=None, role="SUPERADMIN"):
    client, _, ids, _ = fixture
    return client.request(
        method,
        "/api/v1/currency" + path,
        headers={"Authorization": "Bearer " + create_access_token(ids[role])},
        json=body,
    )


def rate_body(**changes):
    return {
        "request_key": str(uuid4()),
        "previous_rate_id": None,
        "valid_on": "2026-11-14",
        "reference_date": "2026-11-14",
        "ves_per_usd": "1.5",
        "note": "TASA SINTETICA para pruebas, no tasa BCV real",
        "confirmed_bcv": True,
        **changes,
    }


def rate(fixture, **changes):
    body = rate_body(**changes)
    response = call(fixture, "POST", "/rates", body)
    assert response.status_code == 201, response.text
    return response.json(), body


def quote_body(rate_id, **changes):
    return {
        "request_key": str(uuid4()),
        "rate_id": rate_id,
        "amount_usd": "0.01",
        "reference": "Cotización de prueba",
        **changes,
    }


@pytest.mark.parametrize(
    "role", ["SUPERADMIN", "GERENTE", "OPERADOR", "AUDITOR", "CLIENTE", "REPARTIDOR"]
)
async def test_context_permissions_and_absence_do_not_create_rate(currency_db, role):
    response = call(currency_db, "GET", "/context", role=role)
    assert response.status_code == (403 if role in ("CLIENTE", "REPARTIDOR") else 200)
    if response.status_code == 200:
        assert (
            response.json()["current_rate"] is None and response.json()["rates"] == []
        )
    _, sessions, _, _ = currency_db
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 0


@pytest.mark.parametrize(
    "role", ["GERENTE", "OPERADOR", "AUDITOR", "CLIENTE", "REPARTIDOR"]
)
async def test_rate_write_permissions(currency_db, role):
    response = call(currency_db, "POST", "/rates", rate_body(), role)
    assert response.status_code == (201 if role == "GERENTE" else 403)


async def test_quote_without_current_rate_is_rejected(currency_db):
    response = call(currency_db, "POST", "/quotes", quote_body(str(uuid4())))
    assert response.status_code == 409


async def test_rate_correction_preserves_receipt_replay_and_audit(currency_db):
    first, original = rate(currency_db)
    body = quote_body(first["id"])
    quote = call(currency_db, "POST", "/quotes", body, "OPERADOR")
    assert quote.status_code == 201
    receipt = quote.json()
    assert receipt["amount_ves"] == "0.02" and receipt["payment_confirmed"] is False
    second, _ = rate(currency_db, previous_rate_id=first["id"], ves_per_usd="2.5")
    assert second["revision"] == 2
    old = call(currency_db, "GET", "/quotes/" + receipt["id"], role="OPERADOR").json()
    assert old == receipt
    assert call(currency_db, "POST", "/rates", original).json() == first
    assert (
        call(
            currency_db, "POST", "/rates", {**original, "previous_rate_id": first["id"]}
        ).status_code
        == 409
    )
    assert call(currency_db, "POST", "/quotes", body, "OPERADOR").json() == receipt
    assert (
        call(currency_db, "POST", "/quotes", quote_body(first["id"])).status_code == 412
    )
    newest = call(currency_db, "POST", "/quotes", quote_body(second["id"])).json()
    assert newest["amount_ves"] == "0.03"
    _, sessions, _, _ = currency_db
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(BcvRate)) == 2
        assert await db.scalar(select(func.count()).select_from(UsdVesQuote)) == 2
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 4


async def test_quote_ownership_and_key_reuse(currency_db):
    row, _ = rate(currency_db)
    body = quote_body(row["id"])
    receipt = call(currency_db, "POST", "/quotes", body, "OPERADOR").json()
    assert (
        call(currency_db, "GET", "/quotes/" + receipt["id"], role="OTHER").status_code
        == 403
    )
    assert (
        call(currency_db, "GET", "/quotes/" + receipt["id"], role="AUDITOR").status_code
        == 200
    )
    assert call(currency_db, "POST", "/quotes", body, "OTHER").status_code == 409
    assert (
        call(
            currency_db, "POST", "/quotes", {**body, "amount_usd": "2"}, "OPERADOR"
        ).status_code
        == 409
    )
    assert (
        call(
            currency_db, "POST", "/quotes", quote_body(row["id"]), "AUDITOR"
        ).status_code
        == 403
    )


async def test_midnight_expires_new_conversion_but_preserves_replay(
    currency_db, monkeypatch
):
    row, original = rate(currency_db)
    body = quote_body(row["id"])
    receipt = call(currency_db, "POST", "/quotes", body).json()
    monkeypatch.setattr(
        service, "utc_now", lambda: datetime(2026, 11, 15, 4, tzinfo=timezone.utc)
    )
    assert call(currency_db, "GET", "/context").json()["current_rate"] is None
    assert (
        call(currency_db, "POST", "/quotes", quote_body(row["id"])).status_code == 409
    )
    assert call(currency_db, "POST", "/quotes", body).json() == receipt
    assert call(currency_db, "POST", "/rates", original).json() == row
    assert call(currency_db, "POST", "/rates", rate_body()).status_code == 409


async def test_previous_reference_requires_explanation_and_daily_attestation(
    currency_db,
):
    assert (
        call(
            currency_db,
            "POST",
            "/rates",
            rate_body(reference_date="2026-11-13", note="Corta"),
        ).status_code
        == 422
    )
    row, _ = rate(
        currency_db,
        reference_date="2026-11-13",
        note="Prueba de confirmación manual en día sin publicación",
    )
    assert row["reference_date"] == "2026-11-13" and row["valid_on"] == "2026-11-14"
    assert row["automatically_verified"] is False and row["source"] == "MANUAL_BCV"


async def test_stale_write_and_token_revocation_do_not_add_rows(currency_db):
    row, _ = rate(currency_db)
    assert call(currency_db, "POST", "/rates", rate_body()).status_code == 412
    _, sessions, ids, _ = currency_db
    async with sessions() as db:
        actor = await db.get(User, ids["SUPERADMIN"])
        actor.token_version += 1
        await db.commit()
    assert (
        call(
            currency_db, "POST", "/rates", rate_body(previous_rate_id=row["id"])
        ).status_code
        == 401
    )
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(BcvRate)) == 1


async def test_concurrent_first_rates_have_one_winner(currency_db):
    responses = await asyncio.gather(
        *(
            asyncio.to_thread(
                call, currency_db, "POST", "/rates", rate_body(ves_per_usd=value)
            )
            for value in ("1.5", "2.5")
        )
    )
    assert sorted(r.status_code for r in responses) == [201, 412]


async def test_concurrent_quote_replay_has_one_row(currency_db):
    row, _ = rate(currency_db)
    body = quote_body(row["id"])
    responses = await asyncio.gather(
        *(
            asyncio.to_thread(call, currency_db, "POST", "/quotes", body)
            for _ in range(2)
        )
    )
    assert [r.status_code for r in responses] == [201, 201]
    assert responses[0].json()["id"] == responses[1].json()["id"]
    _, sessions, _, _ = currency_db
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(UsdVesQuote)) == 1


async def test_commit_failure_rolls_back_rate_and_audit(currency_db, monkeypatch):
    original = AsyncSession.commit

    async def fail(db):
        if db.info.get("currency_request"):
            raise RuntimeError("Synthetic commit failure")
        await original(db)

    monkeypatch.setattr(AsyncSession, "commit", fail)
    assert call(currency_db, "POST", "/rates", rate_body()).status_code == 500
    _, sessions, _, _ = currency_db
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(BcvRate)) == 0
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 0


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE bcv_rates SET ves_per_usd=5",
        "DELETE FROM bcv_rates",
        "TRUNCATE bcv_rates CASCADE",
        "UPDATE usd_ves_quotes SET amount_ves=999",
        "DELETE FROM usd_ves_quotes",
        "TRUNCATE usd_ves_quotes",
    ],
)
async def test_database_blocks_history_rewrites(currency_db, statement):
    row, _ = rate(currency_db)
    assert (
        call(currency_db, "POST", "/quotes", quote_body(row["id"])).status_code == 201
    )
    _, _, _, engine = currency_db
    with pytest.raises(Exception, match="append-only"):
        async with engine.begin() as db:
            await db.execute(text(statement))


async def test_downgrade_refuses_history(currency_db):
    rate(currency_db)
    with pytest.raises(RuntimeError, match="preserve currency history"):
        await migrate(currency_db[3], "downgrade")
    assert len(call(currency_db, "GET", "/context").json()["rates"]) == 1


async def test_empty_downgrade_preserves_users(currency_db):
    await migrate(currency_db[3], "downgrade")
    async with currency_db[1]() as db:
        assert await db.scalar(select(func.count()).select_from(User)) == 7
