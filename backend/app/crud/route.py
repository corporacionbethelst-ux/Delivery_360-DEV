"""Persistence using the existing route schema. Internal callers authorize actors."""

from datetime import datetime
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.delivery import Delivery, DeliveryStatus
from app.models.route import (
    Route,
    RoutePoint,
    RouteDeviation,
    RouteStatus,
    utc_now_naive,
)
from app.services.route_geometry import (
    coordinate,
    finite_number,
    planned_coordinates,
    utc_naive,
)


class CRUDRoute:
    async def get_route(self, db: AsyncSession, route_id: UUID) -> Route | None:
        return await db.scalar(select(Route).where(Route.id == route_id))

    async def get_route_by_delivery(
        self, db: AsyncSession, delivery_id: UUID
    ) -> Route | None:
        return await db.scalar(select(Route).where(Route.delivery_id == delivery_id))

    async def lock_route(self, db: AsyncSession, route_id: UUID) -> Route:
        obj = await db.scalar(
            select(Route)
            .where(Route.id == route_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if obj is None:
            raise ValueError("Ruta no encontrada")
        return obj

    async def create_route(
        self,
        db: AsyncSession,
        delivery_id: UUID,
        estimated_distance: float,
        estimated_duration: int,
        route_data: list[dict[str, float]],
    ) -> Route:
        distance = finite_number(estimated_distance, "estimated_distance", 0, 50_000)
        if (
            isinstance(estimated_duration, bool)
            or not isinstance(estimated_duration, int)
            or not 0 <= estimated_duration <= 43_200
        ):
            raise ValueError("Duración estimada inválida")
        path = planned_coordinates(route_data)
        try:
            delivery = (
                await db.execute(
                    select(Delivery.id, Delivery.status)
                    .where(Delivery.id == delivery_id)
                    .with_for_update()
                )
            ).first()
            if delivery is None:
                raise ValueError("Entrega no encontrada")
            if delivery.status not in (
                DeliveryStatus.PENDIENTE,
                DeliveryStatus.INICIADA,
                DeliveryStatus.EN_PICKUP,
                DeliveryStatus.EN_ROUTE,
                DeliveryStatus.EN_DESTINO,
            ):
                raise ValueError("La entrega no admite una ruta nueva")
            if await self.get_route_by_delivery(db, delivery_id) is not None:
                raise ValueError("La entrega ya tiene ruta")
            obj = Route(
                delivery_id=delivery_id,
                status=RouteStatus.PLANIFICADA,
                planned_distance_km=distance,
                planned_duration_minutes=estimated_duration,
                planned_route=[{"latitude": a, "longitude": b} for a, b in path],
                pickup_latitude=path[0][0],
                pickup_longitude=path[0][1],
                delivery_latitude=path[-1][0],
                delivery_longitude=path[-1][1],
            )
            db.add(obj)
            await db.commit()
            await db.refresh(obj)
            return obj
        except Exception:
            await db.rollback()
            raise

    async def add_route_point(
        self,
        db: AsyncSession,
        route_id: UUID,
        latitude: float,
        longitude: float,
        timestamp: datetime | None = None,
        speed: float | None = None,
        heading: float | None = None,
        *,
        commit: bool = True,
    ) -> RoutePoint:
        lat, lng = coordinate(latitude, longitude)
        if speed is not None:
            speed = finite_number(speed, "speed", 0, 300)
        if heading is not None:
            heading = finite_number(heading, "heading", 0, 360)
        try:
            obj = await self.lock_route(db, route_id)
            if obj.status not in (RouteStatus.PLANIFICADA, RouteStatus.EN_PROGRESO):
                raise ValueError("La ruta no admite puntos")
            point = RoutePoint(
                route_id=route_id,
                latitude=lat,
                longitude=lng,
                timestamp=utc_naive(timestamp or utc_now_naive()),
                speed=speed,
                heading=heading,
            )
            db.add(point)
            obj.status = RouteStatus.EN_PROGRESO
            obj.started_at = obj.started_at or point.timestamp
            if commit:
                await db.commit()
                await db.refresh(point)
            else:
                await db.flush()
            return point
        except Exception:
            await db.rollback()
            raise

    async def get_route_points(
        self, db: AsyncSession, route_id: UUID, skip: int = 0, limit: int = 1000
    ) -> list[RoutePoint]:
        if skip < 0 or not 1 <= limit <= 1000:
            raise ValueError("Paginación inválida")
        return list(
            (
                await db.scalars(
                    select(RoutePoint)
                    .where(RoutePoint.route_id == route_id)
                    .order_by(RoutePoint.timestamp, RoutePoint.id)
                    .offset(skip)
                    .limit(limit)
                )
            ).all()
        )

    async def log_deviation(
        self,
        db: AsyncSession,
        route_id: UUID,
        deviation_distance: float,
        expected_lat: float,
        expected_lng: float,
        actual_lat: float,
        actual_lng: float,
        severity: str = "low",
    ) -> RouteDeviation:
        expected, actual = coordinate(expected_lat, expected_lng), coordinate(
            actual_lat, actual_lng
        )
        meters = finite_number(deviation_distance, "deviation_distance", 0, 40_100_000)
        if severity not in ("low", "medium", "high"):
            raise ValueError("Severidad inválida")
        try:
            obj = await self.lock_route(db, route_id)
            deviation = RouteDeviation(
                route_id=route_id,
                deviation_type="distance",
                severity=severity,
                latitude=actual[0],
                longitude=actual[1],
                detected_at=utc_now_naive(),
                expected_location={"latitude": expected[0], "longitude": expected[1]},
                actual_location={"latitude": actual[0], "longitude": actual[1]},
                distance_from_route_km=meters / 1000,
                status="abierto",
            )
            obj.has_deviation = True
            obj.deviation_distance_km = max(
                obj.deviation_distance_km or 0, meters / 1000
            )
            db.add(deviation)
            await db.commit()
            await db.refresh(deviation)
            return deviation
        except Exception:
            await db.rollback()
            raise

    async def resolve_deviation(
        self,
        db: AsyncSession,
        deviation_id: UUID,
        notes: str | None = None,
        actor_id: UUID | None = None,
    ) -> RouteDeviation | None:
        try:
            obj = await db.scalar(
                select(RouteDeviation)
                .where(RouteDeviation.id == deviation_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if obj is None or obj.status == "resuelto":
                return obj
            if obj.status != "abierto":
                raise ValueError("Estado de desviación requiere revisión")
            obj.status, obj.resolved_at = "resuelto", utc_now_naive()
            obj.resolution_notes, obj.resolved_by = notes, actor_id
            await db.commit()
            await db.refresh(obj)
            return obj
        except Exception:
            await db.rollback()
            raise

    async def get_deviations_by_route(
        self, db: AsyncSession, route_id: UUID, limit: int = 100
    ) -> list[RouteDeviation]:
        return list(
            (
                await db.scalars(
                    select(RouteDeviation)
                    .where(RouteDeviation.route_id == route_id)
                    .order_by(RouteDeviation.detected_at.desc(), RouteDeviation.id)
                    .limit(limit)
                )
            ).all()
        )

    async def get_active_deviations(
        self, db: AsyncSession, limit: int = 100
    ) -> list[RouteDeviation]:
        return list(
            (
                await db.scalars(
                    select(RouteDeviation)
                    .where(RouteDeviation.status == "abierto")
                    .order_by(RouteDeviation.detected_at.desc(), RouteDeviation.id)
                    .limit(limit)
                )
            ).all()
        )


route = CRUDRoute()
