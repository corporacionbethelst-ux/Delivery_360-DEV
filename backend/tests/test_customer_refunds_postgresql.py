"""Real refund transitions, independent reconciliation, cents and SQL protection."""

import asyncio
import importlib.util
from pathlib import Path
from decimal import Decimal
from uuid import uuid4, UUID
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text, func
from sqlalchemy.exc import DBAPIError
from app.core.security import create_access_token
from app.models.customer_refund import CustomerRefund, CustomerRefundEvent
from app.models.audit_log import AuditLog
from app.services import bcv_currency as currency
from tests.test_customer_collections_postgresql import (
    collection_db,
    quote_db,
    currency_db,
    declaration,
    decision,
    call as collect_call,
    path as collect_path,
    review as collect_review,
    rate,
    quote_command,
    quote_call,
    quote_path,
)  # noqa: F401


def module():
    spec = importlib.util.spec_from_file_location(
        "refunds95",
        Path(__file__).parents[1] / "alembic/versions/20261114_customer_refunds.py",
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


async def migrate(engine, direction):
    def apply(conn):
        with Operations.context(MigrationContext.configure(conn)):
            getattr(module(), direction)()

    async with engine.begin() as conn:
        await conn.run_sync(apply)


@pytest.fixture
async def refund_db(collection_db):
    await migrate(collection_db[3], "upgrade")
    yield collection_db


def call(f, method, path, body=None, role="OPERADOR", status=200):
    response = f[0].request(
        method,
        "/api/v1/customer-refunds" + path,
        headers={"Authorization": "Bearer " + create_access_token(f[2][role])},
        json=body,
    )
    assert response.status_code == status, response.text
    return response.json()


def path(f):
    return "/orders/" + str(f[2]["order"])


async def paid(f, ves=False):
    body = declaration(f)
    body.update(amount_usd="0.50", paid_amount="0.50")
    if ves:
        reference = rate(f)
        quote = quote_call(
            f,
            "POST",
            quote_path(f),
            quote_command(f, reference["id"]),
            role="OPERADOR",
            status=201,
        )
        body.update(
            paid_currency="VES",
            paid_amount="0.75",
            method="PAGO_MOVIL",
            quote_id=quote["id"],
        )
    row = collect_call(f, "POST", collect_path(f), body, status=201)
    collect_review(f, row)
    async with f[1]() as db:
        await db.execute(text("UPDATE orders SET status='CANCELADO'"))
        await db.commit()
    return row


def request(row, amount="0.20", revision=0):
    return dict(
        request_key=str(uuid4()),
        collection_id=row["id"],
        expected_book_revision=revision,
        amount_usd=amount,
        reason="Cliente solicita devolución por cancelación",
        confirmed_request=True,
    )


def event(kind="APROBAR", revision=0, **extra):
    evidence = kind in [
        "VERIFICAR_DEVOLUCION",
        "CONFIRMAR_NO_EJECUTADA",
        "ANULAR_APROBACION",
    ]
    result = dict(
        request_key=str(uuid4()),
        expected_revision=revision,
        kind=kind,
        note="Comprobación sintética de esta devolución",
        verified_evidence=evidence,
        confirmed_no_execution=kind in ["CONFIRMAR_NO_EJECUTADA", "ANULAR_APROBACION"],
        confirmed_execution=kind == "DECLARAR_EJECUCION",
    )
    result.update(extra)
    return result


def execute(refund, revision=1, **extra):
    return event(
        "DECLARAR_EJECUCION",
        revision,
        method="EFECTIVO" if refund["return_currency"] == "USD" else "PAGO_MOVIL",
        source_key="CAJA DEVOLUCIONES",
        reference_key="SALIDA-" + uuid4().hex.upper(),
        paid_amount=refund["return_amount"],
        paid_currency=refund["return_currency"],
        executed_on=currency.current_day().isoformat(),
        **extra,
    )


def act(f, row, body, role="GERENTE", status=201):
    return call(f, "POST", "/" + row["id"] + "/events", body, role=role, status=status)


def settle(f, row):
    act(f, row, event())
    act(f, row, execute(row), role="SUPERADMIN")
    return act(f, row, event("VERIFICAR_DEVOLUCION", 2))


@pytest.mark.asyncio
async def test_request_authorize_declare_verify_and_idempotent_history(refund_db):
    f = refund_db
    original = await paid(f)
    body = request(original)
    r = call(f, "POST", path(f), body, status=201)
    assert (
        r["state"] == "SOLICITADA"
        and r["return_amount"] == "0.20"
        and r["bank_verified"] is False
    )
    assert call(f, "POST", path(f), body, status=201) == r
    c = call(f, "GET", path(f))
    assert c["summary"] == dict(
        currency="USD",
        gross_verified_usd="0.50",
        refunded_usd="0.00",
        in_progress_usd="0.20",
        remaining_usd="0.50",
        requestable_now_usd="0.00",
    )
    approve = event()
    a = act(f, r, approve)
    assert a["refund"]["state"] == "APROBADA"
    assert act(f, r, approve) == a
    assert call(f, "GET", path(f))["summary"]["remaining_usd"] == "0.50"
    outbound = execute(r)
    sent = act(f, r, outbound, role="SUPERADMIN")
    assert sent["refund"]["state"] == "EJECUCION_DECLARADA"
    act(f, r, event("VERIFICAR_DEVOLUCION", 2), role="SUPERADMIN", status=403)
    verified = event("VERIFICAR_DEVOLUCION", 2)
    final = act(f, r, verified)
    assert final["refund"]["state"] == "DEVUELTA"
    assert act(f, r, verified) == final
    assert (
        act(f, r, outbound, role="SUPERADMIN")["applied_event"] == sent["applied_event"]
    )
    assert call(f, "POST", path(f), body, status=201)["state"] == "DEVUELTA"
    summary = call(f, "GET", path(f))["summary"]
    assert (
        summary["refunded_usd"],
        summary["remaining_usd"],
        summary["in_progress_usd"],
        summary["requestable_now_usd"],
    ) == ("0.20", "0.30", "0.00", "0.30")
    async with f[1]() as db:
        assert (
            await db.scalar(select(func.count(CustomerRefund.id))) == 1
            and await db.scalar(select(func.count(CustomerRefundEvent.id))) == 3
        )
        assert (
            await db.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.resource_type.in_(
                        ["CUSTOMER_REFUND_REQUEST", "CUSTOMER_REFUND_EVENT"]
                    )
                )
            )
            == 4
        )


