"""Explicit factors, all terminal writers, migration, immutable provenance and row locks."""

import asyncio, importlib.util, json, threading
from concurrent.futures import Future
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
import pytest
from sqlalchemy import select, text, event
from sqlalchemy.exc import DBAPIError
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.core.security import create_access_token
from app.models.zone import Zone
from app.models.user import User, UserRole
from app.models.rider import Rider, RiderTier
from app.models.delivery import Delivery
from app.models.financial import Financial
from app.models.audit_log import AuditLog
from tests.test_bonus_currency_postgresql import bonus_db, payment_db  # noqa:F401
from tests.test_delivery_financial_postgresql import request, OPERATIONS, saved
from tests.test_assignment_concurrency_postgresql import wait_for_blocker

ZFIELDS = (
    "bonus_factor_exact",
    "bonus_factor_revision",
    "bonus_factor_updated_at",
    "bonus_factor_updated_by",
)


def module():
    spec = importlib.util.spec_from_file_location(
        "factors110",
        Path(__file__).parents[1] / "alembic/versions/20261121_zone_bonus_factors.py",
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


async def migration(engine, method):
    def run(c):
        with Operations.context(MigrationContext.configure(c)):
            getattr(module(), method)()

    async with engine.begin() as c:
        await c.run_sync(run)


@pytest.fixture
async def factor_db(bonus_db):
    f = bonus_db
    engine = f[1].kw["bind"]
    async with engine.begin() as c:
        await c.run_sync(lambda db: AuditLog.__table__.create(db, checkfirst=True))
    await migration(engine, "install_factor_guard")
    async with f[1]() as db:
        for role in (
            UserRole.SUPERADMIN,
            UserRole.OPERADOR,
            UserRole.AUDITOR,
            UserRole.CLIENTE,
        ):
            u = User(
                email=role.value + "@factor.test",
                hashed_password="unused",
                first_name="Synthetic",
                last_name=role.value,
                role=role,
                is_active=True,
            )
            db.add(u)
            await db.flush()
            f[2][role.value] = u.id
        zone = Zone(
            name="Legacy factor",
            code="F110",
            bonus_multiplier=1.23456789,
            delivery_fee_base=4000.1234,
        )
        db.add(zone)
        await db.flush()
        f[2]["zone"] = zone.id
        rider = await db.get(Rider, f[2]["rider"])
        rider.zone_id = zone.id
        rider.tier = RiderTier.PLATINO
        await db.commit()
    yield f


def call(f, method="GET", body=None, status=200, role="staff", path=None):
    r = f[0].request(
        method,
        path or f"/api/v1/zones/{f[2]['zone']}/bonus-factor/exact",
        json=body,
        headers={"Authorization": "Bearer " + create_access_token(f[2][role])},
    )
    assert r.status_code == status, r.text
    return r.json()


def put(f, value="1.234567890123456789", revision=0, **kw):
    return call(f, "PUT", dict(expected_revision=revision, factor=value), **kw)


def report(f):
    return call(
        f, path="/api/v1/deliveries/bonuses/exact?order_ids=" + str(f[2]["order"])
    )["records"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", OPERATIONS)
async def test_all_terminal_paths_use_and_freeze_the_full_factor(factor_db, operation):
    f = factor_db
    written = put(f)
    assert (
        written["factor"] == "1.234567890123456789"
        and written["unit"] == "dimensionless"
    )
    response = request(f[0], f[2], operation)
    assert response.status_code == 200, response.text
    async with f[1]() as db:
        d = await db.get(Delivery, f[2]["delivery"])
        amount = Decimal("1.42" if "failure" in operation else "3.55")
        assert d.locked_bonus_amount == amount
        snap = d.locked_bonus_factors
        assert snap == dict(
            version=1,
            unit="dimensionless",
            zone_id=str(f[2]["zone"]),
            zone_revision=1,
            zone_factor=written["factor"],
            tier_factor="1.15",
            basis="declared_exact",
        )
        entry = await db.scalar(
            select(Financial).where(Financial.reference_id == str(f[2]["order"]))
        )
        assert entry.amount == amount and entry.currency_code == "USD"
        zone = await db.get(Zone, f[2]["zone"])
        assert (
            zone.bonus_multiplier == 1.23456789 and zone.delivery_fee_base == 4000.1234
        )
    old = report(f)
    assert old["factor_snapshot"] == snap
    put(f, "2", revision=1)
    assert report(f) == old
    assert request(f[0], f[2], operation).status_code == 400


@pytest.mark.asyncio
async def test_legacy_factor_is_applied_without_fabricating_a_declared_revision(
    factor_db,
):
    f = factor_db
    assert call(f)["factor"] is None
    r = request(f[0], f[2], "service_success")
    assert r.status_code == 200, r.text
    value = report(f)["factor_snapshot"]
    assert (
        value["basis"] == "legacy_decimal_representation"
        and value["zone_revision"] is None
        and value["zone_factor"] == "1.23456789"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["owner", "AUDITOR", "CLIENTE"])
async def test_denied_roles_cannot_read_or_save(factor_db, role):
    call(factor_db, role=role, status=403)
    put(factor_db, role=role, status=403)


@pytest.mark.asyncio
async def test_operator_reads_but_cannot_save(factor_db):
    assert call(factor_db, role="OPERADOR")["revision"] == 0
    put(factor_db, role="OPERADOR", status=403)


@pytest.mark.asyncio
async def test_revision_audit_and_old_writer_guard(factor_db):
    f = factor_db
    value = put(f, role="SUPERADMIN")
    put(f, status=409)
    call(
        f,
        "PATCH",
        {"bonus_multiplier": 2},
        status=409,
        path=f"/api/v1/zones/{f[2]['zone']}",
    )
    async with f[1]() as db:
        rows = (
            await db.scalars(
                select(AuditLog).where(AuditLog.resource_type == "ZoneBonusFactor")
            )
        ).all()
        assert (
            len(rows) == 1
            and rows[0].old_values["revision"] == 0
            and rows[0].new_values == value
        )
        assert rows[0].user_id == f[2]["SUPERADMIN"]


@pytest.mark.asyncio
async def test_audit_failure_rolls_back_the_factor(factor_db):
    f = factor_db

    def reject(mapper, conn, target):
        if target.resource_type == "ZoneBonusFactor":
            raise RuntimeError("Synthetic audit failure")

    event.listen(AuditLog, "before_insert", reject)
    try:
        r = f[0].put(
            f"/api/v1/zones/{f[2]['zone']}/bonus-factor/exact",
            json={"expected_revision": 0, "factor": "2"},
            headers={"Authorization": "Bearer " + create_access_token(f[2]["staff"])},
        )
        assert r.status_code == 500
    finally:
        event.remove(AuditLog, "before_insert", reject)
    assert call(f)["revision"] == 0


@pytest.mark.asyncio
async def test_database_prevents_backfill_and_changes_to_frozen_factor_history(
    factor_db,
):
    f = factor_db
    put(f)
    r = request(f[0], f[2], "success")
    assert r.status_code == 200, r.text
    snapshot = report(f)["factor_snapshot"]
    engine = f[1].kw["bind"]
    for target, value in (
        (f[2]["delivery"], {**snapshot, "zone_factor": "2"}),
        (f[2]["delivery"], None),
        (f[2]["old_paid"], snapshot),
    ):
        with pytest.raises(DBAPIError):
            async with engine.begin() as c:
                await c.execute(
                    text(
                        "UPDATE deliveries SET locked_bonus_factors=CAST(:v AS json) WHERE id=:id"
                    ),
                    {"v": json.dumps(value), "id": target},
                )
    assert report(f)["factor_snapshot"] == snapshot


@pytest.mark.asyncio
async def test_real_migration_keeps_old_zones_and_frozen_deliveries_unchanged(
    factor_db,
):
    f = factor_db
    engine = f[1].kw["bind"]
    async with engine.begin() as c:
        await c.execute(
            text("DROP TRIGGER preserve_delivery_bonus_factors ON deliveries")
        )
        await c.execute(text("DROP FUNCTION preserve_bonus_factors()"))
        await c.execute(text("ALTER TABLE deliveries DROP COLUMN locked_bonus_factors"))
        await c.execute(
            text("ALTER TABLE zones DROP CONSTRAINT ck_zones_exact_bonus_factor")
        )
        for field in ZFIELDS:
            await c.execute(text("ALTER TABLE zones DROP COLUMN " + field))
        old_z = (
            await c.execute(text("SELECT id,to_jsonb(z) FROM zones z ORDER BY id"))
        ).all()
        old_d = (
            await c.execute(text("SELECT id,to_jsonb(d) FROM deliveries d ORDER BY id"))
        ).all()
    await migration(engine, "upgrade")
    async with engine.connect() as c:
        assert (
            old_z
            == (
                await c.execute(
                    text(
                        "SELECT id,to_jsonb(z)-ARRAY['"
                        + "','".join(ZFIELDS)
                        + "'] FROM zones z ORDER BY id"
                    )
                )
            ).all()
        )
        assert (
            old_d
            == (
                await c.execute(
                    text(
                        "SELECT id,to_jsonb(d)-'locked_bonus_factors' FROM deliveries d ORDER BY id"
                    )
                )
            ).all()
        )
    await migration(engine, "downgrade")
    await migration(engine, "upgrade")
    put(f)
    with pytest.raises(RuntimeError, match="preserve explicit"):
        await migration(engine, "downgrade")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["success", "service_success"])
async def test_terminal_waits_for_a_factor_writer_before_freezing_its_revision(
    factor_db, operation
):
    f = factor_db
    put(f)
    engine = f[1].kw["bind"]
    waiting = Future()
    main = threading.get_ident()

    def observe(conn, cursor, statement, params, ctx, many):
        if (
            threading.get_ident() != main
            and "FROM zones" in statement
            and "FOR SHARE" in statement
            and not waiting.done()
        ):
            waiting.set_result(
                conn.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
            )

    event.listen(engine.sync_engine, "before_cursor_execute", observe)
    try:
        async with asyncio.timeout(25):
            async with f[1]() as writer:
                pid = await writer.scalar(text("SELECT pg_backend_pid()"))
                zone = await writer.scalar(
                    select(Zone).where(Zone.id == f[2]["zone"]).with_for_update()
                )
                zone.bonus_factor_exact = Decimal("2")
                zone.bonus_factor_revision = 2
                zone.bonus_factor_updated_at = datetime.now(timezone.utc)
                await writer.flush()
                pending = asyncio.create_task(
                    asyncio.to_thread(request, f[0], f[2], operation)
                )
                try:
                    waiter = await asyncio.wait_for(asyncio.wrap_future(waiting), 5)
                    await wait_for_blocker(f[1], waiter, pid)
                    await writer.commit()
                finally:
                    await writer.rollback()
                result = await pending
                assert result.status_code == 200, result.text
                row = report(f)
                assert (
                    row["amount"] == "5.75"
                    and row["factor_snapshot"]["zone_revision"] == 2
                    and row["factor_snapshot"]["zone_factor"] == "2"
                )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", observe)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", OPERATIONS)
