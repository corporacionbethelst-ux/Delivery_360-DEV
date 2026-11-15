"""Exact rider audit: source units, one-statement cut and independent aggregates."""

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from app.core.security import create_access_token
from app.models.delivery import Delivery, DeliveryStatus
from app.models.financial import TransactionType, PaymentStatus
from app.models.payout import PayoutStatus
from tests.test_financial_reports_exact_postgresql import (
    reports_db,
    quote_db,
    currency_db,
    ledger,
    payout,
)  # noqa: F401

PATH = "/api/v1/riders/audit/summary/exact"


def get(f, params=None, role="GERENTE", status=200):
    response = f[0].get(
        PATH,
        params=params or {},
        headers=(
            {"Authorization": "Bearer " + create_access_token(f[2][role])}
            if role
            else {}
        ),
    )
    assert response.status_code == status, response.text
    return response.json()


@pytest.mark.asyncio
async def test_exact_directions_requests_and_hash(reports_db):
    f = reports_db
    await ledger(f, "-0.10")
    await ledger(f, "0.20", TransactionType.BONO)
    await ledger(f, "-0.07", TransactionType.DESCUENTO)
    await ledger(f, "0.05", TransactionType.RETIRO)
    await ledger(f, "-0.03", TransactionType.AJUSTE)
    await payout(f, "10.01")
    await payout(f, "50.00", PayoutStatus.COMPLETADO)
    v = get(f, {"rider_id": str(f[2]["rider"]), "limit": 1})
    m = v["items"][0]["money"]
    assert {
        k: m[k]
        for k in (
            "credit_usd",
            "debit_usd",
            "adjustment_usd",
            "net_change_usd",
            "pending_usd",
        )
    } == dict(
        credit_usd="0.30",
        debit_usd="0.12",
        adjustment_usd="-0.03",
        net_change_usd="0.15",
        pending_usd="10.01",
    )
    assert m["ledger_rows"] == m["ledger_included"] == 5
    assert m["payout_rows"] == 2 and m["payout_included"] == 1
    assert (
        not v["available_balance_included"]
        and not v["bank_verified"]
        and not v["wallet_cents_included"]
    )
    assert v["snapshot_basis"] == "single_statement_visibility"
    assert v["viewer_user_id"] == str(f[2]["GERENTE"])
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
async def test_exclusions_preserve_unknown_currency_dates_and_status(reports_db):
    f = reports_db
    unknown = await ledger(f, "0.00")
    ves = await ledger(f, "99.99")
    undated = await ledger(f, "1.00")
    future = await ledger(f, "1.00")
    await ledger(f, "1.00", status=PaymentStatus.PENDIENTE)
    await ledger(f, "1.00", TransactionType.DELIVERY_BONUS)
    p = await payout(f, "0.00")
    async with f[1]() as db:
        for id, column, value in [
            (unknown, "currency_code", None),
            (ves, "currency_code", "VES"),
            (undated, "created_at", None),
            (future, "created_at", datetime(2099, 1, 1)),
        ]:
            await db.execute(
                text(f"UPDATE financials SET {column}=:value WHERE id=:id"),
                {"value": value, "id": id},
            )
        await db.execute(
            text("UPDATE payouts SET currency_code=NULL WHERE id=:id"), {"id": p}
        )
        await db.commit()
    m = get(f)["items"][0]["money"]
    assert m["credit_usd"] == m["net_change_usd"] == m["pending_usd"] == "0.00"
    assert m["ledger_rows"] == 6 and m["ledger_included"] == 0
    assert {r["reason"]: r["count"] for r in m["ledger_exclusions"]} == dict(
        FECHA_NO_REGISTRADA=1,
        MONEDA_NO_VERIFICADA=2,
        FECHA_FUTURA=1,
        ESTADO_NO_PROCESADO=1,
        TIPO_NO_ADMITIDO=1,
    )
    assert m["payout_exclusions"][1]["count"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", ["0.00", "NaN"])
async def test_invalid_eligible_amounts_never_publish_false_zero(reports_db, amount):
    await ledger(reports_db, amount)
    get(reports_db, status=409)


@pytest.mark.asyncio
async def test_operational_counts_do_not_multiply_ledger(reports_db):
    f = reports_db
    await ledger(f, "0.10")
    await ledger(f, "0.20")
    async with f[1]() as db:
        await db.execute(
            text(
                "UPDATE orders SET assigned_rider_id=:rider, status='ASIGNADO' WHERE id=:id"
            ),
            {"rider": f[2]["rider"], "id": f[2]["order"]},
        )
        db.add(
            Delivery(
                id=uuid4(),
                order_id=f[2]["order"],
                rider_id=f[2]["rider"],
                status=DeliveryStatus.COMPLETADA,
                sla_compliant=True,
            )
        )
        await db.commit()
    row = get(f)["items"][0]
    assert (
        row["orders_assigned"]
        == row["orders_active"]
        == row["deliveries_total"]
        == row["deliveries_completed"]
        == row["sla_compliant"]
        == 1
    )
    assert row["sla_compliance_rate"] == 100
    assert row["money"]["credit_usd"] == "0.30" and row["money"]["ledger_included"] == 2


@pytest.mark.asyncio
async def test_filters_empty_page_and_direct_identity(reports_db):
    f = reports_db
    async with f[1]() as db:
        await db.execute(
            text("UPDATE riders SET is_online=false, status='ACTIVO' WHERE id=:id"),
            {"id": f[2]["rider"]},
        )
        await db.commit()
    assert get(f, {"is_online": "false", "status_filter": "ACTIVO"})["items"][0][
        "rider_id"
    ] == str(f[2]["rider"])
    for params in [{"is_online": "true"}, {"offset": 500}, {"rider_id": str(uuid4())}]:
        v = get(f, params)
        assert v["items"] == [] and v["total"] == 0 and v["generated_at"].endswith("Z")
    v = get(f, {"rider_id": str(f[2]["rider"]), "limit": 1})
    assert len(v["items"]) == 1 and v["filters"]["rider_id"] == str(f[2]["rider"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role,status",
    [
        (None, 401),
        ("GERENTE", 200),
        ("SUPERADMIN", 200),
        ("OPERADOR", 403),
        ("REPARTIDOR", 403),
        ("CLIENTE", 403),
        ("AUDITOR", 403),
    ],
)
async def test_staff_permission_matrix(reports_db, role, status):
    get(reports_db, role=role, status=status)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 201},
        {"offset": -1},
        {"rider_id": "bad"},
        {"status_filter": "UNKNOWN"},
    ],
)
async def test_invalid_filters(reports_db, params):
    get(reports_db, params, status=422)