@pytest.mark.asyncio
async def test_partial_ves_cumulative_rounding_closes_original_cents_after_rate_change(
    refund_db,
):
    f = refund_db
    original = await paid(f, ves=True)
    current = quote_call(f, "GET", "/context")["current_rate"]
    rate(f, current["id"], "99.00000000")
    book = 0
    amounts = []
    for usd, expected in [("0.01", "0.02"), ("0.01", "0.01"), ("0.48", "0.72")]:
        r = call(f, "POST", path(f), request(original, usd, book), status=201)
        assert r["return_amount"] == expected and r["return_currency"] == "VES"
        amounts.append(Decimal(expected))
        settle(f, r)
        book += 4
    assert sum(amounts) == Decimal(original["paid_amount"])
    ctx = call(f, "GET", path(f))
    assert (
        ctx["summary"]["remaining_usd"] == "0.00"
        and ctx["summary"]["refunded_usd"] == "0.50"
    )
    call(f, "POST", path(f), request(original, "0.01", book), status=409)


@pytest.mark.asyncio
async def test_observed_execution_keeps_reservation_until_independent_reconciliation(
    refund_db,
):
    f = refund_db
    original = await paid(f)
    r = call(f, "POST", path(f), request(original), status=201)
    act(f, r, event())
    first = execute(r)
    act(f, r, first, role="SUPERADMIN")
    act(f, r, event("OBSERVAR_EJECUCION", 2))
    ctx = call(f, "GET", path(f))
    assert (
        ctx["refunds"][0]["state"] == "OBSERVADA"
        and ctx["summary"]["in_progress_usd"] == "0.20"
        and ctx["summary"]["refunded_usd"] == "0.00"
    )
    call(f, "POST", path(f), request(original, "0.01", 4), status=409)
    act(f, r, execute(r, 3), role="SUPERADMIN", status=409)
    act(f, r, event("CONFIRMAR_NO_EJECUTADA", 3), role="SUPERADMIN", status=403)
    act(f, r, event("CONFIRMAR_NO_EJECUTADA", 3))
    act(f, r, execute(r, 4), role="SUPERADMIN")
    final = act(f, r, event("VERIFICAR_DEVOLUCION", 5))
    assert final["refund"]["state"] == "DEVUELTA"
    assert len(final["refund"]["events"]) == 6
    # Even an observed/voided reference cannot identify a second outgoing attempt.
    new = call(f, "POST", path(f), request(original, "0.10", 7), status=201)
    act(f, new, event())
    again = {**first, "request_key": str(uuid4())}
    act(f, new, again, role="SUPERADMIN", status=422)
    again.update(paid_amount="0.10")
    act(f, new, again, role="SUPERADMIN", status=409)


