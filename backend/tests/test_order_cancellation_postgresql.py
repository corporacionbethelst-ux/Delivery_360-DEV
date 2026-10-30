"""Cancellation contracts on real PostgreSQL, with HTTP and independent sessions."""

import asyncio
from concurrent.futures import Future
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import MetaData, select, update, func, text, delete
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_delivery_financial_postgresql import (
    payment_db,
    request,
    saved,
)  # noqa: F401
from app.core.security import create_access_token
from app.models.audit_log import AuditLog
from app.models.delivery import Delivery, DeliveryStatus
from app.models.financial import Financial, RiderWallet, PayoutRequest, PayoutStatus
from app.models.fiscal import (
    ElectronicInvoice,
    PaymentDistributionSnapshot,
    CountryTaxRegime,
)
from app.models.notification import Alert
from app.models.order import Order, OrderStatus
from app.models.route import Route, RouteStatus, RoutePoint
from app.models.user import User, UserRole
from app.services import order_cancellation as cancellation
from app.services.tracking_access import resolve_tracking_channel

REASON = "Cliente solicita cancelar su pedido"


@pytest.fixture
async def cancel_db(payment_db):
    client, sessions, ids = payment_db
    tables = {
        m.__table__
        for m in (
            AuditLog,
            ElectronicInvoice,
            PaymentDistributionSnapshot,
            Route,
            RoutePoint,
            Alert,
            PayoutRequest,
        )
    }
    while True:
        expanded = tables | {
            fk.column.table for table in tables for fk in table.foreign_keys
        }
        if expanded == tables:
            break
        tables = expanded
    ddl = MetaData()
    for table in tables:
        table.to_metadata(ddl)
    async with sessions() as db:
        conn = await db.connection()
        # Fiscal enums use create_type=False; explicitly create them on disposable metadata.
        for table in ddl.tables.values():
            for column in table.columns:
                if hasattr(column.type, "create"):
                    await conn.run_sync(
                        lambda c, t=column.type: t.create(c, checkfirst=True)
                    )
        await conn.run_sync(ddl.create_all)
        route = Route(delivery_id=ids["delivery"], status=RouteStatus.EN_PROGRESO)
        db.add(route)
        await db.flush()
        ids["route"] = route.id
        db.add_all(
            [
                Alert(
                    delivery_id=ids["delivery"],
                    alert_type="SLA_BREACH",
                    title="SLA",
                    status="OPEN",
                ),
                Alert(
                    delivery_id=ids["delivery"],
                    alert_type="INCIDENT",
                    title="Keep evidence",
                    status="OPEN",
                ),
            ]
        )
        order = await db.get(Order, ids["order"])
        order.delivery_instructions = "Conservar instrucciones originales"
        await db.commit()
    return client, sessions, ids


def cancel_request(client, ids, reason=REASON, *, actor="staff", generic=False):
    headers = {"Authorization": "Bearer " + create_access_token(ids[actor])}
    return client.patch(
        f"/api/v1/orders/{ids['order']}/" + ("status" if generic else "cancel"),
        headers=headers,
        **(
            {"params": {"new_status": "CANCELADO"}}
            if generic
            else {"json": {"reason": reason}}
        ),
    )


