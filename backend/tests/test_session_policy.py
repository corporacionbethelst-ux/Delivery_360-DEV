"""Live rider state must be checked even for previously issued tokens."""

from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from app.api.v1 import auth
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    get_current_active_user,
)
from app.models.rider import Rider, RiderStatus
from app.models.user import UserRole


@pytest.fixture
async def session_http(db_session):
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/v1")

    @app.get("/core-profile")
    async def profile(user=Depends(get_current_active_user)):
        return {"id": str(user.id)}

    async def database():
        yield db_session

    app.dependency_overrides[get_db] = database
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rider_status",
    [RiderStatus.SUSPENDIDO, RiderStatus.PENDIENTE, RiderStatus.INACTIVO, None],
)
async def test_disabled_or_missing_rider_cannot_use_access_refresh_or_login(
    db_session, test_user, session_http, rider_status
):
    test_user.role = UserRole.REPARTIDOR
    if rider_status is not None:
        db_session.add(Rider(user_id=test_user.id, status=rider_status))
    await db_session.commit()
    token = create_access_token(str(test_user.id))
    refresh = create_refresh_token(str(test_user.id))
    for path in ["/api/v1/auth/me", "/core-profile"]:
        response = await session_http.get(
            path, headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403, response.text
    response = await session_http.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh}
    )
    assert response.status_code == 403
    response = await session_http.post(
        "/api/v1/auth/login",
        data={"username": test_user.email, "password": "testpassword123"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("rider_status", [RiderStatus.ACTIVO, RiderStatus.OCUPADO])
async def test_active_and_busy_riders_keep_valid_sessions(
    db_session, test_user, session_http, rider_status
):
    test_user.role = UserRole.REPARTIDOR
    db_session.add(Rider(user_id=test_user.id, status=rider_status))
    await db_session.commit()
    response = await session_http.post(
        "/api/v1/auth/login",
        data={"username": test_user.email, "password": "testpassword123"},
    )
    assert response.status_code == 200, response.text
    tokens = response.json()
    assert (
        await session_http.get(
            "/api/v1/auth/me",
            headers={"Authorization": f'Bearer {tokens["access_token"]}'},
        )
    ).status_code == 200
    assert (
        await session_http.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
    ).status_code == 200


@pytest.mark.asyncio
async def test_suspension_takes_effect_for_tokens_issued_before_change(
    db_session, test_user, session_http
):
    test_user.role = UserRole.REPARTIDOR
    rider = Rider(user_id=test_user.id, status=RiderStatus.ACTIVO)
    db_session.add(rider)
    await db_session.commit()
    tokens = (
        await session_http.post(
            "/api/v1/auth/login",
            data={"username": test_user.email, "password": "testpassword123"},
        )
    ).json()
    rider.status = RiderStatus.SUSPENDIDO
    await db_session.commit()
    assert (
        await session_http.get(
            "/api/v1/auth/me",
            headers={"Authorization": f'Bearer {tokens["access_token"]}'},
        )
    ).status_code == 403
    assert (
        await session_http.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
    ).status_code == 403