@pytest.mark.asyncio
async def test_rejection_and_cancelled_approval_release_capacity_without_refund_credit(
    refund_db,
):
    f = refund_db
    original = await paid(f)
    r = call(f, "POST", path(f), request(original), status=201)
    act(f, r, event("RECHAZAR"))
    ctx = call(f, "GET", path(f))
    assert ctx["summary"]["requestable_now_usd"] == "0.50"
    r = call(f, "POST", path(f), request(original, "0.50", 2), status=201)
    act(f, r, event())
    act(f, r, event("ANULAR_APROBACION", 1))
    ctx = call(f, "GET", path(f))
    assert (
        ctx["summary"]["remaining_usd"] == "0.50"
        and ctx["summary"]["in_progress_usd"] == "0.00"
    )


@pytest.mark.asyncio
async def test_roles_ownership_stale_intent_and_unverified_collections(refund_db):
    f = refund_db
    row = collect_call(f, "POST", collect_path(f), declaration(f), status=201)
    call(f, "POST", path(f), request(row), status=409)
    async with f[1]() as db:
        await db.execute(text("UPDATE orders SET status='CANCELADO'"))
        await db.commit()
    call(f, "POST", path(f), request(row), status=409)
    collect_review(f, row, decision(acknowledge_refund_due=True))
    for role in ["CLIENTE", "REPARTIDOR", "AUDITOR"]:
        call(f, "POST", path(f), request(row), role=role, status=403)
    call(f, "POST", path(f), request(row), role="OTHER", status=403)
    r = call(f, "POST", path(f), request(row), role="GERENTE", status=201)
    act(f, r, event(), role="GERENTE", status=403)
    act(f, r, event(), role="OPERADOR", status=403)
    act(f, r, event(revision=1), role="SUPERADMIN", status=412)
    act(f, r, event(), role="SUPERADMIN")
    assert call(f, "GET", "/" + r["id"], role="AUDITOR")["state"] == "APROBADA"
    call(f, "GET", "/" + r["id"], role="OTHER", status=403)
    assert call(f, "GET", path(f), role="OTHER")["refunds"] == []
    body = request(row, "0.01", 0)
    call(f, "POST", path(f), body, status=412)
    changed = {**body, "request_key": r["request_key"]}
    call(f, "POST", path(f), changed, status=409)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"amount_usd": True},
        {"amount_usd": "NaN"},
        {"amount_usd": "0.001"},
        {"amount_usd": "0.00"},
        {"confirmed_request": 1},
        {"reason": "Invalid \x7f note"},
        {"reason": "short"},
        {"expected_book_revision": True},
        {"unexpected": True},
    ],
)
async def test_request_input_rejects_invalid_money_confirmation_and_notes(
    refund_db, change
):
    f = refund_db
    row = await paid(f)
    body = request(row)
    body.update(change)
    call(f, "POST", path(f), body, status=422)
    assert call(f, "GET", path(f))["book_revision"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"note": "Invalid \x00 note"},
        {"note": "Invalid \x7f note"},
        {"verified_evidence": 1},
        {"confirmed_execution": 1},
        {"method": "EFECTIVO"},
        {"paid_amount": "1.00"},
        {"kind": "VERIFICAR_DEVOLUCION", "verified_evidence": False},
    ],
)
async def test_event_input_is_strict_and_cannot_smuggle_execution_data(
    refund_db, change
):
    f = refund_db
    original = await paid(f)
    r = call(f, "POST", path(f), request(original), status=201)
    body = event()
    body.update(change)
    act(f, r, body, status=422)
    assert call(f, "GET", "/" + r["id"])["revision"] == 0


