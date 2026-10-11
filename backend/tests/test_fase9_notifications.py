"""
Fase 9 — Tests UNITARIOS del servicio omnicanal (sin Postgres/Redis reales).

Cubren:
1. render_template: {{var}} sustituidas; variables faltantes -> '' + warning,
   NUNCA excepción al caller.
2. build_dedupe_key: misma ventana de 5 min => misma key; ventana distinta => otra.
3. compute_next_retry_at: backoff exponencial base NOTIFICATION_RETRY_BACKOFF_SEC.
4. OmnichannelNotificationService.send() con DB fake:
   - usuario inexistente -> [] (jamás lanza)
   - plantilla inactiva -> []
   - dedupe < 5 min -> [] (no crea segundo log)
   - NOTIFICATIONS_ENABLED=false -> solo IN_APP stub
   - dispatch paralelo deja logs ENVIADO con providers stub sin credenciales
5. _schedule_retry: agotados (retry_count >= MAX) -> FALLIDO sin next_retry_at.
6. Auto-disable de device token tras 3 fallos consecutivos.
La capa de persistencia se mockea con un doble de AsyncSession determinista
(mismo patrón que test_fase8_integration.py: NO monkeypatch de get_db).
"""
import uuid
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import settings
from app.models.notification import (
    NotificationChannel,
    NotificationLog,
    NotificationTemplate,
    OmnichannelStatus,
    UserDeviceToken,
)
from app.models.user import User, UserRole
from app.services.omnichannel_service import (
    OmnichannelNotificationService,
    ROLE_DEFAULT_CHANNELS,
    build_dedupe_key,
    compute_next_retry_at,
    render_template,
)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _exec_result(scalars_list=None, scalar_one=None, scalar_one_or_none=None):
    res = MagicMock()
    res.scalars.return_value.all.return_value = scalars_list or []
    res.scalar_one_or_none.return_value = scalar_one_or_none
    if scalar_one is not None:
        res.scalar_one.return_value = scalar_one
    return res


def _make_user(role=UserRole.REPARTIDOR):
    u = User()
    u.id = uuid.uuid4()
    u.email = f"rider{str(u.id)[:6]}@delivery360.com"
    u.phone = "+584121234567"
    u.role = role
    u.is_active = True
    return u


def _make_template(code="payout_aprobado", channel=NotificationChannel.PUSH,
                   body="Retiro ${{amount_cents}} aprobado en cuenta ****{{bank_last4}}.",
                   subject=None, is_active=True):
    t = NotificationTemplate()
    t.id = uuid.uuid4()
    t.code = code
    t.channel = channel
    t.subject = subject
    t.body_template = body
    t.language = "es"
    t.is_active = is_active
    return t


class _FakeDB:
    """AsyncSession doble con cola de resultados y registro de add()/commit()."""

    def __init__(self, results=None):
        self.results = list(results or [])
        self.added = []
        self.commits = 0
        self.deleted = 0

    async def execute(self, *a, **k):
        if self.results:
            return self.results.pop(0)
        return _exec_result()

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj, attribute_names=None):
        # Notificación: asignar defaults de timestamp como haría la DB roundtrip
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(timezone.utc).replace(tzinfo=None)

    async def flush(self):
        pass

    async def rollback(self):
        pass


# ----------------------------------------------------------------------
# 1) render_template
# ----------------------------------------------------------------------
def test_render_substitutes_variables():
    out = render_template("Hola {{name}}, pagas {{amount_cents}}", {"name": "Ana", "amount_cents": 1500})
    assert out == "Hola Ana, pagas 1500"


def test_render_missing_variable_returns_empty_string_and_never_raises(caplog):
    # Regla Paso 3: variable faltante -> '' + logger.warning, NUNCA excepción
    with caplog.at_level("WARNING"):
        out = render_template("Monto: {{amount_cents}} banco {{bank_last4}}", {})
    assert out == "Monto:  banco "
    assert any("variable faltante" in r.message for r in caplog.records)


def test_render_none_body_is_safe():
    assert render_template(None, {}) == ""


