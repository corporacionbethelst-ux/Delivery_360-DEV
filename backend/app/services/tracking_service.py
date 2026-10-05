"""
Delivery360 - Fase 8: Tracking en tiempo real.

Servicio responsable de:
    1. Ingesta de posiciones GPS de repartidores (persistencia + broadcast).
    2. Broadcast vía Redis Pub/Sub hacia los suscriptores WebSocket (ConnectionManager).
    3. Consultas geográficas de riders activos por bounding box (fallback B-tree,
       compatible con entornos sin PostGIS).
    4. Cálculo de ETA dinámico (Haversine local como base; Google Distance Matrix
       opcional si GOOGLE_MAPS_API_KEY está configurada).

Diseño anti MissingGreenlet/Async: todas las relaciones se cargan con selectinload
y no se accede a lazy-loads fuera del await.
"""
from __future__ import annotations

import json
import logging
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.location import RiderLiveLocation, DeliveryRouteSnapshot
from app.models.rider import Rider
from app.models.delivery import Delivery

logger = logging.getLogger(__name__)

# Intento de usar redis-py async NATIVO (redis>=5). aioredis está deprecado y NO se usa.
try:  # pragma: no cover - dependencia de entorno
    from redis import asyncio as aioredis  # redis>=5.0: módulo oficial async
except ImportError:  # pragma: no cover
    aioredis = None


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distancia ortodrómica aproximada entre dos puntos en kilómetros."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)), 4)