@pytest.mark.asyncio
async def test_concurrent_requests_and_idempotent_approval_serialize(refund_db):
    f = refund_db
    row = await paid(f)

    def post(body):
        return f[0].post(
            "/api/v1/customer-refunds" + path(f),
            headers={
                "Authorization": "Bearer " + create_access_token(f[2]["OPERADOR"])
            },
            json=body,
        )

    a, b = await asyncio.gather(
        asyncio.to_thread(post, request(row)), asyncio.to_thread(post, request(row))
    )
    assert sorted([a.status_code, b.status_code]) == [201, 412]
    r = a.json() if a.status_code == 201 else b.json()
    body = event()

    def approve():
        return f[0].post(
            "/api/v1/customer-refunds/" + r["id"] + "/events",
            headers={"Authorization": "Bearer " + create_access_token(f[2]["GERENTE"])},
            json=body,
        )

    a, b = await asyncio.gather(asyncio.to_thread(approve), asyncio.to_thread(approve))
    assert a.status_code == b.status_code == 201 and a.json() == b.json()


@pytest.mark.asyncio
async def test_history_guards_wrong_amount_self_approval_reopening_and_downgrade(
    refund_db,
):
    f = refund_db
    original = await paid(f)
    r = call(f, "POST", path(f), request(original), role="GERENTE", status=201)
    async with f[1]() as db:
        for sql in [
            "UPDATE customer_refunds SET amount_usd=0.01",
            "DELETE FROM customer_refunds",
            "TRUNCATE customer_refunds CASCADE",
            "UPDATE orders SET status='PENDIENTE'",
        ]:
            with pytest.raises(DBAPIError):
                await db.execute(text(sql))
            await db.rollback()
        db.add(
            CustomerRefundEvent(
                request_key=uuid4(),
                refund_id=UUID(r["id"]),
                revision=1,
                kind="APROBAR",
                note="Invalid direct self approval",
                verified_evidence=False,
                confirmed_no_execution=False,
                confirmed_execution=False,
                actor_id=f[2]["GERENTE"],
                created_at=currency.utc_now().replace(tzinfo=None),
            )
        )
        with pytest.raises(DBAPIError):
            await db.flush()
        await db.rollback()
    act(f, r, event(), role="SUPERADMIN")
    async with f[1]() as db:
        for sql in [
            "UPDATE customer_refund_events SET note=note",
            "DELETE FROM customer_refund_events",
            "TRUNCATE customer_refund_events",
        ]:
            with pytest.raises(DBAPIError):
                await db.execute(text(sql))
            await db.rollback()
    with pytest.raises(RuntimeError, match="preserve customer refunds"):
        await migrate(f[3], "downgrade")


@pytest.mark.asyncio
async def test_audit_failure_rolls_back_request_and_event(refund_db):
    f = refund_db
    row = await paid(f)
    async with f[3].begin() as conn:
        await conn.execute(
            text(
                "ALTER TABLE audit_logs ADD CONSTRAINT reject_refund95 CHECK (resource_type NOT IN ('CUSTOMER_REFUND_REQUEST','CUSTOMER_REFUND_EVENT'))"
            )
        )
    call(f, "POST", path(f), request(row), status=500)
    assert call(f, "GET", path(f))["book_revision"] == 0
    async with f[3].begin() as conn:
        await conn.execute(
            text("ALTER TABLE audit_logs DROP CONSTRAINT reject_refund95")
        )
    r = call(f, "POST", path(f), request(row), status=201)
    async with f[3].begin() as conn:
        await conn.execute(
            text(
                "ALTER TABLE audit_logs ADD CONSTRAINT reject_event95 CHECK (resource_type <> 'CUSTOMER_REFUND_EVENT')"
            )
        )
    act(f, r, event(), status=500)
    assert call(f, "GET", "/" + r["id"])["revision"] == 0