async def test_unconfirmed_zones_keep_their_existing_entrypoint_rules(
    factor_db, operation
):
    f = factor_db
    r = request(f[0], f[2], operation)
    assert r.status_code == 200, r.text
    expected = {
        "order": "2.50",
        "failure": "1.00",
        "success": "3.55",
        "service_success": "3.55",
        "service_failure": "1.42",
    }[operation]
    value = report(f)
    assert value["amount"] == expected
    if operation in ("order", "failure"):
        assert "factor_snapshot" not in value
    else:
        assert value["factor_snapshot"]["basis"] == "legacy_decimal_representation"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "patch",
    [
        {"version": "1"},
        {"zone_factor": "1.20"},
        {"zone_factor": "5.000000000000000001"},
        {"zone_revision": True},
        {"unit": "USD"},
        {"basis": "unknown"},
    ],
)
async def test_database_rejects_invalid_first_factor_snapshot_atomically(
    factor_db, patch
):
    f = factor_db
    raw = dict(
        version=1,
        unit="dimensionless",
        zone_id=str(f[2]["zone"]),
        zone_revision=1,
        zone_factor="1.2",
        tier_factor="1.15",
        basis="declared_exact",
    )
    raw.update(patch)
    with pytest.raises(DBAPIError):
        async with f[1].kw["bind"].begin() as c:
            await c.execute(
                text(
                    "UPDATE deliveries SET status='COMPLETADA',locked_bonus_currency='USD',locked_bonus_amount=1,locked_bonus_type='SUCCESS',bonus_snapshot_date=NOW(),locked_bonus_factors=CAST(:v AS json) WHERE id=:id"
                ),
                {"v": json.dumps(raw), "id": f[2]["delivery"]},
            )
    async with f[1]() as db:
        row = await db.get(Delivery, f[2]["delivery"])
        assert row.locked_bonus_factors is None and row.locked_bonus_amount is None


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", OPERATIONS)
async def test_confirmed_factor_zero_reward_freezes_provenance_without_zero_credit(
    factor_db, operation
):
    f = factor_db
    put(f)
    async with f[1]() as db:
        await db.execute(text("UPDATE platform_settings SET value='0'"))
        await db.commit()
    result = request(f[0], f[2], operation)
    assert result.status_code == 200, result.text
    value = report(f)
    assert (
        value["amount"] == "0.00"
        and value["factor_snapshot"]["zone_factor"] == "1.234567890123456789"
    )
    async with f[1]() as db:
        assert await db.scalar(text("SELECT count(*) FROM financials")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", OPERATIONS)
async def test_full_precision_changes_the_cent_correctly_in_every_entrypoint(
    factor_db, operation
):
    f = factor_db
    put(f, "0.100000000060000001")
    async with f[1]() as db:
        rider = await db.get(Rider, f[2]["rider"])
        rider.tier = RiderTier.BRONCE
        await db.execute(text("UPDATE platform_settings SET value='99999999.99'"))
        await db.commit()
    response = request(f[0], f[2], operation)
    assert response.status_code == 200, response.text
    value = report(f)
    assert (
        value["amount"] == "10000000.01"
        and value["factor_snapshot"]["zone_factor"] == "0.100000000060000001"
    )
    async with f[1]() as db:
        entry = await db.scalar(
            select(Financial).where(Financial.reference_id == str(f[2]["order"]))
        )
        assert entry.amount == Decimal("10000000.01")


@pytest.mark.asyncio
async def test_factor_calculation_refreshes_a_rider_loaded_before_another_writer(
    factor_db,
):
    from app.services.zone_bonus_factors import configured_rider_bonus

    f = factor_db
    put(f, "2")
    async with f[1]() as reader:
        old = await reader.get(Rider, f[2]["rider"])
        assert old.tier == RiderTier.PLATINO
        async with f[1]() as writer:
            row = await writer.get(Rider, f[2]["rider"])
            row.tier = RiderTier.BRONCE
            await writer.commit()
        amount, factors = await configured_rider_bonus(
            reader, f[2]["rider"], Decimal("2.50")
        )
        assert (
            amount == Decimal("5.00")
            and factors["tier_factor"] == "1"
            and old.tier == RiderTier.BRONCE
        )
