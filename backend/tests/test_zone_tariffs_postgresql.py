"""Real migration, explicit units, row-lock CAS and legacy-writer coordination."""

import asyncio, importlib.util
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4
from decimal import Decimal
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.models.zone import Zone
from app.models.audit_log import AuditLog
from app.core.security import create_access_token
from tests.test_financial_reports_exact_postgresql import (
    reports_db,
    quote_db,
    currency_db,
)  # noqa:F401

FIELDS = (
    "tariff_base_usd",
    "tariff_per_km_usd",
    "tariff_revision",
    "tariff_updated_at",
    "tariff_updated_by",
)


@pytest.fixture
async def zone_db(reports_db):
    f = reports_db
    async with f[1]() as db:
        row = Zone(
            name="Historical zone",
            code="Z109",
            delivery_fee_base=4000.123456789,
            cost_per_km=0.123456789,
            bonus_multiplier=1.23456789,
        )
        db.add(row)
        await db.commit()
        f[2]["zone"] = row.id
    yield f


def request(
    f, method="GET", body=None, role="GERENTE", status=200, path=None, params=None
):
    path = path or f"/api/v1/zones/{f[2]['zone']}/tariff/exact"
    r = f[0].request(
        method,
        path,
        json=body,
        params=params,
        headers={"Authorization": "Bearer " + create_access_token(f[2][role])},
    )
    assert r.status_code == status, r.text
    return r.json()


def body(revision=0, base="0.31", km="0.10"):
    return dict(
        expected_revision=revision, currency="USD", base_usd=base, per_km_usd=km
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["SUPERADMIN", "GERENTE"])
async def test_exact_write_preserves_legacy_rates_and_bonus_factor(zone_db, role):
    f = zone_db
    before = request(f)
    assert (
        before["base_usd"] is None
        and before["currency"] is None
        and before["revision"] == 0
    )
    written = request(f, "PUT", body(), role)
    assert (
        written["base_usd"] == "0.31"
        and written["per_km_usd"] == "0.10"
        and written["currency"] == "USD"
        and written["revision"] == 1
    )
    assert written["updated_by"] == str(f[2][role])
    assert request(f) == written
    async with f[1]() as db:
        zone = await db.get(Zone, f[2]["zone"])
        assert (
            zone.delivery_fee_base == 4000.123456789
            and zone.cost_per_km == 0.123456789
            and zone.bonus_multiplier == 1.23456789
        )
        assert zone.tariff_base_usd == Decimal("0.31")
        logs = (
            await db.scalars(
                select(AuditLog).where(AuditLog.resource_type == "ZoneTariff")
            )
        ).all()
        assert len(logs) == 1 and logs[0].old_values["revision"] == 0
        assert logs[0].new_values == written and logs[0].user_id == f[2][role]
    request(
        f,
        "PATCH",
        {"delivery_fee_base": 99},
        role,
        status=409,
        path=f"/api/v1/zones/{f[2]['zone']}",
    )
    data = request(
        f,
        "PATCH",
        {"name": "Operational rename"},
        role,
        path=f"/api/v1/zones/{f[2]['zone']}",
    )
    assert data["name"] == "Operational rename" and request(f) == written
    request(f, "PUT", body(), role, status=409)
    assert request(f) == written


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["AUDITOR", "CLIENTE", "REPARTIDOR"])
async def test_denied_roles_cannot_read_or_write(zone_db, role):
    f = zone_db
    request(f, role=role, status=403)
    request(f, "PUT", body(), role, status=403)
    request(
        f,
        role=role,
        status=403,
        path="/api/v1/zones/tariffs/exact",
        params={"zone_ids": str(f[2]["zone"])},
    )


@pytest.mark.asyncio
async def test_operator_reads_but_cannot_save(zone_db):
    f = zone_db
    assert request(f, role="OPERADOR")["revision"] == 0
    request(f, "PUT", body(), role="OPERADOR", status=403)
    page = request(
        f,
        role="OPERADOR",
        path="/api/v1/zones/tariffs/exact",
        params={"zone_ids": str(f[2]["zone"])},
    )
    assert page["items"][0]["base_usd"] is None


@pytest.mark.asyncio
async def test_zero_is_explicit_and_query_scope_is_strict(zone_db):
    f = zone_db
    saved = request(f, "PUT", body(base="0", km="0"))
    assert (
        saved["base_usd"] == "0.00"
        and saved["per_km_usd"] == "0.00"
        and saved["revision"] == 1
    )
    request(f, params={"currency": "VES"}, status=422)
    request(f, "PUT", body(1), params={"actor": "other"}, status=422)
    request(f, path=f"/api/v1/zones/{uuid4()}/tariff/exact", status=404)
    request(f, path="/api/v1/zones/not-a-uuid/tariff/exact", status=400)


