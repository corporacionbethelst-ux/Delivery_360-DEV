"""Platform settings API endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import require_role
from app.core.database import get_db
from app.models.audit_log import ActionType, AuditLog
from app.models.platform_setting import PlatformSetting
from app.models.user import User, UserRole

router = APIRouter(prefix="/settings", tags=["Settings"])


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


DEFAULT_PLATFORM_SETTINGS: dict[str, Any] = {
    "delivery_fee_base": 5000,
    "commission_percentage": 15,
    "min_order_amount": 10000,
    "active_zones": ["Norte", "Sur", "Centro"],
    "support_email": "soporte@delivery.com",
    "maintenance_mode": False,
    "rider_delivery_bonus": 2500,
    "rider_failed_attempt_bonus": 1500,
}

SETTING_DESCRIPTIONS: dict[str, str] = {
    "delivery_fee_base": "Tarifa base de envío aplicada por defecto.",
    "commission_percentage": "Porcentaje de comisión de plataforma.",
    "min_order_amount": "Monto mínimo permitido para crear órdenes.",
    "active_zones": "Lista de zonas activas visibles para operación.",
    "support_email": "Correo de soporte público.",
    "maintenance_mode": "Bloquea flujos públicos durante mantenimiento.",
    "rider_delivery_bonus": "Bono base pagado al repartidor por cada entrega completada exitosamente.",
    "rider_failed_attempt_bonus": "Bono pagado al repartidor cuando la entrega falla por causa del cliente (dirección incorrecta, rechazo, etc.).",
}


class PlatformSettingsResponse(BaseModel):
    delivery_fee_base: Optional[float] = None
    commission_percentage: Optional[float] = None
    min_order_amount: Optional[float] = None
    active_zones: List[str] = []
    support_email: Optional[EmailStr] = None
    maintenance_mode: bool = False
    rider_delivery_bonus: Optional[float] = None
    rider_failed_attempt_bonus: Optional[float] = None
    updated_at: Optional[str] = None
    updated_by_user_id: Optional[str] = None


class PlatformSettingsUpdate(BaseModel):
    delivery_fee_base: Optional[float] = Field(None, ge=0)
    commission_percentage: Optional[float] = Field(None, ge=0, le=100)
    min_order_amount: Optional[float] = Field(None, ge=0)
    active_zones: Optional[List[str]] = None
    support_email: Optional[EmailStr] = None
    maintenance_mode: Optional[bool] = None
    rider_delivery_bonus: Optional[float] = Field(None, ge=0)
    rider_failed_attempt_bonus: Optional[float] = Field(None, ge=0)


async def _load_settings_rows(db: AsyncSession) -> dict[str, PlatformSetting]:
    result = await db.execute(select(PlatformSetting))
    return {row.key: row for row in result.scalars().all()}


def _coerce_settings(rows: dict[str, PlatformSetting]) -> dict[str, Any]:
    """Convierte rows de PlatformSetting a un diccionario de valores.
    
    NOTA CRÍTICA: Los valores por defecto (DEFAULT_PLATFORM_SETTINGS) solo se usan
    como referencia estructural, NO como fallback de valores. Si un setting no existe
    en DB, se retorna None explícitamente para forzar validación estricta.
    """
    values: dict[str, Any] = {}
    latest_updated_at: Optional[datetime] = None
    latest_updated_by: Optional[str] = None

    # Inicializar con None explícito para cada key esperada
    for key in DEFAULT_PLATFORM_SETTINGS:
        values[key] = None
    
    # Sobrescribir con valores reales de DB si existen
    for key, row in rows.items():
        if key in values:
            values[key] = row.value
            if row.updated_at and (latest_updated_at is None or row.updated_at > latest_updated_at):
                latest_updated_at = row.updated_at
                latest_updated_by = str(row.updated_by_user_id) if row.updated_by_user_id else None

    values["updated_at"] = latest_updated_at.isoformat() if latest_updated_at else None
    values["updated_by_user_id"] = latest_updated_by
    
    # Conversión segura: None se mantiene como None (validación estricta)
    values["delivery_fee_base"] = float(values.get("delivery_fee_base")) if values.get("delivery_fee_base") is not None else None
    values["commission_percentage"] = float(values.get("commission_percentage")) if values.get("commission_percentage") is not None else None
    values["min_order_amount"] = float(values.get("min_order_amount")) if values.get("min_order_amount") is not None else None
    # BONOS: Sin fallback! None indica falta de configuración crítica
    values["rider_delivery_bonus"] = float(values.get("rider_delivery_bonus")) if values.get("rider_delivery_bonus") is not None else None
    values["rider_failed_attempt_bonus"] = float(values.get("rider_failed_attempt_bonus")) if values.get("rider_failed_attempt_bonus") is not None else None
    
    values["active_zones"] = [str(zone).strip() for zone in (values.get("active_zones") or []) if str(zone).strip()]
    values["maintenance_mode"] = bool(values.get("maintenance_mode")) if values.get("maintenance_mode") is not None else False
    
    return values


async def _ensure_default_settings(db: AsyncSession) -> dict[str, PlatformSetting]:
    rows = await _load_settings_rows(db)
    changed = False
    for key, value in DEFAULT_PLATFORM_SETTINGS.items():
        if key not in rows:
            row = PlatformSetting(key=key, value=value, description=SETTING_DESCRIPTIONS.get(key))
            db.add(row)
            rows[key] = row
            changed = True
    if changed:
        await db.commit()
        rows = await _load_settings_rows(db)
    return rows


def _update_payload(body: PlatformSettingsUpdate) -> dict[str, Any]:
    payload = body.model_dump(exclude_unset=True)
    if "active_zones" in payload and payload["active_zones"] is not None:
        zones = [zone.strip() for zone in payload["active_zones"] if zone and zone.strip()]
        if not zones:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Debe existir al menos una zona activa")
        payload["active_zones"] = zones
    return payload


@router.get("", response_model=PlatformSettingsResponse)
@router.get("/", response_model=PlatformSettingsResponse)
async def get_platform_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE)),
):
    """Obtener configuración global persistida de la plataforma."""
    rows = await _ensure_default_settings(db)
    return _coerce_settings(rows)


@router.patch("", response_model=PlatformSettingsResponse)
@router.patch("/", response_model=PlatformSettingsResponse)
async def update_platform_settings(
    body: PlatformSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN)),
):
    """Actualizar configuración global de plataforma y registrar auditoría."""
    payload = _update_payload(body)
    if not payload:
        rows = await _ensure_default_settings(db)
        return _coerce_settings(rows)

    rows = await _ensure_default_settings(db)
    before = _coerce_settings(rows)
    now = utc_now_naive()

    for key, value in payload.items():
        if key not in DEFAULT_PLATFORM_SETTINGS:
            continue
        row = rows.get(key)
        if not row:
            row = PlatformSetting(key=key, value=value, description=SETTING_DESCRIPTIONS.get(key))
            db.add(row)
            rows[key] = row
        row.value = value
        row.description = SETTING_DESCRIPTIONS.get(key)
        row.updated_by_user_id = current_user.id
        row.updated_at = now

    after_preview = dict(before)
    after_preview.update(payload)

    audit = AuditLog(
        user_id=current_user.id,
        user_email=current_user.email,
        user_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
        action_type=ActionType.CONFIG_CHANGE,
        resource_type="PlatformSettings",
        resource_id="global",
        description="Actualización de configuración global de plataforma",
        old_values={key: before.get(key) for key in payload},
        new_values={key: after_preview.get(key) for key in payload},
        changes_summary=", ".join(sorted(payload.keys())),
        success=True,
        created_at=now,
    )
    db.add(audit)

    await db.commit()
    rows = await _load_settings_rows(db)
    return _coerce_settings(rows)


@router.put("", response_model=PlatformSettingsResponse)
@router.put("/", response_model=PlatformSettingsResponse)
async def replace_platform_settings(
    body: PlatformSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN)),
):
    """Alias PUT para clientes que envían actualización completa o parcial."""
    return await update_platform_settings(body, db, current_user)
