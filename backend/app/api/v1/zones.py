"""Delivery zone API endpoints."""

import uuid
from datetime import date, datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status, Request
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user, require_role
from app.core.database import get_db
from app.models.order import Order, OrderStatus
from app.models.rider import Rider
from app.models.user import User, UserRole
from app.models.zone import Zone

# Asegúrate de que tus schemas en app/schemas/zone.py tengan bonus_multiplier: float = 1.0
from app.schemas.zone import (
    ZoneCreate,
    ZoneResponse,
    ZoneUpdate,
    ZoneTariffInput,
    ZoneBonusFactorInput,
)

router = APIRouter(prefix="/zones", tags=["Zones"])


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_uuid(value: str, field_name: str = "ID") -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"{field_name} inválido"
        )


def _format_date(value: Any) -> Optional[str]:
    if not value:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


async def _zone_stats(db: AsyncSession, zone: Zone) -> tuple[int, int]:
    rider_count_result = await db.execute(
        select(func.count(Rider.id)).where(
            or_(
                Rider.zone_id == zone.id,
                func.upper(Rider.operating_zone) == zone.code.upper(),
                func.upper(Rider.operating_zone) == zone.name.upper(),
            )
        )
    )
    riders_count = int(rider_count_result.scalar_one() or 0)

    active_statuses = [
        OrderStatus.PENDIENTE,
        OrderStatus.ASIGNADO,
        OrderStatus.EN_RECOLECCION,
        OrderStatus.RECOLECTADO,
        OrderStatus.EN_RUTA,
    ]
    active_orders_result = await db.execute(
        select(func.count(Order.id))
        .join(Rider, Order.assigned_rider_id == Rider.id)
        .where(
            or_(
                Rider.zone_id == zone.id,
                func.upper(Rider.operating_zone) == zone.code.upper(),
                func.upper(Rider.operating_zone) == zone.name.upper(),
            ),
            Order.status.in_(active_statuses),
        )
    )
    active_orders_count = int(active_orders_result.scalar_one() or 0)
    return riders_count, active_orders_count


async def _build_zone_response(db: AsyncSession, zone: Zone) -> dict:
    riders_count, active_orders_count = await _zone_stats(db, zone)
    return {
        "id": str(zone.id),
        "name": zone.name,
        "code": zone.code,
        "description": zone.description,
        "delivery_fee_base": float(zone.delivery_fee_base or 0),
        "cost_per_km": float(zone.cost_per_km or 0),
        "estimated_time_min": float(zone.estimated_time_min or 0),
        # FASE 3: Incluir multiplicador en la respuesta
        "bonus_multiplier": float(zone.bonus_multiplier or 1.0),
        "is_priority": bool(zone.is_priority),
        "is_active": bool(zone.is_active),
        "color_hex": zone.color_hex or "#6b7280",
        "center_lat": zone.center_lat,
        "center_lng": zone.center_lng,
        "riders_count": riders_count,
        "active_orders_count": active_orders_count,
        "created_at": _format_date(zone.created_at) or utc_now_naive().isoformat(),
        "updated_at": _format_date(zone.updated_at),
    }


async def _get_zone_or_404(db: AsyncSession, zone_id: str) -> Zone:
    zid = _parse_uuid(zone_id, "zone_id")
    result = await db.execute(select(Zone).where(Zone.id == zid))
    zone = result.scalar_one_or_none()
    if not zone:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Zona no encontrada"
        )
    return zone


@router.get("", response_model=List[ZoneResponse])
async def list_zones(
    search: Optional[str] = Query(None, description="Buscar por nombre o código"),
    active_only: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    page: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.SUPERADMIN, UserRole.GERENTE, UserRole.OPERADOR)
    ),
):
    stmt = select(Zone)
    if active_only:
        stmt = stmt.where(Zone.is_active.is_(True))
    if search:
        pattern = f"%{search.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Zone.name).like(pattern), func.lower(Zone.code).like(pattern)
            )
        )

    offset = (page - 1) * limit
    result = await db.execute(
        stmt.order_by(Zone.is_priority.desc(), Zone.name.asc())
        .offset(offset)
        .limit(limit)
    )
    zones = result.scalars().all()
    return [await _build_zone_response(db, zone) for zone in zones]


