"""Real PostgreSQL: precise stored JSON, same-cut USD scenarios and owner bonus reads."""

import asyncio, hashlib, json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4
import pytest
from sqlalchemy import text, select, event
from app.core.security import create_access_token
from app.models.audit_log import AuditLog
from app.models.delivery import Delivery, DeliveryStatus, LockedBonusType
from app.models.order import Order
from app.models.user import User, UserRole
from app.models.platform_setting import PlatformSetting
from tests.test_delivery_financial_postgresql import payment_db  # noqa: F401

SETTINGS = "/api/v1/settings/exact/v2"
SCENARIO = "/api/v1/settings/simulate-bonus/exact/v2"
BONUS = "/api/v1/deliveries/bonuses/exact"


@pytest.fixture
async def exact_db(payment_db):
    async with payment_db[1].kw["bind"].begin() as db:
        await db.run_sync(lambda c: AuditLog.__table__.create(c))
    yield payment_db


def headers(f, actor="staff"):
    return {"Authorization": "Bearer " + create_access_token(f[2][actor])}


def config(f):
    r = f[0].get(SETTINGS, headers=headers(f))
    assert r.status_code == 200, r.text
    return r.json()


def scenario(f, proposed="0.10", days=7, revision=None, **kwargs):
    body = {
        "new_base_bonus": proposed,
        "days_projection": days,
        "expected_settings_revision": revision or config(f)["revision"],
    }
    return f[0].post(SCENARIO, json=body, headers=headers(f), **kwargs)


async def add(
    f,
    amount="0.10",
    unit="USD",
    kind="SUCCESS",
    status="COMPLETADA",
    undated=False,
    future=False,
    **fields,
):
    at = None if undated else datetime.utcnow() + timedelta(days=1 if future else -1)
    async with f[1]() as db:
        order = Order(
            customer_name="Synthetic exact bonus",
            customer_phone="1",
            pickup_address="A",
            delivery_address="B",
            assigned_rider_id=f[2]["rider"],
        )
        db.add(order)
        await db.flush()
        delivery = Delivery(
            order_id=order.id,
            rider_id=f[2]["rider"],
            status=DeliveryStatus(status),
            locked_bonus_amount=Decimal(amount) if amount is not None else None,
            locked_bonus_currency=unit,
            locked_bonus_type=LockedBonusType(kind) if kind else None,
            completed_at=at,
            bonus_snapshot_date=at if kind else None,
            **fields,
        )
        db.add(delivery)
        await db.commit()
        return order.id, delivery.id


async def deliveries(f):
    async with f[1]() as db:
        return (
            await db.execute(
                text("SELECT id,to_jsonb(d) FROM deliveries d ORDER BY id")
            )
        ).all()