# ----------------------------------------------------------------------
# 2) dedupe key (ventana 5 min)
# ----------------------------------------------------------------------
def test_dedupe_key_same_window_same_key():
    # Ventana de 300 s: ts//300 idéntico para ambos timestamps
    ts = (1_700_000_000 // 300) * 300  # inicio exacto de una ventana
    k1 = build_dedupe_key("payout_aprobado", "entity-1", window_ts=ts)
    k2 = build_dedupe_key("payout_aprobado", "entity-1", window_ts=ts + 120)
    assert k1 == k2


def test_dedupe_key_different_window_or_entity_differs():
    ts = (1_700_000_000 // 300) * 300
    k1 = build_dedupe_key("payout_aprobado", "entity-1", window_ts=ts)
    k2 = build_dedupe_key("payout_aprobado", "entity-1", window_ts=ts + 600)
    k3 = build_dedupe_key("payout_aprobado", "entity-2", window_ts=ts)
    assert k1 != k2 and k1 != k3
    assert len(k1) <= 120


# ----------------------------------------------------------------------
# 3) backoff exponencial
# ----------------------------------------------------------------------
def test_compute_next_retry_exponential_backoff():
    base = int(settings.NOTIFICATION_RETRY_BACKOFF_SEC)
    r0 = compute_next_retry_at(0)
    r1 = compute_next_retry_at(1)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    d0 = (r0 - now).total_seconds()
    d1 = (r1 - now).total_seconds()
    # retry 0 -> ~base*1 ; retry 1 -> ~base*2 (tolerancia de ejecución)
    assert 0 < d0 <= base + 5
    assert abs(d1 - 2 * base) <= 5


# ----------------------------------------------------------------------
# 4) send() con DB fake
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_send_unknown_user_returns_empty_never_raises():
    db = _FakeDB([_exec_result(scalar_one_or_none=None)])  # User no existe
    svc = OmnichannelNotificationService(db, redis_client=False)
    out = await svc.send(uuid.uuid4(), "payout_aprobado", {})
    assert out == []


@pytest.mark.asyncio
async def test_send_inactive_template_returns_empty():
    user = _make_user()
    tpl = _make_template(is_active=False)
    db = _FakeDB([
        _exec_result(scalar_one_or_none=user),      # select(User)
        _exec_result(scalar_one_or_none=tpl),       # plantilla
        _exec_result(scalar_one_or_none=None),      # dedupe lookup
    ])
    svc = OmnichannelNotificationService(db, redis_client=False)
    out = await svc.send(user.id, "payout_aprobado", {"amount_cents": 1, "bank_last4": "0000"})
    assert out == []


@pytest.mark.asyncio
async def test_send_dedupe_within_5min_skips_second_log():
    user = _make_user()
    tpl = _make_template()
    common = [
        _exec_result(scalar_one_or_none=user),   # user
        _exec_result(scalar_one_or_none=tpl),    # template
    ]
    db1 = _FakeDB(common + [_exec_result(scalar_one_or_none=None)])  # primer envío: sin dup
    svc = OmnichannelNotificationService(db1, redis_client=False)
    logs = await svc.send(user.id, "payout_aprobado",
                          {"amount_cents": 15000, "bank_last4": "4321"},
                          payout_id="pay-1")
    assert len(logs) >= 1
    # Segundo envío idéntico dentro de la misma ventana: dedupe ya existe
    existing_id = logs[0].id
    db2 = _FakeDB(common + [_exec_result(scalar_one_or_none=existing_id)])
    svc2 = OmnichannelNotificationService(db2, redis_client=False)
    logs2 = await svc2.send(user.id, "payout_aprobado",
                            {"amount_cents": 15000, "bank_last4": "4321"},
                            payout_id="pay-1")
    assert logs2 == []
    assert len(db2.added) == 0  # no creó ningún log nuevo


@pytest.mark.asyncio
async def test_send_flag_disabled_forces_in_app_stub(monkeypatch):
    user = _make_user(UserRole.GERENTE)  # default rol sería PUSH+EMAIL
    tpl = _make_template(channel=NotificationChannel.EMAIL)
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", False)
    db = _FakeDB([
        _exec_result(scalar_one_or_none=user),
        _exec_result(scalar_one_or_none=tpl),
        _exec_result(scalar_one_or_none=None),          # dedupe
        _exec_result(scalars_list=[]),                  # prefs (ninguna)
    ])
    svc = OmnichannelNotificationService(db, redis_client=False)
    logs = await svc.send(user.id, "payout_aprobado", {"amount_cents": 1, "bank_last4": "1"})
    assert len(logs) == 1
    assert logs[0].channel == NotificationChannel.IN_APP
    assert logs[0].status == OmnichannelStatus.ENVIADO  # IN_APP persistido = enviado


@pytest.mark.asyncio
async def test_send_push_stub_without_credentials_marks_enviado():
    """Sin credenciales FCM el dispatch_push es stub: jamás crash, status ENVIADO."""
    user = _make_user(UserRole.REPARTIDOR)
    tpl = _make_template()
    db = _FakeDB([
        _exec_result(scalar_one_or_none=user),
        _exec_result(scalar_one_or_none=tpl),
        _exec_result(scalar_one_or_none=None),      # dedupe
        _exec_result(scalars_list=[]),              # prefs
        _exec_result(scalars_list=[]),              # device tokens (ninguno)
    ])
    svc = OmnichannelNotificationService(db, redis_client=False)
    logs = await svc.send(user.id, "payout_aprobado",
                          {"amount_cents": 15000, "bank_last4": "4321"}, payout_id="p1")
    assert len(logs) == 1
    assert logs[0].channel == NotificationChannel.PUSH
    assert logs[0].status == OmnichannelStatus.ENVIADO
    assert logs[0].sent_at is not None


@pytest.mark.asyncio
async def test_role_default_channels_contract():
    assert ROLE_DEFAULT_CHANNELS["REPARTIDOR"] == [NotificationChannel.PUSH]
    assert set(ROLE_DEFAULT_CHANNELS["GERENTE"]) == {NotificationChannel.PUSH, NotificationChannel.EMAIL}
    assert set(ROLE_DEFAULT_CHANNELS["CLIENTE"]) == {NotificationChannel.IN_APP, NotificationChannel.EMAIL}


# ----------------------------------------------------------------------
# 5) retry / fallo agotado
# ----------------------------------------------------------------------
def test_schedule_retry_exhausted_marks_fallido():
    db = _FakeDB()
    svc = OmnichannelNotificationService(db, redis_client=False)
    log = NotificationLog(id=uuid.uuid4(), user_id=uuid.uuid4(),
                          channel=NotificationChannel.PUSH,
                          status=OmnichannelStatus.PENDIENTE,
                          retry_count=int(settings.NOTIFICATION_MAX_RETRIES))
    svc._schedule_retry(log, "provider caído")
    assert log.status == OmnichannelStatus.FALLIDO
    assert log.next_retry_at is None


def test_schedule_retry_below_max_schedules_backoff():
    db = _FakeDB()
    svc = OmnichannelNotificationService(db, redis_client=False)
    log = NotificationLog(id=uuid.uuid4(), user_id=uuid.uuid4(),
                          channel=NotificationChannel.PUSH,
                          status=OmnichannelStatus.PENDIENTE, retry_count=0)
    svc._schedule_retry(log, "transitorio")
    assert log.status == OmnichannelStatus.PENDIENTE
    assert log.retry_count == 1
    assert log.next_retry_at is not None


# ----------------------------------------------------------------------
# 6) auto-disable de token tras 3 fallos
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_token_auto_disable_after_three_failures():
    tok = UserDeviceToken(id=uuid.uuid4(), user_id=uuid.uuid4(),
                          device_token="tok-1234567890", platform="android",
                          failure_count=2, is_active=True)
    db = _FakeDB([_exec_result(scalars_list=[tok])])
    svc = OmnichannelNotificationService(db, redis_client=False)
    await svc._mark_token_failures(["tok-1234567890"])
    assert tok.failure_count == 3
    assert tok.is_active is False


# ----------------------------------------------------------------------
# 7) purge_old_logs usa retención configurada
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_purge_old_logs_uses_retention_days():
    res = MagicMock()
    res.rowcount = 3
    db = _FakeDB([res])
    svc = OmnichannelNotificationService(db, redis_client=False)
    n = await svc.purge_old_logs()
    assert n == 3
    assert db.commits == 1