@router.get("/tariffs/exact")
async def exact_zone_tariffs(
    request: Request,
    zone_ids: List[uuid.UUID] = Query(..., min_length=1, max_length=100),
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(
        require_role(UserRole.SUPERADMIN, UserRole.GERENTE, UserRole.OPERADOR)
    ),
):
    from app.services.zone_tariffs import tariff_view

    if set(request.query_params) - {"zone_ids"}:
        raise HTTPException(422, "La consulta solo admite identidades de zonas")
    if len(set(zone_ids)) != len(zone_ids):
        raise HTTPException(422, "No repitas identidades de zonas")
    rows = (
        await db.scalars(select(Zone).where(Zone.id.in_(zone_ids)).order_by(Zone.id))
    ).all()
    if len(rows) != len(zone_ids):
        raise HTTPException(409, "El catálogo cambió; vuelve a consultar las zonas")
    return {
        "version": 1,
        "scope": "zone_usd_tariffs",
        "items": [tariff_view(zone) for zone in rows],
    }


@router.get("/{zone_id}/tariff/exact")
async def exact_zone_tariff(
    zone_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(
        require_role(UserRole.SUPERADMIN, UserRole.GERENTE, UserRole.OPERADOR)
    ),
):
    from app.services.zone_tariffs import tariff_view

    if request.query_params:
        raise HTTPException(422, "La consulta no admite parámetros adicionales")
    return tariff_view(await _get_zone_or_404(db, zone_id))


@router.put("/{zone_id}/tariff/exact")
async def save_exact_zone_tariff(
    zone_id: str,
    body: "ZoneTariffInput",
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE)),
):
    from decimal import Decimal
    from app.services.zone_tariffs import tariff_view

    if request.query_params:
        raise HTTPException(422, "La escritura no admite parámetros adicionales")
    zone = await db.scalar(
        select(Zone)
        .where(Zone.id == _parse_uuid(zone_id, "zone_id"))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if zone is None:
        raise HTTPException(404, "Zona no encontrada")
    if zone.tariff_revision != body.expected_revision:
        raise HTTPException(
            409, "Las tarifas cambiaron; vuelve a consultarlas antes de guardar"
        )
    before = tariff_view(zone)
    zone.tariff_base_usd = Decimal(body.base_usd)
    zone.tariff_per_km_usd = Decimal(body.per_km_usd)
    zone.tariff_revision += 1
    zone.tariff_updated_at = datetime.now(timezone.utc)
    zone.tariff_updated_by = actor.id
    await db.flush()
    result = tariff_view(zone)
    from app.models.audit_log import AuditLog, ActionType

    db.add(
        AuditLog(
            user_id=actor.id,
            user_email=actor.email,
            user_role=actor.role.value if actor.role is not None else None,
            action_type=ActionType.CONFIG_CHANGE,
            resource_type="ZoneTariff",
            resource_id=str(zone.id),
            description="Actualización explícita de tarifas USD de zona",
            old_values=before,
            new_values=result,
            request_method="PUT",
            request_path=f"/api/v1/zones/{zone.id}/tariff/exact",
            status_code=200,
            success=True,
        )
    )
    await db.commit()
    return result


@router.get("/{zone_id}/bonus-factor/exact")
async def exact_zone_bonus_factor(
    zone_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(
        require_role(UserRole.SUPERADMIN, UserRole.GERENTE, UserRole.OPERADOR)
    ),
):
    from app.services.zone_bonus_factors import factor_view

    if request.query_params:
        raise HTTPException(422, "La consulta no admite parámetros adicionales")
    return factor_view(await _get_zone_or_404(db, zone_id))


@router.put("/{zone_id}/bonus-factor/exact")
async def save_zone_bonus_factor(
    zone_id: str,
    body: ZoneBonusFactorInput,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE)),
):
    from decimal import Decimal
    from app.services.zone_bonus_factors import factor_view
    from app.models.audit_log import AuditLog, ActionType

    if request.query_params:
        raise HTTPException(422, "La escritura no admite parámetros adicionales")
    zone = await db.scalar(
        select(Zone)
        .where(Zone.id == _parse_uuid(zone_id, "zone_id"))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if zone is None:
        raise HTTPException(404, "Zona no encontrada")
    if zone.bonus_factor_revision != body.expected_revision:
        raise HTTPException(
            409, "El factor cambió; vuelve a consultar antes de guardar"
        )
    before = factor_view(zone)
    zone.bonus_factor_exact = Decimal(body.factor)
    zone.bonus_factor_revision += 1
    zone.bonus_factor_updated_at = datetime.now(timezone.utc)
    zone.bonus_factor_updated_by = actor.id
    await db.flush()
    result = factor_view(zone)
    db.add(
        AuditLog(
            user_id=actor.id,
            user_email=actor.email,
            user_role=actor.role.value if actor.role else None,
            action_type=ActionType.CONFIG_CHANGE,
            resource_type="ZoneBonusFactor",
            resource_id=str(zone.id),
            description="Actualización explícita de factor de bono de zona",
            old_values=before,
            new_values=result,
            request_method="PUT",
            request_path=f"/api/v1/zones/{zone.id}/bonus-factor/exact",
            status_code=200,
            success=True,
        )
    )
    await db.commit()
    return result


@router.get("/{zone_id}", response_model=ZoneResponse)
async def get_zone(
    zone_id: str = Path(..., description="ID de la zona"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    zone = await _get_zone_or_404(db, zone_id)
    return await _build_zone_response(db, zone)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ZoneResponse)
async def create_zone(
    body: ZoneCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE)),
):
    code = body.code.upper()
    exists = await db.execute(select(Zone).where(func.upper(Zone.code) == code))
    if exists.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"La zona '{code}' ya existe",
        )

    # FASE 3: Usar el multiplicador del body o default 1.0
    multiplier = getattr(body, "bonus_multiplier", 1.0) or 1.0

    zone = Zone(
        id=uuid.uuid4(),
        name=body.name.strip(),
        code=code,
        description=body.description,
        delivery_fee_base=body.delivery_fee_base,
        cost_per_km=body.cost_per_km,
        estimated_time_min=body.estimated_time_min,
        bonus_multiplier=multiplier,
        is_priority=body.is_priority,
        is_active=body.is_active,
        color_hex=body.color_hex,
        center_lat=body.center_lat,
        center_lng=body.center_lng,
        created_at=utc_now_naive(),
    )
    db.add(zone)
    await db.commit()
    await db.refresh(zone)
    return await _build_zone_response(db, zone)


