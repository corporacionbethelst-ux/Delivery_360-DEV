"""Regression tests for malformed token subjects and legacy users without roles."""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1 import auth
from app.core.database import get_db
from app.core.security import create_access_token, create_refresh_token


@pytest.fixture
async def auth_http(db_session):
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/v1")

    async def session():
        yield db_session

    app.dependency_overrides[get_db] = session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest.mark.asyncio
@pytest.mark.parametrize("subject", [None, 123, ["bad"], "invalid-uuid"])
async def test_bad_subject_returns_401_before_database_lookup(auth_http, subject):
    with patch.object(
        auth, "decode_token", return_value={"type": "access", "sub": subject}
    ):
        response = await auth_http.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer sensitive-test-token"}
        )
        assert response.status_code == 401
    with patch.object(
        auth, "decode_token", return_value={"type": "refresh", "sub": subject}
    ):
        response = await auth_http.post(
            "/api/v1/auth/refresh", json={"refresh_token": "sensitive-test-token"}
        )
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_valid_access_does_not_log_token_or_personal_data(
    auth_http, test_user, capsys
):
    token = create_access_token(str(test_user.id))
    response = await auth_http.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    output = capsys.readouterr().out
    assert token[:50] not in output
    assert test_user.email not in output


@pytest.mark.asyncio
async def test_roleless_account_cannot_login_refresh_or_authenticate(
    auth_http, db_session, test_user
):
    user_id = test_user.id
    email = test_user.email
    test_user.role = None
    await db_session.commit()
    response = await auth_http.post(
        "/api/v1/auth/login", data={"username": email, "password": "testpassword123"}
    )
    assert response.status_code == 400
    response = await auth_http.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": create_refresh_token(str(user_id))},
    )
    assert response.status_code == 401
    response = await auth_http.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {create_access_token(str(user_id))}"},
    )
    assert response.status_code == 401
