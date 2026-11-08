"""Read-only catalog: real PostGIS rows, stable ties, filters and current roles."""

from datetime import datetime
from uuid import UUID
import pytest
from sqlalchemy import select, func
from tests.test_delivery_financial_postgresql import payment_db  # noqa: F401
from app.core.security import create_access_token
from app.models.delivery import Delivery, DeliveryStatus
from app.models.order import Order, OrderStatus
from app.models.user import User, UserRole
from app.models.financial import Financial
from app.models.rider import Rider, RiderStatus


@pytest.fixture
async def catalog(payment_db):
    client, sessions, ids = payment_db
    async with sessions() as db:
        other = User(
            email="other@catalog.test",
            hashed_password="unused",
            first_name="Other",
            last_name="Rider",
            role=UserRole.REPARTIDOR,
            is_active=True,
        )
        db.add(other)
        await db.flush()
        other_rider = Rider(user_id=other.id, status=RiderStatus.ACTIVO)
        db.add(other_rider)
        await db.flush()
        existing = await db.get(Delivery, ids["delivery"])
        existing.created_at = datetime(2026, 11, 1)
        for index in range(1, 26):
            order = Order(
                customer_name="Cliente",
                customer_phone="123",
                pickup_address="A",
                delivery_address="B",
                status=OrderStatus.EN_RUTA,
                assigned_rider_id=ids["rider"],
            )
            db.add(order)
            await db.flush()
            db.add(
                Delivery(
                    id=UUID(int=index),
                    order_id=order.id,
                    rider_id=ids["rider"] if index % 2 else other_rider.id,
                    status=(
                        DeliveryStatus.COMPLETADA
                        if index % 3
                        else DeliveryStatus.EN_ROUTE
                    ),
                    total_time=0,
                    created_at=datetime(2026, 11, 1),
                )
            )
        # An assigned order without a delivery must never expand a catalog page.
        db.add(
            Order(
                customer_name="Not a delivery",
                customer_phone="123",
                pickup_address="A",
                delivery_address="B",
                status=OrderStatus.ASIGNADO,
                assigned_rider_id=ids["rider"],
            )
        )
        await db.commit()
    return client, sessions, ids


def get(client, ids, params=None, token=None):
    return client.get(
        "/api/v1/deliveries/page",
        params=params,
        headers={
            "Authorization": "Bearer " + (token or create_access_token(ids["staff"]))
        },
    )


async def test_pages_count_only_real_deliveries_and_preserve_ties(catalog):
    client, sessions, ids = catalog
    first = get(client, ids, {"limit": 20})
    second = get(client, ids, {"limit": 20, "offset": 20})
    assert first.status_code == second.status_code == 200
    a, b = first.json(), second.json()
    assert (
        a["total"] == b["total"] == 26
        and len(a["items"]) == 20
        and len(b["items"]) == 6
    )
    actual = [row["id"] for row in a["items"] + b["items"]]
    assert len(set(actual)) == 26 and actual == sorted(actual, reverse=True)
    assert a == get(client, ids, {"limit": 20}).json()
    assert all(
        row["customer_name"] != "Not a delivery" for row in a["items"] + b["items"]
    )
    assert get(client, ids, {"offset": 100}).json() == {
        "items": [],
        "total": 26,
        "offset": 100,
        "limit": 20,
    }
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Financial)) == 1


@pytest.mark.parametrize(
    "params",
    [
        {"unassigned": "true"},
        {"unassigned": "false"},
        {"status": "COMPLETADA"},
        {"status": "EN_ROUTE", "unassigned": "true"},
        {"status": "COMPLETADA", "unassigned": "false"},
        {"status": "FALLIDA"},
    ],
)
async def test_all_filters_apply_to_count_and_rows(catalog, params):
    client, _, ids = catalog
    response = get(client, ids, {**params, "limit": 200})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == len(data["items"])
    for row in data["items"]:
        if "unassigned" in params:
            assert (row["rider_id"] is None) == (params["unassigned"] == "true")
        if "status" in params:
            assert row["status"] == params["status"]
    if params == {"unassigned": "true"}:
        assert data["total"] == 0
    if params == {"status": "FALLIDA"}:
        assert data["total"] == 0


async def test_rider_id_and_conflicting_assignment_are_explicit(catalog):
    client, _, ids = catalog
    data = get(client, ids, {"rider_id": str(ids["rider"]), "limit": 200}).json()
    assert data["total"] == 14 and all(
        row["rider_id"] == str(ids["rider"]) for row in data["items"]
    )
    assert (
        get(
            client, ids, {"rider_id": str(ids["rider"]), "unassigned": "true"}
        ).status_code
        == 400
    )


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 201},
        {"limit": -1},
        {"offset": -1},
        {"offset": "bad"},
        {"rider_id": "bad"},
        {"status": "EN_RUTA"},
        {"status": "UNKNOWN"},
        {"unassigned": "bad"},
    ],
)
async def test_invalid_queries_are_not_ignored(payment_db, params):
    client, _, ids = payment_db
    assert get(client, ids, params).status_code == 422


@pytest.mark.parametrize(
    "role,expected",
    [
        (UserRole.GERENTE, 200),
        (UserRole.SUPERADMIN, 200),
        (UserRole.OPERADOR, 403),
        (UserRole.REPARTIDOR, 403),
        (UserRole.AUDITOR, 403),
        (UserRole.CLIENTE, 403),
        (None, 401),
    ],
)
async def test_actual_live_roles_protect_catalog(payment_db, role, expected):
    client, sessions, ids = payment_db
    token = create_access_token(ids["staff"])
    async with sessions() as db:
        user = await db.get(User, ids["staff"])
        user.role = role
        await db.commit()
    assert get(client, ids, token=token).status_code == expected


async def test_missing_credentials_never_return_a_catalog(payment_db):
    client, _, _ = payment_db
    assert client.get("/api/v1/deliveries/page").status_code == 401
