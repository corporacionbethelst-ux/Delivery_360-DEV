"""Tests de autenticación y usuarios."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.user import User, UserRole


class TestAuth:
    """Tests para endpoints de autenticación."""

    def test_login_success(self, client: TestClient, test_user: User):
        """Prueba login exitoso."""
        # El endpoint /auth/login usa OAuth2PasswordRequestForm (form-urlencoded),
        # con credenciales en username/password.
        response = client.post(
            "/api/v1/auth/login",
            data={
                "username": test_user.email,
                "password": "testpassword123"
            }
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    def test_login_invalid_credentials(self, client: TestClient):
        """Prueba login con credenciales inválidas."""
        # El endpoint espera form data, no JSON
        response = client.post(
            "/api/v1/auth/login",
            data={
                "username": "nonexistent@example.com",
                "password": "wrongpassword"
            }
        )
        assert response.status_code == 400  # 400 para credenciales incorrectas

    def test_register_new_user(self, client: TestClient):
        """Prueba registro de nuevo repartidor (endpoint disponible).

        El endpoint /auth/register-rider es multipart/form-data con 4 archivos
        obligatorios (license, id_card, vehicle_registration, insurance); se
        envían stubs mínimos para validar el flujo de registro.
        """
        import random
        counter = random.randint(1000, 9999)
        files = {
            name: (f"{name}_{counter}.pdf", b"%PDF-1.4 stub", "application/pdf")
            for name in ("license_file", "id_card_file",
                         "vehicle_registration_file", "insurance_file")
        }
        response = client.post(
            "/api/v1/auth/register-rider",
            data={
                "email": f"newuser_{counter}@example.com",
                "password": "newpassword123",
                "first_name": "Nuevo",
                "last_name": "Usuario Repartidor",
                "phone": "+1234567890",
                "vehicle_type": "MOTO",
                "vehicle_plate": f"ABC{counter}",
            },
            files=files,
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert "user" in data or "id" in data


# Inicializar contador para tests
pytest.test_counter = 0
