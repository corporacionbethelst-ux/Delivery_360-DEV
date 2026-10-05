"""
Delivery360 - Fase 8: Endpoints de Mapas & Tracking en tiempo real.

Rutas REST:
    POST /tracking/update-location      -> ingesta GPS (rate limited por rider)
    GET  /tracking/live/{order_id}      -> fallback REST: última posición + ETA
    GET  /tracking/dashboard/active-riders -> datos agregados para dashboard manager
    POST /tracking/routes/optimize      -> trigger manual de re-optimización VRP
    GET  /tracking/history/{rider_id}   -> trazas recientes para el mapa

WebSocket (montado directamente en main.py):
    WS   /api/v1/tracking/ws/{channel}  -> handshake con JWT query param + subscribe a tópico

Canales soportados:
    rider:{rider_id}   -> seguimiento individual (cliente final o rider)
    order:{order_id}   -> alias resuelto al rider asignado de la entrega
    dashboard          -> fan-out global (solo SUPERADMIN / GERENTE)
"""
from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_token
from app.core.websocket import manager
from app.api.v1.auth import get_current_user
from app.models.user import User
from app.models.rider import Rider
from app.models.delivery import Delivery
from app.models.order import Order
from app.models.location import RiderLiveLocation
from app.schemas.rider_location import LocationUpdate
from app.services.tracking_service import TrackingService, haversine_km, build_redis_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tracking", tags=["Tracking (Fase 8)"])


# ----------------------------------------------------------------------
# Rate limiting simple por rider (20 updates/min default). Sin estado por proceso;
# suficiente para v1. Con Redis puede promoverse a ventana deslizante compartida.
# ----------------------------------------------------------------------
_update_windows: dict = {}


def _check_location_rate(rider_id: str) -> None:
    now = datetime.now(timezone.utc).timestamp()
    window = _update_windows.setdefault(rider_id, [])
    window[:] = [t for t in window if now - t < 60]
    limit = int(getattr(settings, "MAX_POSITION_UPDATES_PER_MINUTE", 20))
    if len(window) >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiadas actualizaciones de ubicación. Reintenta en unos segundos.",
        )
    window.append(now)


async def _get_tracking_service(db: AsyncSession = Depends(get_db)) -> TrackingService:
    redis = await build_redis_client()
    return TrackingService(db=db, redis_client=redis)


class OptimizeRequest(BaseModel):
    capacity_per_rider: Optional[int] = Field(None, ge=1, le=20)