async def snapshot(sessions, ids):
    async with sessions() as db:
        order = await db.get(Order, ids["order"])
        delivery = await db.get(Delivery, ids["delivery"])
        route = await db.get(Route, ids["route"])
        wallet = await db.scalar(
            select(RiderWallet).where(RiderWallet.rider_id == ids["rider"])
        )
        return (
            order.status,
            order.cancelled_by,
            order.cancellation_reason,
            order.assigned_rider_id,
            order.delivery_instructions,
            delivery.status,
            delivery.rider_id,
            delivery.completed_at,
            delivery.locked_bonus_amount,
            delivery.proof_otp,
            route.status,
            route.completed_at,
            wallet.balance_cents,
            await db.scalar(
                select(func.sum(PayoutRequest.amount_cents)).where(
                    PayoutRequest.status == PayoutStatus.PENDIENTE
                )
            ),
            await db.scalar(select(func.count()).select_from(Financial)),
            await db.scalar(select(func.count()).select_from(AuditLog)),
            [
                (a.alert_type, a.status, a.resolved_by, a.resolution_notes)
                for a in (
                    await db.scalars(select(Alert).order_by(Alert.alert_type))
                ).all()
            ],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("generic", [False, True])
async def test_cancel_is_atomic_audited_and_idempotent_without_money_movements(
    cancel_db, generic
):
    client, sessions, ids = cancel_db
    async with sessions() as db:
        wallet = await db.scalar(select(RiderWallet))
        db.add(
            PayoutRequest(wallet_id=wallet.id, rider_id=ids["rider"], amount_cents=300)
        )
        await db.commit()
    financial_before = await saved(sessions, ids)
    response = cancel_request(client, ids, generic=generic)
    assert response.status_code == 200, response.text
    reason = cancellation.LEGACY_REASON if generic else REASON
    assert response.json()["cancellation_reason"] == reason
    assert response.json()["cancelled_by"] == str(ids["staff"])
    first = await snapshot(sessions, ids)
    assert first[:5] == (
        OrderStatus.CANCELADO,
        str(ids["staff"]),
        reason,
        ids["rider"],
        "Conservar instrucciones originales",
    )
    assert first[5:9] == (DeliveryStatus.CANCELADA, ids["rider"], None, None)
    assert first[10:16] == (RouteStatus.CANCELADA, None, 1000, 300, 1, 1)
    assert first[16][0] == ("INCIDENT", "OPEN", None, None)
    assert first[16][1] == (
        "SLA_BREACH",
        "RESOLVED",
        ids["staff"],
        "Orden cancelada: " + reason,
    )
    again = cancel_request(client, ids, generic=generic)
    assert again.status_code == 200, again.text
    assert await snapshot(sessions, ids) == first
    async with sessions() as db:
        receipt = await db.scalar(select(AuditLog))
        assert receipt.old_values["order_status"] == "EN_RUTA"
        assert receipt.new_values["money_changed"] is False
        assert receipt.new_values["resolved_sla_count"] == 1
    # Existing cache and ledger values are preserved; compare their explicit fields.
    after = await saved(sessions, ids)
    assert after[2:] == financial_before[2:]


@pytest.mark.asyncio
@pytest.mark.parametrize("generic", [False, True])
@pytest.mark.parametrize("role", list(UserRole))
async def test_both_entrypoints_share_management_authorization(
    cancel_db, generic, role
):
    client, sessions, ids = cancel_db
    async with sessions() as db:
        await db.execute(update(User).where(User.id == ids["staff"]).values(role=role))
        await db.commit()
    before = await snapshot(sessions, ids)
    response = cancel_request(client, ids, generic=generic)
    assert response.status_code == (
        200 if role in (UserRole.SUPERADMIN, UserRole.GERENTE) else 403
    ), response.text
    if response.status_code != 200:
        assert await snapshot(sessions, ids) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason", [None, "", "corto", "x" * 501, "motivo\ninvalido", "motivo\u200binvalido"]
)
async def test_invalid_reasons_do_not_write(cancel_db, reason):
    client, sessions, ids = cancel_db
    before = await snapshot(sessions, ids)
    response = cancel_request(client, ids, reason)
    assert response.status_code in (400, 422), response.text
    assert await snapshot(sessions, ids) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "conflict",
    [
        "order_complete",
        "order_failed",
        "delivery_complete",
        "delivery_failed",
        "delivery_cancelled",
        "assignment",
        "bonus",
        "receipt_key",
        "reference",
        "source",
        "distribution",
        "invoice",
        "closed_route",
        "duplicate_delivery",
    ],
)
async def test_ambiguous_terminal_or_financial_evidence_refuses_all_writes(
    cancel_db, conflict
):
    client, sessions, ids = cancel_db
    async with sessions() as db:
        if conflict.startswith("order_"):
            order = await db.get(Order, ids["order"])
            order.status = (
                OrderStatus.ENTREGADO
                if conflict.endswith("complete")
                else OrderStatus.FALLIDO
            )
        elif conflict.startswith("delivery_"):
            delivery = await db.get(Delivery, ids["delivery"])
            delivery.status = {
                "delivery_complete": DeliveryStatus.COMPLETADA,
                "delivery_failed": DeliveryStatus.FALLIDA,
                "delivery_cancelled": DeliveryStatus.CANCELADA,
            }[conflict]
        elif conflict == "assignment":
            await db.execute(update(Order).values(assigned_rider_id=None))
        elif conflict == "bonus":
            await db.execute(update(Delivery).values(locked_bonus_amount=Decimal("0")))
        elif conflict in ("receipt_key", "reference", "source"):
            values = {
                "receipt_key": {"idempotency_key": f"pago_fallido_{ids['order']}"},
                "reference": {"reference_id": str(ids["delivery"])},
                "source": {"source_id": str(ids["order"])},
            }[conflict]
            await db.execute(update(Financial).values(**values))
        elif conflict == "distribution":
            db.add(
                PaymentDistributionSnapshot(
                    order_id=ids["order"],
                    gross_amount_cents=0,
                    platform_share_cents=0,
                    rider_share_cents=0,
                )
            )
        elif conflict == "invoice":
            db.add(
                ElectronicInvoice(
                    order_id=ids["order"],
                    resolution_number=1,
                    sequence_number=1,
                    provider_type=CountryTaxRegime.COLOMBIA,
                    subtotal_cents=0,
                    tax_total_cents=0,
                    grand_total_cents=0,
                )
            )
        elif conflict == "closed_route":
            await db.execute(update(Route).values(status=RouteStatus.COMPLETADA))
        else:
            # Model a legacy schema missing the unique index; do not mutate ORM metadata.
            await db.execute(text("DROP INDEX ix_deliveries_order_id"))
            db.add(
                Delivery(
                    order_id=ids["order"],
                    rider_id=ids["rider"],
                    status=DeliveryStatus.INICIADA,
                )
            )
        await db.commit()
    before = await snapshot(sessions, ids)
    response = cancel_request(client, ids)
    assert response.status_code == 409, response.text
    assert await snapshot(sessions, ids) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["flush", "commit"])