@pytest.mark.asyncio
async def test_empty_downgrade_preserves_collection_history(refund_db):
    f = refund_db
    await paid(f)
    await migrate(f[3], "downgrade")
    await migrate(f[3], "upgrade")
    assert call(f, "GET", path(f))["summary"]["gross_verified_usd"] == "0.50"


@pytest.mark.asyncio
async def test_direct_sql_cannot_forge_refund_conversion_prefix_or_missing_role(
    refund_db,
):
    f = refund_db
    original = await paid(f)
    values = dict(
        request_key=uuid4(),
        collection_id=UUID(original["id"]),
        amount_usd=Decimal("0.20"),
        return_amount=Decimal("0.20"),
        return_currency="USD",
        prior_refunded_usd=Decimal("0"),
        prior_refunded_paid=Decimal("0"),
        reason="Synthetic direct SQL guard probe",
        requested_by=f[2]["OPERADOR"],
        created_at=currency.utc_now().replace(tzinfo=None),
    )
    async with f[1]() as db:
        for changes in [
            {"return_amount": Decimal("0.21")},
            {"return_currency": "VES"},
            {
                "prior_refunded_usd": Decimal("0.01"),
                "prior_refunded_paid": Decimal("0.01"),
            },
            {"amount_usd": Decimal("0.51"), "return_amount": Decimal("0.51")},
        ]:
            db.add(CustomerRefund(**{**values, **changes, "request_key": uuid4()}))
            with pytest.raises(DBAPIError):
                await db.flush()
            await db.rollback()
        await db.execute(
            text("UPDATE users SET role=NULL WHERE id=:id"), {"id": f[2]["OPERADOR"]}
        )
        db.add(CustomerRefund(**values))
        with pytest.raises(DBAPIError):
            await db.flush()
        await db.rollback()
    assert call(f, "GET", path(f))["book_revision"] == 0


@pytest.mark.asyncio
async def test_large_event_history_is_paginated_and_recovers_original_request(
    refund_db,
):
    f = refund_db
    original = await paid(f)
    r = call(f, "POST", path(f), request(original), status=201)
    act(f, r, event())
    revision = 1
    async with f[1]() as db:
        for attempt in range(17):
            for kind, actor in [
                ("DECLARAR_EJECUCION", "SUPERADMIN"),
                ("OBSERVAR_EJECUCION", "GERENTE"),
                ("CONFIRMAR_NO_EJECUTADA", "GERENTE"),
            ]:
                revision += 1
                body = (
                    execute(r, revision - 1)
                    if kind == "DECLARAR_EJECUCION"
                    else event(kind, revision - 1)
                )
                payload = {
                    key: body.get(key)
                    for key in [
                        "method",
                        "source_key",
                        "reference_key",
                        "paid_amount",
                        "paid_currency",
                        "executed_on",
                    ]
                }
                if payload["paid_amount"] is not None:
                    payload["paid_amount"] = Decimal(payload["paid_amount"])
                if payload["executed_on"] is not None:
                    from datetime import date

                    payload["executed_on"] = date.fromisoformat(payload["executed_on"])
                db.add(
                    CustomerRefundEvent(
                        request_key=uuid4(),
                        refund_id=UUID(r["id"]),
                        revision=revision,
                        kind=kind,
                        note=body["note"],
                        verified_evidence=body["verified_evidence"],
                        confirmed_no_execution=body["confirmed_no_execution"],
                        confirmed_execution=body["confirmed_execution"],
                        actor_id=f[2][actor],
                        created_at=currency.utc_now().replace(tzinfo=None),
                        **payload,
                    )
                )
                await db.flush()
        await db.commit()
    saved = call(f, "GET", "/" + r["id"])
    assert (
        saved["revision"] == 52
        and len(saved["events"]) == 50
        and saved["has_more_events"]
    )
    older = call(f, "GET", "/" + r["id"] + "/events?before_revision=3")
    assert [x["revision"] for x in older["events"]] == [2, 1] and not older["has_more"]
    assert saved["request_key"] == r["request_key"] and saved["state"] == "APROBADA"
