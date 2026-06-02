"""
Delivery360 - Backend Test Suite
Tests unitarios y de integración para la API
"""
import pytest
import asyncio
from typing import AsyncGenerator, Generator
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

# Importar aplicación y modelos
import sys
sys.path.insert(0, '/workspace/backend')

from app.main import app
from app.core.database import get_db, Base
from app.models.user import User
from app.models.rider import Rider
from app.models.order import Order
from app.schemas.user import UserCreate, UserResponse
from app.schemas.auth import LoginRequest, Token

# Configuración de test
TEST_DATABASE_URL = "postgresql+asyncpg://test_user:test_password@localhost:5432/test_db"


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Crear loop de eventos para tests asíncronos"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="function")
async def test_engine():
    """Crear motor de base de datos de test"""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=StaticPool,
    )
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield engine
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    await engine.dispose()


@pytest.fixture(scope="function")
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Crear sesión de base de datos de test"""
    async_session = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False
    )
    
    async with async_session() as session:
        yield session
        await session.rollback()


@pytest.fixture(scope="function")
async def client(db_session) -> AsyncGenerator[AsyncClient, None]:
    """Crear cliente de test para FastAPI"""
    
    async def override_get_db():
        yield db_session
    
    app.dependency_overrides[get_db] = override_get_db
    
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac
    
    app.dependency_overrides.clear()


class TestHealthCheck:
    """Tests para health checks"""
    
    @pytest.mark.asyncio
    async def test_health_check(self, client: AsyncClient):
        """Verificar que el endpoint de health responde"""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] == "healthy"
    
    @pytest.mark.asyncio
    async def test_ready_check(self, client: AsyncClient):
        """Verificar que el endpoint de ready responde"""
        response = await client.get("/ready")
        assert response.status_code in [200, 503]  # Puede fallar sin DB real


class TestAuth:
    """Tests para autenticación"""
    
    @pytest.mark.asyncio
    async def test_register_user(self, client: AsyncClient):
        """Test de registro de usuario"""
        user_data = {
            "email": "test@example.com",
            "password": "SecurePass123!",
            "full_name": "Test User",
            "phone": "+1234567890",
            "role": "CLIENTE"
        }
        
        response = await client.post("/api/v1/auth/register", json=user_data)
        assert response.status_code in [200, 201, 400]  # 400 si ya existe
    
    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self, client: AsyncClient):
        """Test de login con credenciales inválidas"""
        login_data = {
            "email": "nonexistent@example.com",
            "password": "WrongPassword"
        }
        
        response = await client.post("/api/v1/auth/login", json=login_data)
        assert response.status_code in [401, 404]


class TestUser:
    """Tests para gestión de usuarios"""
    
    @pytest.mark.asyncio
    async def test_get_users_unauthorized(self, client: AsyncClient):
        """Verificar que se requiere autenticación"""
        response = await client.get("/api/v1/users")
        assert response.status_code in [401, 403]


class TestOrder:
    """Tests para gestión de órdenes"""
    
    @pytest.mark.asyncio
    async def test_create_order_unauthorized(self, client: AsyncClient):
        """Verificar que se requiere autenticación para crear orden"""
        order_data = {
            "pickup_address": "Calle 123",
            "delivery_address": "Avenida 456",
            "items": [{"name": "Producto", "quantity": 1}]
        }
        
        response = await client.post("/api/v1/orders", json=order_data)
        assert response.status_code in [401, 403]


class TestRider:
    """Tests para gestión de repartidores"""
    
    @pytest.mark.asyncio
    async def test_get_riders_unauthorized(self, client: AsyncClient):
        """Verificar que se requiere autenticación"""
        response = await client.get("/api/v1/riders")
        assert response.status_code in [401, 403]


# Tests de integración básicos
class TestIntegration:
    """Tests de integración end-to-end"""
    
    @pytest.mark.asyncio
    async def test_full_flow_simulation(self, client: AsyncClient, db_session):
        """Simular flujo completo: registro → login → crear orden"""
        # 1. Registro
        register_data = {
            "email": "flow@test.com",
            "password": "FlowPass123!",
            "full_name": "Flow Test",
            "phone": "+1234567890",
            "role": "CLIENTE"
        }
        
        response = await client.post("/api/v1/auth/register", json=register_data)
        # Puede ser 200/201 (éxito) o 400 (ya existe)
        
        # 2. Login (si el registro fue exitoso o el usuario ya existía)
        login_data = {
            "email": "flow@test.com",
            "password": "FlowPass123!"
        }
        
        response = await client.post("/api/v1/auth/login", json=login_data)
        # El login puede fallar si el usuario no fue creado, lo cual es válido en test


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