async def test_late_failure_rolls_back_order_delivery_route_alerts_and_audit(
    cancel_db, monkeypatch, failure
):
    client, sessions, ids = cancel_db
    before = await snapshot(sessions, ids)
    original = getattr(AsyncSession, failure)

    async def broken(db, *args, **kwargs):
        if db.info.get("workflow_request"):
            raise RuntimeError("injected cancellation failure")
        return await original(db, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, failure, broken)
    response = cancel_request(client, ids)
    assert response.status_code == 500, response.text
    assert await snapshot(sessions, ids) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["reason", "actor", "route", "historical"])
async def test_retries_cannot_overwrite_prior_or_partial_cancellation(
    cancel_db, change
):
    client, sessions, ids = cancel_db
    if change == "historical":
        async with sessions() as db:
            await db.execute(update(Order).values(status=OrderStatus.CANCELADO))
            await db.commit()
    else:
        assert cancel_request(client, ids).status_code == 200
        if change == "actor":
            async with sessions() as db:
                await db.execute(
                    update(User)
                    .where(User.id == ids["owner"])
                    .values(role=UserRole.GERENTE)
                )
                await db.commit()
        elif change == "route":
            async with sessions() as db:
                await db.execute(update(Route).values(status=RouteStatus.EN_PROGRESO))
                await db.commit()
    before = await snapshot(sessions, ids)
    response = cancel_request(
        client,
        ids,
        "Otro motivo de cancelación" if change == "reason" else REASON,
        actor="owner" if change == "actor" else "staff",
    )
    assert response.status_code == 409, response.text
    assert await snapshot(sessions, ids) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation", ["success", "failure", "service_success", "service_failure"]
)
@pytest.mark.parametrize("historical", [False, True])
async def test_cancelled_parent_blocks_all_delivery_terminal_entrypoints(
    cancel_db, operation, historical
):
    client, sessions, ids = cancel_db
    if historical:
        async with sessions() as db:
            await db.execute(update(Order).values(status=OrderStatus.CANCELADO))
            await db.commit()
    else:
        assert cancel_request(client, ids).status_code == 200
    before = await snapshot(sessions, ids)
    response = request(client, ids, operation)
    assert response.status_code in (400, 409), response.text
    assert await snapshot(sessions, ids) == before