class TrackingService:
    """Servicio de tracking en tiempo real (ingesta + broadcast + consultas espaciales)."""

    def __init__(self, db: AsyncSession, redis_client=None):
        self.db = db
        self.redis = redis_client
        self.channel_prefix = getattr(
            settings, "REDIS_PUBSUB_CHANNEL_PREFIX", "rider_location_updates"
        )

    # ------------------------------------------------------------------
    # 1) Ingesta + broadcast
    # ------------------------------------------------------------------
    async def record_location_update(
        self,
        rider_id: uuid.UUID,
        lat: float,
        lng: float,
        accuracy_meters: Optional[float] = None,
        speed_kmh: Optional[float] = None,
        heading_degrees: Optional[float] = None,
    ) -> RiderLiveLocation:
        """Persiste la posición y dispara el broadcast en tiempo real."""
        location = RiderLiveLocation(
            rider_id=rider_id,
            latitude=lat,
            longitude=lng,
            accuracy_meters=accuracy_meters,
            speed_kmh=speed_kmh,
            heading_degrees=heading_degrees,
            recorded_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        self.db.add(location)

        # Actualizar snapshot "última posición" en riders (columnas planas, sin PostGIS obligatorio)
        result = await self.db.execute(select(Rider).where(Rider.id == rider_id))
        rider = result.scalar_one_or_none()
        if rider is not None:
            rider.last_lat = lat
            rider.last_lng = lng
            rider.last_location_at = location.recorded_at
            rider.is_online = True

        await self.db.commit()
        await self.db.refresh(location)

        await self.broadcast_location_update(rider_id, lat, lng, location.recorded_at)
        return location

    async def broadcast_location_update(
        self,
        rider_id: uuid.UUID,
        lat: float,
        lng: float,
        timestamp: datetime,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Publica la posición en Redis Pub/Sub para fan-out multi-worker."""
        payload = {
            "type": "POSITION_UPDATE",
            "payload": {
                "riderId": str(rider_id),
                "lat": lat,
                "lng": lng,
                "timestamp": timestamp.isoformat(),
                **(extra or {}),
            },
        }
        channel = f"{self.channel_prefix}:rider:{rider_id}"
        if self.redis is not None:
            try:
                await self.redis.publish(channel, json.dumps(payload))
                # Canal global para el dashboard de managers
                await self.redis.publish(
                    f"{self.channel_prefix}:dashboard", json.dumps(payload)
                )
            except Exception as exc:  # pragma: no cover - fallo de infra no debe tumbar ingesta
                logger.warning("Redis publish falló (%s). Broadcast degradado a WS local.", exc)

    # ------------------------------------------------------------------
    # 2) Consultas geográficas
    # ------------------------------------------------------------------
    async def get_active_riders_in_zone(
        self,
        min_lat: float,
        max_lat: float,
        min_lng: float,
        max_lng: float,
        stale_minutes: int = 5,
    ) -> List[Rider]:
        """Riders online cuya última posición cae dentro del bounding box.

        Usa bounding box SQL plano (compatible sin PostGIS). Con PostGIS disponible
        puede promoverse a ST_Contains con el índice GiST creado en la migración 20260901.
        """
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=stale_minutes)
        query = (
            select(Rider)
            .options(selectinload(Rider.user))  # selectinload => evita MissingGreenlet en async
            .where(
                and_(
                    Rider.is_online.is_(True),
                    Rider.last_location_at >= cutoff,
                    Rider.last_lat.isnot(None),
                    Rider.last_lng.isnot(None),
                    Rider.last_lat >= min_lat,
                    Rider.last_lat <= max_lat,
                    Rider.last_lng >= min_lng,
                    Rider.last_lng <= max_lng,
                )
            )
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_latest_positions(self, rider_ids: Optional[List[uuid.UUID]] = None) -> List[Dict[str, Any]]:
        """Últimas N posiciones registradas (para hidratación inicial del mapa)."""
        query = select(RiderLiveLocation).order_by(RiderLiveLocation.recorded_at.desc()).limit(500)
        if rider_ids:
            query = query.where(RiderLiveLocation.rider_id.in_(rider_ids))
        result = await self.db.execute(query)
        rows = result.scalars().all()

        # Deduplicar: solo la posición más reciente por rider
        seen: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            key = str(row.rider_id)
            if key not in seen:
                seen[key] = {
                    "riderId": key,
                    "lat": row.latitude,
                    "lng": row.longitude,
                    "speedKmh": row.speed_kmh,
                    "headingDegrees": row.heading_degrees,
                    "accuracyMeters": row.accuracy_meters,
                    "timestamp": row.recorded_at.isoformat() if row.recorded_at else None,
                }
        return list(seen.values())

    # ------------------------------------------------------------------
    # 3) ETA dinámico
    # ------------------------------------------------------------------
    async def calculate_eta(self, delivery_id: uuid.UUID, current_lat: float, current_lng: float) -> int:
        """ETA en minutos hacia el punto de entrega.

        Base: Haversine local / velocidad promedio configurable (cero costo API).
        Mejora opcional: Google Distance Matrix si settings.GOOGLE_MAPS_API_KEY existe.
        Coordenadas de destino: Order.delivery_latitude/delivery_longitude (esquema real).
        """
        result = await self.db.execute(
            select(Delivery).options(selectinload(Delivery.order)).where(Delivery.id == delivery_id)
        )
        delivery = result.scalar_one_or_none()
        if delivery is None:
            raise ValueError(f"Delivery {delivery_id} no encontrada")

        order = getattr(delivery, "order", None)
        dest_lat = getattr(order, "delivery_latitude", None) if order else None
        dest_lng = getattr(order, "delivery_longitude", None) if order else None
        # Fallbacks defensivos por si la entrega ya trae coordenadas propias
        dest_lat = dest_lat or getattr(delivery, "current_latitude", None)
        dest_lng = dest_lng or getattr(delivery, "current_longitude", None)
        if dest_lat is None or dest_lng is None:
            raise ValueError("La entrega no tiene coordenadas de destino")

        distance_km = haversine_km(current_lat, current_lng, float(dest_lat), float(dest_lng))
        speed = float(getattr(settings, "AVG_RIDER_SPEED_KMH", 18.0)) or 18.0
        eta_minutes = int(math.ceil((distance_km / speed) * 60))

        # Capa opcional Google (no bloqueante-fatal: si falla se conserva el ETA local)
        api_key = getattr(settings, "GOOGLE_MAPS_API_KEY", None)
        if api_key:
            try:
                eta_minutes = await self._google_distance_matrix_eta(
                    api_key, current_lat, current_lng, float(dest_lat), float(dest_lng)
                ) or eta_minutes
            except Exception as exc:  # pragma: no cover
                logger.debug("Distance Matrix no disponible (%s). Usando ETA local.", exc)

        return max(1, eta_minutes)

    async def _google_distance_matrix_eta(
        self, api_key: str, origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float
    ) -> Optional[int]:
        """Consulta ligera a Distance Matrix (solo si hay SDK/red disponibles)."""
        try:
            import googlemaps  # import perezoso: la librería es opcional
        except ImportError:
            return None
        gmaps = googlemaps.Client(key=api_key)
        resp = gmaps.distance_matrix(
            origins=(origin_lat, origin_lng),
            destinations=(dest_lat, dest_lng),
            mode="driving",
            departure_time="now",
        )
        elements = resp.get("rows", [{}])[0].get("elements", [])
        if elements and elements[0].get("status") == "OK":
            seconds = elements[0].get("duration_in_traffic", {}).get("value") or elements[0]["duration"]["value"]
            return int(math.ceil(seconds / 60))
        return None

    # ------------------------------------------------------------------
    # 4) Retención de datos (job periódico)
    # ------------------------------------------------------------------
    async def purge_expired_locations(self) -> int:
        """Elimina posiciones más antiguas que LIVE_LOCATION_RETENTION_DAYS."""
        days = int(getattr(settings, "LIVE_LOCATION_RETENTION_DAYS", 7))
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        stmt = delete(RiderLiveLocation).where(RiderLiveLocation.recorded_at < cutoff)
        result = await self.db.execute(stmt)
        await self.db.commit()
        deleted = result.rowcount or 0
        if deleted:
            logger.info("Retención Fase 8: %s posiciones > %d días eliminadas.", deleted, days)
        return deleted


async def build_redis_client():
    """Crea el cliente async de Redis (redis-py>=5 nativo). Devuelve None si no está disponible."""
    if aioredis is None:
        logger.warning("redis-py async no instalado; broadcast Pub/Sub deshabilitado.")
        return None
    try:
        client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_keepalive=True,
        )
        await client.ping()
        return client
    except Exception as exc:
        logger.warning("Redis no disponible (%s). Tracking funcionará en modo WS-local.", exc)
        return None