@pytest.mark.asyncio
async def test_single_statement_snapshot_survives_concurrent_insert(reports_db):
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy import event

    f = reports_db
    seen = []

    def listener(conn, cursor, statement, parameters, context, many):
        if "audit_exact_clock" not in statement or seen:
            return
        seen.append(statement)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(lambda: asyncio.run(ledger(f, "0.01"))).result(timeout=15)

    event.listen(f[3].sync_engine, "after_cursor_execute", listener)
    try:
        before = get(f)["items"][0]["money"]
    finally:
        event.remove(f[3].sync_engine, "after_cursor_execute", listener)
    after = get(f)["items"][0]["money"]
    assert len(seen) == 1 and before["ledger_rows"] == 0
    assert after["ledger_rows"] == 1 and after["credit_usd"] == "0.01"
    assert after == get(f)["items"][0]["money"]


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", ["0.00", "NaN", "-0.01"])
async def test_invalid_pending_request_blocks_summary(reports_db, amount):
    await payout(reports_db, amount)
    get(reports_db, status=409)


@pytest.mark.asyncio
async def test_equal_names_have_stable_uuid_tie_break_and_no_join_duplication(
    reports_db,
):
    from uuid import UUID
    from app.models.user import User, UserRole
    from app.models.rider import Rider, RiderStatus

    f = reports_db
    keys = [UUID(int=1), UUID(int=2)]
    async with f[1]() as db:
        for key in reversed(keys):
            u = User(
                email=str(key) + "@example.test",
                hashed_password="unused",
                first_name="AAA",
                last_name="Same",
                role=UserRole.REPARTIDOR,
                is_active=True,
            )
            db.add(u)
            await db.flush()
            db.add(
                Rider(id=key, user_id=u.id, status=RiderStatus.ACTIVO, is_online=False)
            )
        await db.commit()
    a = get(f, {"is_online": "false", "limit": 1})
    b = get(f, {"is_online": "false", "limit": 1, "offset": 1})
    assert [a["items"][0]["rider_id"], b["items"][0]["rider_id"]] == [
        str(k) for k in keys
    ]
    assert get(f, {"rider_id": str(keys[1]), "limit": 1})["items"][0][
        "rider_id"
    ] == str(keys[1])
