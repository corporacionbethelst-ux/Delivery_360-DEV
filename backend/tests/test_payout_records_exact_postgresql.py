"""Decimal payout read scopes, existing signed cursors and coherent full history."""

import asyncio, hashlib, json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4
import pytest
from sqlalchemy import text, event, insert
from app.core.security import create_access_token
from app.models.payout import Payout, PayoutStatus, PayoutStatusHistory
from tests.test_financial_reports_exact_postgresql import (
    reports_db,
    quote_db,
    currency_db,
    payout,
)  # noqa: F401

BASE = "/api/v1/payouts/exact"
STAMP = datetime(2026, 11, 15, 16)


@pytest.fixture
async def exact_db(reports_db):
    async with reports_db[3].begin() as db:
        await db.run_sync(
            lambda c: PayoutStatusHistory.__table__.create(c, checkfirst=True)
        )
    yield reports_db


def get(f, id=None, params=None, role="GERENTE", status=200):
    r = f[0].get(
        BASE + ("/" + str(id) if id is not None else "/page"),
        params=params or {},
        headers=(
            {"Authorization": "Bearer " + create_access_token(f[2][role])}
            if role
            else {}
        ),
    )
    assert r.status_code == status, r.text
    return r.json()


async def history(f, payout_id, **extra):
    async with f[1]() as db:
        values = dict(
            id=uuid4(),
            payout_id=payout_id,
            currency_code="USD",
            old_status="PENDIENTE",
            new_status="EN_PROCESO",
            created_at=STAMP,
            balance_before=Decimal("20.10"),
            balance_after=Decimal("10.00"),
            changed_by_user_id=f[2]["GERENTE"],
        )
        values.update(extra)
        row = PayoutStatusHistory(**values)
        db.add(row)
        await db.commit()
        return row.id


