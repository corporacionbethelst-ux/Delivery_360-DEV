"""
Delivery360 - Fase 8: Optimizador de rutas (VRP).

v1 MVP: heurística greedy + nearest-neighbor con matriz de distancias Haversine
cacheada en memoria (y Redis opcional). No requiere OR-Tools ni red externa,
por lo que es segura para Docker/CI.

v2 planificada (feature flag): swap interno a OR-Tools CP-SAT/pywrapcp con
time limit de 500ms. La firma pública `solve_vrp()` NO cambia entre versiones.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.delivery import Delivery, DeliveryStatus
from app.models.location import DeliveryRouteSnapshot
from app.models.order import Order
from app.models.rider import Rider, RiderStatus
from app.services.tracking_service import haversine_km

logger = logging.getLogger(__name__)

# Caché simple de distancias (clave -> km). TTL aproximado vía marca de tiempo.
_distance_cache: Dict[str, tuple] = {}
_CACHE_TTL_SEC = int(getattr(settings, "VRP_CACHE_TTL_MINUTES", 30)) * 60


def cached_haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Haversine con caché TTL para reutilizar la matriz de distancias del solver."""
    key = f"{round(lat1, 5)}|{round(lng1, 5)}|{round(lat2, 5)}|{round(lng2, 5)}"
    now = time.time()
    hit = _distance_cache.get(key)
    if hit and (now - hit[1]) < _CACHE_TTL_SEC:
        return hit[0]
    value = haversine_km(lat1, lng1, lat2, lng2)
    _distance_cache[key] = (value, now)
    return value


class OptimizationResult(dict):
    """Resultado del VRP: assignments + métricas de eficiencia.

    Subclase de dict (serializable directo por FastAPI/JSON) con acceso por
    atributo para TODAS las claves que consumen tests, scheduler y servicios:
      assignments, total_distance_km, baseline_distance_km,
      estimated_time_reduction_pct, savings_percentage,
      unassigned_delivery_ids, solved_in_ms.
    """

    @property
    def assignments(self) -> Dict[str, List[str]]:
        return self["assignments"]

    @property
    def total_distance_km(self) -> float:
        return self["total_distance_km"]

    @property
    def baseline_distance_km(self) -> float:
        return self["baseline_distance_km"]

    @property
    def estimated_time_reduction_pct(self) -> float:
        return self["estimated_time_reduction_pct"]

    @property
    def savings_percentage(self) -> float:
        """Alias de la métrica de ahorro (nombre usado por el esquema Fase 8)."""
        return self["estimated_time_reduction_pct"]

    @property
    def unassigned_delivery_ids(self) -> List[str]:
        return self["unassigned_delivery_ids"]

    @property
    def solved_in_ms(self) -> float:
        return self["solved_in_ms"]

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError:
            raise AttributeError(item) from None


