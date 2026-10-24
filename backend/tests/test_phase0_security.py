"""Regression tests for phase 0: real HTTP routing, fake persistence only.

No application lifespan, real database, Redis, payouts or notifications run here.
"""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI

from app.api.v1 import deliveries, orders, riders
from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.core.delivery_rules import validate_delivery_otp
from app.core.operation_permissions import ensure_rider_resource_access
from app.models.delivery import DeliveryStatus, ProofType
from app.models.order import OrderStatus
from app.models.rider import RiderTier, VehicleType
from app.models.user import UserRole
from app.schemas.delivery import ProofOfDeliveryCreate
from app.services.delivery_service import DeliveryService


def result(value=None, row=None):
    res = MagicMock()
    res.scalar_one_or_none.return_value = value
    res.unique.return_value.scalar_one_or_none.return_value = value
    res.unique.return_value.scalar_one.return_value = value
    res.first.return_value = row
    res.all.return_value = []
    return res


@pytest.fixture
def db():
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.flush = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.fixture
def user():
    return SimpleNamespace(id=uuid.uuid4(), role=UserRole.REPARTIDOR)


@pytest.fixture
def delivery():
    return SimpleNamespace(id=uuid.uuid4(), rider_id=uuid.uuid4(),
        order_id=uuid.uuid4(), status=DeliveryStatus.EN_ROUTE,
        proof_type=ProofType.NINGUNO, proof_otp=None, rider=None, order=None)


@pytest.fixture
def api_app(db, user):
    app = FastAPI()
    for router in (deliveries.router, orders.router, riders.router):
        app.include_router(router, prefix="/api/v1")
    async def current_user():
        return user
    async def session():
        yield db
    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[get_db] = session
    return app


@pytest.fixture
def http(api_app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=api_app), base_url="http://test")


MUTATIONS = [
    ("post", "start", {}),
    ("post", "complete", {}),
    ("post", "fail", {"failure_cause": "CLIENTE_NO_ESTA"}),
    ("patch", "location", {"lat": 0, "lng": 0}),
    ("patch", "status", {"status": "COMPLETADA"}),
]


@pytest.mark.parametrize("role", [UserRole.CLIENTE, UserRole.AUDITOR])
@pytest.mark.parametrize("method,path,body", MUTATIONS)
async def test_non_operational_roles_cannot_mutate_delivery(http, db, user, delivery, role, method, path, body):
    user.role = role
    async with http:
        response = await http.request(method, f"/api/v1/deliveries/{delivery.id}/{path}", json=body)
    assert response.status_code == 403
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("method,path,body", MUTATIONS)
async def test_rider_cannot_mutate_another_delivery(http, db, user, delivery, method, path, body, monkeypatch):
    db.execute.side_effect = [result(delivery), result(SimpleNamespace(id=uuid.uuid4()))]
    complete = AsyncMock()
    monkeypatch.setattr(deliveries.delivery_service, "complete_delivery", complete)
    async with http:
        response = await http.request(method, f"/api/v1/deliveries/{delivery.id}/{path}", json=body)
    assert response.status_code == 403
    complete.assert_not_awaited()
    db.commit.assert_not_awaited()
    assert delivery.status == DeliveryStatus.EN_ROUTE


@pytest.mark.parametrize("role", [UserRole.REPARTIDOR, UserRole.OPERADOR, UserRole.GERENTE, UserRole.SUPERADMIN])
async def test_complete_preserves_authorized_path_and_proof_contract(http, db, user, delivery, monkeypatch, role):
    user.role = role
    sequence = [result(delivery)]
    if role == UserRole.REPARTIDOR:
        sequence.append(result(SimpleNamespace(id=delivery.rider_id)))
    sequence.append(result(row=(delivery, None, None, None)))
    db.execute.side_effect = sequence
    complete = AsyncMock(return_value=delivery)
    monkeypatch.setattr(deliveries.delivery_service, "complete_delivery", complete)
    monkeypatch.setattr(deliveries, "_serialize_delivery", lambda *a: {"id": str(delivery.id)})
    async with http:
        response = await http.post(f"/api/v1/deliveries/{delivery.id}/complete", json={"notes": "Recibido"})
    assert response.status_code == 200, response.text
    proof = complete.await_args.kwargs["proof_data"]
    assert proof.delivery_id == delivery.id
    assert proof.notes == "Recibido"
    assert complete.await_args.kwargs["completed_by"] == user.id


