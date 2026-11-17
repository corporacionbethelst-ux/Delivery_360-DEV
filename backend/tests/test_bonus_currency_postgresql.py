"""Prospective USD snapshots: real migration, all terminal paths and immutable history."""

import importlib.util, json, asyncio
from pathlib import Path
from datetime import datetime
from decimal import Decimal
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import text, select, update, event
from sqlalchemy.exc import DBAPIError
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.models.delivery import Delivery, DeliveryStatus
from app.models.order import Order
from app.models.financial import Financial
from app.core.security import create_access_token
from tests.test_delivery_financial_postgresql import (
    payment_db,
    request,
    saved,
    OPERATIONS,
)  # noqa:F401


def migration_module():
    spec = importlib.util.spec_from_file_location(
        "bonus105",
        Path(__file__).parents[1] / "alembic/versions/20261117_bonus_currency.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def migrate(engine, direction):
    def run(c):
        with Operations.context(MigrationContext.configure(c)):
            getattr(migration_module(), direction)()

    async with engine.begin() as c:
        await c.run_sync(run)


@pytest.fixture
async def bonus_db(payment_db):
    client, sessions, ids = payment_db
    engine = sessions.kw["bind"]
    old = []
    async with engine.begin() as c:
        await c.execute(
            text("ALTER TABLE deliveries DROP COLUMN locked_bonus_currency")
        )
        for suffix, amount, status in [
            ("paid", Decimal("17.03"), "COMPLETADA"),
            ("zero", Decimal("0.00"), "COMPLETADA"),
            ("empty", None, "FALLIDA"),
            ("partial", Decimal("9.01"), "EN_ROUTE"),
        ]:
            oid, did = uuid4(), uuid4()
            ids["old_" + suffix] = did
            await c.execute(
                text(
                    "INSERT INTO orders(id,customer_name,customer_phone,pickup_address,delivery_address,assigned_rider_id,ordered_at) VALUES(:id,'Historical','1','A','B',:rider,NOW())"
                ),
                dict(id=oid, rider=ids["rider"]),
            )
            await c.execute(
                text(
                    "INSERT INTO deliveries(id,order_id,rider_id,status,locked_bonus_amount,locked_bonus_type,bonus_snapshot_date) VALUES(:id,:order,:rider,CAST(:status AS deliverystatus),:amount,CAST(:kind AS lockedbonustype),:stamp)"
                ),
                dict(
                    id=did,
                    order=oid,
                    rider=ids["rider"],
                    status=status,
                    amount=amount,
                    kind="SUCCESS" if amount is not None else None,
                    stamp=datetime(2026, 11, 10) if amount is not None else None,
                ),
            )
        old = (
            await c.execute(
                text("SELECT id,to_jsonb(d) AS value FROM deliveries d ORDER BY id")
            )
        ).all()
    await migrate(engine, "upgrade")
    async with engine.connect() as c:
        after = (
            await c.execute(
                text(
                    "SELECT id,to_jsonb(d)-'locked_bonus_currency' AS value FROM deliveries d ORDER BY id"
                )
            )
        ).all()
        assert old == after
        assert (
            await c.scalar(
                text(
                    "SELECT count(*) FROM deliveries WHERE locked_bonus_currency IS NOT NULL"
                )
            )
            == 0
        )
    yield payment_db


async def snapshot(sessions, did):
    async with sessions() as db:
        return (
            await db.execute(
                select(
                    Delivery.locked_bonus_amount,
                    Delivery.locked_bonus_currency,
                    Delivery.locked_bonus_type,
                    Delivery.bonus_snapshot_date,
                ).where(Delivery.id == did)
            )
        ).one()


def page(f, version=2):
    client, _, ids = f
    r = client.get(
        "/api/v1/riders/audit/records/exact" + ("/v2" if version == 2 else ""),
        params=dict(kind="deliveries", rider_id=str(ids["rider"]), limit=51),
        headers={"Authorization": "Bearer " + create_access_token(ids["staff"])},
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", OPERATIONS)
async def test_all_paths_commit_exact_bonus_currency_and_ledger_atomically(
    bonus_db, operation
):
    f = bonus_db
    c, s, ids = f
    r = request(c, ids, operation)
    assert r.status_code == 200, r.text
    amount, unit, kind, date = await snapshot(s, ids["delivery"])
    assert (
        unit == "USD"
        and amount == (Decimal("1.00") if "failure" in operation else Decimal("2.50"))
        and date
    )
    async with s() as db:
        entry = (
            await db.execute(
                select(Financial.amount, Financial.currency_code).where(
                    Financial.idempotency_key
                    == ("pago_fallido_" if "failure" in operation else "pago_entrega_")
                    + str(ids["order"])
                )
            )
        ).one()
        assert entry == (amount, "USD")
    before = await saved(s, ids)
    assert request(c, ids, operation).status_code == 400
    assert (
        await saved(s, ids) == before
        and (await snapshot(s, ids["delivery"]))[1] == "USD"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", OPERATIONS)
async def test_zero_bonus_has_explicit_usd_without_a_zero_credit(bonus_db, operation):
    c, s, ids = bonus_db
    async with s() as db:
        await db.execute(text("UPDATE platform_settings SET value='0'"))
        await db.commit()
    r = request(c, ids, operation)
    assert r.status_code == 200, r.text
    row = await snapshot(s, ids["delivery"])
    assert row[0:2] == (Decimal("0.00"), "USD")
    async with s() as db:
        assert await db.scalar(text("SELECT count(*) FROM financials")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["failure", "service_failure"])
async def test_nonbonifiable_failure_does_not_invent_a_bonus_or_currency(
    bonus_db, operation
):
    c, s, ids = bonus_db
    kwargs = (
        {"issue_type": "REPARTIDOR_NO_QUIERE_ENTREGAR"}
        if operation == "failure"
        else {"failure_cause": "REPARTIDOR_NO_QUIERE_ENTREGAR"}
    )
    r = request(c, ids, operation, **kwargs)
    assert r.status_code == 200, r.text
    assert await snapshot(s, ids["delivery"]) == (None, None, None, None)


@pytest.mark.asyncio
async def test_history_and_v1_are_preserved_while_v2_reads_own_stored_unit(bonus_db):
    f = bonus_db
    c, s, ids = f
    assert request(c, ids, "success").status_code == 200
    modern = page(f)
    legacy = page(f, 1)
    assert modern["version"] == 2 and legacy["version"] == 1
    now = next(r for r in modern["items"] if r["id"] == str(ids["delivery"]))
    assert (
        now["currency"] == now["currency_recorded"] == "USD"
        and now["currency_basis"] == "locked_bonus_snapshot"
    )
    assert (
        next(r for r in legacy["items"] if r["id"] == str(ids["delivery"]))["currency"]
        is None
    )
    for key in ["paid", "zero", "empty", "partial"]:
        old = next(r for r in modern["items"] if r["id"] == str(ids["old_" + key]))
        assert old["currency"] is None and old["currency_recorded"] is None
    assert all(
        r["currency"] is None and r["locked_bonus_amount"] is None
        for r in modern["fallback"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("locked_bonus_currency", None),
        ("locked_bonus_currency", "VES"),
        ("locked_bonus_amount", Decimal("88.00")),
        ("locked_bonus_type", None),
        ("bonus_snapshot_date", None),
        ("locked_bonus_base", Decimal("1.00")),
        ("locked_bonus_zone_multiplier", Decimal("2.00")),
        ("locked_bonus_tier_multiplier", Decimal("2.00")),
        ("locked_bonus_tier_level", "ORO"),
        ("bonus_config_warning_snapshot", "new"),
        ("status", "EN_ROUTE"),
        ("rider_id", uuid4()),
        ("order_id", uuid4()),
    ],
)
async def test_sql_cannot_rewrite_frozen_snapshot_or_ownership(bonus_db, field, value):
    c, s, ids = bonus_db
    assert request(c, ids, "success").status_code == 200
    before = await snapshot(s, ids["delivery"])
    async with s() as db:
        with pytest.raises(DBAPIError):
            await db.execute(
                update(Delivery)
                .where(Delivery.id == ids["delivery"])
                .values(**{field: value})
            )
            await db.commit()
        await db.rollback()
    assert await snapshot(s, ids["delivery"]) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["paid", "zero", "empty", "partial"])
async def test_historical_null_unit_cannot_be_relabelled_even_for_old_zero(
    bonus_db, key
):
    _, s, ids = bonus_db
    async with s() as db:
        with pytest.raises(DBAPIError):
            await db.execute(
                text("UPDATE deliveries SET locked_bonus_currency='USD' WHERE id=:id"),
                {"id": ids["old_" + key]},
            )
            await db.commit()
        await db.rollback()
    assert (await snapshot(s, ids["old_" + key]))[1] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sql", ["DELETE FROM deliveries WHERE id=:id", "TRUNCATE deliveries CASCADE"]
)
async def test_history_cannot_be_removed(bonus_db, sql):
    _, s, ids = bonus_db
    async with s() as db:
        with pytest.raises(DBAPIError):
            await db.execute(text(sql), dict(id=ids["old_paid"]))
            await db.commit()
        await db.rollback()
    assert (await snapshot(s, ids["old_paid"]))[0] == Decimal("17.03")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "locked_bonus_amount=1",
        "locked_bonus_currency='USD'",
        "locked_bonus_amount='NaN',locked_bonus_currency='USD',locked_bonus_type='SUCCESS',bonus_snapshot_date=NOW(),status='COMPLETADA'",
        "locked_bonus_amount=-1,locked_bonus_currency='USD',locked_bonus_type='SUCCESS',bonus_snapshot_date=NOW(),status='COMPLETADA'",
        "locked_bonus_amount=1,locked_bonus_currency='VES',locked_bonus_type='SUCCESS',bonus_snapshot_date=NOW(),status='COMPLETADA'",
    ],
)
async def test_new_incomplete_or_untyped_snapshots_are_rejected(bonus_db, change):
    _, s, ids = bonus_db
    async with s() as db:
        with pytest.raises(DBAPIError):
            await db.execute(
                text("UPDATE deliveries SET " + change + " WHERE id=:id"),
                dict(id=ids["delivery"]),
            )
            await db.commit()
        await db.rollback()
    assert await snapshot(s, ids["delivery"]) == (None, None, None, None)


