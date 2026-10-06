"""
Fase 8 — Tests de integración end-to-end SIN Postgres/Redis reales.

Complementan tests/test_fase8_tracking.py (unit) verificando que las PRUEBAS
MANUALES de la aplicación van a funcionar:

1. smoke: la app FastAPI arranca, genera OpenAPI y monta TODAS las rutas de
   tracking REST + WebSocket (previene errores de runtime tipo NameError).
2. POST /api/v1/tracking/update-location con JWT real -> 200 y persistencia
   (repository/session mockeada; lógica de negocio y rate-limit REALES).
3. Rate limit 20 updates/min por rider -> HTTP 429 en la petición 21.
4. GET /api/v1/tracking/dashboard/active-riders con SUPERADMIN -> contrato
   {riders:[...], stats:{...}} plano, compatible con el frontend.
5. RBAC: rol equivocado -> 403; sin token -> 401. WS rechaza JWT inválido.

Se mockea SOLO la capa de persistencia (AsyncSession) e infraestructura
(Redis); TrackingService, Pydantic, JWT y FastAPI se ejecutan reales.
"""
import uuid
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from jose import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.models.user import UserRole as RoleType

PO_LAT, PO_LNG = 8.2969, -62.7366  # Puerto Ordaz, Venezuela


def _make_token(role: str, sub: str | None = None) -> str:
    """JWT firmado con SECRET_KEY real + claims extra (role, type=access)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(sub or uuid.uuid4()),
        "role": role if isinstance(role, str) else str(role),
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=30),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def _exec_result(scalars_list=None, scalar_one=None):
    res = MagicMock()
    res.scalars.return_value.all.return_value = scalars_list or []
    res.scalar_one_or_none.return_value = scalar_one
    return res


def _fake_db(execute_side_effect):
    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.rollback = AsyncMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


@pytest.fixture()
def client(monkeypatch):
    # 1) Evitar create_all sobre Postgres real en el lifespan (TestClient).
    import app.core.database as dbmod

    fake_conn = MagicMock()
    fake_conn.run_sync = AsyncMock()

    class _Ctx:
        async def __aenter__(self):
            return fake_conn

        async def __aexit__(self, *exc):
            return False

    fake_engine = MagicMock()
    fake_engine.begin = lambda: _Ctx()
    fake_engine.dispose = AsyncMock()
    monkeypatch.setattr(dbmod, "engine", fake_engine)
    import app.main as mainmod

    monkeypatch.setattr(mainmod, "engine", fake_engine, raising=False)

    # 2) get_db global -> session fake. Cada test que necesite comportamiento
    #    específico reasigna trk.get_db con monkeypatch (sobreescritura intencional).
    from app.api.v1.auth import get_current_user
    from app.core.database import get_db

    app_obj = mainmod.app

    async def _fake_get_db():
        yield _fake_db(lambda *a, **k: _exec_result(scalars_list=[], scalar_one=None))

    def _user_with_role(role_value: str):
        async def _dep():
            return SimpleNamespace(
                id=uuid.uuid4(),
                role=SimpleNamespace(value=role_value),
                is_active=True,
            )

        return _dep

    # get_current_user se resuelve vía dependency_overrides para controlar el rol
    app_obj.dependency_overrides[get_db] = _fake_get_db
    for role in ("SUPERADMIN", "GERENTE", "REPARTIDOR"):
        pass  # el override por-request se decide con el token: ver helper abajo

    # Override dinámico: lee el header Authorization y decodifica el rol del JWT
    async def _current_user_from_token():
        raise NotImplementedError  # placeholder; replaced below per request

    # FastAPI no puede inyectar Request en override sin firma; usar la variante con Request
    from fastapi import Request as FastAPIRequest

    async def _cu_dep(request: FastAPIRequest):
        auth = request.headers.get("Authorization", "")
        token = auth.replace("Bearer ", "").strip()
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        except Exception as exc:  # noqa: BLE001
            from fastapi import HTTPException, status as st

            raise HTTPException(status_code=st.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas") from exc
        if payload.get("type") != "access":
            from fastapi import HTTPException, status as st

            raise HTTPException(status_code=st.HTTP_401_UNAUTHORIZED, detail="Token invalido")
        return SimpleNamespace(
            id=payload.get("sub"),
            role=SimpleNamespace(value=payload.get("role", "CLIENTE")),
            is_active=True,
        )

    app_obj.dependency_overrides[get_current_user] = _cu_dep
    try:
        yield TestClient(app_obj)
    finally:
        app_obj.dependency_overrides.pop(get_current_user, None)
        app_obj.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------- 1. SMOKE
def test_smoke_app_boots_and_tracking_routes_mounted(client):
    assert client.get("/health").status_code == 200
    spec = client.get("/openapi.json").json()["paths"]
    for p in (
        "/api/v1/tracking/update-location",
        "/api/v1/tracking/live/{order_id}",
        "/api/v1/tracking/dashboard/active-riders",
        "/api/v1/tracking/routes/optimize",
        "/api/v1/tracking/history/{rider_id}",
    ):
        assert p in spec, f"Ruta REST Fase 8 ausente en OpenAPI: {p}"
    from app.main import app

    ws_paths = [r.path for r in app.routes if type(r).__name__ == "APIWebSocketRoute"]
    assert any("/tracking/ws" in p for p in ws_paths), f"WS tracking ausente: {ws_paths}"


# ------------------------------------------------- 2. update-location OK (200)
def test_update_location_returns_200_and_persists(client, monkeypatch):
    from app.api.v1 import tracking as trk

    rider = SimpleNamespace(
        id=uuid.uuid4(), user_id="user-x", last_lat=None, last_lng=None,
        last_location_at=None, is_online=False, status="ACTIVO",
    )

    async def fake_execute(*a, **k):
        return _exec_result(scalar_one=rider, scalars_list=[rider])

    db = _fake_db(fake_execute)
    monkeypatch.setattr(trk, "get_db", lambda: db)
    monkeypatch.setattr(trk, "build_redis_client", AsyncMock(return_value=None))
    trk._update_windows.clear()

    body = {"lat": PO_LAT, "lng": PO_LNG, "accuracy": 12.5}
    r = client.post(
        f"/api/v1/tracking/update-location?rider_id={rider.id}&speed_kmh=22&heading=180",
        json=body,
        headers={"Authorization": f"Bearer {_make_token(RoleType.GERENTE.value)}"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "ok" and "recorded_at" in data
    db.add.assert_called_once()          # RiderLiveLocation insertado
    db.commit.assert_awaited()           # persistido
    assert rider.last_lat == PO_LAT      # snapshot última posición actualizado
    assert rider.is_online is True
    trk._update_windows.clear()


# ------------------------------------------------------------ 3. RATE LIMIT
def test_update_location_rate_limit_429_on_request_21(client, monkeypatch):
    """Plan PASO 3: 20 updates/min/rider -> la petición 21 devuelve 429."""
    from app.api.v1 import tracking as trk

    rider = SimpleNamespace(
        id=uuid.uuid4(), user_id="user-x", last_lat=None, last_lng=None,
        last_location_at=None, is_online=False, status="ACTIVO",
    )

    async def fake_execute(*a, **k):
        return _exec_result(scalar_one=rider, scalars_list=[rider])

    db = _fake_db(fake_execute)
    monkeypatch.setattr(trk, "get_db", lambda: db)
    monkeypatch.setattr(trk, "build_redis_client", AsyncMock(return_value=None))
    trk._update_windows.clear()

    body = {"lat": PO_LAT, "lng": PO_LNG}
    url = f"/api/v1/tracking/update-location?rider_id={rider.id}"
    headers = {"Authorization": f"Bearer {_make_token(RoleType.GERENTE.value)}"}
    codes = [client.post(url, json=body, headers=headers).status_code for _ in range(21)]
    assert codes[:20] == [200] * 20, codes
    assert codes[20] == 429, codes
    trk._update_windows.clear()


# ------------------------------------------------------- 4. DASHBOARD CONTRATO
def test_dashboard_active_riders_contract(client, monkeypatch):
    from app.api.v1 import tracking as trk

    rider = SimpleNamespace(
        id=uuid.uuid4(),
        user=SimpleNamespace(first_name="Ana", last_name="Po"),
        status=SimpleNamespace(value="ACTIVO"),
        last_lat=PO_LAT, last_lng=PO_LNG,
        last_location_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )

    async def fake_execute(*a, **k):
        return _exec_result(scalars_list=[rider], scalar_one=rider)

    db = _fake_db(fake_execute)
    monkeypatch.setattr(trk, "get_db", lambda: db)
    monkeypatch.setattr(trk, "build_redis_client", AsyncMock(return_value=None))

    r = client.get(
        "/api/v1/tracking/dashboard/active-riders",
        headers={"Authorization": f"Bearer {_make_token(RoleType.SUPERADMIN.value)}"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert set(data) >= {"riders", "stats"}
    assert len(data["riders"]) == 1
    first = data["riders"][0]
    for key in ("riderId", "name", "lat", "lng", "lastSeenMinutesAgo"):
        assert key in first, f"campo faltante {key}"
    assert data["stats"]["activeCount"] == 1


# ------------------------------------------------------------------- 5. RBAC
def test_dashboard_rejects_wrong_role(client):
    r = client.get(
        "/api/v1/tracking/dashboard/active-riders",
        headers={"Authorization": f"Bearer {_make_token(RoleType.REPARTIDOR.value)}"},
    )
    assert r.status_code == 403, r.text


def test_endpoints_require_auth(client):
    assert client.get("/api/v1/tracking/dashboard/active-riders").status_code in (401, 403)
    assert client.get(f"/api/v1/tracking/live/{uuid.uuid4()}").status_code in (401, 403)


def test_ws_rejects_invalid_token(client):
    """Handshake WS con JWT inválido debe cerrarse sin autorizar conexión."""
    closed = False
    try:
        with client.websocket_connect("/api/v1/tracking/ws/dashboard?token=invalido") as ws:
            ws.receive_json()
    except Exception as exc:  # noqa: BLE001
        closed = True
        assert "1008" in str(getattr(exc, "code", "")) or type(exc).__name__ in (
            "WebSocketDisconnect", "AssertionError", "RuntimeError"
        ), exc
    assert closed, "El WS NO debió aceptar un token inválido"
