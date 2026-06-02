"""Tests de autenticación y usuarios."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.user import User, UserRole


class TestAuth:
    """Tests para endpoints de autenticación."""

    @pytest.mark.asyncio
    async def test_login_success(self, client: AsyncClient, test_user: User):
        """Prueba login exitoso."""
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": test_user.email,
                "password": "testpassword123"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self, client: AsyncClient):
        """Prueba login con credenciales inválidas."""
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "nonexistent@example.com",
                "password": "wrongpassword"
            }
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_register_new_user(self, client: AsyncClient):
        """Prueba registro de nuevo usuario."""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"newuser_{pytest.test_counter}@example.com",
                "password": "newpassword123",
                "full_name": "Nuevo Usuario",
                "role": "OPERADOR"
            }
        )
        pytest.test_counter += 1
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == f"newuser_{pytest.test_counter - 1}@example.com"
        assert "id" in data


# Inicializar contador para tests
pytest.test_counter = 0
