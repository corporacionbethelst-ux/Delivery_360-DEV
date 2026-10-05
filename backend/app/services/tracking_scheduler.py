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
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        if self._task_optimize is not None:
            return  # ya iniciado
        self._stopping.clear()
        self._task_optimize = asyncio.create_task(self._optimize_loop(), name="fase8-optimize-loop")
        self._task_purge = asyncio.create_task(self._purge_loop(), name="fase8-purge-loop")
        logger.info("Fase 8 scheduler iniciado (optimización + purga de ubicaciones)")

    async def shutdown(self) -> None:
        self._stopping.set()
        for task in (self._task_optimize, self._task_purge):
            if task:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._task_optimize = self._task_purge = None
        logger.info("Fase 8 scheduler detenido")

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
                logger.warning("Scheduler VRP falló este ciclo (se reintentará): %s", exc)

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
                        logger.info("Scheduler retención: %d ubicaciones >%d días purgadas",
                                    deleted, getattr(settings, "LIVE_LOCATION_RETENTION_DAYS", 7))
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning("Scheduler de purga falló este ciclo: %s", exc)


# Singleton usado por main.py lifespan
tracking_scheduler = TrackingScheduler()