@pytest.mark.asyncio
async def test_failed_commit_reverts_currency_snapshot_and_ledger(
    bonus_db, monkeypatch
):
    from sqlalchemy.ext.asyncio import AsyncSession

    c, s, ids = bonus_db
    before = await saved(s, ids)
    original = AsyncSession.commit

    async def fail_request(self):
        if self.info.get("workflow_request"):
            raise RuntimeError("synthetic final commit failure")
        return await original(self)

    monkeypatch.setattr(AsyncSession, "commit", fail_request)
    assert request(c, ids, "success").status_code == 500
    assert (
        await saved(s, ids) == before
        and (await snapshot(s, ids["delivery"]))[1] is None
    )


@pytest.mark.asyncio
async def test_downgrade_refuses_loss_of_new_recorded_units(bonus_db):
    c, s, ids = bonus_db
    assert request(c, ids, "success").status_code == 200
    with pytest.raises(RuntimeError, match="preserve declared"):
        await migrate(s.kw["bind"], "downgrade")
    assert (await snapshot(s, ids["delivery"]))[1] == "USD"


@pytest.mark.asyncio
async def test_unused_migration_can_roll_back_and_reapply_without_history_rewrite(
    bonus_db,
):
    _, s, ids = bonus_db
    engine = s.kw["bind"]
    await migrate(engine, "downgrade")
    await migrate(engine, "upgrade")
    assert (await snapshot(s, ids["old_paid"]))[:2] == (Decimal("17.03"), None)


