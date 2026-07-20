"""
Delivery360 - API Endpoints para Entregas (VERSIÓN PRODUCCIÓN CON FASES 1, 2 y 3)
Optimizado para rendimiento, sin logs de debug y con serialización robusta.
Incluye:
- Fase 1: Bonos configurables.
- Fase 2: Pagos por intentos fallidos.
- Fase 3: Multiplicadores por zona geográfica.
"""
from datetime import datetime, timezone
import uuid
import logging
from typing import Optional, Dict, Any, List
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.v1.auth import get_current_user, require_role
from app.core.database import get_db
from app.models.delivery import Delivery, DeliveryStatus
from app.models.order import Order, OrderStatus
from app.models.rider import Rider, RiderStatus
from app.models.user import User, UserRole
from app.models.financial import Financial, TransactionType, PaymentStatus
from app.models.platform_setting import PlatformSetting
from app.models.zone import Zone  # Importado para Fase 3
from app.services.notification_service import NotificationService
from app.services.redis_audit_service import get_redis_audit_logger
from app.services.audit_service import get_audit_service
from app.models.audit_log import ActionType
from app.utils.delivery_analysis import DeliveryIssueAnalyzer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/deliveries")

# --- Schemas de Entrada ---
class DeliveryAssign(BaseModel):
    rider_id: str

class DeliveryStart(BaseModel):
    lat: Optional[float] = None
    lng: Optional[float] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class DeliveryComplete(BaseModel):
    otp_code: Optional[str] = None
    notes: Optional[str] = None
    customer_name_received: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None

class DeliveryFail(BaseModel):
    issue_type: str
    issue_description: Optional[str] = None

class DeliveryStatusUpdate(BaseModel):
    """Schema para actualizar el estado de una entrega."""
    status: str
    issue_type: Optional[str] = None
    issue_description: Optional[str] = None
    otp_code: Optional[str] = None
    notes: Optional[str] = None
    customer_name_received: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None

# --- Helpers Internos ---

def _parse_uuid(value: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field_name} inválido")