@router.patch("/{zone_id}", response_model=ZoneResponse)
async def update_zone(
    zone_id: str,
    body: ZoneUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE)),
):
    zone = await db.scalar(
        select(Zone)
        .where(Zone.id == _parse_uuid(zone_id, "zone_id"))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if zone is None:
        raise HTTPException(404, "Zona no encontrada")
    data = body.model_dump(exclude_unset=True)
    if zone.bonus_factor_revision and "bonus_multiplier" in data:
        raise HTTPException(
            409,
            "Esta zona usa un factor decimal explícito; actualízalo en su configuración de bonos",
        )
    if zone.tariff_revision and {"delivery_fee_base", "cost_per_km"}.intersection(data):
        raise HTTPException(
            409,
            "Esta zona usa tarifas USD exactas; actualízalas en su configuración de tarifas",
        )

    if "code" in data and data["code"]:
        new_code = data["code"].upper()
        duplicate = await db.execute(
            select(Zone).where(func.upper(Zone.code) == new_code, Zone.id != zone.id)
        )
        if duplicate.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"La zona '{new_code}' ya está en uso",
            )
        data["code"] = new_code

    # FASE 3: Actualizar multiplicador si viene en el request
    for field, value in data.items():
        setattr(zone, field, value)

    zone.updated_at = utc_now_naive()

    await db.commit()
    await db.refresh(zone)
    return await _build_zone_response(db, zone)


@router.delete("/{zone_id}")
async def delete_zone(
    zone_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE)),
):
    zone = await _get_zone_or_404(db, zone_id)

    await db.execute(
        update(Rider)
        .where(
            or_(
                Rider.zone_id == zone.id,
                func.upper(Rider.operating_zone) == zone.code.upper(),
                func.upper(Rider.operating_zone) == zone.name.upper(),
            )
        )
        .values(zone_id=None, operating_zone=None, updated_at=utc_now_naive())
    )
    await db.delete(zone)
    await db.commit()
    return {"message": "Zona eliminada exitosamente", "id": str(zone.id)}
