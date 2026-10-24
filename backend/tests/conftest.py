"""
Configuration file for pytest.
Provides fixtures and configuration for all tests.
"""
import pytest
import asyncio
from typing import AsyncGenerator, Generator
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import get_db, Base
from app.models.user import User, UserRole
from app.models.rider import Rider
from app.models.order import Order
from app.core.security import get_password_hash

# Test database configuration - using SQLite for simplicity in unit tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="function")
async def test_engine():
    """Create test database engine - using SQLite for simplicity"""
    # Use SQLite for unit tests to avoid PostgreSQL dependency
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        poolclass=StaticPool,
    )
    
    # Create only the tables needed for tests (excluding PostGIS-dependent ones)
    from sqlalchemy import MetaData
    from app.models.user import User
    from app.models.vehicle import Vehicle  # FK riders.assigned_vehicle_id
    from app.models.rider import Rider
    from app.models.rider_document import RiderDocument

    # SQLite no soporta PostGIS: se registran funciones SQL vacías vía connect
    # event y riders.last_location se degrada a TEXT solo para el DDL de test.
    from sqlalchemy import event as _sa_event

    def _register_geo_stub(dbapi_conn, _rec):
        dbapi_conn.create_function("GeomFromEWKT", 1, lambda x: None)
        dbapi_conn.create_function("ST_AsEWKT", 1, lambda x: None)

    _sa_event.listen(engine.sync_engine, "connect", _register_geo_stub)

    geo_col = Rider.__table__.c.last_location
    from sqlalchemy import Text as _Text
    old_type = geo_col.type
    geo_col.type = _Text()
    # rider_documents usa server_default=sa.text('NOW()') (valido en PG, no en
    # SQLite). Se sustituye temporalmente por CURRENT_TIMESTAMP para el DDL de
    # tests; se restaura despues para no afectar la app real.
    rd_cols = [RiderDocument.__table__.c.created_at,
               RiderDocument.__table__.c.updated_at]
    old_defaults = [c.server_default for c in rd_cols]
    try:
        from sqlalchemy import func as _func
        for c in rd_cols:
            import sqlalchemy as sa
            c.server_default = sa.schema.DefaultClause(_func.now())
        async with engine.begin() as conn:
            def _create_tables(sync_conn):
                User.__table__.create(sync_conn, checkfirst=True)
                Vehicle.__table__.create(sync_conn, checkfirst=True)
                Rider.__table__.create(sync_conn, checkfirst=True)
                RiderDocument.__table__.create(sync_conn, checkfirst=True)
            await conn.run_sync(_create_tables)
    finally:
        geo_col.type = old_type
        for c, d in zip(rd_cols, old_defaults):
            c.server_default = d
    
    yield engine
    
    await engine.dispose()


@pytest.fixture(scope="function")
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create test database session"""
    async_session = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False
    )
    
    async with async_session() as session:
        yield session
        await session.rollback()


@pytest.fixture(scope="function")
def client(db_session, monkeypatch, tmp_path) -> Generator[TestClient, None, None]:
    """Create test client for FastAPI"""
    
    async def override_get_db():
        yield db_session
    
    # Registration writes relative uploads: keep test evidence out of the checkout.
    (tmp_path / "uploads").mkdir()
    monkeypatch.chdir(tmp_path)
    app.dependency_overrides[get_db] = override_get_db
    
    test_client = TestClient(app)
    
    yield test_client
    
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
async def test_user(db_session: AsyncSession) -> User:
    """Create a test user for authentication tests."""
    from app.core.security import get_password_hash as hash_pwd
    
    user = User(
        email="testuser@example.com",
        hashed_password=hash_pwd("testpassword123"),
        first_name="Test",
        last_name="User",
        role=UserRole.OPERADOR,
        is_active=True
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user
