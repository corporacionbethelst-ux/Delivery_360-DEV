"""Persisted progress must agree across order, delivery and map coordinates."""

from datetime import datetime

import pytest
from sqlalchemy import select, func

from tests.test_delivery_financial_postgresql import payment_db  # noqa: F401
from app.core.security import create_access_token
from app.models.delivery import Delivery, DeliveryStatus
from app.models.financial import Financial
from app.models.order import Order, OrderStatus


@pytest.mark.parametrize("collected", [False, True])
@pytest.mark.parametrize("already_started", [False, True])
async def test_start_persists_utc_progress_in_both_resources_without_creating_money(
    payment_db, collected, already_started
):
    client, sessions, ids = payment_db
    original = datetime(2026, 11, 1, 12) if already_started else None
    async with sessions() as db:
        delivery = await db.get(Delivery, ids["delivery"])
        delivery.status = (
            DeliveryStatus.EN_PICKUP if collected else DeliveryStatus.INICIADA
        )
        delivery.started_at = original
        order = await db.get(Order, ids["order"])
        order.status = OrderStatus.RECOLECTADO if collected else OrderStatus.ASIGNADO
        receipts = await db.scalar(select(func.count()).select_from(Financial))
        await db.commit()
    headers = {"Authorization": "Bearer " + create_access_token(ids["owner"])}
    response = client.post(
        f"/api/v1/deliveries/{ids['delivery']}/start",
        headers=headers,
        json={"lat": 0, "lng": 0},
    )
    assert response.status_code == 200, response.text
    async with sessions() as db:
        delivery = await db.get(Delivery, ids["delivery"])
        order = await db.get(Order, ids["order"])
        assert delivery.status == DeliveryStatus.EN_ROUTE
        assert order.status == OrderStatus.EN_RUTA
        assert delivery.started_at is not None and delivery.started_at.tzinfo is None
        if original is not None:
            assert delivery.started_at == original
        assert delivery.left_pickup_at is not None
        departed = delivery.left_pickup_at
        assert (delivery.current_latitude, delivery.current_longitude) == (0, 0)
        assert await db.scalar(select(func.count()).select_from(Financial)) == receipts
    repeated = client.post(
        f"/api/v1/deliveries/{ids['delivery']}/start", headers=headers, json={}
    )
    assert repeated.status_code == 400
    async with sessions() as db:
        assert (await db.get(Delivery, ids["delivery"])).left_pickup_at == departed
        assert await db.scalar(select(func.count()).select_from(Financial)) == receipts


@pytest.mark.parametrize("target", ["EN_ROUTE", "COMPLETADA"])
@pytest.mark.parametrize("coordinates", [(0, 0), (0, 13), (12, 0)])
async def test_zero_coordinates_survive_unified_progress_and_completion(
    payment_db, target, coordinates
):
    client, sessions, ids = payment_db
    async with sessions() as db:
        delivery = await db.get(Delivery, ids["delivery"])
        delivery.status = (
            DeliveryStatus.EN_PICKUP
            if target == "EN_ROUTE"
            else DeliveryStatus.EN_DESTINO
        )
        delivery.current_latitude = 25
        delivery.current_longitude = 30
        await db.commit()
    response = client.patch(
        f"/api/v1/deliveries/{ids['delivery']}/status",
        headers={"Authorization": "Bearer " + create_access_token(ids["owner"])},
        json={"status": target, "lat": coordinates[0], "lng": coordinates[1]},
    )
    assert response.status_code == 200, response.text
    async with sessions() as db:
        delivery = await db.get(Delivery, ids["delivery"])
        assert (delivery.current_latitude, delivery.current_longitude) == coordinates
        order = await db.get(Order, ids["order"])
        assert order.status == (
            OrderStatus.EN_RUTA if target == "EN_ROUTE" else OrderStatus.ENTREGADO
        )


@pytest.mark.parametrize(
    "terminal", [OrderStatus.ENTREGADO, OrderStatus.FALLIDO, OrderStatus.CANCELADO]
)
async def test_start_never_reopens_a_finished_order_from_an_inconsistent_delivery(
    payment_db, terminal
):
    client, sessions, ids = payment_db
    async with sessions() as db:
        delivery = await db.get(Delivery, ids["delivery"])
        delivery.status = DeliveryStatus.INICIADA
        delivery.started_at = None
        delivery.left_pickup_at = None
        order = await db.get(Order, ids["order"])
        order.status = terminal
        receipts = await db.scalar(select(func.count()).select_from(Financial))
        await db.commit()
    response = client.post(
        f"/api/v1/deliveries/{ids['delivery']}/start",
        headers={"Authorization": "Bearer " + create_access_token(ids["owner"])},
        json={"lat": 0, "lng": 0},
    )
    assert response.status_code == 409, response.text
    async with sessions() as db:
        order = await db.get(Order, ids["order"])
        delivery = await db.get(Delivery, ids["delivery"])
        assert order.status == terminal and delivery.status == DeliveryStatus.INICIADA
        assert delivery.started_at is None and delivery.left_pickup_at is None
        assert await db.scalar(select(func.count()).select_from(Financial)) == receipts


@pytest.mark.parametrize(
    "progress", [DeliveryStatus.INICIADA, DeliveryStatus.EN_PICKUP]
)
@pytest.mark.parametrize("actor", ["staff", "owner"])
@pytest.mark.parametrize("transport", ["fail", "status"])
async def test_closed_business_can_be_reported_before_departure_with_one_bonus(
    payment_db, progress, actor, transport
):
    client, sessions, ids = payment_db
    async with sessions() as db:
        delivery = await db.get(Delivery, ids["delivery"])
        delivery.status = progress
        order = await db.get(Order, ids["order"])
        order.status = (
            OrderStatus.RECOLECTADO
            if progress == DeliveryStatus.EN_PICKUP
            else OrderStatus.ASIGNADO
        )
        await db.commit()
    headers = {"Authorization": "Bearer " + create_access_token(ids[actor])}
    path = f"/api/v1/deliveries/{ids['delivery']}/{transport}"
    body = (
        {"failure_cause": "COMERCIO_CERRADO"}
        if transport == "fail"
        else {"status": "FALLIDA", "issue_type": "COMERCIO_CERRADO"}
    )
    response = (
        client.post(path, headers=headers, json=body)
        if transport == "fail"
        else client.patch(path, headers=headers, json=body)
    )
    assert response.status_code == 200, response.text
    async with sessions() as db:
        order = await db.get(Order, ids["order"])
        delivery = await db.get(Delivery, ids["delivery"])
        assert (
            order.status == OrderStatus.FALLIDO
            and delivery.status == DeliveryStatus.FALLIDA
        )
        assert delivery.left_pickup_at is None
        receipts = list(
            (
                await db.scalars(
                    select(Financial).where(
                        Financial.idempotency_key == f"pago_fallido_{ids['order']}"
                    )
                )
            ).all()
        )
        assert len(receipts) == 1 and receipts[0].amount == 1
    replay = (
        client.post(path, headers=headers, json=body)
        if transport == "fail"
        else client.patch(path, headers=headers, json=body)
    )
    assert replay.status_code == 400
