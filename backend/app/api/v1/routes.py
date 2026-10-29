"""Persisted routes and GPS history. Mounted once at /api/v1/routes."""

from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, raiseload
from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.core.operation_permissions import OPERATIONS_STAFF, ensure_operation_role
from app.crud.route import route as crud
from app.models.delivery import Delivery, DeliveryStatus
from app.models.rider import Rider
from app.models.route import Route, RoutePoint, RouteDeviation
from app.models.user import User, UserRole
from app.services.document_review import ensure_rider_can_report_online
from app.services.route_geometry import finite_number, planned_coordinates
from app.services.route_service import RouteService
from app.services.tracking_access import authorize_rider_tracking

router = APIRouter()


class Waypoint(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

    @field_validator("latitude", "longitude", mode="before")
    @classmethod
    def numeric(cls, value):
        return finite_number(value, "coordenada", -180, 180)


class RouteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    delivery_id: UUID
    planned_route: list[Waypoint] = Field(min_length=2, max_length=2000)
    distance_km: float = Field(default=0, ge=0, le=50_000)
    duration_minutes: int = Field(default=0, ge=0, le=43_200, strict=True)

    @field_validator("distance_km", mode="before")
    @classmethod
    def distance(cls, value):
        return finite_number(value, "distance_km", 0, 50_000)


class GPSPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    delivery_id: UUID | None = None
    speed_kmh: float | None = Field(default=None, ge=0, le=300)
    heading: float | None = Field(default=None, ge=0, le=360)

    @field_validator("lat", "lng", "speed_kmh", "heading", mode="before")
    @classmethod
    def numeric(cls, value):
        return None if value is None else finite_number(value, "GPS", -180, 360)


class DeviationResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notes: str = Field(min_length=1, max_length=2000)

    @field_validator("notes")
    @classmethod
    def trim(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Se requieren notas")
        return value.strip()


def route_data(obj: Route) -> dict[str, object]:
    return {
        "id": obj.id,
        "delivery_id": obj.delivery_id,
        "status": obj.status,
        "planned_route": obj.planned_route,
        "planned_distance_km": obj.planned_distance_km,
        "planned_duration_minutes": obj.planned_duration_minutes,
        "has_deviation": obj.has_deviation,
        "started_at": obj.started_at,
        "completed_at": obj.completed_at,
    }


async def accessible_route(db: AsyncSession, user: User, route_id: UUID) -> Route:
    ensure_operation_role(user)
    row = (
        await db.execute(
            select(Route, Delivery.rider_id)
            .join(Delivery, Route.delivery_id == Delivery.id)
            .where(Route.id == route_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Ruta no encontrada")
    await authorize_rider_tracking(db, user, row.rider_id)
    return row[0]


@router.get("")
@router.get("/", include_in_schema=False)
async def list_routes(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ensure_operation_role(current_user)
    query = select(Route).join(Delivery, Route.delivery_id == Delivery.id)
    if current_user.role == UserRole.REPARTIDOR:
        query = query.join(Rider, Delivery.rider_id == Rider.id).where(
            Rider.user_id == current_user.id
        )
    rows = (
        await db.scalars(
            query.order_by(Route.created_at.desc(), Route.id).offset(skip).limit(limit)
        )
    ).all()
    return {"data": [route_data(obj) for obj in rows], "skip": skip, "limit": limit}


@router.post("", status_code=201)
@router.post("/", status_code=201, include_in_schema=False)
async def create_route(
    payload: RouteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in OPERATIONS_STAFF:
        raise HTTPException(
            status_code=403, detail="Crear rutas requiere personal operativo"
        )
    if (
        await db.scalar(select(Delivery.id).where(Delivery.id == payload.delivery_id))
        is None
    ):
        raise HTTPException(status_code=404, detail="Entrega no encontrada")
    try:
        obj = await RouteService(db).create_route(
            payload.delivery_id,
            [p.model_dump() for p in payload.planned_route],
            payload.distance_km,
            payload.duration_minutes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return route_data(obj)


@router.post("/{rider_id}/track")
@router.post("/routes/{rider_id}/track", include_in_schema=False)
async def add_gps_point(
    rider_id: UUID,
    point: GPSPoint,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ensure_operation_role(current_user, write=True)
    await authorize_rider_tracking(db, current_user, rider_id)
    rider = await db.scalar(
        select(Rider)
        .options(
            raiseload("*"),
            load_only(
                Rider.id,
                Rider.user_id,
                Rider.status,
                Rider.is_online,
                Rider.approved_at,
            ),
        )
        .where(Rider.id == rider_id)
    )
    if rider is None:
        raise HTTPException(status_code=404, detail="Repartidor no encontrado")
    # Same document/account guard as the live-location channel. Called before payload writes.
    await ensure_rider_can_report_online(db, rider, allow_busy=True)
    query = select(Delivery).where(
        Delivery.rider_id == rider_id,
        Delivery.status.in_(
            [
                DeliveryStatus.INICIADA,
                DeliveryStatus.EN_PICKUP,
                DeliveryStatus.EN_ROUTE,
                DeliveryStatus.EN_DESTINO,
            ]
        ),
    )
    if point.delivery_id is not None:
        query = query.where(Delivery.id == point.delivery_id)
    deliveries = list(
        (await db.scalars(query.order_by(Delivery.id).limit(2).with_for_update())).all()
    )
    if len(deliveries) != 1:
        raise HTTPException(
            status_code=409,
            detail="Indica una entrega activa inequívoca del repartidor",
        )
    obj = await crud.get_route_by_delivery(db, deliveries[0].id)
    if obj is None:
        raise HTTPException(
            status_code=409, detail="La entrega requiere una ruta planificada"
        )
    try:
        gps = await crud.add_route_point(
            db,
            obj.id,
            point.lat,
            point.lng,
            speed=point.speed_kmh,
            heading=point.heading,
            commit=False,
        )
        rider.last_lat, rider.last_lng, rider.last_location_at = (
            gps.latitude,
            gps.longitude,
            gps.timestamp,
        )
        # Reporting a route point does not override the rider's availability flag.
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except Exception:
        await db.rollback()
        raise
    count = await db.scalar(
        select(func.count())
        .select_from(RoutePoint)
        .where(RoutePoint.route_id == obj.id)
    )
    return {"ok": True, "route_id": obj.id, "point_id": gps.id, "points_count": count}


@router.get("/{route_id}")
async def get_route(
    route_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return route_data(await accessible_route(db, current_user, route_id))


@router.get("/{route_id}/points")
async def get_route_points(
    route_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await accessible_route(db, current_user, route_id)
    try:
        points = await RouteService(db).get_route_history(
            route_id, start_time, end_time, limit, skip
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return {
        "data": [
            {
                "id": p.id,
                "latitude": p.latitude,
                "longitude": p.longitude,
                "timestamp": p.timestamp,
                "speed_kmh": p.speed,
                "heading": p.heading,
            }
            for p in points
        ]
    }


@router.get("/{route_id}/metrics")
async def get_metrics(
    route_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await accessible_route(db, current_user, route_id)
    try:
        return await RouteService(db).calculate_route_metrics(route_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/{route_id}/deviations")
async def get_deviations(
    route_id: UUID,
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await accessible_route(db, current_user, route_id)
    rows = await crud.get_deviations_by_route(db, route_id, limit)
    return {
        "data": [
            {
                "id": d.id,
                "status": d.status,
                "latitude": d.latitude,
                "longitude": d.longitude,
                "distance_from_route_km": d.distance_from_route_km,
                "detected_at": d.detected_at,
                "resolved_at": d.resolved_at,
                "resolved_by": d.resolved_by,
                "resolution_notes": d.resolution_notes,
            }
            for d in rows
        ]
    }


@router.post("/{route_id}/analyze")
async def analyze_route(
    route_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in OPERATIONS_STAFF:
        raise HTTPException(
            status_code=403, detail="Analizar rutas requiere personal operativo"
        )
    obj = await accessible_route(db, current_user, route_id)
    if obj.delivery_id is None:
        raise HTTPException(status_code=409, detail="Ruta sin entrega")
    try:
        planned_coordinates(obj.planned_route)
        return await RouteService(db).analyze_route(obj.delivery_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/{route_id}/deviations/{deviation_id}/resolve")
async def resolve_deviation(
    route_id: UUID,
    deviation_id: UUID,
    payload: DeviationResolution,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in OPERATIONS_STAFF:
        raise HTTPException(
            status_code=403, detail="Resolver desvíos requiere personal operativo"
        )
    await accessible_route(db, current_user, route_id)
    if (
        await db.scalar(
            select(RouteDeviation.id).where(
                RouteDeviation.id == deviation_id, RouteDeviation.route_id == route_id
            )
        )
        is None
    ):
        raise HTTPException(status_code=404, detail="Desviación no encontrada")
    try:
        obj = await RouteService(db).resolve_deviation(
            deviation_id, payload.notes, current_user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {
        "id": obj.id,
        "status": obj.status,
        "resolved_at": obj.resolved_at,
        "resolved_by": obj.resolved_by,
    }