@pytest.mark.asyncio
async def test_historical_active_partial_snapshot_is_blocked_before_mutation(bonus_db):
    c, s, ids = bonus_db
    # Point the request at the already frozen active delivery; no field may be reset.
    other = dict(ids)
    other["delivery"] = ids["old_partial"]
    before = await snapshot(s, other["delivery"])
    r = request(c, other, "success")
    assert r.status_code == 409, r.text
    assert await snapshot(s, other["delivery"]) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operations",
    [
        ("success", "failure"),
        ("service_success", "service_failure"),
        ("order", "service_success"),
        ("order", "success"),
    ],
)
async def test_concurrent_closures_freeze_one_currency_and_one_credit(
    bonus_db, operations
):
    c, s, ids = bonus_db
    responses = await asyncio.wait_for(
        asyncio.gather(
            *(asyncio.to_thread(request, c, ids, name) for name in operations)
        ),
        15,
    )
    assert sorted(r.status_code for r in responses) == [200, 400], [
        r.text for r in responses
    ]
    row = await snapshot(s, ids["delivery"])
    assert row[1] == "USD"
    async with s() as db:
        assert await db.scalar(text("SELECT count(*) FROM financials")) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", OPERATIONS)
async def test_ledger_flush_failure_rolls_back_the_new_unit(
    bonus_db, operation, monkeypatch
):
    from sqlalchemy.ext.asyncio import AsyncSession

    c, s, ids = bonus_db
    before = await saved(s, ids)
    original = AsyncSession.flush

    async def fail(self, *args, **kwargs):
        if self.info.get("workflow_request") and any(
            isinstance(x, Financial) for x in self.new
        ):
            raise RuntimeError("synthetic credit flush failure")
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "flush", fail)
    assert request(c, ids, operation).status_code == 500
    assert (
        await saved(s, ids) == before
        and (await snapshot(s, ids["delivery"]))[1] is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("unit", [None, "USD"])
async def test_old_receipt_without_snapshot_is_not_repriced_or_used_to_label_history(
    bonus_db, operation, unit
):
    from app.models.financial import TransactionType, PaymentStatus

    c, s, ids = bonus_db
    failed = "failure" in operation
    async with s() as db:
        db.add(
            Financial(
                rider_id=ids["rider"],
                currency_code=unit,
                amount=Decimal("2.50"),
                balance_before=100,
                balance_after=Decimal("102.50"),
                transaction_type=(
                    TransactionType.PAGO_INTENTO_FALLIDO
                    if failed
                    else TransactionType.PAGO_ENTREGA
                ),
                status=PaymentStatus.PROCESADO,
                reference_id=str(ids["order"]),
                idempotency_key=("pago_fallido_" if failed else "pago_entrega_")
                + str(ids["order"]),
            )
        )
        await db.commit()
    before = await saved(s, ids)
    r = request(c, ids, operation)
    assert r.status_code == 409, r.text
    assert (
        await saved(s, ids) == before
        and (await snapshot(s, ids["delivery"]))[1] is None
    )


@pytest.mark.asyncio
async def test_new_insert_cannot_create_a_snapshot_without_its_unit(bonus_db):
    _, s, ids = bonus_db
    async with s() as db:
        o = Order(
            customer_name="New",
            customer_phone="1",
            pickup_address="A",
            delivery_address="B",
        )
        db.add(o)
        await db.commit()
        oid = o.id
        with pytest.raises(DBAPIError) as caught:
            await db.execute(
                text(
                    "INSERT INTO deliveries(id,order_id,rider_id,status,locked_bonus_amount,locked_bonus_type,bonus_snapshot_date) VALUES(:id,:oid,:rid,'COMPLETADA',1,'SUCCESS',NOW())"
                ),
                dict(id=uuid4(), oid=oid, rid=ids["rider"]),
            )
            await db.commit()
        assert "P0105" in str(getattr(caught.value.orig, "sqlstate", ""))
        await db.rollback()
