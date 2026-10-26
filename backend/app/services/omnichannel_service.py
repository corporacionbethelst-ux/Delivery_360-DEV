"""
Fase 9 — Servicio omnicanal de notificaciones (Delivery360).

DISEÑO:
- No reemplaza al NotificationService legacy (tabla `notifications`, usado por
  alertas operacionales); conviven. Este servicio escribe en notification_logs.
- Providers firebase-admin / twilio son OPCIONALES (import
  try/except, patrón OR-Tools de Fase 8). Sin credenciales → fallback IN_APP
  para PUSH/SMS. EMAIL usa SMTP real y reintento ante fallo, sin éxito simulado.
- Redis async SOLO vía `from redis import asyncio as aioredis` (regla heredada).
- Plantillas cacheadas en Redis TTL 1h con fallback a DB si Redis está caído.
- Dedupe: hash(template_code+entity_id+ventana_5min) → skippa reenvíos <5 min.
- Rate limit interno: 10 eventos/min/usuario (patrón dict _update_windows de
  tracking_scheduler de Fase 8).
- Reintentos exponenciales: base NOTIFICATION_RETRY_BACKOFF_SEC, máx
  NOTIFICATION_MAX_RETRIES; agotados → FALLIDO.
- Fan-out WS: publica NEW_NOTIFICATION en Redis Pub/Sub
  `notifications:user:{id}` — UN solo suscriptor hace fan-out (regla 6).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.email_service import send_smtp_email
from app.models.notification import (
    NotificationChannel,
    NotificationLog,
    NotificationPreference,
    NotificationTemplate,
    OmnichannelStatus,
    UserDeviceToken,
)
from app.models.user import User

logger = logging.getLogger(__name__)

# Imports opcionales de providers (patrón OR-Tools Fase 8) ───────────────────
try:  # pragma: no cover - depende de entorno
    from firebase_admin import messaging as fcm_messaging  # type: ignore

    FCM_AVAILABLE = True
except Exception:  # ImportError u otros
    fcm_messaging = None
    FCM_AVAILABLE = False

try:  # pragma: no cover
    from twilio.rest import Client as TwilioClient  # type: ignore

    TWILIO_AVAILABLE = True
except Exception:
    TwilioClient = None
    TWILIO_AVAILABLE = False

# Redis async NATIVO (redis>=5). PROHIBIDO el paquete deprecado `aioredis`.
try:  # pragma: no cover
    from redis import asyncio as aioredis

    REDIS_LIB_AVAILABLE = True
except Exception:
    aioredis = None
    REDIS_LIB_AVAILABLE = False


_VAR_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")

# Regla por rol (Paso 1): riders→PUSH, managers→PUSH+EMAIL, clientes→IN_APP+EMAIL
ROLE_DEFAULT_CHANNELS: Dict[str, List[NotificationChannel]] = {
    "REPARTIDOR": [NotificationChannel.PUSH],
    "RIDER": [NotificationChannel.PUSH],
    "GERENTE": [NotificationChannel.PUSH, NotificationChannel.EMAIL],
    "MANAGER": [NotificationChannel.PUSH, NotificationChannel.EMAIL],
    "ADMINISTRADOR": [NotificationChannel.PUSH, NotificationChannel.EMAIL],
    "SUPERADMIN": [NotificationChannel.PUSH, NotificationChannel.EMAIL],
    "CLIENTE": [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    "CUSTOMER": [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    "OPERADOR": [NotificationChannel.IN_APP],
}


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RenderError(Exception):
    """Error controlable de renderizado (nunca llega al caller: se loguea)."""


def render_template(template_body: str, context: Dict[str, Any]) -> str:
    """Renderiza {{variable}}. Variables faltantes → '' + warning (NUNCA lanza).

    Devuelve siempre string; jamás propaga excepción al llamador (regla Paso 3).
    """

    def _sub(m: re.Match) -> str:
        key = m.group(1)
        if key in context and context[key] is not None:
            return str(context[key])
        logger.warning("Notificación: variable faltante '%s' → sustituida por ''", key)
        return ""

    try:
        return _VAR_RE.sub(_sub, template_body or "")
    except Exception as exc:  # doble red de seguridad
        logger.error("Render inesperado falló (%s); devolviendo plantilla cruda", exc)
        return template_body or ""


def build_dedupe_key(
    template_code: str, entity_id: Optional[Any], window_ts: Optional[float] = None
) -> str:
    """hash(template_code + entity_id + ventana_5min) — 120 chars max."""
    ts = window_ts if window_ts is not None else time.time()
    window = int(ts // 300)  # ventana de 5 minutos
    raw = f"{template_code}|{entity_id or 'global'}|{window}"
    return hashlib.sha256(raw.encode()).hexdigest()[:120]


def compute_next_retry_at(retry_count: int) -> datetime:
    """Backoff exponencial: base * 2^retry_count segundos."""
    base = max(1, int(settings.NOTIFICATION_RETRY_BACKOFF_SEC))
    delay = base * (2 ** max(0, retry_count))
    return utc_now_naive() + timedelta(seconds=delay)


class OmnichannelNotificationService:
    """Servicio omnicanal Fase 9 (plantillas + logs + preferencias + providers)."""

    def __init__(self, db: AsyncSession, redis_client: Optional[Any] = None):
        self.db = db
        self._redis = redis_client  # inyectable para tests; lazy si None
        # Cache local de plantillas como último fallback (dict simple)
        self._local_template_cache: Dict[str, tuple] = {}

    # ------------------------------------------------------------------
    # Redis helpers (todo tolerante a fallos: Redis caído nunca rompe envío)
    # ------------------------------------------------------------------
    async def _get_redis(self):
        # -1 centinela: ya se intentó conectar y falló → no reintentar por request
        if self._redis is not None and self._redis is not False:
            return self._redis
        if self._redis is False or not REDIS_LIB_AVAILABLE:
            return None
        try:
            client = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=2,
            )
            await client.ping()
            self._redis = client
            return client
        except Exception as exc:
            logger.warning("Redis no disponible para notificaciones: %s", exc)
            self._redis = False  # degrade suave: no reintenta en cada envío
            return None

    async def _get_template(self, code: str) -> Optional[NotificationTemplate]:
        """Plantilla con cache Redis TTL 1h + fallback DB."""
        r = await self._get_redis()
        cache_key = f"notif:template:{code}"
        if r is not None:
            try:
                cached = await r.get(cache_key)
                if cached:
                    data = json.loads(cached)
                    return NotificationTemplate(**data)
            except Exception as exc:
                logger.warning("Cache plantilla ilegible (%s): %s", code, exc)

        result = await self.db.execute(
            select(NotificationTemplate).where(NotificationTemplate.code == code)
        )
        tpl = result.scalar_one_or_none()
        if tpl is None:
            return None

        if r is not None:
            try:
                payload = {
                    "code": tpl.code,
                    "channel": (
                        tpl.channel.value
                        if hasattr(tpl.channel, "value")
                        else str(tpl.channel)
                    ),
                    "subject": tpl.subject,
                    "body_template": tpl.body_template,
                    "language": tpl.language,
                    "is_active": bool(tpl.is_active),
                }
                await r.set(
                    cache_key,
                    json.dumps(payload),
                    ex=settings.NOTIFICATION_TEMPLATE_CACHE_TTL_SEC,
                )
            except Exception as exc:
                logger.warning("No se pudo cachear plantilla %s: %s", code, exc)
        return tpl

    # ------------------------------------------------------------------
    # Rate limit (patrón dict _update_windows de tracking Fase 8)
    # ------------------------------------------------------------------
    _rate_windows: Dict[str, List[float]] = {}

    @classmethod
    def _rate_limited(cls, user_id: Any) -> bool:
        now = time.time()
        key = str(user_id)
        window = cls._rate_windows.setdefault(key, [])
        window[:] = [t for t in window if now - t < 60]
        if len(window) >= settings.NOTIFICATION_RATE_LIMIT_PER_MIN:
            return True
        window.append(now)
        # Poda global suave para no crecer sin límite
        if len(cls._rate_windows) > 10000:
            stale = [
                k for k, v in cls._rate_windows.items() if not v or now - max(v) > 120
            ]
            for k in stale:
                cls._rate_windows.pop(k, None)
        return False

    # ------------------------------------------------------------------
    # Preferencias por usuario + rol
    # ------------------------------------------------------------------
    async def resolve_channels(
        self,
        user: User,
        template: NotificationTemplate,
        event_code: str,
        channels: Optional[List[NotificationChannel]] = None,
    ) -> List[NotificationChannel]:
        """Canales efectivos: override explícito > preferencias > default por rol.

        Las preferencias deshabilitadas filtran SIEMPRE (incluso overrides),
        salvo que el canal sea IN_APP (inbox garantizado, regla de negocio).
        """
        requested = channels or ROLE_DEFAULT_CHANNELS.get(
            getattr(
                getattr(user, "role", None), "value", str(getattr(user, "role", ""))
            ),
            [NotificationChannel.IN_APP],
        )

        pref_rows = await self.db.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user.id,
                NotificationPreference.event_code == event_code,
            )
        )
        prefs = {p.channel: p.enabled for p in pref_rows.scalars().all()}

        resolved: List[NotificationChannel] = []
        for ch in requested:
            enabled = prefs.get(ch, True)
            if enabled or ch == NotificationChannel.IN_APP:
                resolved.append(ch)
        # Garantizar entrega in-app mínima para campana (siempre se registra)
        return resolved or [NotificationChannel.IN_APP]

    # ------------------------------------------------------------------
    # API principal
    # ------------------------------------------------------------------
    async def send(
        self,
        user_id: Any,
        template_code: str,
        context: Dict[str, Any],
        channels: Optional[List[NotificationChannel]] = None,
        delivery_id: Optional[Any] = None,
        payout_id: Optional[Any] = None,
        title: Optional[str] = None,
    ) -> List[NotificationLog]:
        """Envío omnicanal. NUNCA lanza excepciones al caller: devuelve [].

        Pasos: plantilla → dedupe → rate-limit → render → logs PENDIENTE →
        dispatch paralelo → pub/sub NEW_NOTIFICATION.
        """
        try:
            return await self._send_inner(
                user_id,
                template_code,
                context,
                channels,
                delivery_id,
                payout_id,
                title,
            )
        except Exception as exc:
            # Regla Fase 4: un fallo de notificación JAMÁS interrumpe el flujo de negocio
            logger.error("Notificación %s falló (no crítico): %s", template_code, exc)
            return []

    async def _send_inner(
        self,
        user_id: Any,
        template_code: str,
        context: Dict[str, Any],
        channels: Optional[List[NotificationChannel]],
        delivery_id: Any,
        payout_id: Any,
        title: Optional[str],
    ) -> List[NotificationLog]:
        if not settings.NOTIFICATIONS_ENABLED:
            # Flag apagado → todo queda IN_APP stub (test unitario lo exige)
            channels = [NotificationChannel.IN_APP]

        user = (
            await self.db.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None:
            logger.warning("send(): usuario %s inexistente", user_id)
            return []

        template = await self._get_template(template_code)
        if template is None or not template.is_active:
            logger.warning("Plantilla %s inexistente o inactiva", template_code)
            return []

        entity_id = payout_id or delivery_id or context.get("entity_id")
        dedupe_key = build_dedupe_key(template_code, entity_id)
        existing = (
            await self.db.execute(
                select(NotificationLog.id).where(
                    NotificationLog.dedupe_key == dedupe_key
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            logger.info(
                "Dedupe: %s ya enviado en la ventana actual (skip)", template_code
            )
            return []

        if self._rate_limited(user_id):
            logger.warning("Rate limit notificaciones alcanzado para user %s", user_id)
            return []

        body = render_template(template.body_template, context)
        rendered_subject = (
            render_template(template.subject, context) if template.subject else None
        )
        notif_title = (
            title or rendered_subject or template_code.replace("_", " ").capitalize()
        )

        effective = await self.resolve_channels(user, template, template_code, channels)
        if not settings.NOTIFICATIONS_ENABLED:
            effective = [NotificationChannel.IN_APP]

        logs: List[NotificationLog] = []
        created_keys: set = (
            set()
        )  # dedupe intra-call (mismo canal para varias entidades)
        for ch in effective:
            key = f"{dedupe_key}:{ch.value}"  # dedupe por canal
            if key in created_keys:
                # send() NUNCA debe estallar: si otra entidad del mismo batch ya
                # ocupó la clave, se omite el duplicado en vez de violar el UNIQUE.
                logger.info(
                    "Dedupe intra-lote: %s ya encolado en esta ventana (skip)", key[:16]
                )
                continue
            created_keys.add(key)
            log = NotificationLog(
                id=uuid.uuid4(),
                user_id=user.id,
                template_code=template_code,
                delivery_id=delivery_id,
                payout_id=payout_id,
                channel=ch,
                status=OmnichannelStatus.PENDIENTE,
                payload_json=json.dumps(context, default=str),
                dedupe_key=key,
                title=notif_title[:255],
                body=body,
                created_at=utc_now_naive(),
            )
            self.db.add(log)
            logs.append(log)

        if not logs:
            return []

        try:
            await self.db.commit()
        except Exception as exc:
            # Carrera real entre workers/requests contra uq_notiflogs_dedupe_key.
            # CRÍTICO (auditoría): si el UNIQUE explotó, SQLAlchemy revierte la
            # transacción automáticamente; cualquier sentencia siguiente sobre la
            # misma sesión sin rollback previo cae en PendingRollbackError y
            # send() devolvería [] silenciosamente (notificación perdida).
            await self.db.rollback()
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            inserted_any = False
            for log in logs:
                stmt = (
                    pg_insert(NotificationLog)
                    .values(
                        id=log.id,
                        user_id=log.user_id,
                        template_code=log.template_code,
                        delivery_id=log.delivery_id,
                        payout_id=log.payout_id,
                        channel=log.channel,
                        status=OmnichannelStatus.PENDIENTE,
                        payload_json=log.payload_json,
                        dedupe_key=log.dedupe_key,
                        title=log.title,
                        body=log.body,
                        created_at=log.created_at,
                    )
                    .on_conflict_do_nothing(index_elements=["dedupe_key"])
                )
                res = await self.db.execute(stmt)
                if res.rowcount:
                    inserted_any = True
            if not inserted_any:
                logger.info("Dedupe (carrera): %s ya existía (skip)", template_code)
                return []
            await self.db.commit()
            logs = (
                (
                    await self.db.execute(
                        select(NotificationLog).where(
                            NotificationLog.dedupe_key.in_(created_keys)
                        )
                    )
                )
                .scalars()
                .all()
            )

        for log in logs:
            await self.db.refresh(log)

        # Dispatch EN PARALELO (gather) — cada canal aislado
        await asyncio.gather(
            *(self._dispatch_one(log, user, template, body) for log in logs),
            return_exceptions=True,
        )

        # Fan-out WS: publicar NEW_NOTIFICATION (solo una vez por evento)
        in_app = next(
            (l for l in logs if l.channel == NotificationChannel.IN_APP), None
        )
        await self._publish_new_notification(in_app or (logs[0] if logs else None))
        return logs

    # ------------------------------------------------------------------
    # Dispatch por canal
    # ------------------------------------------------------------------
    async def _dispatch_one(
        self,
        log: NotificationLog,
        user: User,
        template: NotificationTemplate,
        body: str,
    ) -> None:
        try:
            if log.channel == NotificationChannel.PUSH:
                tokens = (
                    (
                        await self.db.execute(
                            select(UserDeviceToken).where(
                                UserDeviceToken.user_id == user.id,
                                UserDeviceToken.is_active.is_(True),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                ok = await self.dispatch_push(
                    [t.device_token for t in tokens], log.title or "", body
                )
            elif log.channel == NotificationChannel.SMS:
                ok = await self.dispatch_sms(getattr(user, "phone", None), body)
            elif log.channel == NotificationChannel.EMAIL:
                ok = await self.dispatch_email(
                    getattr(user, "email", None),
                    log.title or template_code_safe(template),
                    body,
                )
            else:  # IN_APP: persistido es suficiente
                ok = True

            if ok:
                log.status = OmnichannelStatus.ENVIADO
                log.sent_at = utc_now_naive()
                if log.channel == NotificationChannel.EMAIL:
                    # Legacy models use unparameterized Column attributes.
                    email_log: Any = log
                    email_log.next_retry_at = None
                    email_log.error_message = None
                if log.channel == NotificationChannel.IN_APP:
                    log.delivered_at = log.sent_at
            else:
                self._schedule_retry(log, "Provider reportó fallo")
        except Exception as exc:
            if log.channel == NotificationChannel.EMAIL:
                logger.warning("Notification SMTP dispatch failed")
                self._schedule_retry(log, "SMTP dispatch failed")
            else:
                logger.error("Dispatch %s falló: %s", log.channel, exc)
                self._schedule_retry(log, str(exc))
        await self.db.commit()

    def _schedule_retry(self, log: NotificationLog, error: str) -> None:
        max_retries = int(settings.NOTIFICATION_MAX_RETRIES)
        log.error_message = (error or "")[:2000]
        if log.retry_count >= max_retries:
            log.status = OmnichannelStatus.FALLIDO
            log.next_retry_at = None
        else:
            log.retry_count += 1
            log.next_retry_at = compute_next_retry_at(log.retry_count)
            # vuelve a cola PENDIENTE para el job periódico
            log.status = OmnichannelStatus.PENDIENTE

    # ------------------------------------------------------------------
    # Providers (todos opcionales vía feature flag / credenciales)
    # ------------------------------------------------------------------
    async def dispatch_push(
        self,
        device_tokens: List[str],
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if not device_tokens:
            # Sin dispositivos → simular éxito stub (el IN_APP cubre la bandeja)
            logger.debug("PUSH sin tokens: fallback stub")
            return True
        if not (FCM_AVAILABLE and settings.FCM_CREDENTIALS_JSON_PATH):
            logger.debug("FCM no configurado → provider='stub'")
            return True
        try:  # pragma: no cover - requiere credenciales reales
            msg = fcm_messaging.MulticastMessage(
                tokens=device_tokens,
                notification=fcm_messaging.Notification(title=title, body=body),
                data=data or {},
            )
            resp = fcm_messaging.send_multicast(msg)
            failed_idx = [i for i, r in enumerate(resp.responses) if not r.success]
            if failed_idx:
                await self._mark_token_failures([device_tokens[i] for i in failed_idx])
            return resp.success_count > 0
        except Exception as exc:
            logger.error("FCM error: %s", exc)
            return False

    async def dispatch_sms(self, phone: Optional[str], message: str) -> bool:
        if not phone:
            return True  # nada que enviar, no es fallo duro
        if not (
            TWILIO_AVAILABLE
            and settings.TWILIO_ACCOUNT_SID
            and settings.TWILIO_AUTH_TOKEN
        ):
            logger.debug("Twilio no configurado → provider='stub'")
            return True
        try:  # pragma: no cover
            client = TwilioClient(
                settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN
            )
            msg = client.messages.create(
                body=message[:1600], from_=settings.TWILIO_FROM_NUMBER, to=phone
            )
            return bool(msg.sid)
        except Exception as exc:
            logger.error("Twilio error: %s", exc)
            return False

    async def dispatch_email(self, to: Optional[str], subject: str, html: str) -> bool:
        # Disabled/unconfigured/missing recipient is not a delivered EMAIL.
        if not to or not settings.NOTIFICATIONS_ENABLED:
            return False
        try:
            return await send_smtp_email(
                to,
                subject,
                html,
                html,
                from_address=settings.notification_email_from_computed,
            )
        except Exception:
            logger.warning("Notification SMTP dispatch failed")
            return False

    async def _mark_token_failures(self, tokens: List[str]) -> None:
        """Auto-desactivar token tras 3 fallos consecutivos (regla Paso 1)."""
        rows = (
            (
                await self.db.execute(
                    select(UserDeviceToken).where(
                        UserDeviceToken.device_token.in_(tokens)
                    )
                )
            )
            .scalars()
            .all()
        )
        for t in rows:
            t.failure_count = (t.failure_count or 0) + 1
            if t.failure_count >= 3:
                t.is_active = False
                logger.info(
                    "Token %s... auto-desactivado tras %d fallos",
                    t.device_token[:12],
                    t.failure_count,
                )
        await self.db.commit()

    # ------------------------------------------------------------------
    # Pub/Sub fan-out WS
    # ------------------------------------------------------------------
    async def _publish_new_notification(self, log: Optional[NotificationLog]) -> None:
        if log is None:
            return
        r = await self._get_redis()
        if r is None:
            return
        try:
            channel = f"{settings.REDIS_NOTIF_CHANNEL_PREFIX}:{log.user_id}"
            payload = {
                "type": "NEW_NOTIFICATION",
                "id": str(log.id),
                "title": log.title,
                "template_code": log.template_code,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            await r.publish(channel, json.dumps(payload, default=str))
        except Exception as exc:
            logger.warning("Pub/Sub notificación falló (no crítico): %s", exc)

    # ------------------------------------------------------------------
    # Jobs periódicos
    # ------------------------------------------------------------------
    async def process_retry_queue(self, batch_size: int = 50) -> int:
        """Reintenta logs PENDIENTE con next_retry_at vencido. Devuelve procesados."""
        now = utc_now_naive()
        rows = (
            (
                await self.db.execute(
                    select(NotificationLog)
                    .where(
                        NotificationLog.status == OmnichannelStatus.PENDIENTE,
                        NotificationLog.next_retry_at.is_not(None),
                        NotificationLog.next_retry_at <= now,
                    )
                    .order_by(NotificationLog.next_retry_at)
                    .limit(batch_size)
                )
            )
            .scalars()
            .all()
        )

        processed = 0
        for log in rows:
            user = (
                await self.db.execute(select(User).where(User.id == log.user_id))
            ).scalar_one_or_none()
            if user is None:
                log.status = OmnichannelStatus.FALLIDO
                log.error_message = "Usuario inexistente en reintento"
                await self.db.commit()
                continue
            template = None
            if log.template_code:
                template = await self._get_template(log.template_code)
            ok = False
            if log.channel == NotificationChannel.PUSH:
                tokens = (
                    (
                        await self.db.execute(
                            select(UserDeviceToken).where(
                                UserDeviceToken.user_id == user.id,
                                UserDeviceToken.is_active.is_(True),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                ok = await self.dispatch_push(
                    [t.device_token for t in tokens], log.title or "", log.body or ""
                )
            elif log.channel == NotificationChannel.SMS:
                ok = await self.dispatch_sms(user.phone, log.body or "")
            elif log.channel == NotificationChannel.EMAIL:
                ok = await self.dispatch_email(
                    user.email, log.title or "", log.body or ""
                )
            else:
                ok = True

            if not ok and log.channel == NotificationChannel.EMAIL:
                self._schedule_retry(log, "SMTP unavailable or failed")
                processed += 1
                continue
            if ok:
                log.status = OmnichannelStatus.ENVIADO
                log.sent_at = now
                log.next_retry_at = None
                log.error_message = None
            elif log.retry_count >= int(settings.NOTIFICATION_MAX_RETRIES):
                log.status = OmnichannelStatus.FALLIDO
                log.next_retry_at = None
            else:
                log.retry_count += 1
                log.next_retry_at = compute_next_retry_at(log.retry_count)
            processed += 1
        if processed:
            await self.db.commit()
        return processed

    async def purge_old_logs(self) -> int:
        """Retención NOTIFICATION_RETENTION_DAYS (default 30)."""
        from sqlalchemy import delete

        cutoff = utc_now_naive() - timedelta(
            days=int(settings.NOTIFICATION_RETENTION_DAYS)
        )
        result = await self.db.execute(
            delete(NotificationLog).where(NotificationLog.created_at < cutoff)
        )
        await self.db.commit()
        n = result.rowcount or 0
        if n:
            logger.info(
                "purge_old_logs: %d logs >%d días eliminados",
                n,
                settings.NOTIFICATION_RETENTION_DAYS,
            )
        return n


def template_code_safe(template: Optional[NotificationTemplate]) -> str:
    return getattr(template, "code", "notificacion") if template else "notificacion"


# Singleton ligero por-request (se instancia con la session de request)
def get_omnichannel_service(db: AsyncSession) -> OmnichannelNotificationService:
    return OmnichannelNotificationService(db)
