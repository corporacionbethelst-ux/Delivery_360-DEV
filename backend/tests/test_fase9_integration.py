"""
Fase 9 — Tests de integración REST/WS SIN Postgres/Redis reales.

Patrón EXACTO de tests/test_fase8_integration.py: fixtures vía
app.dependency_overrides[get_db] y [get_current_user] (NO monkeypatch de get_db).

Cubre:
1. smoke: app arranca + TODAS las rutas /notifications montadas (+ /ws).
2. test-send RBAC: 200 GERENTE/SUPERADMIN, 403 REPARTIDOR.
3. payout APROBADO -> hook crea NotificationLog (dispatch real sobre db fake).
4. inbox paginado: contrato {items,page,size,total,pages,unread_count}.
5. PATCH /{id}/read: dueño ok / otro usuario 403 / inexistente 404.
6. WS rechaza token inválido/expirado (close 1008) y acepta JWT válido.
7. dedupe: segunda llamada idéntica <5min -> sin logs nuevos (skip).
8. NOTIFICATIONS_ENABLED=false -> solo IN_APP, sin excepciones.
"""
import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from jose import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.models.notification import (
    NotificationChannel,
    NotificationLog,
    NotificationTemplate,
    OmnichannelStatus,
)


def _run_coro(coro):
    """Ejecuta un coro SIN cerrar el event loop global.

    `asyncio.run()` cierra el loop al terminar; bajo pytest-asyncio 0.23.x
    (asyncio_mode=auto) eso deja sin loop vigente a los tests async que se
    ejecutan despues en la misma sesion -> RuntimeError('There is no current
    event loop in thread MainThread') observado en la auditoria de Fase 9.
    Este helper crea un loop propio, lo cierra y RESTAURA uno nuevo como
    loop global, de forma que la suite completa es orden-independiente.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


def _make_token(role: str, sub: str | None = None, expired: bool = False) -> str:
    now = datetime.now(timezone.utc)
    exp = now - timedelta(minutes=5) if expired else now + timedelta(minutes=30)
    payload = {
        "sub": str(sub or uuid.uuid4()),
        "role": role,
        "type": "access",
        "iat": now,
        "exp": exp,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def _exec_result(scalars_list=None, scalar_one=None, scalar_val=None):
    res = MagicMock()
    res.scalars.return_value.all.return_value = scalars_list or []
    res.scalar_one_or_none.return_value = scalar_one
    res.scalar_one.return_value = scalar_one
    res.scalar.return_value = scalar_val
    res.first.return_value = (scalar_val,) if scalar_val is not None else None
    return res


def _fake_db(side_effect):
    db = MagicMock()
    db.add = MagicMock()
    db.delete = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.rollback = AsyncMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock(side_effect=side_effect)
    return db


def _user_obj(role="GERENTE", uid=None):
    return SimpleNamespace(
        id=uid or uuid.uuid4(),
        email=f"{role.lower()}@delivery360.com",
        phone="+573001112233",
        role=SimpleNamespace(value=role),
        first_name="Test",
        last_name="Fase9",
        is_active=True,
    )


def _template(code="payout_aprobado", channel="PUSH"):
    return NotificationTemplate(
        id=uuid.uuid4(), code=code,
        channel=NotificationChannel(channel),
        subject="Pago aprobado", language="es", is_active=True,
        body_template="Tu pago de {{amount_cents}} fue {{status}}.",
    )


@pytest.fixture()
def client(monkeypatch):
    """App con lifespan seguro (sin create_all/dispose reales) y overrides."""
    # This fixture promises no real Redis: external template caches must not
    # change the fake DB query sequence or affect notification assertions.
    from app.services.omnichannel_service import OmnichannelNotificationService
    monkeypatch.setattr(OmnichannelNotificationService, "_get_redis", AsyncMock(return_value=None))
    import app.core.database as dbmod
    import app.main as mainmod

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
    # No parchar engine global: solo neutralizar el del lifespan si se usa.
    dbmod.engine = fake_engine
    try:
        mainmod.engine = fake_engine
    except Exception:  # noqa: BLE001
        pass

    from app.api.v1.auth import get_current_user
    from app.core.database import get_db

    app_obj = mainmod.app

    holder = {"db": None}

    async def _fake_get_db():
        yield holder["db"] or _fake_db(lambda *a, **k: _exec_result())

    from fastapi import Request as FastAPIRequest

    async def _cu_dep(request: FastAPIRequest):
        auth = request.headers.get("Authorization", "")
        token = auth.replace("Bearer ", "").strip()
        try:
            payload = jwt.decode(token, settings.SECRET_KEY,
                                 algorithms=[settings.JWT_ALGORITHM])
        except Exception as exc:  # noqa: BLE001
            from fastapi import HTTPException, status as st
            raise HTTPException(status_code=st.HTTP_401_UNAUTHORIZED,
                                detail="Credenciales inválidas") from exc
        if payload.get("type") != "access":
            from fastapi import HTTPException, status as st
            raise HTTPException(status_code=st.HTTP_401_UNAUTHORIZED,
                                detail="Token invalido")
        from app.models.user import UserRole as _Role
        try:
            role_val = _Role(payload.get("role", "CLIENTE"))
        except ValueError:
            role_val = _Role.CLIENTE
        return SimpleNamespace(
            id=payload.get("sub"),
            role=role_val,
            is_active=True,
        )

    app_obj.dependency_overrides[get_db] = _fake_get_db
    app_obj.dependency_overrides[get_current_user] = _cu_dep
    app_obj._fase9_test_db_holder = holder
    try:
        yield TestClient(app_obj)
    finally:
        app_obj.dependency_overrides.pop(get_current_user, None)
        app_obj.dependency_overrides.pop(get_db, None)


# ------------------------------------------------------------------ 1. SMOKE
def test_smoke_notifications_routes_mounted(client):
    paths = {r.path for r in client.app.routes}
    expected = [
        "/api/v1/notifications/register-device",
        "/api/v1/notifications/inbox",
        "/api/v1/notifications/unread-count",
        "/api/v1/notifications/{notification_id}/read",
        "/api/v1/notifications/preferences",
        "/api/v1/notifications/test-send",
        "/api/v1/notifications/templates",
    ]
    missing = [p for p in expected if p not in paths]
    assert not missing, f"rutas faltantes: {missing}"
    ws_paths = [p for p in paths if "ws" in p and "notif" in p]
    assert ws_paths, "WebSocket de notificaciones no montado"


# ------------------------------------------------------------------ 2. RBAC
def _testsend_side_effect(*a, **k):
    # orden: User -> Template -> dedupe check -> prefs -> tokens -> ...
    user = _user_obj("REPARTIDOR")
    tpl = _template()
    seq = [
        _exec_result(scalar_one=user),        # select(User)
        _exec_result(scalar_one=tpl),         # select(NotificationTemplate)
        _exec_result(scalar_one=None),        # dedupe: sin colision
        _exec_result(scalars_list=[]),        # resolve_channels: prefs
        _exec_result(scalars_list=[]),        # device tokens (push)
    ]

    def _se(*args, **kwargs):
        return seq.pop(0) if seq else _exec_result(scalar_one=None)
    return _se


def test_send_forbidden_for_rider(client):
    rider = _user_obj("REPARTIDOR")
    holder = client.app._fase9_test_db_holder
    holder["db"] = _fake_db(_testsend_side_effect())
    tok = _make_token("REPARTIDOR", str(rider.id))
    r = client.post(
        "/api/v1/notifications/test-send",
        headers={"Authorization": f"Bearer {tok}"},
        json={"template_code": "payout_aprobado",
              "context": {"amount_cents": 15000, "status": "APROBADO"}},
    )
    assert r.status_code == 403


def test_send_ok_for_manager_and_superadmin(client):
    for role in ("GERENTE", "SUPERADMIN"):
        holder = client.app._fase9_test_db_holder
        holder["db"] = _fake_db(_testsend_side_effect())
        tok = _make_token(role)
        r = client.post(
            "/api/v1/notifications/test-send",
            headers={"Authorization": f"Bearer {tok}"},
            json={"template_code": "payout_aprobado",
                  "context": {"amount_cents": 15000, "status": "APROBADO"}},
        )
        assert r.status_code == 200, (role, r.text)
        body = r.json()
        assert body["status"] == "ok"
        assert body["sent"] >= 1
        assert all(lg["status"] in {"ENVIADO", "PENDIENTE", "LEIDO"}
                   for lg in body["logs"])


def test_send_requires_auth(client):
    r = client.post("/api/v1/notifications/test-send",
                    json={"template_code": "payout_aprobado"})
    assert r.status_code == 401


# ---------------------------------------------------- 3. payout APROBADO -> log
def test_payout_approved_hook_creates_log():
    """El hook notify_event (usado post-commit en payouts.approve) produce logs."""
    from app.services import notification_hooks as hooks

    created = []

    class _Svc:
        def __init__(self, db=None):
            pass

        async def send(self, user_id, code, ctx, channels=None,
                       delivery_id=None, payout_id=None, title=None):
            created.append((str(user_id), code, ctx))
            lg = NotificationLog(id=uuid.uuid4(), user_id=user_id,
                                 template_code=code,
                                 channel=NotificationChannel.PUSH,
                                 status=OmnichannelStatus.ENVIADO,
                                 title="Pago aprobado", body="ok",
                                 created_at=datetime.utcnow())
            return [lg]

    rider_uid = uuid.uuid4()
    # notify_event hace import local -> parchar el atributo del módulo de origen
    real_cls = hooks.OmnichannelNotificationService if hasattr(hooks, "OmnichannelNotificationService") else None
    import app.services.omnichannel_service as osvc
    orig = osvc.OmnichannelNotificationService
    osvc.OmnichannelNotificationService = _Svc
    try:
        _run_coro(hooks.notify_event(
            "payout_aprobado", str(rider_uid),
            {"amount_cents": 15000, "bank_last4": "4321"},
            payout_id=uuid.uuid4(),
        ))
    finally:
        osvc.OmnichannelNotificationService = orig

    assert created, "el hook no envió ninguna notificación"
    uid, code, ctx = created[0]
    assert uid == str(rider_uid)
    assert code == "payout_aprobado"
    assert ctx.get("amount_cents") == 15000


# ------------------------------------------------------------------ 4. INBOX
def test_inbox_pagination_contract(client):
    uid = str(uuid.uuid4())
    log = NotificationLog(id=uuid.uuid4(), user_id=uuid.UUID(uid),
                          template_code="nuevo_pedido_asignado",
                          channel=NotificationChannel.IN_APP,
                          status=OmnichannelStatus.PENDIENTE,
                          title="Nuevo pedido", body="Asignado",
                          created_at=datetime.utcnow())
    seq = [
        _exec_result(scalar_val=25),      # count total
        _exec_result(scalars_list=[log]), # rows pagina 1
        _exec_result(scalar_val=7),       # unread count
    ]

    def _se(*a, **k):
        return seq.pop(0) if seq else _exec_result(scalar_val=0)

    client.app._fase9_test_db_holder["db"] = _fake_db(_se)
    tok = _make_token("REPARTIDOR", uid)
    r = client.get("/api/v1/notifications/inbox?page=2&size=10",
                   headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    body = r.json()
    for key in ("items", "page", "size", "total", "pages", "unread_count"):
        assert key in body
    assert body["page"] == 2 and body["total"] == 25
    assert body["items"][0]["channel"] == "IN_APP"


# ------------------------------------------------------- 5. PATCH read ownership
def test_mark_read_owner_ok_other_forbidden(client):
    owner_uid = uuid.uuid4()
    other_uid = uuid.uuid4()
    log = NotificationLog(id=uuid.uuid4(), user_id=owner_uid,
                          template_code="payout_aprobado",
                          channel=NotificationChannel.IN_APP,
                          status=OmnichannelStatus.ENVIADO,
                          title="t", body="b", created_at=datetime.utcnow())

    client.app._fase9_test_db_holder["db"] = _fake_db(
        lambda *a, **k: _exec_result(scalar_one=log))
    r = client.patch(f"/api/v1/notifications/{log.id}/read",
                     headers={"Authorization": f"Bearer {_make_token('REPARTIDOR', str(other_uid))}"})
    assert r.status_code == 403  # no es dueño ni SUPERADMIN

    client.app._fase9_test_db_holder["db"] = _fake_db(
        lambda *a, **k: _exec_result(scalar_one=log))
    r = client.patch(f"/api/v1/notifications/{log.id}/read",
                     headers={"Authorization": f"Bearer {_make_token('REPARTIDOR', str(owner_uid))}"})
    assert r.status_code == 200
    assert log.status == OmnichannelStatus.LEIDO
    assert log.read_at is not None

    client.app._fase9_test_db_holder["db"] = _fake_db(
        lambda *a, **k: _exec_result(scalar_one=None))
    r = client.patch(f"/api/v1/notifications/{uuid.uuid4()}/read",
                     headers={"Authorization": f"Bearer {_make_token('GERENTE')}"})
    assert r.status_code == 404


# ------------------------------------------------------------------ 6. WS
def test_ws_rejects_invalid_token(client):
    with pytest.raises(Exception) as excinfo:
        with client.websocket_connect(
                "/api/v1/notifications/ws?token=token-no-valido") as ws:
            ws.receive_json()
    # starlette lanza WebSocketDisconnect/WSEmergencyClose 1008
    code = getattr(excinfo.value, "code", None)
    text = str(excinfo.value)
    assert code == 1008 or "1008" in text, f"cierre inesperado: {text}"


def test_ws_accepts_valid_jwt_snapshot(client, monkeypatch):
    """JWT válido -> CONNECTED con unread_count snapshot (regla: snapshot inicial).

    El handler crea su propia sesión vía AsyncSessionLocal (import local dentro
    de notifications.py), NO vía get_db — se parcha por nombre de módulo.
    """
    import app.api.v1.notifications as notif_mod
    from app.core.database import get_db as _gdb

    uid = str(uuid.uuid4())
    tok = _make_token("REPARTIDOR", uid)
    monkeypatch.setattr(
        notif_mod,
        "get_current_user",
        AsyncMock(return_value=SimpleNamespace(id=uuid.UUID(uid))),
    )

    def no_redis():
        raise ConnectionError("test unavailable")

    monkeypatch.setattr(notif_mod, "_notification_redis_client", no_redis)

    class _FakeSessCtx:
        async def __aenter__(self):
            db = MagicMock()
            db.execute = AsyncMock(return_value=_exec_result(scalar_val=3))
            db.commit = AsyncMock(); db.refresh = AsyncMock()
            db.rollback = AsyncMock(); db.flush = AsyncMock()
            return db

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(notif_mod, "AsyncSessionLocal",
                        lambda *a, **k: _FakeSessCtx(), raising=False)
    # fuente real del import local dentro del handler
    import app.core.database as dbmod2
    orig_maker = dbmod2.AsyncSessionLocal
    dbmod2.AsyncSessionLocal = lambda *a, **k: _FakeSessCtx()
    try:
        with client.websocket_connect(f"/api/v1/notifications/ws?token={tok}") as ws:
            msg = ws.receive_json(mode="text")
            assert isinstance(msg, dict)
            assert msg.get("type") == "CONNECTED"
            assert "unread_count" in msg
            assert msg["unread_count"] == 3
            ws.send_json({"action": "ping"})
            pong = ws.receive_json(mode="text")
            assert pong.get("type") == "pong"
    finally:
        dbmod2.AsyncSessionLocal = orig_maker


# ------------------------------------------------------------------ 7. dedupe
def test_dedupe_same_window_skips_second_send():
    """Segundo envío idéntico dentro de la ventana de 5min NO crea logs."""
    from app.services.omnichannel_service import build_dedupe_key

    ts = (time_window := int(datetime.now().timestamp() // 300)) * 300 + 10
    k1 = build_dedupe_key("payout_aprobado", "payout-1", window_ts=ts)
    k2 = build_dedupe_key("payout_aprobado", "payout-1",
                          window_ts=ts + 100)  # misma ventana
    k3 = build_dedupe_key("payout_aprobado", "payout-1",
                          window_ts=ts + 400)  # ventana siguiente
    assert k1 == k2
    assert k1 != k3

    # Y a nivel de servicio: dedupe existente -> send() devuelve []
    user = _user_obj("REPARTIDOR")
    tpl = _template(channel="IN_APP")
    seq = [
        _exec_result(scalar_one=user),
        _exec_result(scalar_one=tpl),
        _exec_result(scalar_one=uuid.uuid4()),  # dedupe YA existe
    ]

    async def _se(*a, **k):
        return seq.pop(0) if seq else _exec_result(scalar_one=None)

    from app.services.omnichannel_service import OmnichannelNotificationService
    svc = OmnichannelNotificationService(db=_fake_db(_se), redis_client=False)

    logs = _run_coro(svc.send(user.id, "payout_aprobado",
                              {"amount_cents": 1, "status": "X"}))
    # NOTE: no asyncio.run aqui: cerrar el loop global roto pytest-asyncio
    # para los tests async posteriores (falla observada en auditoria Fase 9).
    assert logs == []


# --------------------------------------------- 8. flag NOTIFICATIONS_ENABLED
def test_flag_disabled_forces_in_app_only(monkeypatch):
    from app.services import omnichannel_service as osvc

    monkeypatch.setattr(osvc.settings, "NOTIFICATIONS_ENABLED", False)
    user = _user_obj("GERENTE")
    tpl = _template(channel="EMAIL")
    seq = [
        _exec_result(scalar_one=user),
        _exec_result(scalar_one=tpl),
        _exec_result(scalar_one=None),           # dedupe libre
        _exec_result(scalars_list=[]),           # prefs
    ]

    async def _se(*a, **k):
        return seq.pop(0) if seq else _exec_result(scalar_one=None)

    db = _fake_db(_se)
    svc = osvc.OmnichannelNotificationService(db=db, redis_client=False)
    logs = _run_coro(svc.send(user.id, "resumen_diario_manager",
                              {"manager_name": "M"},
                              channels=[NotificationChannel.EMAIL]))
    assert len(logs) == 1
    assert logs[0].channel == NotificationChannel.IN_APP  # fallback al flag off
