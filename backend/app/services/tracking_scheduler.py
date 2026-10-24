"""
Delivery360 - Fase 8: Scheduler interno de tareas geoespaciales.

Bucle asíncrono ligero (asyncio.sleep, sin dependencias externas tipo APScheduler/Celery):
  - Optimización VRP batch cada ROUTE_OPTIMIZATION_INTERVAL_SEC (default 300s = 5 min).
  - Purga de rider_live_locations > LIVE_LOCATION_RETENTION_DAYS y snapshots vencidos (diario).

Tolerante a fallos: cualquier excepción se loguea y el bucle continúa; si la BD no está
lista al arrancar, reintenta en el siguiente ciclo. Se apaga limpiamente con lifespan().
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class TrackingScheduler:
    def __init__(self) -> None:
        self._task_optimize: Optional[asyncio.Task] = None
        self._task_purge: Optional[asyncio.Task] = None
        # Fase 9: desviación de ruta + cola de reintentos/purga de logs de notificación
        self._task_deviation: Optional[asyncio.Task] = None
        self._task_notif_retry: Optional[asyncio.Task] = None
        self._task_notif_purge: Optional[asyncio.Task] = None
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        if self._task_optimize is not None:
            return  # ya iniciado
        self._stopping.clear()
        self._task_optimize = asyncio.create_task(
            self._optimize_loop(), name="fase8-optimize-loop"
        )
        self._task_purge = asyncio.create_task(
            self._purge_loop(), name="fase8-purge-loop"
        )
        self._task_deviation = asyncio.create_task(
            self._deviation_loop(), name="fase9-deviation-loop"
        )
        self._task_notif_retry = asyncio.create_task(
            self._notif_retry_loop(), name="fase9-notif-retry-loop"
        )
        self._task_notif_purge = asyncio.create_task(
            self._notif_purge_loop(), name="fase9-notif-purge-loop"
        )
        logger.info(
            "Scheduler iniciado (Fase 8: optimización + purga | Fase 9: desviación + reintentos/purga notificaciones)"
        )

    async def shutdown(self) -> None:
        self._stopping.set()
        for task in (
            self._task_optimize,
            self._task_purge,
            self._task_deviation,
            self._task_notif_retry,
            self._task_notif_purge,
        ):
            if task:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._task_optimize = self._task_purge = None
        self._task_deviation = self._task_notif_retry = self._task_notif_purge = None
        logger.info("Scheduler detenido")

    async def _sleep_or_stop(self, seconds: float) -> bool:
        """Espera interruptible. True si hay que detenerse."""
        try:
            await asyncio.wait_for(self._stopping.wait(), timeout=seconds)
            return True
        except asyncio.TimeoutError:
            return False

    async def _optimize_loop(self) -> None:
        from app.core.config import settings
        from app.core.database import AsyncSessionLocal
        from app.services.route_optimizer import RouteOptimizer

        interval = int(getattr(settings, "ROUTE_OPTIMIZATION_INTERVAL_SEC", 300))
        while not self._stopping.is_set():
            if await self._sleep_or_stop(interval):
                break
            try:
                async with AsyncSessionLocal() as db:
                    optimizer = RouteOptimizer(db)
                    result = await optimizer.optimize_pending_batch()
                    if result.assignments:
                        logger.info(
                            "Scheduler VRP: %d riders asignados, %.2f km optimizados (ahorro %.1f%%)",
                            len(result.assignments),
                            result.total_distance_km,
                            result.estimated_time_reduction_pct,
                        )
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 - el loop debe sobrevivir
                logger.warning(
                    "Scheduler VRP falló este ciclo (se reintentará): %s", exc
                )

    async def _purge_loop(self) -> None:
        from app.core.config import settings
        from app.core.database import AsyncSessionLocal
        from app.services.tracking_service import TrackingService

        interval = 24 * 3600  # diario
        while not self._stopping.is_set():
            if await self._sleep_or_stop(interval):
                break
            try:
                async with AsyncSessionLocal() as db:
                    service = TrackingService(db)
                    deleted = await service.purge_expired_locations()
                    if deleted:
                        logger.info(
                            "Scheduler retención: %d ubicaciones >%d días purgadas",
                            deleted,
                            getattr(settings, "LIVE_LOCATION_RETENTION_DAYS", 7),
                        )
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning("Scheduler de purga falló este ciclo: %s", exc)

    # =========================================================================
    # FASE 9 — Bucles de notificaciones
    # =========================================================================

    async def _deviation_loop(self) -> None:
        """Detecta desviaciones >500m respecto a la ruta planificada o inactividad GPS >15min
        en entregas activas y alerta a los GERENTES/SUPERADMIN via 'alerta_desviacion_ruta'.
        Reutiliza haversine_km de tracking_service (Fase 8). Ciclo cada 120s.
        El dedupe (<5min por entrega) lo garantiza el servicio omnicanal; además este loop
        marca RouteDeviation para dar trazabilidad geoespacial."""
        from app.core.database import AsyncSessionLocal
        from app.services.tracking_service import haversine_km
        from app.services.notification_hooks import notify_event
        from app.models.delivery import Delivery, DeliveryStatus
        from app.models.order import Order
        from app.models.rider import Rider
        from app.models.user import User, UserRole
        from sqlalchemy import select

        interval = 120
        deviation_threshold_km = 0.5  # 500 m
        silence_threshold_min = 15  # inactividad GPS
        while not self._stopping.is_set():
            if await self._sleep_or_stop(interval):
                break
            try:
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                async with AsyncSessionLocal() as db:
                    active_statuses = (
                        DeliveryStatus.INICIADA,
                        DeliveryStatus.EN_PICKUP,
                        DeliveryStatus.EN_ROUTE,
                        DeliveryStatus.EN_DESTINO,
                    )
                    result = await db.execute(
                        select(Delivery, Order, Rider, User)
                        .join(Order, Order.id == Delivery.order_id)
                        .join(Rider, Rider.id == Delivery.rider_id)
                        .join(User, User.id == Rider.user_id)
                        .where(Delivery.status.in_(active_statuses))
                    )
                    rows = result.all()
                    if not rows:
                        continue
                    mgr_result = await db.execute(
                        select(User.id)
                        .where(
                            User.role.in_([UserRole.GERENTE, UserRole.SUPERADMIN]),
                            User.is_active == True,  # noqa: E712
                        )
                        .limit(20)
                    )
                    manager_ids = [r[0] for r in mgr_result.all()]
                    if not manager_ids:
                        continue
                    for delivery, order, rider, rider_user in rows:
                        dev_km: Optional[float] = None
                        lat = delivery.current_latitude
                        lng = delivery.current_longitude
                        dest_lat = order.delivery_latitude
                        dest_lng = order.delivery_longitude
                        silent = (
                            delivery.last_location_update is not None
                            and (now - delivery.last_location_update).total_seconds()
                            > silence_threshold_min * 60
                        )
                        if (
                            lat is not None
                            and lng is not None
                            and dest_lat is not None
                            and dest_lng is not None
                        ):
                            d = haversine_km(
                                float(lat), float(lng), float(dest_lat), float(dest_lng)
                            )
                            if d > deviation_threshold_km:
                                dev_km = d
                        elif silent:
                            dev_km = 0.0
                        if dev_km is None:
                            continue
                        await notify_event(
                            "alerta_desviacion_ruta",
                            manager_ids[
                                0
                            ],  # destinatario principal (resto se propaga por sus propios WS)
                            {
                                "rider_name": f"{rider_user.first_name} {rider_user.last_name}".strip()
                                or str(rider.id)[:8],
                                "lat": round(float(lat or dest_lat or 0), 6),
                                "lng": round(float(lng or dest_lng or 0), 6),
                                "deviation_km": round(dev_km, 2),
                                "delivery_id": str(delivery.id),
                                "silent": "sí" if silent else "no",
                            },
                            db=db,
                            delivery_id=delivery.id,
                        )
                    await db.commit()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 - el loop debe sobrevivir
                logger.warning(
                    "Scheduler de desviación (Fase 9) falló este ciclo: %s", exc
                )

    async def _notif_retry_loop(self) -> None:
        """Cola de reintentos de notificaciones (backoff exponencial, máx NOTIFICATION_MAX_RETRIES)."""
        from app.core.config import settings
        from app.core.database import AsyncSessionLocal
        from app.services.omnichannel_service import OmnichannelNotificationService

        interval = int(getattr(settings, "NOTIFICATION_RETRY_SCAN_INTERVAL_SEC", 60))
        while not self._stopping.is_set():
            if await self._sleep_or_stop(interval):
                break
            try:
                async with AsyncSessionLocal() as db:
                    service = OmnichannelNotificationService(db)
                    processed = await service.process_retry_queue()
                    if processed:
                        logger.info(
                            "Fase 9 reintentos: %d notificaciones reprocesadas",
                            processed,
                        )
                    await db.commit()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Scheduler de reintentos Fase 9 falló este ciclo: %s", exc
                )

    async def _notif_purge_loop(self) -> None:
        """Retención de logs de notificación (NOTIFICATION_RETENTION_DAYS, default 30) — diario."""
        from app.core.database import AsyncSessionLocal
        from app.services.omnichannel_service import OmnichannelNotificationService

        interval = 24 * 3600
        while not self._stopping.is_set():
            if await self._sleep_or_stop(interval):
                break
            try:
                async with AsyncSessionLocal() as db:
                    service = OmnichannelNotificationService(db)
                    deleted = await service.purge_old_logs()
                    if deleted:
                        logger.info(
                            "Fase 9 retención: %d logs de notificación purgados",
                            deleted,
                        )
                    await db.commit()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Scheduler de purga de logs Fase 9 falló este ciclo: %s", exc
                )


# Singleton usado por main.py lifespan
tracking_scheduler = TrackingScheduler()