@pytest.mark.parametrize("status", [DeliveryStatus.COMPLETADA, DeliveryStatus.FALLIDA])
@pytest.mark.parametrize("target", ["EN_PICKUP", "EN_ROUTE", "EN_DESTINO", "COMPLETADA", "FALLIDA"])
async def test_terminal_delivery_cannot_be_reopened(http, db, user, delivery, status, target):
    user.role = UserRole.GERENTE
    delivery.status = status
    db.execute.return_value = result(delivery)
    async with http:
        response = await http.patch(f"/api/v1/deliveries/{delivery.id}/status", json={"status": target})
    assert response.status_code == 400
    assert delivery.status == status
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("status", [DeliveryStatus.PENDIENTE, DeliveryStatus.COMPLETADA, DeliveryStatus.FALLIDA])
async def test_location_rejected_outside_active_delivery(http, db, user, delivery, status):
    user.role = UserRole.GERENTE
    delivery.status = status
    db.execute.return_value = result(delivery)
    async with http:
        response = await http.patch(f"/api/v1/deliveries/{delivery.id}/location", json={"lat": 0, "lng": 0})
    assert response.status_code == 400
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("otp", [None, "", "654321"])
async def test_unified_completion_requires_existing_otp(http, db, user, delivery, otp):
    user.role = UserRole.GERENTE
    delivery.proof_type = ProofType.OTP
    delivery.proof_otp = "123456"
    db.execute.return_value = result(delivery)
    async with http:
        response = await http.patch(f"/api/v1/deliveries/{delivery.id}/status", json={"status": "COMPLETADA", "otp_code": otp})
    assert response.status_code == 400
    assert delivery.status == DeliveryStatus.EN_ROUTE
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("otp", [None, "", "654321"])
async def test_service_rejects_otp_before_bonus_or_writes(db, delivery, otp):
    delivery.proof_otp = "123456"
    svc = DeliveryService()
    svc.get_delivery = AsyncMock(return_value=delivery)
    svc._get_bonus_config_and_snapshot = AsyncMock()
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await svc.complete_delivery(db, delivery.id, ProofOfDeliveryCreate(delivery_id=delivery.id, otp_code=otp), uuid.uuid4())
    assert exc.value.status_code == 400
    svc._get_bonus_config_and_snapshot.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("proof_type,expected,supplied", [
    (ProofType.OTP, "123456", "123456"),
    (ProofType.NINGUNO, None, None),
    (ProofType.NINGUNO, "123456", "123456"),
])
def test_otp_preserves_valid_and_non_otp_deliveries(delivery, proof_type, expected, supplied):
    delivery.proof_type, delivery.proof_otp = proof_type, expected
    validate_delivery_otp(delivery, supplied)


def test_required_otp_without_secret_is_rejected(delivery):
    from fastapi import HTTPException
    delivery.proof_type = ProofType.OTP
    with pytest.raises(HTTPException):
        validate_delivery_otp(delivery, "123456")


async def test_order_status_cannot_bypass_delivery_otp(http, db, user, delivery, monkeypatch):
    user.role = UserRole.GERENTE
    order = SimpleNamespace(id=delivery.order_id, assigned_rider_id=delivery.rider_id, status=OrderStatus.EN_RUTA)
    delivery.proof_otp = "123456"
    db.execute.side_effect = [result(order), result(delivery)]
    financial = AsyncMock()
    monkeypatch.setattr(orders, "_ensure_delivery_and_financial_records", financial)
    async with http:
        response = await http.patch(f"/api/v1/orders/{order.id}/status", params={"new_status": "ENTREGADO"})
    assert response.status_code == 400
    assert order.status == OrderStatus.EN_RUTA
    financial.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("path,method", [("/me", "put"), ("/{id}", "patch")])
@pytest.mark.parametrize("payload", [{"tier": "PLATINO"}, {"tier": None}, {"assigned_vehicle_id": str(uuid.uuid4())}, {"vehicle_ownership_type": "EMPRESA"}])
@pytest.mark.parametrize("role", [UserRole.REPARTIDOR, UserRole.OPERADOR, UserRole.CLIENTE, UserRole.AUDITOR])
async def test_sensitive_rider_fields_require_management(http, db, user, path, method, payload, role):
    user.role = role
    async with http:
        response = await http.request(method, "/api/v1/riders" + path.format(id=uuid.uuid4()), json=payload)
    assert response.status_code == 403
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("role", [UserRole.GERENTE, UserRole.SUPERADMIN])
async def test_management_can_still_update_tier(http, db, user, role, monkeypatch):
    user.role = role
    rider = SimpleNamespace(id=uuid.uuid4(), tier=RiderTier.BRONCE, assigned_vehicle_id=None)
    db.execute.return_value = result(rider)
    monkeypatch.setattr(riders, "_rider_to_dict", lambda r: {"tier": r.tier.value})
    async with http:
        response = await http.patch(f"/api/v1/riders/{rider.id}", json={"tier": "ORO"})
    assert response.status_code == 200, response.text
    assert rider.tier == RiderTier.ORO
    db.commit.assert_awaited_once()


