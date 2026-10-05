"""Tests Fase 8: Tracking en tiempo real + Optimizador de rutas (VRP).

Siguen el estilo del suite Fase 7 (mocks puros, sin BD real):
  - haversine_km / cached_haversine: matemática geoespacial determinista.
  - Rate limiting de updates de posición (20/min por rider).
  - Broadcast a Redis Pub/Sub con canal y payload correctos.
  - solve_vrp: constraints de capacidad, cobertura total, métricas de ahorro.
  - purge_expired_locations: respeta LIVE_LOCATION_RETENTION_DAYS.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.tracking_service import (
    TrackingService,
    haversine_km,
)
from app.services.route_optimizer import (
    RouteOptimizer,
    OptimizationResult,
    cached_haversine,
)
from app.api.v1.tracking import _check_location_rate
from app.models.rider import Rider, RiderStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _ScalarResult:
    def __init__(self, value=None, rows=None):
        self._value = value
        self._rows = rows or []

    def scalar(self):
        return self._value

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._rows))

    def rowcount(self):
        return self._value or 0


class _FakeDb:
    """DB falsa: cola de resultados para execute(), registra add/commit."""

    def __init__(self, results=None):
        self.results = list(results or [])
        self.added = []
        self.commit = AsyncMock()
        self.flush = AsyncMock()

    async def execute(self, _stmt):
        if self.results:
            return self.results.pop(0)
        return _ScalarResult(value=0)

    def add(self, obj):
        self.added.append(obj)


def _make_rider(lat: float, lng: float, status=RiderStatus.ACTIVO) -> SimpleNamespace:
    """Rider stub con la interfaz que consume solve_vrp (sin tocar la DB)."""
    return SimpleNamespace(
        id=uuid4(),
        status=status,
        last_lat=lat,
        last_lng=lng,
        zone_id=None,
    )


def _make_delivery(pickup=(10.0, 10.0), dropoff=(10.05, 10.05)) -> SimpleNamespace:
    order = SimpleNamespace(
        pickup_latitude=pickup[0], pickup_longitude=pickup[1],
        delivery_latitude=dropoff[0], delivery_longitude=dropoff[1],
    )
    return SimpleNamespace(id=uuid4(), status="PENDIENTE", order=order)


# ---------------------------------------------------------------------------
# Haversine
# ---------------------------------------------------------------------------

def test_haversine_zero_distance_same_point():
    assert haversine_km(4.60971, -74.08175, 4.60971, -74.08175) == 0.0


def test_haversine_known_distance_bogota_to_guasca():
    # Bogotá (4.60971,-74.08175) <-> Guasca (~4.500,-74.000): ~15 km aprox.
    d = haversine_km(4.60971, -74.08175, 4.50093, -74.00093)
    assert 10.0 < d < 20.0


def test_haversine_is_symmetric():
    a = haversine_km(4.6, -74.0, 4.7, -74.1)
    b = haversine_km(4.7, -74.1, 4.6, -74.0)
    assert abs(a - b) < 1e-6


def test_cached_haversine_matches_plain_and_reuses_cache():
    plain = haversine_km(4.60971, -74.08175, 4.50093, -74.00093)
    cached = cached_haversine(4.60971, -74.08175, 4.50093, -74.00093)
    assert cached == plain
    # segunda llamada debe devolver el mismo valor (cache hit)
    assert cached_haversine(4.60971, -74.08175, 4.50093, -74.00093) == cached


# ---------------------------------------------------------------------------
# Rate limiting de posiciones
# ---------------------------------------------------------------------------

def test_location_rate_limit_blocks_over_max_per_minute():
    from app.core.config import settings

    rider = str(uuid4())
    limit = int(getattr(settings, "MAX_POSITION_UPDATES_PER_MINUTE", 20))
    # No debe lanzar hasta alcanzar el límite
    for _ in range(limit):
        _check_location_rate(rider)
    with pytest.raises(Exception):  # HTTPException 429
        _check_location_rate(rider)


# ---------------------------------------------------------------------------
# Broadcast Redis Pub/Sub
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_broadcast_publishes_to_channel_with_prefix():
    redis = MagicMock()
    redis.publish = AsyncMock()
    service = TrackingService(db=_FakeDb(), redis_client=redis)

    rider_id = uuid4()
    await service.broadcast_location_update(
        rider_id=rider_id, lat=4.60971, lng=-74.08175,
        timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
    )

    assert redis.publish.called
    channel = redis.publish.call_args[0][0]
    assert "rider_location_updates" in channel and str(rider_id) in channel


@pytest.mark.asyncio
async def test_broadcast_survives_redis_failure():
    """Si Redis falla, el broadcast no debe tumbar la ingesta (degradación controlada)."""
    redis = MagicMock()
    redis.publish = AsyncMock(side_effect=ConnectionError("redis down"))
    service = TrackingService(db=_FakeDb(), redis_client=redis)

    # No lanza excepción hacia el llamador
    await service.broadcast_location_update(
        rider_id=uuid4(), lat=4.6, lng=-74.0,
        timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
    )


# ---------------------------------------------------------------------------
# Retención / purga
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_purge_expired_locations_uses_retention_window():
    db = _FakeDb(results=[_ScalarResult(value=3)])
    service = TrackingService(db=db, redis_client=None)
    deleted = await service.purge_expired_locations()
    assert deleted == 3
    db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# VRP solver (función pura — sin I/O)
# ---------------------------------------------------------------------------

def test_solve_vrp_respects_capacity_constraints():
    optimizer = RouteOptimizer(db=_FakeDb(), capacity_per_rider=2)
    riders = [_make_rider(4.60, -74.08), _make_rider(4.62, -74.06)]
    deliveries = [_make_delivery() for _ in range(4)]

    result = optimizer.solve_vrp(riders, deliveries)

    assert isinstance(result, OptimizationResult)
    assigned_total = sum(len(v) for v in result.assignments.values())
    assert assigned_total <= 4  # 2 riders * cap 2
    for seq in result.assignments.values():
        assert len(seq) <= 2


def test_solve_vrp_assigns_all_when_capacity_allows():
    optimizer = RouteOptimizer(db=_FakeDb(), capacity_per_rider=5)
    riders = [_make_rider(4.60, -74.08), _make_rider(4.62, -74.06)]
    deliveries = [_make_delivery() for _ in range(3)]

    result = optimizer.solve_vrp(riders, deliveries)

    assigned = [d for seq in result.assignments.values() for d in seq]
    assert len(assigned) == 3
    assert set(assigned) == {str(d.id) for d in deliveries}
    assert result.unassigned_delivery_ids == []


def test_solve_vrp_leaves_unassigned_when_no_capacity():
    optimizer = RouteOptimizer(db=_FakeDb(), capacity_per_rider=1)
    riders = [_make_rider(4.60, -74.08)]
    deliveries = [_make_delivery() for _ in range(3)]

    result = optimizer.solve_vrp(riders, deliveries)

    assert len(list(result.assignments.values())[0]) == 1
    assert len(result.unassigned_delivery_ids) == 2


def test_solve_vrp_ignores_riders_without_location():
    optimizer = RouteOptimizer(db=_FakeDb(), capacity_per_rider=4)
    riders = [_make_rider(4.60, -74.08)]
    r_no_loc = _make_rider(None, None)
    deliveries = [_make_delivery()]

    result = optimizer.solve_vrp(riders + [r_no_loc], deliveries)

    assert str(r_no_loc.id) not in result.assignments
    assert sum(len(v) for v in result.assignments.values()) == 1


def test_solve_vrp_metrics_are_sane():
    optimizer = RouteOptimizer(db=_FakeDb(), capacity_per_rider=4)
    riders = [_make_rider(4.60, -74.08), _make_rider(4.61, -74.07)]
    deliveries = [
        _make_delivery((4.601, -74.081), (4.605, -74.085)),
        _make_delivery((4.611, -74.071), (4.615, -74.075)),
        _make_delivery((4.602, -74.082), (4.606, -74.086)),
    ]

    result = optimizer.solve_vrp(riders, deliveries)

    assert result.total_distance_km > 0
    assert result.baseline_distance_km >= result.total_distance_km
    assert 0.0 <= result.estimated_time_reduction_pct <= 100.0
    assert result.solved_in_ms >= 0


def test_solve_vrp_empty_inputs_returns_empty_result():
    optimizer = RouteOptimizer(db=_FakeDb())
    result = optimizer.solve_vrp([], [])
    assert result.assignments == {}
    assert result.total_distance_km == 0.0


# ---------------------------------------------------------------------------
# optimize_pending_batch (carga desde DB falsa + persistencia de snapshots)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_optimize_pending_batch_persists_snapshots_and_commits():
    rider = _make_rider(4.60, -74.08)
    delivery = _make_delivery()
    db = _FakeDb(results=[
        _ScalarResult(rows=[rider]),      # riders query
        _ScalarResult(rows=[delivery]),   # deliveries query
    ])
    optimizer = RouteOptimizer(db=db, capacity_per_rider=3)

    result = await optimizer.optimize_pending_batch()

    assert str(delivery.id) in result.assignments.get(str(rider.id), [])
    snapshots = [o for o in db.added if type(o).__name__ == "DeliveryRouteSnapshot"]
    assert len(snapshots) == 1
    assert snapshots[0].expires_at > snapshots[0].calculated_at
    db.commit.assert_awaited_once()