@pytest.mark.asyncio
async def test_scenario_keeps_usd_zero_and_excludes_unknown_other_and_invalid(exact_db):
    f = exact_db
    await add(f, "0.10")
    await add(f, "0.20")
    await add(f, "0.00")
    await add(f, "0.05", kind="FAILED_ATTEMPT", status="FALLIDA")
    await add(f, "99.99", unit=None)
    await add(f, "88.88", unit="VES")
    await add(f, None, unit=None, kind=None, status="FALLIDA")
    await add(f, "1.00", undated=True)
    await add(f, "NaN")
    await add(f, "9.00", future=True)
    before = await deliveries(f)
    r = scenario(f)
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["completed_deliveries"] == 3 and v["failed_bonus_deliveries"] == 1
    assert (
        v["historical_cost"] == "0.35"
        and v["scenario_cost"] == "0.35"
        and v["difference"] == "0.00"
        and v["percentage_change"] == "0.00"
    )
    assert v["exclusions"] == dict(
        undated=1, unknown_currency=1, other_currency=1, no_bonus=1, invalid_snapshot=1
    )
    assert v["candidate_deliveries"] == 9 and v["bank_verified"] is False
    assert v["actor"]["user_id"] == str(f[2]["staff"])
    digest = v.pop("content_sha256")
    assert (
        digest
        == hashlib.sha256(
            json.dumps(
                v, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest()
    )
    assert datetime.fromisoformat(v["period_end"][:-1]) - datetime.fromisoformat(
        v["period_start"][:-1]
    ) == timedelta(days=7)
    assert before == await deliveries(f)


@pytest.mark.asyncio
async def test_raw_json_precision_has_distinct_revision_even_when_legacy_float_collides(
    exact_db,
):
    f = exact_db
    config(f)

    async def raw(value):
        async with f[1]() as db:
            await db.execute(
                text(
                    "UPDATE platform_settings SET value=CAST(:v AS JSON) WHERE key='rider_delivery_bonus'"
                ),
                {"v": value},
            )
            await db.commit()

    await raw("0.1")
    before = config(f)
    assert before["rider_delivery_bonus"] == "0.10"
    await raw("0.10000000000000001")
    after = config(f)
    assert after["rider_delivery_bonus"] is None and after["field_issues"]
    assert (
        before["legacy_revision"] == after["legacy_revision"]
        and before["revision"] != after["revision"]
    )
    r = f[0].patch(
        SETTINGS,
        json={"rider_delivery_bonus": "0.20"},
        headers={**headers(f), "If-Match": '"' + before["revision"] + '"'},
    )
    assert r.status_code == 412
    assert scenario(f, revision=before["revision"]).status_code == 412


@pytest.mark.asyncio
async def test_numeric_and_exact_writers_share_locks_and_cannot_overwrite_each_other(
    exact_db,
):
    f = exact_db
    saved = config(f)

    def write(path, value, revision):
        return f[0].patch(
            path,
            json={"rider_delivery_bonus": value},
            headers={**headers(f), "If-Match": '"' + revision + '"'},
        )

    results = await asyncio.gather(
        asyncio.to_thread(write, SETTINGS, "0.10", saved["revision"]),
        asyncio.to_thread(write, "/api/v1/settings", 0.2, saved["legacy_revision"]),
    )
    assert sorted(r.status_code for r in results) == [200, 412], [
        r.text for r in results
    ]
    assert config(f)["rider_delivery_bonus"] in ["0.10", "0.20"]
    async with f[1]() as db:
        assert len((await db.scalars(select(AuditLog))).all()) == 1


@pytest.mark.asyncio
async def test_scenario_checks_configuration_inside_its_one_sql_cut(exact_db):
    f = exact_db
    before = config(f)
    engine = f[1].kw["bind"]
    statements = []
    changed = False

    async def change():
        async with f[1]() as db:
            await db.execute(
                text(
                    "UPDATE platform_settings SET value='\"3.00\"'::json WHERE key='rider_delivery_bonus'"
                )
            )
            await db.commit()

    def interleave(conn, cursor, statement, parameters, context, executemany):
        nonlocal changed
        if "scenario_settings" in statement:
            statements.append(statement)
            if not changed:
                changed = True
                with ThreadPoolExecutor(max_workers=1) as worker:
                    worker.submit(lambda: asyncio.run(change())).result(timeout=10)

    event.listen(engine.sync_engine, "before_cursor_execute", interleave)
    try:
        r = await asyncio.to_thread(scenario, f, revision=before["revision"])
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", interleave)
    assert r.status_code == 412 and len(statements) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("proposed", ["0.00", "0.10", "99999999.99"])
async def test_exact_scenario_handles_zero_and_large_values_without_float(
    exact_db, proposed
):
    f = exact_db
    await add(f, "0.00")
    r = scenario(f, proposed)
    assert r.status_code == 200, r.text
    v = r.json()
    assert (
        v["scenario_cost"] == proposed
        and v["historical_cost"] == "0.00"
        and v["percentage_change"] is None
    )


@pytest.mark.asyncio
async def test_empty_usd_subset_does_not_adopt_unknown_units(exact_db):
    await add(exact_db, "10.00", unit=None)
    v = scenario(exact_db).json()
    assert (
        v["completed_deliveries"] == 0
        and v["historical_cost"] == v["scenario_cost"] == "0.00"
        and v["exclusions"]["unknown_currency"] == 1
    )


@pytest.mark.asyncio
async def test_scenario_materialization_is_bounded_and_never_truncated_as_complete(
    exact_db,
):
    f = exact_db
    async with f[1]() as db:
        await db.execute(
            text(
                "WITH new_orders AS (INSERT INTO orders(id,customer_name,customer_phone,pickup_address,delivery_address,assigned_rider_id,ordered_at,status) SELECT gen_random_uuid(),'Synthetic bounded scenario','1','A','B',:rid,NOW(),'ENTREGADO' FROM generate_series(1,10001) RETURNING id) INSERT INTO deliveries(id,order_id,rider_id,status,locked_bonus_amount,locked_bonus_currency,locked_bonus_type,completed_at,bonus_snapshot_date) SELECT gen_random_uuid(),id,:rid,'COMPLETADA',0,'USD','SUCCESS',NOW(),NOW() FROM new_orders"
            ),
            {"oid": f[2]["order"], "rid": f[2]["rider"]},
        )
        await db.commit()
    r = scenario(f)
    assert r.status_code == 409 and "10000" in r.text


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [0.1, True, "0.001", "1e1", "NaN", None])
async def test_scenario_rejects_numeric_and_overprecise_proposals(exact_db, bad):
    r = scenario(exact_db, bad)
    assert r.status_code == (200 if bad is None else 422), r.text


def read_bonus(f, order_ids=None, actor="owner"):
    return f[0].get(
        BONUS,
        params={"order_ids": ",".join(str(i) for i in (order_ids or [f[2]["order"]]))},
        headers=headers(f, actor),
    )


@pytest.mark.asyncio
async def test_bonus_read_preserves_exact_components_units_zero_and_actor(exact_db):
    f = exact_db
    order, did = await add(
        f,
        "0.00",
        locked_bonus_base=Decimal("0.10"),
        locked_bonus_zone_multiplier=Decimal("1.50"),
        locked_bonus_tier_multiplier=Decimal("1.10"),
        locked_bonus_tier_level="ORO",
    )
    before = await deliveries(f)
    r = read_bonus(f, [order])
    assert r.status_code == 200, r.text
    v = r.json()
    row = v["records"][0]
    assert (
        row["amount"] == "0.00"
        and row["base"] == "0.10"
        and row["zone_multiplier"] == "1.50"
        and row["tier_multiplier"] == "1.10"
    )
    assert (
        row["currency"] == row["currency_recorded"] == "USD"
        and row["delivery_id"] == str(did)
        and row["state_review"] is False
    )
    assert (
        v["actor"]["user_id"] == str(f[2]["owner"])
        and not v["ledger_credit_included"]
        and not v["available_balance_included"]
    )
    assert before == await deliveries(f)


@pytest.mark.asyncio
async def test_historical_bonus_does_not_inherit_currency_or_current_configuration(
    exact_db,
):
    f = exact_db
    order, _ = await add(f, "17.03", unit=None)
    before = read_bonus(f, [order]).json()["records"][0]
    assert before["amount"] == "17.03" and before["currency"] is None
    saved = config(f)
    r = f[0].patch(
        SETTINGS,
        json={"rider_delivery_bonus": "99.99"},
        headers={**headers(f), "If-Match": '"' + saved["revision"] + '"'},
    )
    assert r.status_code == 200, r.text
    assert read_bonus(f, [order]).json()["records"][0] == before


@pytest.mark.asyncio
async def test_order_without_delivery_is_not_a_bonus_or_a_synthetic_zero(exact_db):
    f = exact_db
    async with f[1]() as db:
        order = Order(
            customer_name="Fallback",
            customer_phone="1",
            pickup_address="A",
            delivery_address="B",
            assigned_rider_id=f[2]["rider"],
        )
        db.add(order)
        await db.commit()
        oid = order.id
    r = read_bonus(f, [oid])
    assert r.status_code == 200, r.text
    row = r.json()["records"][0]
    assert (
        row["source"] == "order_without_delivery"
        and row["delivery_id"] is None
        and row["amount"] is None
        and row["currency"] is None
    )


@pytest.mark.asyncio
async def test_owner_cannot_read_a_different_assignment_or_partial_batch(exact_db):
    f = exact_db
    oid, _ = await add(f)
    async with f[1]() as db:
        await db.execute(
            text("UPDATE orders SET assigned_rider_id=NULL WHERE id=:id"), {"id": oid}
        )
        await db.commit()
    r = read_bonus(f, [f[2]["order"], oid])
    assert r.status_code == 403 and "records" not in r.json()


@pytest.mark.asyncio
async def test_contradictory_delivery_identity_requires_review(exact_db):
    f = exact_db
    async with f[1]() as db:
        await db.execute(
            text("UPDATE orders SET assigned_rider_id=NULL WHERE id=:id"),
            {"id": f[2]["order"]},
        )
        await db.commit()
    assert read_bonus(f, actor="staff").status_code == 409


@pytest.mark.asyncio
async def test_unknown_and_invalid_fields_remain_visible_without_fake_zero(exact_db):
    f = exact_db
    oid, _ = await add(f, "NaN", unit=None)
    r = read_bonus(f, [oid])
    assert r.status_code == 200, r.text
    row = r.json()["records"][0]
    assert (
        row["amount"] is None
        and row["currency"] is None
        and row["money_review"]
        == [{"field": "locked_bonus_amount", "reason": "IMPORTE_NO_VALIDO"}]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("ids", ["bad", "", ",".join(str(uuid4()) for _ in range(11))])
async def test_bonus_query_is_bounded_and_validated(exact_db, ids):
    r = exact_db[0].get(BONUS, params={"order_ids": ids}, headers=headers(exact_db))
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_unreadable_legacy_float_can_be_repaired_without_losing_raw_audit(
    exact_db,
):
    f = exact_db
    config(f)
    async with f[1]() as db:
        await db.execute(
            text(
                "UPDATE platform_settings SET value='1e1000'::json WHERE key='rider_delivery_bonus'"
            )
        )
        await db.commit()
    before = config(f)
    assert before["legacy_revision"] is None and before["rider_delivery_bonus"] is None
    r = f[0].patch(
        SETTINGS,
        json={"rider_delivery_bonus": "0.10"},
        headers={**headers(f), "If-Match": '"' + before["revision"] + '"'},
    )
    assert r.status_code == 200, r.text
    async with f[1]() as db:
        audit = (await db.scalars(select(AuditLog))).one()
        assert audit.old_values["stored_json"]["rider_delivery_bonus"] == "1e1000"
    assert (
        r.json()["rider_delivery_bonus"] == "0.10"
        and r.json()["legacy_revision"] is not None
    )


@pytest.mark.asyncio
async def test_rider_cannot_query_global_scenarios_or_settings(exact_db):
    f = exact_db
    revision = config(f)["revision"]
    assert f[0].get(SETTINGS, headers=headers(f, "owner")).status_code == 403
    assert (
        f[0]
        .post(
            SCENARIO,
            json={
                "new_base_bonus": "0.00",
                "days_projection": 7,
                "expected_settings_revision": revision,
            },
            headers=headers(f, "owner"),
        )
        .status_code
        == 403
    )