@pytest.mark.asyncio
async def test_batched_identity_limits_and_missing_catalog(zone_db):
    f = zone_db
    path = "/api/v1/zones/tariffs/exact"
    key = str(f[2]["zone"])
    result = request(f, path=path, params={"zone_ids": key})
    assert result["items"] == [request(f)]
    for values in ([key, key], [key] * 101):
        request(f, path=path, params={"zone_ids": values}, status=422)
    request(f, path=path, params={"zone_ids": str(uuid4())}, status=409)
    request(f, path=path, params={"zone_ids": key, "currency": "VES"}, status=422)


@pytest.mark.asyncio
async def test_two_writers_cannot_replace_the_same_revision(zone_db):
    f = zone_db
    path = f"/api/v1/zones/{f[2]['zone']}/tariff/exact"

    def write(amount):
        return f[0].put(
            path,
            json=body(base=amount),
            headers={"Authorization": "Bearer " + create_access_token(f[2]["GERENTE"])},
        )

    values = await asyncio.gather(
        asyncio.to_thread(write, "0.31"), asyncio.to_thread(write, "0.32")
    )
    assert sorted(v.status_code for v in values) == [200, 409]
    winner = next(v.json() for v in values if v.status_code == 200)
    assert request(f) == winner and winner["revision"] == 1


async def migrate(engine, direction):
    spec = importlib.util.spec_from_file_location(
        "tariffs109",
        Path(__file__).parents[1] / "alembic/versions/20261121_zone_tariffs.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def run(c):
        with Operations.context(MigrationContext.configure(c)):
            getattr(module, direction)()

    async with engine.begin() as c:
        await c.run_sync(run)


@pytest.mark.asyncio
async def test_real_migration_preserves_original_rows_and_refuses_lossy_downgrade(
    zone_db,
):
    f = zone_db
    engine = f[3]
    async with engine.begin() as c:
        await c.execute(text("ALTER TABLE zones DROP CONSTRAINT ck_zones_exact_tariff"))
        for field in FIELDS:
            await c.execute(text("ALTER TABLE zones DROP COLUMN " + field))
        old = (
            await c.execute(text("SELECT id,to_jsonb(z) FROM zones z ORDER BY id"))
        ).all()
    await migrate(engine, "upgrade")
    async with engine.connect() as c:
        new = (
            await c.execute(
                text(
                    "SELECT id,to_jsonb(z)-ARRAY['"
                    + "','".join(FIELDS)
                    + "'] FROM zones z ORDER BY id"
                )
            )
        ).all()
        assert old == new
        assert (
            await c.scalar(
                text("SELECT count(*) FROM zones WHERE tariff_base_usd IS NOT NULL")
            )
            == 0
        )
    await migrate(engine, "downgrade")
    await migrate(engine, "upgrade")
    saved = request(f, "PUT", body())
    with pytest.raises(RuntimeError, match="preserve explicit USD"):
        await migrate(engine, "downgrade")
    assert request(f) == saved


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sql",
    [
        "tariff_base_usd=0",
        "tariff_revision=1",
        "tariff_base_usd=-1,tariff_per_km_usd=0,tariff_revision=1,tariff_updated_at=NOW(),tariff_updated_by=gen_random_uuid()",
    ],
)
async def test_database_rejects_partial_or_invalid_tariffs(zone_db, sql):
    async with zone_db[3].begin() as c:
        with pytest.raises(DBAPIError):
            await c.execute(text("UPDATE zones SET " + sql))


@pytest.mark.asyncio
async def test_audit_failure_rolls_back_the_tariff_with_its_revision(zone_db):
    from sqlalchemy import event

    f = zone_db

    def reject(mapper, connection, target):
        if target.resource_type == "ZoneTariff":
            raise RuntimeError("Synthetic audit failure")

    event.listen(AuditLog, "before_insert", reject)
    try:
        response = f[0].put(
            f"/api/v1/zones/{f[2]['zone']}/tariff/exact",
            json=body(),
            headers={"Authorization": "Bearer " + create_access_token(f[2]["GERENTE"])},
        )
        assert response.status_code == 500
    finally:
        event.remove(AuditLog, "before_insert", reject)
    assert request(f)["revision"] == 0 and request(f)["base_usd"] is None