@pytest.mark.asyncio
async def test_decimal_record_and_history_one_cut_with_original_units(exact_db):
    f = exact_db
    id = await payout(f, "10.10", balance_before=Decimal("20.10"))
    await history(f, id, currency_code=None, balance_after=None)
    async with f[1]() as db:
        await db.execute(
            text("UPDATE payouts SET balance_after=NULL,updated_at=NULL WHERE id=:id"),
            {"id": id},
        )
        await db.commit()
    v = get(f, id)
    r = v["items"][0]
    h = v["history"][0]
    assert (
        r["amount"] == r["total_amount"] == "10.10"
        and r["balance_before"] == "20.10"
        and r["balance_after"] is None
        and r["updated_at"] is None
    )
    assert r["orders_count"] is None and r["period"] is None
    assert (
        h["currency"] is None
        and h["balance_before"] == "20.10"
        and h["balance_after"] is None
    )
    assert (
        v["history_included"] and v["history_complete"] and v["history_limit"] == 1000
    )
    assert (
        not v["available_balance_included"]
        and not v["bank_verified"]
        and not v["wallet_cents_included"]
    )
    digest = v.pop("content_sha256")
    assert (
        digest
        == hashlib.sha256(
            json.dumps(
                v, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "currency,expected,review",
    [
        (None, None, False),
        ("VES", "VES", False),
        ("COP", "COP", False),
        ("usd", None, True),
        ("", None, True),
    ],
)
async def test_currency_not_converted_or_relabelled(
    exact_db, currency, expected, review
):
    f = exact_db
    id = await payout(f, "10.01")
    async with f[1]() as db:
        await db.execute(
            text("UPDATE payouts SET currency_code=:c WHERE id=:id"),
            {"c": currency, "id": id},
        )
        await db.commit()
    r = get(f, id)["items"][0]
    assert (
        r["currency"] == expected
        and r["currency_recorded"] == currency
        and r["currency_review"] == review
        and r["amount"] == "10.01"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", ["0.00", "-0.01", "NaN"])
async def test_invalid_amount_stays_as_reviewable_record(exact_db, amount):
    f = exact_db
    bad = await payout(f, amount)
    healthy = await payout(f, "10.01")
    v = get(f)
    assert len(v["items"]) == 2
    r = next(r for r in v["items"] if r["id"] == str(bad))
    assert (
        r["amount"] is None
        and r["total_amount"] is None
        and r["money_review"] == [{"field": "amount", "reason": "IMPORTE_NO_VALIDO"}]
    )
    assert next(r for r in v["items"] if r["id"] == str(healthy))["amount"] == "10.01"


@pytest.mark.asyncio
async def test_unknown_state_method_and_bad_destination_remain_read_only(exact_db):
    f = exact_db
    id = await payout(f, "10.00", balance_before=Decimal("NaN"))
    async with f[1]() as db:
        await db.execute(
            text(
                "UPDATE payouts SET status=NULL,method=NULL,bank_account_last4='1234567890' WHERE id=:id"
            ),
            {"id": id},
        )
        await db.commit()
    r = get(f, id)["items"][0]
    assert (
        r["status"] is None
        and r["method"] is None
        and r["bank_account_last4"] is None
        and r["bank_destination_review"]
    )
    assert r["balance_before"] is None and r["money_review"] == [
        {"field": "balance_before", "reason": "IMPORTE_NO_VALIDO"}
    ]


@pytest.mark.asyncio
async def test_page_reuses_legacy_cursor_and_stable_null_boundary(exact_db):
    f = exact_db
    ids = [await payout(f, "10.01"), await payout(f, "10.02"), await payout(f, "10.03")]
    async with f[1]() as db:
        await db.execute(
            text("UPDATE payouts SET requested_at=NULL WHERE id=:id"), {"id": ids[-1]}
        )
        await db.commit()
    old = f[0].get(
        "/api/v1/payouts/page",
        params={"limit": 1},
        headers={"Authorization": "Bearer " + create_access_token(f[2]["GERENTE"])},
    )
    assert old.status_code == 200
    a = get(f, params={"limit": 1})
    assert (
        a["items"][0]["id"] == old.json()["items"][0]["id"]
        and a["next_cursor"] == old.json()["next_cursor"]
    )
    b = get(f, params={"limit": 1, "cursor": a["next_cursor"]})
    c = get(f, params={"limit": 1, "cursor": b["next_cursor"]})
    assert (
        len({a["items"][0]["id"], b["items"][0]["id"], c["items"][0]["id"]}) == 3
        and c["items"][0]["id"] == str(ids[-1])
        and c["next_cursor"] is None
    )
    assert not a["history_included"] and not a["history_complete"]
    await payout(f, "10.04")
    again = get(f, params={"limit": 1, "cursor": a["next_cursor"]})
    assert again["items"][0]["id"] == b["items"][0]["id"]


@pytest.mark.asyncio
async def test_cursor_is_bound_to_actor_filter_and_limit(exact_db):
    f = exact_db
    for _ in range(3):
        await payout(f, "10.00")
    cursor = get(f, params={"limit": 1})["next_cursor"]
    for changes in [
        {"limit": 2},
        {"status": "PENDIENTE"},
        {"rider_id": str(f[2]["rider"])},
    ]:
        get(f, params={"limit": 1, "cursor": cursor, **changes}, status=400)
    get(f, params={"limit": 1, "cursor": cursor}, role="SUPERADMIN", status=400)
    get(
        f,
        params={
            "limit": 1,
            "cursor": cursor[:-1] + ("0" if cursor[-1] != "0" else "1"),
        },
        status=400,
    )


@pytest.mark.asyncio
async def test_rider_scope_cannot_select_another_owner_or_use_staff_cursor(exact_db):
    from app.models.rider import Rider

    f = exact_db
    own = await payout(f, "10.00")
    async with f[1]() as db:
        other = Rider(user_id=f[2]["OTHER"])
        db.add(other)
        await db.flush()
        foreign = Payout(
            rider_id=other.id,
            amount=Decimal("10.00"),
            currency_code="USD",
            status=PayoutStatus.PENDIENTE,
        )
        db.add(foreign)
        await db.commit()
        foreign_id = foreign.id
        other_id = other.id
    v = get(f, role="REPARTIDOR")
    assert (
        len(v["items"]) == 1
        and v["items"][0]["id"] == str(own)
        and v["effective_rider_id"] == str(f[2]["rider"])
    )
    assert get(f, own, role="REPARTIDOR")["items"][0]["id"] == str(own)
    get(f, foreign_id, role="REPARTIDOR", status=404)
    get(f, params={"rider_id": str(other_id)}, role="REPARTIDOR", status=403)
    cursor = get(f, params={"limit": 1})["next_cursor"]
    get(f, params={"limit": 1, "cursor": cursor}, role="REPARTIDOR", status=400)


@pytest.mark.asyncio
async def test_history_ties_nulls_and_foreign_events_do_not_mix(exact_db):
    f = exact_db
    id = await payout(f, "10.00")
    foreign = await payout(f, "10.00")
    await history(f, id, id=UUID(int=2))
    await history(f, id, id=UUID(int=1))
    last = await history(f, id, created_at=None, new_status="LEGACY_STATE")
    async with f[1]() as db:
        await db.execute(
            text("UPDATE payout_status_history SET created_at=NULL WHERE id=:id"),
            {"id": last},
        )
        await db.commit()
    await history(f, foreign)
    v = get(f, id)
    assert [r["id"] for r in v["history"]] == [
        str(UUID(int=1)),
        str(UUID(int=2)),
        str(last),
    ] and v["history"][-1]["new_status"] == "LEGACY_STATE"
    assert all(r["payout_id"] == str(id) for r in v["history"])


@pytest.mark.asyncio
async def test_complete_history_cap_never_returns_a_partial_success(exact_db):
    f = exact_db
    id = await payout(f, "10.00")
    async with f[1]() as db:
        await db.execute(
            insert(PayoutStatusHistory),
            [
                dict(id=uuid4(), payout_id=id, new_status="PENDIENTE", created_at=STAMP)
                for _ in range(1001)
            ],
        )
        await db.commit()
    get(f, id, status=409)


@pytest.mark.asyncio
async def test_parent_and_events_survive_concurrent_write_as_one_snapshot(exact_db):
    f = exact_db
    id = await payout(f, "10.00")
    seen = []

    async def write():
        async with f[1]() as db:
            await db.execute(
                text("UPDATE payouts SET status='RECHAZADO' WHERE id=:id"), {"id": id}
            )
            db.add(
                PayoutStatusHistory(
                    payout_id=id, new_status="RECHAZADO", created_at=STAMP
                )
            )
            await db.commit()

    def listener(conn, cursor, statement, parameters, context, many):
        if "exact_payout_clock" not in statement or seen:
            return
        seen.append(statement)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(lambda: asyncio.run(write())).result(timeout=15)

    event.listen(f[3].sync_engine, "after_cursor_execute", listener)
    try:
        before = get(f, id)
    finally:
        event.remove(f[3].sync_engine, "after_cursor_execute", listener)
    after = get(f, id)
    assert (
        before["items"][0]["status"] == "PENDIENTE"
        and before["history"] == []
        and after["items"][0]["status"] == "RECHAZADO"
        and len(after["history"]) == 1
        and len(seen) == 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role,expected",
    [
        (None, 401),
        ("GERENTE", 200),
        ("SUPERADMIN", 200),
        ("REPARTIDOR", 200),
        ("OPERADOR", 403),
        ("CLIENTE", 403),
        ("AUDITOR", 403),
    ],
)
async def test_read_permissions_before_resource_lookup(exact_db, role, expected):
    f = exact_db
    get(f, role=role, status=expected)
    get(f, uuid4(), role=role, status=404 if expected == 200 else expected)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 201},
        {"cursor": "bad"},
        {"status": "CANCELADO"},
        {"rider_id": "bad"},
        {"offset": 0},
        {"user_id": str(uuid4())},
    ],
)
async def test_invalid_page_query_never_falls_back_to_offset(exact_db, params):
    get(exact_db, params=params, status=400 if params.get("cursor") == "bad" else 422)


