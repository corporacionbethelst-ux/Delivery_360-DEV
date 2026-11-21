from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
import pytest
from fastapi import HTTPException
from app.api.v1 import payouts as api
from app.models.user import UserRole


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role", [UserRole.OPERADOR, UserRole.AUDITOR, UserRole.CLIENTE, UserRole.REPARTIDOR]
)
async def test_staff_balance_denies_other_roles_before_database_access(role):
    db = SimpleNamespace(scalar=AsyncMock())
    with pytest.raises(HTTPException) as error:
        await api.staff_exact_rider_balance(
            uuid4(), SimpleNamespace(query_params={}), db, SimpleNamespace(role=role)
        )
    assert error.value.status_code == 403
    db.scalar.assert_not_awaited()


@pytest.mark.asyncio
async def test_staff_balance_rejects_extra_scope_parameters_before_database_access():
    db = SimpleNamespace(scalar=AsyncMock())
    with pytest.raises(HTTPException) as error:
        await api.staff_exact_rider_balance(
            uuid4(),
            SimpleNamespace(query_params={"user_id": str(uuid4())}),
            db,
            SimpleNamespace(role=UserRole.GERENTE),
        )
    assert error.value.status_code == 422
    db.scalar.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.GERENTE, UserRole.SUPERADMIN])
async def test_staff_balance_uses_target_rider_user_and_separates_actor(
    monkeypatch, role
):
    rider = SimpleNamespace(id=uuid4(), user_id=uuid4())
    actor = SimpleNamespace(id=uuid4(), role=role)
    db = SimpleNamespace(scalar=AsyncMock(return_value=rider))
    read = AsyncMock(
        return_value={
            "user_id": str(rider.user_id),
            "rider_id": str(rider.id),
            "available": "0.01",
            "scope": "own_canonical_usd_balance",
        }
    )
    monkeypatch.setattr(api, "_exact_balance_snapshot", read)
    result = await api.staff_exact_rider_balance(
        rider.id, SimpleNamespace(query_params={}), db, actor
    )
    read.assert_awaited_once_with(db, rider, rider.user_id)
    assert result["scope"] == "staff_canonical_usd_balance"
    assert result["available"] == "0.01"
    assert result["actor"] == {"user_id": str(actor.id), "role": role.value}
    assert result["user_id"] != result["actor"]["user_id"]


@pytest.mark.asyncio
async def test_staff_balance_missing_profile_is_not_a_zero_balance(monkeypatch):
    db = SimpleNamespace(scalar=AsyncMock(return_value=None))
    read = AsyncMock()
    monkeypatch.setattr(api, "_exact_balance_snapshot", read)
    with pytest.raises(HTTPException) as error:
        await api.staff_exact_rider_balance(
            uuid4(),
            SimpleNamespace(query_params={}),
            db,
            SimpleNamespace(role=UserRole.GERENTE),
        )
    assert error.value.status_code == 404
    read.assert_not_awaited()