async def _get_rider_for_user(db: AsyncSession, user_id) -> Optional[Rider]:
    """Obtiene el perfil rider de un usuario de forma eficiente."""
    stmt = select(Rider).where(Rider.user_id == user_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()

def _serialize_delivery(delivery: Delivery, rider: Optional[Rider], user: Optional[User], order: Optional[Order]) -> Dict[str, Any]:
    """
    Serialización centralizada y segura.
    Maneja casos donde las relaciones pueden ser None sin lanzar excepciones.
    """
    # Datos del Rider
    rider_data = None
    if rider:
        rider_data = {
            "id": str(rider.id),
            "first_name": user.first_name if user else "Sin Nombre",
            "last_name": user.last_name or "",
            "vehicle_type": rider.vehicle_type.value if rider.vehicle_type else None,
            "status": rider.status.value if rider.status else None,
            "is_online": getattr(rider, 'is_online', False)
        }

    # Datos de la Orden/Cliente
    customer_name = "Desconocido"
    external_id = None
    if order:
        customer_name = order.customer_name or "Desconocido"
        external_id = order.external_id

    return {
        "id": str(delivery.id),
        "order_id": str(delivery.order_id),
        "external_id": external_id,
        "customer_name": customer_name,
        "rider_id": str(delivery.rider_id) if delivery.rider_id else None,
        "rider": rider_data,
        "status": delivery.status.value if hasattr(delivery.status, "value") else str(delivery.status),
        "started_at": delivery.started_at.isoformat() if delivery.started_at else None,
        "completed_at": delivery.completed_at.isoformat() if delivery.completed_at else None,
        "current_latitude": delivery.current_latitude,
        "current_longitude": delivery.current_longitude,
        "last_location_update": delivery.last_location_update.isoformat() if delivery.last_location_update else None,
        "pickup_address": order.pickup_address if order else None,
        "delivery_address": order.delivery_address if order else None,
        "estimated_delivery_time": order.estimated_delivery_time.isoformat() if order and order.estimated_delivery_time else None,
        "total_amount": order.total if order else None,
        "payment_method": order.payment_method if order else None,
        "total_time": delivery.total_time,
        "distance_total": delivery.distance_total,
        "sla_compliant": delivery.sla_compliant,
        "sla_actual_minutes": delivery.sla_actual_minutes,
        "created_at": delivery.created_at.isoformat() if delivery.created_at else None,
        "updated_at": delivery.updated_at.isoformat() if delivery.updated_at else None,
    }


def _order_status_to_delivery_status(order_status) -> str:
    status_value = order_status.value if hasattr(order_status, "value") else str(order_status)
    if status_value == OrderStatus.ENTREGADO.value:
        return DeliveryStatus.COMPLETADA.value
    if status_value == OrderStatus.FALLIDO.value:
        return DeliveryStatus.FALLIDA.value
    if status_value in (OrderStatus.RECOLECTADO.value, OrderStatus.EN_RUTA.value):
        return DeliveryStatus.EN_ROUTE.value
    if status_value == OrderStatus.ASIGNADO.value:
        return DeliveryStatus.INICIADA.value
    return DeliveryStatus.PENDIENTE.value


def _serialize_order_as_delivery(order: Order, rider: Optional[Rider], user: Optional[User]) -> Dict[str, Any]:
    """Fallback para órdenes asignadas que aún no tienen fila en deliveries."""
    rider_data = None
    if rider:
        rider_data = {
            "id": str(rider.id),
            "first_name": user.first_name if user else "Sin Nombre",
            "last_name": user.last_name or "",
            "vehicle_type": rider.vehicle_type.value if rider.vehicle_type else None,
            "status": rider.status.value if rider.status else None,
            "is_online": getattr(rider, 'is_online', False),
        }

    status = _order_status_to_delivery_status(order.status)
    return {
        "id": f"order-{order.id}",
        "order_id": str(order.id),
        "external_id": order.external_id,
        "customer_name": order.customer_name or "Desconocido",
        "rider_id": str(order.assigned_rider_id) if order.assigned_rider_id else None,
        "rider": rider_data,
        "status": status,
        "started_at": order.accepted_at.isoformat() if order.accepted_at else None,
        "completed_at": order.delivered_at.isoformat() if order.delivered_at else None,
        "current_latitude": getattr(rider, "last_lat", None) if rider else None,
        "current_longitude": getattr(rider, "last_lng", None) if rider else None,
        "last_location_update": rider.last_location_at.isoformat() if rider and rider.last_location_at else None,
        "pickup_address": order.pickup_address,
        "delivery_address": order.delivery_address,
        "estimated_delivery_time": order.estimated_delivery_time.isoformat() if order.estimated_delivery_time else None,
        "total_amount": order.total,
        "payment_method": order.payment_method,
        "total_time": None,
        "distance_total": None,
        "sla_compliant": None,
        "sla_actual_minutes": None,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "updated_at": order.updated_at.isoformat() if order.updated_at else None,
    }

# --- Endpoints Principales ---

@router.get("")
async def list_deliveries(
    status: Optional[str] = Query(None),
    rider_id: Optional[str] = Query(None),
    order_id: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    include_total: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Lista entregas con JOINs explícitos para obtener datos de Riders, Users y Orders.
    Soporta paginación y filtros por estado, rider u orden.
    Devuelve: { "items": [...], "total": <count_real> }
    """
    # 1. Definición de Alias para evitar ambigüedades en JOINs
    d_alias = aliased(Delivery)
    r_alias = aliased(Rider)
    u_alias = aliased(User)
    o_alias = aliased(Order)

    # 2. Construcción de consulta base SIN paginación (para contar)
    base_stmt = (
        select(d_alias, r_alias, u_alias, o_alias)
        .outerjoin(r_alias, d_alias.rider_id == r_alias.id)
        .outerjoin(u_alias, r_alias.user_id == u_alias.id)
        .outerjoin(o_alias, d_alias.order_id == o_alias.id)
    )

    # 3. Filtros de Seguridad y Negocio
    if current_user.role == UserRole.REPARTIDOR:
        rider_profile = await _get_rider_for_user(db, current_user.id)
        if not rider_profile:
            raise HTTPException(status_code=404, detail="Perfil de repartidor no encontrado")
        base_stmt = base_stmt.where(d_alias.rider_id == rider_profile.id)

    if status:
        try:
            base_stmt = base_stmt.where(d_alias.status == DeliveryStatus(status))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Estado inválido: {status}")
    
    if rider_id:
        base_stmt = base_stmt.where(d_alias.rider_id == _parse_uuid(rider_id, "rider_id"))
        
    if order_id:
        base_stmt = base_stmt.where(d_alias.order_id == _parse_uuid(order_id, "order_id"))

    # 4. Conteo TOTAL antes de aplicar cualquier lógica de fallback o paginación
    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total_result = await db.execute(count_stmt)
    total_count = total_result.scalar() or 0

    # 5. Aplicar ordenamiento y paginación a la consulta principal
    stmt = base_stmt.order_by(d_alias.created_at.desc())
    stmt = stmt.offset(offset).limit(limit)
    
    # 6. Ejecución consulta principal
    result = await db.execute(stmt)
    rows = result.all()

    # 7. Serialización
    items = []
    for row in rows:
        delivery, rider, user, order = row
        items.append(_serialize_delivery(delivery, rider, user, order))

    # 8. Fallback: órdenes asignadas que todavía no tienen registro en deliveries.
    missing_delivery_alias = aliased(Delivery)
    fallback_rider = aliased(Rider)
    fallback_user = aliased(User)
    fallback_stmt = (
        select(o_alias, fallback_rider, fallback_user)
        .outerjoin(missing_delivery_alias, missing_delivery_alias.order_id == o_alias.id)
        .outerjoin(fallback_rider, o_alias.assigned_rider_id == fallback_rider.id)
        .outerjoin(fallback_user, fallback_rider.user_id == fallback_user.id)
        .where(
            o_alias.assigned_rider_id.isnot(None),
            missing_delivery_alias.id.is_(None),
        )
        .order_by(o_alias.created_at.desc())
    )

    if current_user.role == UserRole.REPARTIDOR:
        rider_profile = await _get_rider_for_user(db, current_user.id)
        if rider_profile:
            fallback_stmt = fallback_stmt.where(o_alias.assigned_rider_id == rider_profile.id)

    if rider_id:
        fallback_stmt = fallback_stmt.where(o_alias.assigned_rider_id == _parse_uuid(rider_id, "rider_id"))
    if order_id:
        fallback_stmt = fallback_stmt.where(o_alias.id == _parse_uuid(order_id, "order_id"))

    if offset == 0:
        fallback_result = await db.execute(fallback_stmt.limit(50))
        for order, rider, user in fallback_result.all():
            fallback_item = _serialize_order_as_delivery(order, rider, user)
            if status and fallback_item["status"] != status:
                continue
            items.append(fallback_item)

    final_total = total_count + len(items) - len(rows) if offset == 0 else total_count

    return {
        "items": items,
        "total": final_total,
        "limit": limit,
        "offset": offset
    }

@router.get("/{delivery_id}")
async def get_delivery(
    delivery_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Obtiene el detalle completo de una entrega específica."""
    d_alias = aliased(Delivery)
    r_alias = aliased(Rider)
    u_alias = aliased(User)
    o_alias = aliased(Order)

    stmt = (
        select(d_alias, r_alias, u_alias, o_alias)
        .outerjoin(r_alias, d_alias.rider_id == r_alias.id)
        .outerjoin(u_alias, r_alias.user_id == u_alias.id)
        .outerjoin(o_alias, d_alias.order_id == o_alias.id)
        .where(d_alias.id == _parse_uuid(delivery_id, "delivery_id"))
    )
    
    result = await db.execute(stmt)
    row = result.first()
    
    if not row:
        raise HTTPException(status_code=404, detail="Entrega no encontrada")
        
    delivery, rider, user, order = row

    if current_user.role == UserRole.REPARTIDOR:
        rider_profile = await _get_rider_for_user(db, current_user.id)
        if not rider_profile or delivery.rider_id != rider_profile.id:
            raise HTTPException(status_code=403, detail="Acceso denegado")

    return _serialize_delivery(delivery, rider, user, order)

@router.post("/{delivery_id}/assign")
async def assign_delivery(
    delivery_id: str,
    body: DeliveryAssign,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE, UserRole.OPERADOR)),
):
    """Asigna un repartidor a una entrega pendiente."""
    stmt = select(Delivery).where(Delivery.id == _parse_uuid(delivery_id, "delivery_id"))
    result = await db.execute(stmt)
    delivery = result.scalar_one_or_none()
    
    if not delivery:
        raise HTTPException(status_code=404, detail="Entrega no encontrada")
    if delivery.status != DeliveryStatus.PENDIENTE:
        raise HTTPException(status_code=400, detail=f"No se puede asignar en estado {delivery.status.value}")

    rider_result = await db.execute(select(Rider).where(Rider.id == _parse_uuid(body.rider_id, "rider_id")))
    rider = rider_result.scalar_one_or_none()
    if not rider or rider.status != RiderStatus.ACTIVO:
        raise HTTPException(status_code=400, detail="Repartidor no disponible")

    now = datetime.now(timezone.utc)

    delivery.rider_id = rider.id
    delivery.status = DeliveryStatus.INICIADA
    delivery.started_at = now

    order_result = await db.execute(select(Order).where(Order.id == delivery.order_id))
    order = order_result.scalar_one_or_none()
    if order:
        order.assigned_rider_id = rider.id
        order.status = OrderStatus.ASIGNADO
        order.accepted_at = now

    await db.commit()
    
    await db.refresh(delivery, attribute_names=['rider', 'order'])
    if delivery.rider:
        await db.refresh(delivery.rider, attribute_names=['user'])
    
    r_alias = aliased(Rider)
    u_alias = aliased(User)
    o_alias = aliased(Order)
    
    final_stmt = (
        select(Delivery, r_alias, u_alias, o_alias)
        .outerjoin(r_alias, Delivery.rider_id == r_alias.id)
        .outerjoin(u_alias, r_alias.user_id == u_alias.id)
        .outerjoin(o_alias, Delivery.order_id == o_alias.id)
        .where(Delivery.id == delivery.id)
    )
    res = await db.execute(final_stmt)
    d_row, r_row, u_row, o_row = res.first()
    
    return _serialize_delivery(d_row, r_row, u_row, o_row)