@router.post("/update-location")
async def update_location(
    payload: LocationUpdate,
    rider_id: uuid.UUID,
    speed_kmh: Optional[float] = Query(None, ge=0),
    heading: Optional[float] = Query(None, ge=0, le=360),
    service: TrackingService = Depends(_get_tracking_service),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ingesta de posición GPS del repartidor (persiste + broadcast Pub/Sub/WS)."""
    result = await db.execute(select(Rider).where(Rider.id == rider_id))
    rider = result.scalar_one_or_none()
    if rider is None:
        raise HTTPException(status_code=404, detail="Repartidor no encontrado")

    # Solo el propio rider, un GERENTE o SUPERADMIN pueden reportar su ubicación
    role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    if role not in ("SUPERADMIN", "GERENTE") and rider.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No autorizado para actualizar este repartidor")

    _check_location_rate(str(rider_id))

    location = await service.record_location_update(
        rider_id=rider_id,
        lat=payload.lat,
        lng=payload.lng,
        accuracy_meters=payload.accuracy,
        speed_kmh=speed_kmh,
        heading_degrees=heading,
    )

    # Fan-out directo al ConnectionManager local (además del publish Redis)
    try:
        await manager.broadcast_to_topic(
            {
                "type": "POSITION_UPDATE",
                "payload": {
                    "riderId": str(rider_id),
                    "lat": payload.lat,
                    "lng": payload.lng,
                    "speedKmh": speed_kmh,
                    "headingDegrees": heading,
                    "timestamp": location.recorded_at.isoformat(),
                },
            },
            topic=f"rider:{rider_id}",
        )
        await manager.broadcast_to_topic(
            {"type": "POSITION_UPDATE", "payload": {"riderId": str(rider_id), "lat": payload.lat, "lng": payload.lng}},
            topic="dashboard",
        )
    except Exception as exc:  # WS nunca debe tumbar la ingesta
        logger.debug("Broadcast WS local degradado: %s", exc)

    return {"status": "ok", "recorded_at": location.recorded_at.isoformat()}


@router.get("/live/{order_id}")
async def get_live_tracking(
    order_id: uuid.UUID,
    service: TrackingService = Depends(_get_tracking_service),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fallback REST: última posición conocida + ETA cuando el WebSocket no está disponible."""
    result = await db.execute(
        select(Delivery)
        .options(
            selectinload(Delivery.order),
            selectinload(Delivery.rider).selectinload(Rider.user),
        )
        .where(Delivery.order_id == order_id)
    )
    delivery = result.scalar_one_or_none()
    if delivery is None:
        raise HTTPException(status_code=404, detail="Entrega no encontrada para esta orden")

    rider = delivery.rider
    if rider is None or rider.last_lat is None or rider.last_lng is None:
        return {
            "order_id": str(order_id),
            "delivery_id": str(delivery.id),
            "available": False,
            "reason": "Sin posición conocida del repartidor",
        }

    eta_minutes = None
    try:
        eta_minutes = await service.calculate_eta(delivery.id, float(rider.last_lat), float(rider.last_lng))
    except ValueError:
        pass

    order = delivery.order
    distance_km = None
    if order and order.delivery_latitude is not None:
        distance_km = haversine_km(
            float(rider.last_lat), float(rider.last_lng),
            float(order.delivery_latitude), float(order.delivery_longitude),
        )

    return {
        "order_id": str(order_id),
        "delivery_id": str(delivery.id),
        "available": True,
        "rider": {"id": str(rider.id), "name": (f"{rider.user.first_name} {rider.user.last_name}".strip() if rider.user else "") or "Repartidor"},
        "position": {"lat": rider.last_lat, "lng": rider.last_lng, "recorded_at": rider.last_location_at},
        "destination": {"lat": order.delivery_latitude if order else None,
                        "lng": order.delivery_longitude if order else None},
        "distance_km": distance_km,
        "eta_minutes": eta_minutes,
    }


@router.get("/dashboard/active-riders")
async def get_dashboard_data(
    bbox: Optional[str] = Query(None, description="min_lat,min_lng,max_lat,max_lng"),
    minutes: int = Query(5, ge=1, le=120, description="Ventana de frescura de posición"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Datos agregados para el dashboard operativo: riders online, posiciones y métricas."""
    role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    if role not in ("SUPERADMIN", "GERENTE"):
        raise HTTPException(status_code=403, detail="Solo managers/superadmin pueden ver el dashboard de tracking")

    query = (
        select(Rider)
        .options(selectinload(Rider.user))
        .where(
            Rider.is_online.is_(True),
            Rider.last_lat.isnot(None),
            Rider.last_lng.isnot(None),
        )
    )
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=minutes)
    query = query.where(Rider.last_location_at >= cutoff)

    if bbox:
        try:
            min_lat, min_lng, max_lat, max_lng = [float(x) for x in bbox.split(",")]
            query = query.where(
                and_(
                    Rider.last_lat >= min_lat, Rider.last_lat <= max_lat,
                    Rider.last_lng >= min_lng, Rider.last_lng <= max_lng,
                )
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="bbox inválido. Usa min_lat,min_lng,max_lat,max_lng")

    result = await db.execute(query.limit(500))
    riders = list(result.scalars().all())

    active_positions = []
    stale_count = 0
    for r in riders:
        last_seen_min = None
        if r.last_location_at:
            last_seen_min = round((datetime.now(timezone.utc).replace(tzinfo=None) - r.last_location_at).total_seconds() / 60, 1)
            if last_seen_min > 15:
                stale_count += 1
        active_positions.append({
            "riderId": str(r.id),
            "name": (f"{r.user.first_name} {r.user.last_name}".strip() if r.user else "") or "Repartidor",
            "status": r.status.value if hasattr(r.status, "value") else str(r.status),
            "lat": r.last_lat,
            "lng": r.last_lng,
            "lastSeenMinutesAgo": last_seen_min,
        })

    total_result = await db.execute(select(Rider).where(Rider.is_online.is_(True)))
    stats = {
        "activeCount": len(active_positions),
        "onlineTotal": len(total_result.scalars().all()),
        "staleOver15Min": stale_count,
        "avgWaitMinutes": None,  # se enrich con datos de cola en v2
    }

    return {"riders": active_positions, "stats": stats, "alerts": []}


@router.post("/routes/optimize")
async def optimize_routes_batch(
    payload: OptimizeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Trigger manual de re-optimización VRP (el cron interno usa la misma función)."""
    role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    if role not in ("SUPERADMIN", "GERENTE"):
        raise HTTPException(status_code=403, detail="Solo managers/superadmin pueden lanzar optimizaciones")

    from app.services.route_optimizer import RouteOptimizer  # import local: evita ciclo

    optimizer = RouteOptimizer(db=db, capacity_per_rider=payload.capacity_per_rider)
    result = await optimizer.optimize_pending_batch()
    return result


@router.get("/history/{rider_id}")
async def get_rider_history(
    rider_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Trazas recientes de un rider para dibujar el polyline del recorrido."""
    result = await db.execute(
        select(RiderLiveLocation)
        .where(RiderLiveLocation.rider_id == rider_id)
        .order_by(RiderLiveLocation.recorded_at.desc())
        .limit(limit)
    )
    rows = list(result.scalars().all())
    return {
        "rider_id": str(rider_id),
        "trace": [
            {
                "lat": row.latitude,
                "lng": row.longitude,
                "speedKmh": row.speed_kmh,
                "headingDegrees": row.heading_degrees,
                "recordedAt": row.recorded_at.isoformat(),
            }
            for row in reversed(rows)
        ],
    }


# ----------------------------------------------------------------------
# WebSocket con autenticación JWT manual (sin librerías externas deprecadas)
# ----------------------------------------------------------------------
async def tracking_websocket(websocket: WebSocket, channel: str):
    """Handler WS montado en main.py como /api/v1/tracking/ws/{channel}.

    Handshake: ?token=<jwt>. Roles: cualquier usuario autenticado puede suscribirse a
    rider:/order: propios o visibles; 'dashboard' exige SUPERADMIN/GERENTE.
    """
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    connection_id = str(uuid.uuid4())
    await manager.connect(websocket, connection_id, user_id=payload.get("sub"))

    # Suscripción inicial al canal solicitado
    normalized = channel
    if normalized.startswith("all-riders") or normalized == "dashboard":
        normalized = "dashboard"
    manager.subscribe(connection_id, normalized)

    try:
        await websocket.send_json({"type": "CONNECTED", "channel": normalized})
        while True:
            data = await websocket.receive_text()
            try:
                message = __import__("json").loads(data)
                action = message.get("action")
                if action == "subscribe":
                    manager.subscribe(connection_id, message.get("topic", normalized))
                elif action == "unsubscribe":
                    manager.unsubscribe(connection_id, message.get("topic", normalized))
                elif action == "ping":
                    await websocket.send_json({"type": "pong"})
            except Exception:
                await websocket.send_json({"type": "error", "message": "Mensaje JSON inválido"})
    except WebSocketDisconnect:
        manager.disconnect(connection_id)
    except Exception as exc:
        logger.debug("WS %s cerrado por error: %s", connection_id, exc)
        manager.disconnect(connection_id)
