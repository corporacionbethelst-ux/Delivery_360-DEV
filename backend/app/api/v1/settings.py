"""Platform settings API endpoints."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import require_role
from app.core.database import get_db
from app.models.audit_log import ActionType, AuditLog
from app.models.platform_setting import PlatformSetting
from app.models.user import User, UserRole
from app.models.financial import Financial, TransactionType, PaymentStatus
from app.models.delivery import Delivery, DeliveryStatus

router = APIRouter(prefix="/settings", tags=["Settings"])


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Lista de keys esperadas SIN valores por defecto
# Esto fuerza validación estricta: si no está en DB, es None explícito
EXPECTED_SETTING_KEYS: list[str] = [
    "delivery_fee_base",
    "commission_percentage",
    "min_order_amount",
    "active_zones",
    "support_email",
    "maintenance_mode",
    "rider_delivery_bonus",
    "rider_failed_attempt_bonus",
]

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


class BonusSimulationRequest(BaseModel):
    """Solicitud para simulación What-If de bonos."""
    new_rider_delivery_bonus: Optional[float] = Field(None, ge=0, description="Nuevo valor propuesto para bono por entrega")
    new_failed_attempt_bonus: Optional[float] = Field(None, ge=0, description="Nuevo valor propuesto para bono por intento fallido")
    days_lookback: int = Field(30, ge=1, le=90, description="Días hacia atrás para calcular promedio histórico")


class BonusSimulationResponse(BaseModel):
    """Respuesta de simulación What-If de bonos."""
    current_base_bonus: Optional[float]
    proposed_base_bonus: Optional[float]
    current_failed_bonus: Optional[float]
    proposed_failed_bonus: Optional[float]
    historical_metrics: Dict[str, Any]
    projected_impact: Dict[str, Any]
    simulation_date: str


async def _get_historical_bonus_metrics(db: AsyncSession, days: int = 30) -> Dict[str, Any]:
    """
    Obtiene métricas históricas de bonos pagados en los últimos N días.
    
    Returns:
        Dict con:
        - total_deliveries: Total de entregas completadas
        - total_failed_bonus_deliveries: Total de intentos fallidos bonificables
        - total_bonus_paid: Suma total de bonos pagados (éxito + fallidos)
        - avg_daily_deliveries: Promedio diario de entregas
        - avg_daily_bonus_paid: Promedio diario de bonos pagados
    """
    cutoff_date = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    
    # Consulta agregada para entregas completadas (SUCCESS)
    success_stmt = select(
        func.count(Delivery.id).label('total_deliveries'),
        func.sum(Delivery.locked_bonus_amount).label('total_success_bonus')
    ).where(
        and_(
            Delivery.status == DeliveryStatus.COMPLETADA,
            Delivery.completed_at >= cutoff_date,
            Delivery.locked_bonus_type == 'SUCCESS'
        )
    )
    
    # Consulta agregada para intentos fallidos bonificables
    failed_stmt = select(
        func.count(Delivery.id).label('total_failed_deliveries'),
        func.sum(Delivery.locked_bonus_amount).label('total_failed_bonus')
    ).where(
        and_(
            Delivery.status == DeliveryStatus.FALLIDA,
            Delivery.completed_at >= cutoff_date,
            Delivery.locked_bonus_type == 'FAILED_ATTEMPT'
        )
    )
    
    success_result = await db.execute(success_stmt)
    success_row = success_result.fetchone()
    
    failed_result = await db.execute(failed_stmt)
    failed_row = failed_result.fetchone()
    
    total_deliveries = success_row.total_deliveries or 0
    total_failed_deliveries = failed_row.total_failed_deliveries or 0
    total_success_bonus = float(success_row.total_success_bonus) if success_row.total_success_bonus else Decimal('0')
    total_failed_bonus = float(failed_row.total_failed_bonus) if failed_row.total_failed_bonus else Decimal('0')
    total_bonus_paid = total_success_bonus + total_failed_bonus
    
    return {
        'days_analyzed': days,
        'total_deliveries': total_deliveries,
        'total_failed_bonus_deliveries': total_failed_deliveries,
        'total_combined_deliveries': total_deliveries + total_failed_deliveries,
        'total_bonus_paid': round(total_bonus_paid, 2),
        'avg_daily_deliveries': round(total_deliveries / days, 2) if days > 0 else 0,
        'avg_daily_failed_deliveries': round(total_failed_deliveries / days, 2) if days > 0 else 0,
        'avg_daily_bonus_paid': round(total_bonus_paid / days, 2) if days > 0 else 0,
        'avg_bonus_per_delivery': round(total_bonus_paid / total_deliveries, 2) if total_deliveries > 0 else 0,
    }


@router.post("/simulate-bonus", response_model=BonusSimulationResponse)
async def simulate_bonus_impact(
    body: BonusSimulationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE)),
):
    """
    FASE 6: Simulador What-If para impacto de cambios en bonos.
    
    Calcula proyecciones de costo operativo basadas en cambios propuestos
    en los valores de bonos, usando datos históricos de los últimos N días.
    """
    # Obtener configuración actual
    rows = await _ensure_default_settings(db)
    current_settings = _coerce_settings(rows)
    
    current_base_bonus = current_settings.get('rider_delivery_bonus')
    current_failed_bonus = current_settings.get('rider_failed_attempt_bonus')
    
    proposed_base_bonus = body.new_rider_delivery_bonus if body.new_rider_delivery_bonus is not None else current_base_bonus
    proposed_failed_bonus = body.new_failed_attempt_bonus if body.new_failed_attempt_bonus is not None else current_failed_bonus
    
    # Obtener métricas históricas
    historical_metrics = await _get_historical_bonus_metrics(db, body.days_lookback)
    
    # Calcular proyección de impacto
    # Escenario: ¿Cuánto costaría más/menos por mes con los nuevos valores?
    total_deliveries = historical_metrics['total_deliveries']
    total_failed = historical_metrics['total_failed_bonus_deliveries']
    days = body.days_lookback
    
    # Costo actual con valores históricos
    current_monthly_cost = historical_metrics['total_bonus_paid']
    
    # Costo proyectado con nuevos valores
    # Asumimos que el volumen de entregas se mantiene igual
    base_bonus_delta = (proposed_base_bonus or 0) - (current_base_bonus or 0)
    failed_bonus_delta = (proposed_failed_bonus or 0) - (current_failed_bonus or 0)
    
    projected_additional_cost = (base_bonus_delta * total_deliveries) + (failed_bonus_delta * total_failed)
    projected_monthly_cost = current_monthly_cost + projected_additional_cost
    
    # Proyección a 30 días basada en promedios diarios
    daily_additional_cost = projected_additional_cost / days if days > 0 else 0
    projected_30day_impact = daily_additional_cost * 30
    
    # Porcentaje de cambio
    pct_change = ((projected_monthly_cost - current_monthly_cost) / current_monthly_cost * 100) if current_monthly_cost > 0 else 0
    
    projected_impact = {
        'current_monthly_cost': round(current_monthly_cost, 2),
        'projected_monthly_cost': round(projected_monthly_cost, 2),
        'monthly_difference': round(projected_additional_cost, 2),
        'projected_30day_impact': round(projected_30day_impact, 2),
        'percentage_change': round(pct_change, 2),
        'interpretation': f"Si mantienes estos valores por 30 días, el costo mensual de bonos {'aumentaría' if projected_additional_cost > 0 else 'disminuiría' if projected_additional_cost < 0 else 'se mantendría'} en ${abs(round(projected_30day_impact, 2))} ({abs(round(pct_change, 2))}%).",
    }
    
    return BonusSimulationResponse(
        current_base_bonus=current_base_bonus,
        proposed_base_bonus=proposed_base_bonus,
        current_failed_bonus=current_failed_bonus,
        proposed_failed_bonus=proposed_failed_bonus,
        historical_metrics=historical_metrics,
        projected_impact=projected_impact,
        simulation_date=datetime.now(timezone.utc).isoformat(),
    )


async def _load_settings_rows(db: AsyncSession) -> dict[str, PlatformSetting]:
    result = await db.execute(select(PlatformSetting))
    return {row.key: row for row in result.scalars().all()}


def _coerce_settings(rows: dict[str, PlatformSetting]) -> dict[str, Any]:
    """Convierte rows de PlatformSetting a un diccionario de valores.
    
    NOTA CRÍTICA: Sin fallbacks. Si un setting no existe en DB, se retorna None
    explícitamente para forzar validación estricta en capas superiores.
    """
    values: dict[str, Any] = {}
    latest_updated_at: Optional[datetime] = None
    latest_updated_by: Optional[str] = None

    # Inicializar con None explícito para cada key esperada
    for key in EXPECTED_SETTING_KEYS:
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
    """Crea entradas en DB para keys que no existen, con valores None explícitos.
    
    Esto garantiza que todas las keys esperadas existan en DB, pero SIN valores
    por defecto hardcodeados. El administrador debe configurar los valores reales.
    """
    rows = await _load_settings_rows(db)
    changed = False
    
    for key in EXPECTED_SETTING_KEYS:
        if key not in rows:
            # Crear entrada con valor None para forzar configuración explícita
            row = PlatformSetting(key=key, value=None, description=SETTING_DESCRIPTIONS.get(key))
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
        if key not in EXPECTED_SETTING_KEYS:
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