async def test_rider_can_still_edit_ordinary_profile(http, db, user, monkeypatch):
    rider = SimpleNamespace(id=uuid.uuid4(), user_id=user.id, vehicle_type=VehicleType.MOTO, vehicle_plate="ABC", assigned_vehicle_id=None)
    db.execute.return_value = result(rider)
    monkeypatch.setattr(riders, "_rider_to_dict", lambda r: {"phone": user.phone})
    async with http:
        response = await http.put("/api/v1/riders/me", json={"phone": "+584121234567"})
    assert response.status_code == 200, response.text
    assert user.phone == "+584121234567"
    db.commit.assert_awaited_once()


@pytest.mark.parametrize("path", ["/orders", "/orders/stats/summary", "/deliveries"])
async def test_customer_cannot_read_operational_lists(http, db, user, path):
    user.role = UserRole.CLIENTE
    async with http:
        response = await http.get("/api/v1" + path)
    assert response.status_code == 403
    db.execute.assert_not_awaited()


@pytest.mark.parametrize("role", [UserRole.CLIENTE, UserRole.AUDITOR])
async def test_order_cannot_be_mutated_by_customer_or_auditor(http, db, user, role):
    user.role = role
    order = SimpleNamespace(id=uuid.uuid4(), assigned_rider_id=uuid.uuid4(), status=OrderStatus.EN_RUTA)
    db.execute.return_value = result(order)
    async with http:
        response = await http.patch(f"/api/v1/orders/{order.id}/status", params={"new_status": "ENTREGADO"})
    assert response.status_code == 403
    assert order.status == OrderStatus.EN_RUTA
    db.commit.assert_not_awaited()


async def test_missing_rider_profile_denies_owned_resources(db, user):
    from fastapi import HTTPException
    db.execute.return_value = result(None)
    with pytest.raises(HTTPException) as exc:
        await ensure_rider_resource_access(db, user, uuid.uuid4())
    assert exc.value.status_code == 403


@pytest.mark.parametrize("method,path,body", MUTATIONS)
async def test_delivery_mutations_require_authentication(api_app, db, delivery, method, path, body):
    api_app.dependency_overrides.pop(get_current_user)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api_app), base_url="http://test") as client:
        response = await client.request(method, f"/api/v1/deliveries/{delivery.id}/{path}", json=body)
    assert response.status_code == 401
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()


async def test_valid_transition_still_updates_delivery_and_order(http, db, user, delivery, monkeypatch):
    order = SimpleNamespace(status=OrderStatus.ASIGNADO)
    owner = SimpleNamespace(id=delivery.rider_id)
    db.execute.side_effect = [result(delivery), result(owner), result(order), result(row=(delivery, None, None, order))]
    monkeypatch.setattr(deliveries, "_serialize_delivery", lambda d, *a: {"status": d.status.value})
    async with http:
        response = await http.patch(f"/api/v1/deliveries/{delivery.id}/status", json={"status": "EN_DESTINO"})
    assert response.status_code == 200, response.text
    assert delivery.status == DeliveryStatus.EN_DESTINO
    assert order.status == OrderStatus.EN_RUTA
    db.commit.assert_awaited_once()


async def test_correct_otp_keeps_legacy_order_completion_usable(http, db, user, delivery, monkeypatch):
    user.role = UserRole.GERENTE
    order = SimpleNamespace(id=delivery.order_id, assigned_rider_id=delivery.rider_id, status=OrderStatus.EN_RUTA)
    delivery.proof_otp = "123456"
    db.execute.side_effect = [result(order), result(delivery)]
    financial = AsyncMock()
    monkeypatch.setattr(orders, "_ensure_delivery_and_financial_records", financial)
    monkeypatch.setattr(orders, "_order_to_dict", lambda o: {"status": o.status.value})
    async with http:
        response = await http.patch(f"/api/v1/orders/{order.id}/status", params={"new_status": "ENTREGADO", "otp_code": "123456"})
    assert response.status_code == 200, response.text
    financial.assert_awaited_once()
    db.commit.assert_awaited_once()