@pytest.mark.asyncio
async def test_legacy_numeric_contracts_and_empty_clock_preserved(exact_db):
    f = exact_db
    v = get(f)
    assert v["items"] == [] and v["generated_at"].endswith("Z") and v["total"] == 0
    id = await payout(f, "10.01")
    old = f[0].get(
        "/api/v1/payouts/" + str(id),
        headers={"Authorization": "Bearer " + create_access_token(f[2]["GERENTE"])},
    )
    assert old.status_code == 200 and old.json()["amount"] == 10.01
    assert get(f, id)["items"][0]["amount"] == "10.01"
    get(f, id, params={"rider_id": str(f[2]["rider"])}, status=422)
    get(f, "bad", status=422)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["GERENTE", "SUPERADMIN", "REPARTIDOR"])
async def test_audience_binds_page_and_detail_to_the_intended_role(exact_db, role):
    f = exact_db
    pid = await payout(f, "10.10")
    owner = role == "REPARTIDOR"
    audience = "OWNER" if owner else "STAFF"
    # The fixture payout belongs to this rider; owner reads retain their own scope.
    for value in (None, pid):
        result = get(f, value, {"audience": audience}, role=role)
        assert result["filters"]["audience"] == audience
        assert result["viewer_role"] == role
        get(
            f, value, {"audience": "STAFF" if owner else "OWNER"}, role=role, status=403
        )
    get(f, params={"audience": "GLOBAL"}, role=role, status=422)