@pytest.mark.asyncio
async def test_cancel_closes_tracking_and_revenue_settlement(cancel_db):
    from app.services.split_payment_service import process_order_settlement

    client, sessions, ids = cancel_db
    assert cancel_request(client, ids).status_code == 200
    async with sessions() as db:
        actor = await db.get(User, ids["staff"])
        with pytest.raises(HTTPException) as error:
            await resolve_tracking_channel(db, actor, f"order:{ids['order']}")
        assert error.value.status_code == 409
        assert await process_order_settlement(db, ids["order"]) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["cancel", "success", "service_failure"])
async def test_concurrent_cancel_and_terminal_actions_have_one_consistent_winner(
    cancel_db, operation
):
    client, sessions, ids = cancel_db

    def other():
        return (
            cancel_request(client, ids)
            if operation == "cancel"
            else request(client, ids, operation)
        )

    async with asyncio.timeout(15):
        responses = await asyncio.gather(
            asyncio.to_thread(cancel_request, client, ids), asyncio.to_thread(other)
        )
    codes = sorted(r.status_code for r in responses)
    assert codes in ([200, 200], [200, 400], [200, 409]), [r.text for r in responses]
    async with sessions() as db:
        order = await db.get(Order, ids["order"])
        delivery = await db.get(Delivery, ids["delivery"])
        audits = await db.scalar(select(func.count()).select_from(AuditLog))
        count = await db.scalar(select(func.count()).select_from(Financial))
        if order.status == OrderStatus.CANCELADO:
            assert delivery.status == DeliveryStatus.CANCELADA
            assert (audits, count) == (1, 1)
        else:
            assert (order.status, delivery.status) in (
                (OrderStatus.ENTREGADO, DeliveryStatus.COMPLETADA),
                (OrderStatus.FALLIDO, DeliveryStatus.FALLIDA),
            )
            assert audits == 0
            assert count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change,code", [("role", 403), ("inactive", 401), ("token", 401)]
)
async def test_actor_is_rechecked_after_locks_before_cancellation(
    cancel_db, monkeypatch, change, code
):
    client, sessions, ids = cancel_db
    entered, release = Future(), Future()
    original = cancellation._enum_ready

    async def paused(db):
        entered.set_result(None)
        await asyncio.wrap_future(release)
        await original(db)

    monkeypatch.setattr(cancellation, "_enum_ready", paused)
    async with asyncio.timeout(15):
        pending = asyncio.create_task(asyncio.to_thread(cancel_request, client, ids))
        try:
            await asyncio.wait_for(asyncio.wrap_future(entered), 5)
            async with sessions() as db:
                values = {
                    "role": {"role": UserRole.CLIENTE},
                    "inactive": {"is_active": False},
                    "token": {"token_version": 1},
                }[change]
                await db.execute(
                    update(User).where(User.id == ids["staff"]).values(**values)
                )
                await db.commit()
        finally:
            release.set_result(None)
        response = await asyncio.wait_for(pending, 10)
    assert response.status_code == code, response.text
    result = await snapshot(sessions, ids)
    assert result[0] == OrderStatus.EN_RUTA
    assert result[5] == DeliveryStatus.EN_ROUTE
    assert result[15] == 0