@router.post("/{delivery_id}/start")
async def start_delivery(
    delivery_id: str,
    body: DeliveryStart,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Inicia el proceso de entrega (camino a pickup)."""
    result = await db.execute(select(Delivery).where(Delivery.id == _parse_uuid(delivery_id, "delivery_id")))
    delivery = result.scalar_one_or_none()
    if not delivery:
        raise HTTPException(status_code=404, detail="Entrega no encontrada")

    if current_user.role == UserRole.REPARTIDOR:
        rider = await _get_rider_for_user(db, current_user.id)
        if not rider or delivery.rider_id != rider.id:
            raise HTTPException(status_code=403, detail="No tienes permiso para iniciar esta entrega")

    if delivery.status not in [DeliveryStatus.INICIADA, DeliveryStatus.EN_PICKUP]:
         raise HTTPException(status_code=400, detail=f"Estado inválido para iniciar: {delivery.status.value}")

    if body.lat is not None:
        delivery.current_latitude = body.lat
    if body.lng is not None:
        delivery.current_longitude = body.lng
        
    delivery.status = DeliveryStatus.EN_ROUTE
    delivery.started_at = delivery.started_at or datetime.now(timezone.utc)

    await db.commit()
    
    await db.refresh(delivery, attribute_names=['rider', 'order'])
    if delivery.rider:
        await db.refresh(delivery.rider, attribute_names=['user'])
        
    r_alias = aliased(Rider)
    u_alias = aliased(User)
    o_alias = aliased(Order)
    final_stmt = (
        select(Delivery, r_alias, u_alias, o_alias)
        .outerjoin(r_alias, Delivery.rider_id == r_alias.id)
        .outerjoin(u_alias, r_alias.user_id == u_alias.id)
        .outerjoin(o_alias, Delivery.order_id == o_alias.id)
        .where(Delivery.id == delivery.id)
    )
    res = await db.execute(final_stmt)
    d_row, r_row, u_row, o_row = res.first()
    
    return _serialize_delivery(d_row, r_row, u_row, o_row)

@router.post("/{delivery_id}/complete")
async def complete_delivery(
    delivery_id: str,
    body: DeliveryComplete,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Marca la entrega como completada exitosamente y genera el registro financiero."""
    result = await db.execute(select(Delivery).where(Delivery.id == _parse_uuid(delivery_id, "delivery_id")))
    delivery = result.scalar_one_or_none()
    if not delivery:
        raise HTTPException(status_code=404, detail="Entrega no encontrada")

    if current_user.role == UserRole.REPARTIDOR:
        rider = await _get_rider_for_user(db, current_user.id)
        if not rider or delivery.rider_id != rider.id:
            raise HTTPException(status_code=403, detail="No tienes permiso")

    if delivery.status not in [DeliveryStatus.EN_ROUTE, DeliveryStatus.EN_DESTINO]:
        raise HTTPException(status_code=400, detail=f"Estado inválido para completar: {delivery.status.value}")

    if body.otp_code and delivery.proof_otp and body.otp_code != delivery.proof_otp:
        raise HTTPException(status_code=400, detail="Código OTP incorrecto")

    now = datetime.now(timezone.utc)
    delivery.status = DeliveryStatus.COMPLETADA
    delivery.completed_at = now
    delivery.proof_notes = body.notes
    delivery.customer_name_received = body.customer_name_received
    
    if body.lat is not None:
        delivery.current_latitude = body.lat
    if body.lng is not None:
        delivery.current_longitude = body.lng

    if delivery.started_at:
        elapsed_minutes = max(0, int((now - delivery.started_at).total_seconds() / 60))
        delivery.sla_actual_minutes = elapsed_minutes
        if delivery.sla_expected_minutes is not None:
            delivery.sla_compliant = elapsed_minutes <= delivery.sla_expected_minutes

    order_result = await db.execute(select(Order).where(Order.id == delivery.order_id))
    order = order_result.scalar_one_or_none()
    if order:
        order.status = OrderStatus.ENTREGADO
        order.delivered_at = now

    idempotency_key = f"pago_entrega_{delivery.order_id}"
    
    financial_result = await db.execute(
        select(Financial).where(Financial.idempotency_key == idempotency_key)
    )
    existing_financial = financial_result.scalar_one_or_none()
    
    if not existing_financial and delivery.rider_id:
        # Obtener bono base
        settings_result = await db.execute(
            select(PlatformSetting.value).where(PlatformSetting.key == "rider_delivery_bonus")
        )
        bonus_value = settings_result.scalar_one_or_none()
        base_payment = Decimal(str(bonus_value)) if bonus_value is not None else Decimal("2.50")
        
        # FASE 3: Aplicar multiplicador de zona
        multiplier = Decimal("1.0")
        rider_obj = await _get_rider_for_user(db, rider.id)
        
        if rider_obj and rider_obj.zone_id:
            zone_result = await db.execute(
                select(Zone.bonus_multiplier).where(Zone.id == rider_obj.zone_id)
            )
            zone_mult = zone_result.scalar_one_or_none()
            if zone_mult is not None:
                multiplier = Decimal(str(zone_mult))
        
        final_payment = base_payment * multiplier
        
        financial = Financial(
            rider_id=delivery.rider_id,
            amount=final_payment,
            transaction_type=TransactionType.PAGO_ENTREGA,
            description=f"Pago por entrega (Orden {order.external_id if order else delivery.order_id}) - Mult. Zona: {multiplier}",
            reference_id=str(order.id) if order else str(delivery.order_id),
            source_type="delivery",
            source_id=str(delivery.id),
            idempotency_key=idempotency_key,
            status=PaymentStatus.PROCESADO,
        )
        db.add(financial)
        logger.info(f"Pago calculado: Base {base_payment} * Mult {multiplier} = {final_payment}")
    
    await db.flush()
    await db.commit()

    try:
        if order:
            customer_result = await db.execute(
                select(User).where(User.email == order.customer_email)
            )
            customer = customer_result.scalar_one_or_none()
            if customer:
                notification_service = NotificationService(db)
                await notification_service.create_notification(
                    user_id=customer.id,
                    notification_type="ENTREGA_COMPLETADA",
                    title="✅ Pedido Entregado",
                    message=f"Tu pedido #{order.external_id or str(order.id)[:8]} ha sido entregado exitosamente",
                    data={"order_id": str(order.id), "delivery_id": str(delivery.id)},
                    channel="push"
                )
                logger.info(f"Notificación de entrega enviada al cliente {customer.id}")
    except Exception as e:
        logger.warning(f"No se pudo enviar notificación de entrega al cliente: {e}")
    
    try:
        audit_service = get_audit_service(db)
        await audit_service.log_action_async(
            user_id=current_user.id,
            action=ActionType.COMPLETE,
            resource_type="DELIVERY",
            resource_id=str(delivery.id),
            description=f"Entrega {delivery.id} completada para orden {order.external_id if order else delivery.order_id}",
            old_values={"status": DeliveryStatus.EN_ROUTE.value},
            new_values={
                "status": DeliveryStatus.COMPLETADA.value,
                "completed_at": now.isoformat(),
                "sla_compliant": delivery.sla_compliant,
                "total_time_minutes": delivery.sla_actual_minutes,
            },
        )
    except Exception as e:
        logger.warning(f"No se pudo crear audit log en PostgreSQL: {e}")
    
    try:
        redis_logger = get_redis_audit_logger()
        if redis_logger.connected:
            await redis_logger.log_order_completed(
                order_id=str(delivery.order_id),
                rider_id=str(delivery.rider_id),
                completed_by=str(current_user.id),
                delivery_time_minutes=delivery.sla_actual_minutes,
                sla_compliant=delivery.sla_compliant,
            )
    except Exception as e:
        logger.warning(f"No se pudo escribir audit en Redis: {e}")
    
    await db.refresh(delivery, attribute_names=['rider', 'order'])
    if delivery.rider:
        await db.refresh(delivery.rider, attribute_names=['user'])

    r_alias = aliased(Rider)
    u_alias = aliased(User)
    o_alias = aliased(Order)
    final_stmt = (
        select(Delivery, r_alias, u_alias, o_alias)
        .outerjoin(r_alias, Delivery.rider_id == r_alias.id)
        .outerjoin(u_alias, r_alias.user_id == u_alias.id)
        .outerjoin(o_alias, Delivery.order_id == o_alias.id)
        .where(Delivery.id == delivery.id)
    )
    res = await db.execute(final_stmt)
    d_row, r_row, u_row, o_row = res.first()
    
    return _serialize_delivery(d_row, r_row, u_row, o_row)

@router.post("/{delivery_id}/fail")
async def fail_delivery(
    delivery_id: str,
    body: DeliveryFail,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Marca la entrega como fallida con razón y crea pago de intento fallido si corresponde."""
    result = await db.execute(select(Delivery).where(Delivery.id == _parse_uuid(delivery_id, "delivery_id")))
    delivery = result.scalar_one_or_none()
    if not delivery:
        raise HTTPException(status_code=404, detail="Entrega no encontrada")

    if current_user.role == UserRole.REPARTIDOR:
        rider = await _get_rider_for_user(db, current_user.id)
        if not rider or delivery.rider_id != rider.id:
            raise HTTPException(status_code=403, detail="No tienes permiso")

    allowed_statuses = [
        DeliveryStatus.PENDIENTE, DeliveryStatus.INICIADA, 
        DeliveryStatus.EN_PICKUP, DeliveryStatus.EN_ROUTE, DeliveryStatus.EN_DESTINO
    ]
    if delivery.status not in allowed_statuses:
        raise HTTPException(status_code=400, detail=f"Estado inválido para fallar: {delivery.status.value}")

    # Analizar la causa usando el analizador de texto
    analysis = DeliveryIssueAnalyzer.analyze(body.issue_description)
    is_external_cause = analysis["is_external_fault"]
    analysis_reason = analysis["reason"]
    
    delivery.status = DeliveryStatus.FALLIDA
    delivery.has_issues = True
    delivery.issue_type = body.issue_type
    delivery.issue_description = body.issue_description
    # Guardar el resultado del análisis en la descripción o campo dedicado si existe
    delivery.issue_analysis_result = analysis_reason if hasattr(delivery, 'issue_analysis_result') else body.issue_description

    order_result = await db.execute(select(Order).where(Order.id == delivery.order_id))
    order = order_result.scalar_one_or_none()
    if order:
        order.status = OrderStatus.FALLIDO
        order.failure_reason = body.issue_type
        order.failure_notes = body.issue_description

    bonus_applied = False
    bonus_amount = Decimal("0.00")
    
    if delivery.rider_id:
        # Determinar si se debe pagar: usa issue_type O el análisis de texto
        customer_fault_reasons = ["cliente_no_esta", "direccion_incorrecta", "cliente_rechaza", "otro_cliente"]
        should_pay_rider = body.issue_type.lower() in customer_fault_reasons or is_external_cause
        
        if should_pay_rider:
            idempotency_key = f"pago_fallido_{delivery.order_id}"
            
            financial_result = await db.execute(
                select(Financial).where(Financial.idempotency_key == idempotency_key)
            )
            existing_financial = financial_result.scalar_one_or_none()
            
            if not existing_financial:
                settings_result = await db.execute(
                    select(PlatformSetting.value).where(PlatformSetting.key == "rider_failed_attempt_bonus")
                )
                bonus_value = settings_result.scalar_one_or_none()
                failed_payment = Decimal(str(bonus_value)) if bonus_value is not None else Decimal("1500.00")
                
                financial = Financial(
                    rider_id=delivery.rider_id,
                    amount=failed_payment,
                    transaction_type=TransactionType.PAGO_INTENTO_FALLIDO,
                    description=f"Pago por intento fallido (orden {order.external_id if order else delivery.order_id}) - Motivo: {body.issue_type}. Análisis: {analysis_reason}",
                    reference_id=str(order.id) if order else str(delivery.order_id),
                    source_type="delivery_failed",
                    source_id=str(delivery.id),
                    idempotency_key=idempotency_key,
                    status=PaymentStatus.PROCESADO,
                )
                db.add(financial)
                bonus_applied = True
                bonus_amount = failed_payment
                logger.info(f"Registro financiero creado para entrega fallida {delivery.id} - Rider {delivery.rider_id} - Bono: {failed_payment}")

    await db.commit()
    
    await db.refresh(delivery, attribute_names=['rider', 'order'])
    if delivery.rider:
        await db.refresh(delivery.rider, attribute_names=['user'])

    r_alias = aliased(Rider)
    u_alias = aliased(User)
    o_alias = aliased(Order)
    final_stmt = (
        select(Delivery, r_alias, u_alias, o_alias)
        .outerjoin(r_alias, Delivery.rider_id == r_alias.id)
        .outerjoin(u_alias, r_alias.user_id == u_alias.id)
        .outerjoin(o_alias, Delivery.order_id == o_alias.id)
        .where(Delivery.id == delivery.id)
    )
    res = await db.execute(final_stmt)
    d_row, r_row, u_row, o_row = res.first()
    
    # Serializar y agregar información del bono aplicado
    response_data = _serialize_delivery(d_row, r_row, u_row, o_row)
    response_data["bonus_applied"] = bonus_applied
    response_data["bonus_amount"] = float(bonus_amount) if bonus_applied else 0.0
    response_data["issue_analysis"] = analysis
    
    return response_data


@router.patch("/{delivery_id}/location")
async def update_location(
    delivery_id: str,
    body: DeliveryStart,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Actualiza la ubicación GPS de una entrega en curso."""
    stmt = select(Delivery).where(Delivery.id == _parse_uuid(delivery_id, "delivery_id"))
    result = await db.execute(stmt)
    delivery = result.scalar_one_or_none()
    
    if not delivery:
        raise HTTPException(status_code=404, detail="Entrega no encontrada")

    if current_user.role == UserRole.REPARTIDOR:
        rider_profile = await _get_rider_for_user(db, current_user.id)
        if not rider_profile or delivery.rider_id != rider_profile.id:
            raise HTTPException(status_code=403, detail="No autorizado para actualizar esta ubicación")
    
    if delivery.status not in [DeliveryStatus.INICIADA, DeliveryStatus.EN_PICKUP, DeliveryStatus.EN_ROUTE, DeliveryStatus.EN_DESTINO]:
        pass 

    lat = body.lat if body.lat is not None else body.latitude
    lng = body.lng if body.lng is not None else body.longitude

    if lat is not None and lng is not None:
        delivery.current_latitude = lat
        delivery.current_longitude = lng
        delivery.last_location_update = datetime.now(timezone.utc)
        
        if delivery.rider_id:
            rider_stmt = select(Rider).where(Rider.id == delivery.rider_id)
            rider_res = await db.execute(rider_stmt)
            rider = rider_res.scalar_one_or_none()
            if rider:
                rider.last_lat = lat
                rider.last_lng = lng
                rider.last_location_at = datetime.now(timezone.utc)

        await db.commit()
        
        return {"status": "success", "message": "Ubicación actualizada", "lat": lat, "lng": lng}
    
    raise HTTPException(status_code=400, detail="Latitud y longitud son requeridas")


@router.get("/navigation/previous")
async def get_previous_view(
    current_user: User = Depends(get_current_user)
):
    """Endpoint auxiliar para el botón 'Volver' del frontend."""
    routes = {
        UserRole.SUPERADMIN: "/manager/dashboard",
        UserRole.GERENTE: "/manager/dashboard",
        UserRole.OPERADOR: "/manager/dispatch",
        UserRole.REPARTIDOR: "/rider/dashboard",
        UserRole.CLIENTE: "/client/orders"
    }
    
    target_route = routes.get(current_user.role, "/manager/dashboard")
    
    return {
        "redirect_to": target_route,
        "label": "Volver al Panel Principal"
    }


@router.patch("/{delivery_id}/status")
async def update_delivery_status(
    delivery_id: str,
    body: DeliveryStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Endpoint unificado para que el repartidor actualice el estado de su entrega.
    Permite transiciones: ASIGNADO→RECOLECTADO→EN_RUTA→ENTREGADO/FALLIDO
    Incluye lógica de FASE 3 para cálculo de bonos con multiplicador de zona.
    """
    result = await db.execute(select(Delivery).where(Delivery.id == _parse_uuid(delivery_id, "delivery_id")))
    delivery = result.scalar_one_or_none()
    if not delivery:
        raise HTTPException(status_code=404, detail="Entrega no encontrada")

    if current_user.role == UserRole.REPARTIDOR:
        rider = await _get_rider_for_user(db, current_user.id)
        if not rider or delivery.rider_id != rider.id:
            raise HTTPException(status_code=403, detail="No tienes permiso para actualizar esta entrega")
    
    status_mapping = {
        "EN_PICKUP": DeliveryStatus.EN_PICKUP,
        "EN_ROUTE": DeliveryStatus.EN_ROUTE,
        "EN_DESTINO": DeliveryStatus.EN_DESTINO,
        "COMPLETADA": DeliveryStatus.COMPLETADA,
        "FALLIDA": DeliveryStatus.FALLIDA,
    }
    
    new_status = status_mapping.get(body.status.upper())
    if not new_status:
        raise HTTPException(status_code=400, detail=f"Estado inválido: {body.status}")
    
    allowed_transitions = {
        DeliveryStatus.INICIADA: [DeliveryStatus.EN_PICKUP, DeliveryStatus.EN_ROUTE],
        DeliveryStatus.EN_PICKUP: [DeliveryStatus.EN_ROUTE],
        DeliveryStatus.EN_ROUTE: [DeliveryStatus.EN_DESTINO, DeliveryStatus.COMPLETADA, DeliveryStatus.FALLIDA],
        DeliveryStatus.EN_DESTINO: [DeliveryStatus.COMPLETADA, DeliveryStatus.FALLIDA],
    }
    
    current_status = delivery.status
    if current_status in allowed_transitions:
        if new_status not in allowed_transitions[current_status]:
            raise HTTPException(
                status_code=400, 
                detail=f"No se puede cambiar de {current_status.value} a {new_status.value}. Transiciones validas: {[s.value for s in allowed_transitions[current_status]]}"
            )
    
    # CORRECCIÓN CRÍTICA: Usar fecha naive para compatibilidad con PostgreSQL TIMESTAMP WITHOUT TIME ZONE
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    
    if new_status == DeliveryStatus.EN_PICKUP:
        delivery.status = DeliveryStatus.EN_PICKUP
        delivery.arrived_pickup_at = now
        
        order_result = await db.execute(select(Order).where(Order.id == delivery.order_id))
        order = order_result.scalar_one_or_none()
        if order:
            order.status = OrderStatus.RECOLECTADO
            order.picked_up_at = now
        
    elif new_status == DeliveryStatus.EN_ROUTE:
        delivery.status = DeliveryStatus.EN_ROUTE
        delivery.left_pickup_at = now
        if body.lat and body.lng:
            delivery.current_latitude = body.lat
            delivery.current_longitude = body.lng
            
        order_result = await db.execute(select(Order).where(Order.id == delivery.order_id))
        order = order_result.scalar_one_or_none()
        if order:
            order.status = OrderStatus.EN_RUTA
        
    elif new_status == DeliveryStatus.EN_DESTINO:
        delivery.status = DeliveryStatus.EN_DESTINO
        delivery.arrived_delivery_at = now
        
        order_result = await db.execute(select(Order).where(Order.id == delivery.order_id))
        order = order_result.scalar_one_or_none()
        if order:
            order.status = OrderStatus.EN_RUTA
        
    elif new_status == DeliveryStatus.COMPLETADA:
        if body.otp_code and delivery.proof_otp and body.otp_code != delivery.proof_otp:
            raise HTTPException(status_code=400, detail="Código OTP incorrecto")
        
        delivery.status = DeliveryStatus.COMPLETADA
        delivery.completed_at = now
        delivery.proof_notes = body.notes
        delivery.customer_name_received = body.customer_name_received
        if body.lat and body.lng:
            delivery.current_latitude = body.lat
            delivery.current_longitude = body.lng
        
        if delivery.started_at:
            # Asegurar que started_at sea naive si viene con tzinfo para la resta
            start_time = delivery.started_at
            if start_time.tzinfo is not None:
                start_time = start_time.replace(tzinfo=None)
            
            elapsed_minutes = max(0, int((now - start_time).total_seconds() / 60))
            delivery.sla_actual_minutes = elapsed_minutes
            if delivery.sla_expected_minutes is not None:
                delivery.sla_compliant = elapsed_minutes <= delivery.sla_expected_minutes
        
        order_result = await db.execute(select(Order).where(Order.id == delivery.order_id))
        order = order_result.scalar_one_or_none()
        if order:
            order.status = OrderStatus.ENTREGADO
            order.delivered_at = now
        
        # FASE 1 + FASE 3: Crear registro financiero con multiplicador de zona
        idempotency_key = f"pago_entrega_{delivery.order_id}"
        financial_result = await db.execute(select(Financial).where(Financial.idempotency_key == idempotency_key))
        existing_financial = financial_result.scalar_one_or_none()
        
        if not existing_financial and delivery.rider_id:
            settings_result = await db.execute(
                select(PlatformSetting.value).where(PlatformSetting.key == "rider_delivery_bonus")
            )
            bonus_value = settings_result.scalar_one_or_none()
            base_payment = Decimal(str(bonus_value)) if bonus_value is not None else Decimal("2.50")
            
            # FASE 3: Obtener multiplicador de la zona del rider
            multiplier = Decimal("1.0")
            rider_obj = await _get_rider_for_user(db, rider.id)
            
            if rider_obj and rider_obj.zone_id:
                zone_result = await db.execute(
                    select(Zone.bonus_multiplier).where(Zone.id == rider_obj.zone_id)
                )
                zone_mult = zone_result.scalar_one_or_none()
                if zone_mult is not None:
                    multiplier = Decimal(str(zone_mult))
            
            final_payment = base_payment * multiplier
            
            financial = Financial(
                rider_id=delivery.rider_id,
                amount=final_payment,
                transaction_type=TransactionType.PAGO_ENTREGA,
                description=f"Pago por entrega (Orden {order.external_id if order else delivery.order_id}) - Mult. Zona: {multiplier}",
                reference_id=str(order.id) if order else str(delivery.order_id),
                source_type="delivery",
                source_id=str(delivery.id),
                idempotency_key=idempotency_key,
                status=PaymentStatus.PROCESADO,
            )
            db.add(financial)
            logger.info(f"Pago calculado: Base {base_payment} * Mult {multiplier} = {final_payment}")
            
    elif new_status == DeliveryStatus.FALLIDA:
        if not body.issue_type:
            raise HTTPException(status_code=400, detail="El motivo del fallo es requerido")
        
        # Analizar la causa usando el analizador de texto para determinar si hay bono
        analysis = DeliveryIssueAnalyzer.analyze(body.issue_description)
        is_external_cause = analysis["is_external_fault"]
        analysis_reason = analysis["reason"]
        
        delivery.status = DeliveryStatus.FALLIDA
        delivery.has_issues = True
        delivery.issue_type = body.issue_type
        delivery.issue_description = body.issue_description
        delivery.issue_analysis_result = analysis_reason if hasattr(delivery, 'issue_analysis_result') else body.issue_description
        
        order_result = await db.execute(select(Order).where(Order.id == delivery.order_id))
        order = order_result.scalar_one_or_none()
        if order:
            order.status = OrderStatus.FALLIDO
            order.failure_reason = body.issue_type
            order.failure_notes = body.issue_description
        
        # FASE 2: Crear registro financiero por intento fallido si corresponde
        bonus_applied = False
        bonus_amount = Decimal("0.00")
        
        if delivery.rider_id:
            # Determinar si se debe pagar: usa issue_type O el análisis de texto
            customer_fault_reasons = ["cliente_no_esta", "direccion_incorrecta", "cliente_rechaza", "otro_cliente"]
            should_pay_rider = body.issue_type.lower() in customer_fault_reasons or is_external_cause
            
            if should_pay_rider:
                idempotency_key = f"pago_fallido_{delivery.order_id}"
                financial_result = await db.execute(select(Financial).where(Financial.idempotency_key == idempotency_key))
                existing_financial = financial_result.scalar_one_or_none()
                
                if not existing_financial:
                    settings_result = await db.execute(
                        select(PlatformSetting.value).where(PlatformSetting.key == "rider_failed_attempt_bonus")
                    )
                    bonus_value = settings_result.scalar_one_or_none()
                    failed_payment = Decimal(str(bonus_value)) if bonus_value is not None else Decimal("1500.00")
                    
                    financial = Financial(
                        rider_id=delivery.rider_id,
                        amount=failed_payment,
                        transaction_type=TransactionType.PAGO_INTENTO_FALLIDO,
                        description=f"Pago por intento fallido (orden {order.external_id if order else delivery.order_id}) - Motivo: {body.issue_type}. Análisis: {analysis_reason}",
                        reference_id=str(order.id) if order else str(delivery.order_id),
                        source_type="delivery_failed",
                        source_id=str(delivery.id),
                        idempotency_key=idempotency_key,
                        status=PaymentStatus.PROCESADO,
                    )
                    db.add(financial)
                    bonus_applied = True
                    bonus_amount = failed_payment
                    logger.info(f"Registro financiero creado para entrega fallida {delivery.id} - Rider {delivery.rider_id} - Bono: {failed_payment}")
    
    await db.flush()
    await db.commit()
    
    await db.refresh(delivery, attribute_names=['rider', 'order'])
    if delivery.rider:
        await db.refresh(delivery.rider, attribute_names=['user'])
    
    r_alias = aliased(Rider)
    u_alias = aliased(User)
    o_alias = aliased(Order)
    final_stmt = (
        select(Delivery, r_alias, u_alias, o_alias)
        .outerjoin(r_alias, Delivery.rider_id == r_alias.id)
        .outerjoin(u_alias, r_alias.user_id == u_alias.id)
        .outerjoin(o_alias, Delivery.order_id == o_alias.id)
        .where(Delivery.id == delivery.id)
    )
    res = await db.execute(final_stmt)
    d_row, r_row, u_row, o_row = res.first()
    
    # Serializar y agregar información del bono aplicado si es estado FALLIDA
    response_data = _serialize_delivery(d_row, r_row, u_row, o_row)
    if new_status == DeliveryStatus.FALLIDA:
        response_data["bonus_applied"] = bonus_applied
        response_data["bonus_amount"] = float(bonus_amount) if bonus_applied else 0.0
        response_data["issue_analysis"] = analysis if 'analysis' in locals() else None
    
    return response_data