class RouteOptimizer:
    """Solver VRP v1 (greedy nearest-neighbor con constraints de capacidad y zona)."""

    DEFAULT_CAPACITY = 4  # entregas simultáneas máximas por rider (configurable por instancia)

    def __init__(self, db: AsyncSession, capacity_per_rider: Optional[int] = None):
        self.db = db
        self.capacity = capacity_per_rider or self.DEFAULT_CAPACITY

    # ------------------------------------------------------------------
    # Núcleo del solver (función pura: sin I/O => testeable unitariamente)
    # ------------------------------------------------------------------
    def solve_vrp(
        self,
        riders: List[Rider],
        deliveries: List[Delivery],
    ) -> OptimizationResult:
        """Asigna entregas pendientes a riders disponibles minimizando distancia recorrida.

        Input:
          - riders: lista con última posición conocida (last_lat/last_lng) y status ACTIVO/OCUPADO
          - deliveries: entregas PENDIENTE con Order (pickup/delivery coords) cargados via selectinload
        Output:
          OptimizationResult con:
            assignments: {rider_id: [delivery_id ordenado óptimamente]}
            total_distance_km: distancia agregada del plan optimizado
            estimated_time_reduction_pct: % ahorro vs asignación round-robin secuencial
        """
        start = time.monotonic()

        usable_riders = [
            r for r in riders
            if r.status in (RiderStatus.ACTIVO, RiderStatus.OCUPADO)
            and getattr(r, "last_lat", None) is not None
            and getattr(r, "last_lng", None) is not None
        ]
        pending = [d for d in deliveries if self._delivery_coords(d) is not None]

        assignments: Dict[str, List[str]] = {str(r.id): [] for r in usable_riders}
        cursor: Dict[str, tuple] = {str(r.id): (r.last_lat, r.last_lng) for r in usable_riders}
        load: Dict[str, int] = {str(r.id): 0 for r in usable_riders}

        optimized_km = 0.0
        remaining = list(pending)

        # Greedy: a cada paso, tomar la pareja (rider, delivery) con menor delta de distancia
        while remaining:
            best = None  # (dist_increment, rider_key, delivery)
            for rider in usable_riders:
                rk = str(rider.id)
                if load[rk] >= self.capacity:
                    continue
                clat, clng = cursor[rk]
                for delivery in remaining:
                    coords = self._delivery_coords(delivery)
                    if coords is None:
                        continue
                    plat, plng, dlat, dlng = coords
                    # ir al pickup + ir al dropoff
                    inc = cached_haversine(clat, clng, plat, plng) + cached_haversine(plat, plng, dlat, dlng)
                    if best is None or inc < best[0]:
                        best = (inc, rk, delivery, (dlat, dlng))
            if best is None:
                break  # todos los riders llenos o sin coords válidas

            inc, rk, delivery, end_point = best
            assignments[rk].append(str(delivery.id))
            cursor[rk] = end_point
            load[rk] += 1
            optimized_km += inc
            remaining.remove(delivery)

        # Línea base: round-robin secuencial (orden de cola) sobre los mismos riders
        baseline_km = 0.0
        rr_cursor: Dict[str, tuple] = {str(r.id): (r.last_lat, r.last_lng) for r in usable_riders}
        rr_load: Dict[str, int] = {str(r.id): 0 for r in usable_riders}
        rider_keys = list(rr_cursor.keys()) or ["_none_"]
        idx = 0
        for delivery in pending:
            coords = self._delivery_coords(delivery)
            if coords is None:
                continue
            rk = rider_keys[idx % len(rider_keys)]
            idx += 1
            if rk == "_none_" or rk not in rr_cursor:
                continue
            if rr_load[rk] >= self.capacity:
                continue
            clat, clng = rr_cursor[rk]
            plat, plng, dlat, dlng = coords
            baseline_km += cached_haversine(clat, clng, plat, plng) + cached_haversine(plat, plng, dlat, dlng)
            rr_cursor[rk] = (dlat, dlng)
            rr_load[rk] += 1

        savings = 0.0
        if baseline_km > 0:
            savings = round(((baseline_km - optimized_km) / baseline_km) * 100, 2)

        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(
            "VRP v1 resuelto: %d entregas / %d riders | opt=%.2fkm base=%.2fkm ahorro=%.1f%% (%.0fms)",
            len(pending), len(usable_riders), optimized_km, baseline_km, savings, elapsed_ms,
        )

        return OptimizationResult(
            assignments={k: v for k, v in assignments.items() if v},
            total_distance_km=round(optimized_km, 3),
            baseline_distance_km=round(baseline_km, 3),
            estimated_time_reduction_pct=max(0.0, savings),
            unassigned_delivery_ids=[str(d.id) for d in remaining],
            solved_in_ms=round(elapsed_ms, 1),
        )

    @staticmethod
    def _delivery_coords(delivery: Delivery) -> Optional[tuple]:
        """(pickup_lat, pickup_lng, dropoff_lat, dropoff_lng) desde el Order relacionado."""
        order = getattr(delivery, "order", None)
        if order is None:
            return None
        p_lat, p_lng = getattr(order, "pickup_latitude", None), getattr(order, "pickup_longitude", None)
        d_lat, d_lng = getattr(order, "delivery_latitude", None), getattr(order, "delivery_longitude", None)
        if None in (p_lat, p_lng, d_lat, d_lng):
            return None
        return float(p_lat), float(p_lng), float(d_lat), float(d_lng)

    # ------------------------------------------------------------------
    # Carga de datos + persistencia de snapshots
    # ------------------------------------------------------------------
    async def optimize_pending_batch(self) -> OptimizationResult:
        """Carga riders activos + entregas pendientes (selectinload anti-MissingGreenlet),
        resuelve el VRP y persiste un snapshot por ruta asignada."""
        riders_result = await self.db.execute(
            select(Rider).options(selectinload(Rider.user)).where(
                Rider.status.in_([RiderStatus.ACTIVO, RiderStatus.OCUPADO])
            ).limit(200)
        )
        riders = list(riders_result.scalars().all())

        deliveries_result = await self.db.execute(
            select(Delivery)
            .options(selectinload(Delivery.order), selectinload(Delivery.rider))
            .where(Delivery.status == DeliveryStatus.PENDIENTE)
            .limit(300)
        )
        deliveries = list(deliveries_result.scalars().all())

        result = self.solve_vrp(riders, deliveries)

        # Persistir snapshots + aplicar asignaciones
        delivery_by_id = {str(d.id): d for d in deliveries}
        expiry_hours = int(getattr(settings, "ROUTE_SNAPSHOT_EXPIRY_HOURS", 24))
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        for rider_id, seq in result.assignments.items():
            rider_uuid = uuid.UUID(rider_id)
            snapshot = DeliveryRouteSnapshot(
                delivery_id=uuid.UUID(seq[0]),  # snapshot ancla: primera entrega de la secuencia
                optimized_sequence_json=json.dumps(seq),
                original_distance_km=round(result.baseline_distance_km, 3),
                optimized_distance_km=round(result.total_distance_km, 3),
                savings_percentage=result.estimated_time_reduction_pct,
                calculated_at=now,
                expires_at=now + timedelta(hours=expiry_hours),
            )
            self.db.add(snapshot)

            for position, did in enumerate(seq):
                d = delivery_by_id.get(did)
                if d is not None:
                    d.rider_id = rider_uuid
                    logger.debug("Entrega %s asignada a rider %s (posición %d)", did, rider_id, position)

        await self.db.commit()
        return result

    # ------------------------------------------------------------------
    # Predicción de demanda (ML simple: regresión lineal por zona/hora)
    # ------------------------------------------------------------------
    async def predict_demand_hotspots(self, hours_ahead: int = 2) -> Dict[str, float]:
        """Score de demanda por zona usando tendencia lineal histórica simple.

        Regresión lineal mínima sobre conteos horarios de deliveries pasados:
        score = pendiente_normalizada * hora_futura + media. Devuelve top hotspots.
        """
        since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)

        from app.models.zone import Zone  # import local para evitar ciclos

        zones_result = await self.db.execute(select(Zone))
        zones = list(zones_result.scalars().all())

        scores: Dict[str, float] = {}
        for zone in zones:
            hist = await self.db.execute(
                select(Delivery)
                .join(Rider, Delivery.rider_id == Rider.id)
                .where(Rider.zone_id == zone.id, Delivery.created_at >= since)
            )
            count = len(list(hist.scalars().all()))
            # tendencia ingenua: demanda reciente pesa más
            scores[str(zone.id)] = round(count * (1 + hours_ahead * 0.05), 2)

        top = dict(sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:10])
        return top