@pytest.mark.asyncio
async def test_pending_order_without_delivery_can_be_cancelled(cancel_db):
    client, sessions, ids = cancel_db
    async with sessions() as db:
        order = Order(
            customer_name="Pending",
            customer_phone="123",
            pickup_address="A",
            delivery_address="B",
            status=OrderStatus.PENDIENTE,
        )
        db.add(order)
        await db.commit()
        result = await cancellation.cancel_order(
            db, order.id, ids["staff"], "  " + "x" * 500 + "  ", commit=True
        )
        assert result.status == OrderStatus.CANCELADO
        assert result.cancellation_reason == "x" * 500
        assert (
            await cancellation.cancel_order(
                db, order.id, ids["staff"], "x" * 500, commit=True
            )
            is result
        )


@pytest.mark.asyncio
async def test_old_physical_enum_fails_closed_without_writes(cancel_db, monkeypatch):
    client, sessions, ids = cancel_db
    # Native physical enum without CANCELADA, matching a deployment missing the migration.
    async with sessions() as db:
        await db.execute(text("ALTER TYPE deliverystatus RENAME TO old_deliverystatus"))
        labels = ",".join(
            "'" + status.value + "'"
            for status in DeliveryStatus
            if status != DeliveryStatus.CANCELADA
        )
        await db.execute(text("CREATE TYPE deliverystatus AS ENUM (" + labels + ")"))
        await db.execute(
            text(
                "ALTER TABLE deliveries ALTER COLUMN status TYPE deliverystatus USING status::text::deliverystatus"
            )
        )
        await db.commit()
    before = await snapshot(sessions, ids)
    response = cancel_request(client, ids)
    assert response.status_code == 503, response.text
    assert await snapshot(sessions, ids) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation",
    [
        "start",
        "location",
        "assign",
        "order_status",
        "order_edit",
        "order_assign",
        "order_auto",
    ],
)
async def test_cancelled_order_cannot_move_reassign_or_reopen(cancel_db, operation):
    client, sessions, ids = cancel_db
    assert cancel_request(client, ids).status_code == 200
    before = await snapshot(sessions, ids)
    headers = {"Authorization": "Bearer " + create_access_token(ids["staff"])}
    did, oid = ids["delivery"], ids["order"]
    if operation == "start":
        response = client.post(
            f"/api/v1/deliveries/{did}/start",
            json={"lat": 4.5, "lng": -74},
            headers=headers,
        )
    elif operation == "location":
        response = client.patch(
            f"/api/v1/deliveries/{did}/location",
            json={"lat": 4.5, "lng": -74},
            headers=headers,
        )
    elif operation == "assign":
        response = client.post(
            f"/api/v1/deliveries/{did}/assign",
            json={"rider_id": str(ids["rider"])},
            headers=headers,
        )
    elif operation == "order_status":
        response = client.patch(
            f"/api/v1/orders/{oid}/status",
            params={"new_status": "ASIGNADO"},
            headers=headers,
        )
    elif operation == "order_edit":
        response = client.patch(
            f"/api/v1/orders/{oid}", json={"customer_name": "Changed"}, headers=headers
        )
    elif operation == "order_assign":
        response = client.patch(
            f"/api/v1/orders/{oid}/assign",
            json={"rider_id": str(ids["rider"])},
            headers=headers,
        )
    else:
        response = client.post(f"/api/v1/orders/{oid}/assign-auto", headers=headers)
    assert response.status_code in (400, 409), response.text
    assert await snapshot(sessions, ids) == before


@pytest.mark.asyncio
async def test_sla_monitor_ignores_historical_cancelled_order_with_active_child(
    cancel_db,
):
    from datetime import datetime, timedelta
    from app.services.worker_jobs import WorkerJobs

    _, sessions, ids = cancel_db
    async with sessions() as db:
        await db.execute(update(Order).values(status=OrderStatus.CANCELADO))
        await db.execute(
            update(Delivery).values(
                started_at=datetime.utcnow() - timedelta(hours=3),
                sla_expected_minutes=30,
            )
        )
        await db.execute(delete(Alert))
        await db.commit()
        result = await WorkerJobs(db).monitor_sla(datetime.utcnow())
        assert result["alerts_created"] == 0
        assert await db.scalar(select(func.count()).select_from(Alert)) == 0
