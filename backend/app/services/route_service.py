"""GPS analysis: metres for geometry, km/h for device speed, UTC storage."""

from collections.abc import Sequence
from datetime import datetime
from typing import TypedDict
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool
from app.crud.route import route as crud
from app.models.route import Route, RoutePoint, RouteDeviation
from app.services.route_geometry import (
    coordinate,
    distance_m,
    finite_number,
    planned_coordinates,
    route_distance_m,
    utc_naive,
)


class RouteMetricsData(TypedDict):
    total_distance_km: float
    avg_speed_kmh: float
    max_speed_kmh: float
    total_time_minutes: float
    points_count: int
    stops_count: int


class RouteService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_route(
        self,
        delivery_id: UUID,
        planned_route: list[dict[str, float]],
        distance_km: float = 0,
        duration_minutes: int = 0,
    ) -> Route:
        return await crud.create_route(
            self.db, delivery_id, distance_km, duration_minutes, planned_route
        )

    async def add_route_point(
        self,
        route_id: UUID,
        latitude: float,
        longitude: float,
        speed: float | None = None,
        bearing: float | None = None,
    ) -> RoutePoint:
        return await crud.add_route_point(
            self.db, route_id, latitude, longitude, speed=speed, heading=bearing
        )

    async def detect_deviation(
        self,
        route_id: UUID,
        current_lat: float,
        current_lon: float,
        expected_route: list[dict[str, float]],
        threshold_meters: float = 100,
    ) -> RouteDeviation | None:
        position, path = coordinate(current_lat, current_lon), planned_coordinates(
            expected_route
        )
        threshold = finite_number(threshold_meters, "threshold_meters", 1, 100_000)
        meters = route_distance_m(position, path)
        if meters <= threshold:
            return None
        # A reference waypoint, not a projected road position.
        nearest = min(path, key=lambda p: distance_m(position, p))
        return await crud.log_deviation(
            self.db,
            route_id,
            meters,
            *nearest,
            *position,
            severity="high" if meters > 500 else "low",
        )

    async def get_route_history(
        self,
        route_id: UUID,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 1000,
        skip: int = 0,
    ) -> list[RoutePoint]:
        if not 1 <= limit <= 1000 or skip < 0:
            raise ValueError("Paginación inválida")
        start, end = utc_naive(start_time) if start_time else None, (
            utc_naive(end_time) if end_time else None
        )
        if start and end and start > end:
            raise ValueError("Intervalo de fechas inválido")
        query = select(RoutePoint).where(RoutePoint.route_id == route_id)
        if start:
            query = query.where(RoutePoint.timestamp >= start)
        if end:
            query = query.where(RoutePoint.timestamp <= end)
        return list(
            (
                await self.db.scalars(
                    query.order_by(RoutePoint.timestamp, RoutePoint.id)
                    .offset(skip)
                    .limit(limit)
                )
            ).all()
        )

    async def calculate_route_metrics(self, route_id: UUID) -> RouteMetricsData:
        points = list(
            (
                await self.db.scalars(
                    select(RoutePoint)
                    .where(RoutePoint.route_id == route_id)
                    .order_by(RoutePoint.timestamp, RoutePoint.id)
                    .limit(10_001)
                )
            ).all()
        )
        if len(points) > 10_000:
            raise ValueError("Ruta excede 10000 puntos; requiere análisis por lotes")
        return await run_in_threadpool(self.metrics, points)

    @staticmethod
    def metrics(points: Sequence[RoutePoint]) -> RouteMetricsData:
        positions = [coordinate(p.latitude, p.longitude) for p in points]
        timestamps = [utc_naive(p.timestamp) for p in points]
        if timestamps != sorted(timestamps):
            raise ValueError("Puntos fuera de orden temporal")
        distance = sum(distance_m(a, b) for a, b in zip(positions, positions[1:]))
        seconds = (
            (timestamps[-1] - timestamps[0]).total_seconds()
            if len(points) >= 2
            else 0.0
        )
        speeds = [
            finite_number(p.speed, "speed", 0, 300)
            for p in points
            if p.speed is not None
        ]
        return {
            "total_distance_km": round(distance / 1000, 3),
            "avg_speed_kmh": round(distance / seconds * 3.6, 2) if seconds > 0 else 0.0,
            "max_speed_kmh": round(max(speeds), 2) if speeds else 0.0,
            "total_time_minutes": round(seconds / 60, 2),
            "points_count": len(points),
            "stops_count": RouteService._detect_stops(points),
        }

    @staticmethod
    def _detect_stops(
        points: Sequence[RoutePoint], threshold_minutes: float = 5
    ) -> int:
        """Stationary cluster <=30m for >=5min; GPS gaps over 120s break evidence."""
        if not points:
            return 0
        anchor = previous = points[0]
        counted, stops = False, 0
        for point in points[1:]:
            gap = (
                utc_naive(point.timestamp) - utc_naive(previous.timestamp)
            ).total_seconds()
            if (
                gap < 0
                or gap > 120
                or distance_m(
                    coordinate(anchor.latitude, anchor.longitude),
                    coordinate(point.latitude, point.longitude),
                )
                > 30
            ):
                anchor, counted = point, False
            elif (
                not counted
                and (
                    utc_naive(point.timestamp) - utc_naive(anchor.timestamp)
                ).total_seconds()
                >= threshold_minutes * 60
            ):
                stops += 1
                counted = True
            previous = point
        return stops

    async def resolve_deviation(
        self,
        deviation_id: UUID,
        resolution_notes: str | None = None,
        actor_id: UUID | None = None,
    ) -> RouteDeviation:
        result = await crud.resolve_deviation(
            self.db, deviation_id, resolution_notes, actor_id
        )
        if result is None:
            raise ValueError("Desviación no encontrada")
        return result

    async def analyze_route(
        self, delivery_id: UUID, threshold_meters: float = 500
    ) -> dict[str, object]:
        """Bounded manual batch; cooperative workers serialize and deduplicate point IDs."""
        threshold = finite_number(threshold_meters, "threshold_meters", 1, 100_000)
        try:
            obj = await self.db.scalar(
                select(Route)
                .where(Route.delivery_id == delivery_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if obj is None:
                return {"success": False, "reason": "Route not found"}
            path = planned_coordinates(obj.planned_route)
            points = list(
                (
                    await self.db.scalars(
                        select(RoutePoint)
                        .where(RoutePoint.route_id == obj.id)
                        .order_by(RoutePoint.timestamp, RoutePoint.id)
                        .limit(10_001)
                    )
                ).all()
            )
            if len(points) > 10_000:
                raise ValueError(
                    "Ruta excede 10000 puntos; requiere análisis por lotes"
                )
            previous = (
                await self.db.scalars(
                    select(RouteDeviation.actual_location).where(
                        RouteDeviation.route_id == obj.id
                    )
                )
            ).all()
            seen = {
                v["route_point_id"]
                for v in previous
                if isinstance(v, dict) and isinstance(v.get("route_point_id"), str)
            }
            # Copy scalar observations before offloading the CPU-heavy geometry;
            # the worker thread never accesses a session or lazy ORM relations.
            observations = [
                (point.id, coordinate(point.latitude, point.longitude), point.timestamp)
                for point in points
                if str(point.id) not in seen
            ]
            distances = await run_in_threadpool(
                lambda: [
                    route_distance_m(position, path) for _, position, _ in observations
                ]
            )
            count = 0
            for (point_id, position, timestamp), meters in zip(observations, distances):
                if meters <= threshold:
                    continue
                self.db.add(
                    RouteDeviation(
                        route_id=obj.id,
                        deviation_type="distance",
                        severity="high",
                        latitude=position[0],
                        longitude=position[1],
                        detected_at=timestamp,
                        distance_from_route_km=meters / 1000,
                        status="abierto",
                        actual_location={
                            "route_point_id": str(point_id),
                            "latitude": position[0],
                            "longitude": position[1],
                        },
                        expected_location={
                            "reference": "planned_route",
                            "threshold_meters": threshold,
                        },
                    )
                )
                obj.has_deviation = True
                obj.deviation_distance_km = max(
                    obj.deviation_distance_km or 0, meters / 1000
                )
                count += 1
            await self.db.commit()
            return {
                "success": True,
                "deviations_count": count,
                "points_count": len(points),
            }
        except Exception:
            await self.db.rollback()
            raise
