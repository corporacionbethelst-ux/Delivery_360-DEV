"""Recovery lookup is read-only and keys never grant cross-account access."""

from uuid import uuid4
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update

from tests.test_payout_reservations import reservation_context  # noqa: F401
from tests.test_ledger_integrity import payout_context, ledger_context  # noqa: F401
from tests.test_reconciliation_safety import reconciliation_context  # noqa: F401
from app.api.v1 import payouts as api
from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.financial import Financial, PayoutStatus
from app.models.payout import Payout, PayoutStatusHistory
from app.models.user import User, UserRole
from app.models.rider import Rider, RiderStatus


@pytest.fixture
async def recovery_context(reservation_context):
    session, rider_id, user = reservation_context
    request = await api.request_payout(
        api.PayoutRequestBody(amount=60, idempotency_key="recover-key"),
        db=session,
        current_user=user,
    )
    app = FastAPI()
    app.include_router(api.router)
    current = [user]

    async def database():
        yield session

    async def current_user():
        return current[0]

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = current_user
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, session, rider_id, request, current


@pytest.mark.asyncio
async def test_lookup_is_read_only_and_returns_authoritative_state(recovery_context):
    client, session, rider_id, request, _ = recovery_context
    with patch.object(session, "commit", wraps=session.commit) as commit:
        response = await client.get(
            "/payouts/request-status", params={"idempotency_key": "recover-key"}
        )
        assert response.status_code == 200
        assert response.json()["id"] == request["id"]
        commit.assert_not_awaited()
    assert await session.scalar(select(func.count()).select_from(Payout)) == 1
    assert (
        await session.scalar(select(func.count()).select_from(PayoutStatusHistory)) == 1
    )
    assert await session.scalar(select(func.count()).select_from(Financial)) == 1
    await session.execute(update(Payout).values(status=PayoutStatus.RECHAZADO))
    await session.commit()
    assert (
        await client.get(
            "/payouts/request-status", params={"idempotency_key": "recover-key"}
        )
    ).json()["status"] == "RECHAZADO"


@pytest.mark.asyncio
async def test_known_key_cannot_expose_another_riders_request(recovery_context):
    client, session, _, _, current = recovery_context
    other = User(
        email="other-recovery@example.test",
        hashed_password="unused",
        first_name="Other",
        last_name="User",
        role=UserRole.REPARTIDOR,
    )
    session.add(other)
    await session.flush()
    session.add(Rider(user_id=other.id, status=RiderStatus.ACTIVO))
    await session.commit()
    current[0] = other
    foreign = await client.get(
        "/payouts/request-status", params={"idempotency_key": "recover-key"}
    )
    missing = await client.get(
        "/payouts/request-status", params={"idempotency_key": "missing-key"}
    )
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role", [UserRole.GERENTE, UserRole.OPERADOR, UserRole.CLIENTE]
)
async def test_lookup_requires_rider_role(recovery_context, role):
    client, _, _, _, current = recovery_context
    current[0].role = role
    assert (
        await client.get(
            "/payouts/request-status", params={"idempotency_key": "recover-key"}
        )
    ).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["", " ", "x" * 101])
async def test_invalid_lookup_keys_are_rejected(recovery_context, key):
    client, *_ = recovery_context
    assert (
        await client.get("/payouts/request-status", params={"idempotency_key": key})
    ).status_code == 422


@pytest.mark.asyncio
async def test_lookup_without_a_bearer_token_is_unauthorized():
    app = FastAPI()
    app.include_router(api.router)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/payouts/request-status", params={"idempotency_key": str(uuid4())}
        )
    assert response.status_code == 401
