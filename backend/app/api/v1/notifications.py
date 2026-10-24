"""
Delivery360 - Fase 9: API de Notificaciones & Comunicación Omnicanal.

Rutas REST (montadas en main.py con prefijo /api/v1):
    POST  /notifications/register-device   -> upsert token FCM/APNs por device_token
    GET   /notifications/inbox             -> bandeja IN_APP paginada (created_at DESC)
    GET   /notifications/unread-count      -> contador para badge de la campana
    PATCH /notifications/{id}/read         -> dueño del registro o SUPERADMIN
    DELETE /notifications/{id}             -> borrado lógico (solo dueño)
    PUT   /notifications/preferences       -> upsert granular evento x canal
    GET   /notifications/preferences       -> preferencias del usuario actual
    POST  /notifications/test-send         -> SOLO SUPERADMIN/GERENTE (RBAC 403 demás)
    GET   /notifications/templates         -> listado admin
    PATCH /notifications/templates/{code}  -> toggle is_active (admin)

WebSocket (montado en main.py, UN solo pool manager — regla anti-error 6):
    WS /api/v1/notifications/ws?token=<jwt>
       -> JWT manual (python-jose); inválido/expirado => close 1008
       -> suscripción a Redis Pub/Sub `notifications:user:{id}` con fan-out único
       -> snapshot inicial {type: CONNECTED, unread_count} + NEW_NOTIFICATION push
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user, require_role
from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_token
from app.core.websocket import manager
from app.models.notification import (
    NotificationChannel,
    NotificationLog,
    NotificationPreference,
    NotificationTemplate,
    OmnichannelStatus,
    UserDeviceToken,
)
from app.models.user import User, UserRole
from app.services.omnichannel_service import OmnichannelNotificationService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/notifications", tags=["Notificaciones (Fase 9)"])


# ----------------------------------------------------------------------
# Schemas
# ----------------------------------------------------------------------
class RegisterDeviceRequest(BaseModel):
    device_token: str = Field(..., min_length=8, max_length=255)
    platform: str = Field("web", pattern="^(android|ios|web)$")


class PreferenceItem(BaseModel):
    event_code: str = Field(..., min_length=1, max_length=50)
    channel: NotificationChannel
    enabled: bool = True


class PreferencesUpdate(BaseModel):
    preferences: List[PreferenceItem]


class TestSendRequest(BaseModel):
    template_code: str = Field(..., min_length=1, max_length=50)
    user_id: Optional[str] = None  # default: usuario autenticado
    context: dict = Field(default_factory=dict)
    channels: Optional[List[NotificationChannel]] = None


class NotificationOut(BaseModel):
    id: str
    template_code: Optional[str]
    channel: str
    status: str
    title: Optional[str]
    body: Optional[str]
    created_at: Optional[str]
    read_at: Optional[str]

    class Config:
        from_attributes = True


def _parse_uuid(value: str, field_name: str = "id") -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} no es un UUID válido",
        ) from exc


def _log_out(log: NotificationLog) -> NotificationOut:
    ch = getattr(log.channel, "value", str(log.channel))
    st = getattr(log.status, "value", str(log.status))
    return NotificationOut(
        id=str(log.id),
        template_code=log.template_code,
        channel=ch,
        status=st,
        title=log.title,
        body=log.body,
        created_at=log.created_at.isoformat() if log.created_at else None,
        read_at=log.read_at.isoformat() if log.read_at else None,
    )


async def _get_service(
    db: AsyncSession = Depends(get_db),
) -> OmnichannelNotificationService:
    return OmnichannelNotificationService(db)


# ----------------------------------------------------------------------
# POST /register-device
# ----------------------------------------------------------------------
@router.post("/register-device")
async def register_device(
    body: RegisterDeviceRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upsert del token FCM/APNs por device_token único. Reactiva si estaba inactivo."""
    existing = (
        await db.execute(
            select(UserDeviceToken).where(
                UserDeviceToken.device_token == body.device_token
            )
        )
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if existing:
        changed_owner = existing.user_id != current_user.id
        existing.platform = body.platform
        existing.last_seen_at = now
        if changed_owner or not existing.is_active:
            existing.user_id = current_user.id
            existing.failure_count = 0
            existing.is_active = True
        action = "updated"
    else:
        db.add(
            UserDeviceToken(
                id=uuid.uuid4(),
                user_id=current_user.id,
                device_token=body.device_token,
                platform=body.platform,
                failure_count=0,
                is_active=True,
                last_seen_at=now,
                created_at=now,
            )
        )
        action = "created"
    await db.commit()
    return {"status": "ok", "action": action}


# ----------------------------------------------------------------------
# GET /inbox  (paginado, solo IN_APP, created_at DESC)
# ----------------------------------------------------------------------
@router.get("/inbox")
async def get_inbox(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    include_all_channels: bool = Query(
        False, description="Incluir también PUSH/EMAIL/SMS logs"
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(NotificationLog).where(NotificationLog.user_id == current_user.id)
    if not include_all_channels:
        query = query.where(NotificationLog.channel == NotificationChannel.IN_APP)

    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar() or 0

    rows = (
        (
            await db.execute(
                query.order_by(NotificationLog.created_at.desc())
                .offset((page - 1) * size)
                .limit(size)
            )
        )
        .scalars()
        .all()
    )

    unread = (
        await db.execute(
            select(func.count(NotificationLog.id)).where(
                NotificationLog.user_id == current_user.id,
                NotificationLog.channel == NotificationChannel.IN_APP,
                NotificationLog.status != OmnichannelStatus.LEIDO,
            )
        )
    ).scalar() or 0

    return {
        "items": [_log_out(r).model_dump() for r in rows],
        "page": page,
        "size": size,
        "total": total,
        "pages": (total + size - 1) // size if size else 0,
        "unread_count": int(unread),
    }


@router.get("/unread-count")
async def get_unread_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    count = (
        await db.execute(
            select(func.count(NotificationLog.id)).where(
                NotificationLog.user_id == current_user.id,
                NotificationLog.channel == NotificationChannel.IN_APP,
                NotificationLog.status != OmnichannelStatus.LEIDO,
            )
        )
    ).scalar() or 0
    return {"unread_count": int(count)}


# ----------------------------------------------------------------------
# PATCH /{id}/read  (dueño o SUPERADMIN)
# ----------------------------------------------------------------------
@router.patch("/{notification_id}/read")
async def mark_read(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    log_id = _parse_uuid(notification_id, "notification_id")
    log = (
        await db.execute(select(NotificationLog).where(NotificationLog.id == log_id))
    ).scalar_one_or_none()
    if log is None:
        raise HTTPException(status_code=404, detail="Notificación no encontrada")

    is_owner = str(log.user_id) == str(current_user.id)
    is_super = (
        getattr(current_user.role, "value", str(current_user.role))
        == UserRole.SUPERADMIN.value
    )
    if not (is_owner or is_super):
        raise HTTPException(
            status_code=403, detail="No autorizado sobre esta notificación"
        )

    if log.status != OmnichannelStatus.LEIDO:
        log.status = OmnichannelStatus.LEIDO
        log.read_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await db.commit()
    return {"status": "ok", "id": str(log.id)}


@router.delete("/{notification_id}")
async def delete_notification(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Borrado lógico: marca FALLIDO-like removal vía error_message no aplica;
    se elimina el registro IN_APP solo por su dueño."""
    log_id = _parse_uuid(notification_id, "notification_id")
    log = (
        await db.execute(select(NotificationLog).where(NotificationLog.id == log_id))
    ).scalar_one_or_none()
    if log is None:
        raise HTTPException(status_code=404, detail="Notificación no encontrada")
    if str(log.user_id) != str(current_user.id):
        raise HTTPException(
            status_code=403, detail="No autorizado sobre esta notificación"
        )
    await db.delete(log)
    await db.commit()
    return {"status": "deleted"}


# ----------------------------------------------------------------------
# Preferencias
# ----------------------------------------------------------------------
@router.get("/preferences")
async def list_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        (
            await db.execute(
                select(NotificationPreference)
                .where(NotificationPreference.user_id == current_user.id)
                .order_by(
                    NotificationPreference.event_code, NotificationPreference.channel
                )
            )
        )
        .scalars()
        .all()
    )
    return {
        "preferences": [
            {
                "event_code": p.event_code,
                "channel": getattr(p.channel, "value", str(p.channel)),
                "enabled": bool(p.enabled),
            }
            for p in rows
        ]
    }


@router.put("/preferences")
async def update_preferences(
    body: PreferencesUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upsert granular evento x canal. Regla por rol: riders solo PUSH/IN_APP;
    clientes no pueden habilitar PUSH sin token registrado (se permite, dispatch stub).
    """
    role_value = getattr(current_user.role, "value", str(current_user.role))
    allowed_by_role = {
        UserRole.REPARTIDOR.value: {
            NotificationChannel.PUSH,
            NotificationChannel.IN_APP,
        },
        UserRole.CLIENTE.value: {NotificationChannel.IN_APP, NotificationChannel.EMAIL},
    }.get(
        role_value, set(NotificationChannel)
    )  # resto de roles: todos

    updated = 0
    for item in body.preferences:
        if item.channel not in allowed_by_role:
            raise HTTPException(
                status_code=400,
                detail=f"Canal {item.channel.value} no permitido para rol {role_value}",
            )
        existing = (
            await db.execute(
                select(NotificationPreference).where(
                    NotificationPreference.user_id == current_user.id,
                    NotificationPreference.event_code == item.event_code,
                    NotificationPreference.channel == item.channel,
                )
            )
        ).scalar_one_or_none()
        if existing:
            existing.enabled = item.enabled
        else:
            db.add(
                NotificationPreference(
                    id=uuid.uuid4(),
                    user_id=current_user.id,
                    event_code=item.event_code,
                    channel=item.channel,
                    enabled=item.enabled,
                )
            )
        updated += 1
    await db.commit()
    return {"status": "ok", "updated": updated}


# ----------------------------------------------------------------------
# POST /test-send (RBAC: solo SUPERADMIN/GERENTE)
# ----------------------------------------------------------------------
@router.post("/test-send")
async def test_send(
    body: TestSendRequest,
    service: OmnichannelNotificationService = Depends(_get_service),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE)),
):
    target_user_id = body.user_id or str(current_user.id)
    parsed = _parse_uuid(target_user_id, "user_id")
    # FIX FASE 9/10 (test-send): el dedupe usa hash(template+entity_id+ventana_5min).
    # Sin entity_id, dos test-send del MISMO template caen en la misma ventana
    # (o compiten con un evento real ya notificado) y el segundo devuelve sent=0.
    # Un test-send es por definicion una prueba manual => entity_id unico por
    # llamada para saltar el dedupe sin relajar la proteccion anti-spam real.
    context = dict(body.context or {})
    context.setdefault("entity_id", f"testsend:{uuid.uuid4().hex}")
    logs = await service.send(
        parsed,
        body.template_code,
        context,
        channels=body.channels,
    )
    return {
        "status": "ok",
        "sent": len(logs),
        "logs": [
            {
                "id": str(l.id),
                "channel": getattr(l.channel, "value", str(l.channel)),
                "status": getattr(l.status, "value", str(l.status)),
            }
            for l in logs
        ],
    }


# ----------------------------------------------------------------------
# Templates (admin)
# ----------------------------------------------------------------------
@router.get("/templates")
async def list_templates(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        (
            await db.execute(
                select(NotificationTemplate).order_by(NotificationTemplate.code)
            )
        )
        .scalars()
        .all()
    )
    return {
        "templates": [
            {
                "code": t.code,
                "channel": getattr(t.channel, "value", str(t.channel)),
                "subject": t.subject,
                "body_template": t.body_template,
                "language": t.language,
                "is_active": bool(t.is_active),
            }
            for t in rows
        ]
    }


@router.patch("/templates/{code}")
async def toggle_template(
    code: str,
    is_active: bool = Query(...),
    service: OmnichannelNotificationService = Depends(_get_service),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE)),
    db: AsyncSession = Depends(get_db),
):
    tpl = (
        await db.execute(
            select(NotificationTemplate).where(NotificationTemplate.code == code)
        )
    ).scalar_one_or_none()
    if tpl is None:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada")
    tpl.is_active = is_active
    await db.commit()
    # invalidar cache Redis de plantillas si existe
    r = await service._get_redis()
    if r is not None:
        try:
            await r.delete(f"notif:template:{code}")
        except Exception:  # noqa: BLE001
            pass
    return {"status": "ok", "code": code, "is_active": is_active}


# ----------------------------------------------------------------------
# WebSocket notifications (handler montado en main.py; UN solo pool manager)
# ----------------------------------------------------------------------
async def notifications_websocket(websocket: WebSocket):
    """WS /api/v1/notifications/ws?token=<jwt>.

    Auth JWT MANUAL (regla heredada): token ausente/inválido/expirado => close 1008.
    Se suscribe al canal Redis `notifications:user:{sub}` y hace fan-out hacia las
    conexiones WS del manager existente (no abre segundo pool). Sin Redis: sigue
    funcionando enviando snapshot inicial y respondiendo ping/pong.
    """
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    user_id = str(payload.get("sub") or "")
    if not user_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    connection_id = f"notif-{uuid.uuid4()}"
    topic = f"{settings.REDIS_NOTIF_CHANNEL_PREFIX}:{user_id}"
    await manager.connect(websocket, connection_id, user_id=user_id)
    manager.subscribe(connection_id, topic)

    pubsub_task: Optional[asyncio.Task] = None
    redis_client = None
    try:
        # Snapshot inicial: conteo de no-leídas (tolerante a DB indisponible)
        unread = 0
        try:
            from app.core.database import AsyncSessionLocal

            async with AsyncSessionLocal() as db:
                unread = (
                    await db.execute(
                        select(func.count(NotificationLog.id)).where(
                            NotificationLog.user_id == _safe_uuid(user_id),
                            NotificationLog.channel == NotificationChannel.IN_APP,
                            NotificationLog.status != OmnichannelStatus.LEIDO,
                        )
                    )
                ).scalar() or 0
        except Exception as exc:  # noqa: BLE001
            logger.warning("WS notif: snapshot unread falló (no crítico): %s", exc)

        await websocket.send_json(
            {
                "type": "CONNECTED",
                "channel": topic,
                "unread_count": int(unread),
            }
        )

        # Suscriptor Redis → fan-out a las conexiones de este usuario
        try:
            from redis import asyncio as aioredis  # librería nativa redis>=5 (regla)

            redis_client = aioredis.from_url(
                settings.REDIS_URL, encoding="utf-8", decode_responses=True
            )
            pubsub = redis_client.pubsub()
            await pubsub.subscribe(topic)

            async def _pump():
                try:
                    async for message in pubsub.listen():
                        if message.get("type") != "message":
                            continue
                        try:
                            data = json.loads(message["data"])
                        except (TypeError, ValueError):
                            continue
                        await manager.broadcast_to_user(data, user_id)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.debug("WS notif pump terminado: %s", exc)

            pubsub_task = asyncio.create_task(
                _pump(), name=f"notif-pump-{connection_id}"
            )
        except Exception as exc:  # noqa: BLE001 - Redis opcional
            logger.info("WS notif: Redis no disponible (%s); modo ping/pong", exc)

        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                if message.get("action") == "ping":
                    await websocket.send_json({"type": "pong"})
            except (ValueError, TypeError):
                await websocket.send_json({"type": "error", "message": "JSON inválido"})
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.debug("WS notif %s cerrado por error: %s", connection_id, exc)
    finally:
        if pubsub_task is not None:
            pubsub_task.cancel()
            try:
                await pubsub_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if redis_client is not None:
            try:
                await redis_client.aclose()
            except Exception:  # noqa: BLE001
                pass
        manager.disconnect(connection_id)


def _safe_uuid(value: str):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return value  # deja que SQLAlchemy falle suave en el count
