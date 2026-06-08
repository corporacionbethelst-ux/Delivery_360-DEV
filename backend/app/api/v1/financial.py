from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case
from sqlalchemy.orm import selectinload
from typing import Optional
from datetime import datetime, timedelta

from app.core.database import get_db
from app.models.financial import Financial, TransactionType, PaymentStatus
from app.models.order import Order, OrderStatus
from app.models.payout import Payout, PayoutStatus
from app.models.rider import Rider
from app.models.user import User, UserRole
from app.api.v1.auth import get_current_user, require_role

router = APIRouter(prefix="/financial", tags=["Financial"])

@router.get("/riders/me")
async def get_my_earnings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Obtener resumen de ganancias del repartidor actual."""
    if current_user.role != UserRole.REPARTIDOR:
        raise HTTPException(status_code=403, detail="Acceso denegado")

    # Obtener rider
    result = await db.execute(
        select(Rider)
        .options(selectinload(Rider.user))
        .where(Rider.user_id == current_user.id)
    )
    rider = result.scalar_one_or_none()
    if not rider:
        raise HTTPException(status_code=404, detail="Perfil de repartidor no encontrado")

    # 1. Calcular Total Ganado (Suma de entregas y bonos procesados)
    earnings_result = await db.execute(
        select(func.sum(Financial.amount)).where(
            Financial.rider_id == rider.id,
            Financial.transaction_type.in_([TransactionType.PAGO_ENTREGA, TransactionType.BONO]),
            Financial.status == PaymentStatus.PROCESADO
        )
    )
    total_earned = float(earnings_result.scalar() or 0)

    # 2. Calcular Total Retirado (Suma de retiros PROCESADOS)
    # Nota: No restamos los PENDIENTE aquí para que el frontend calcule el "pending_payout" correctamente
    withdrawn_result = await db.execute(
        select(func.sum(Financial.amount)).where(
            Financial.rider_id == rider.id,
            Financial.transaction_type == TransactionType.RETIRO,
            Financial.status == PaymentStatus.PROCESADO
        )
    )
    total_withdrawn = float(withdrawn_result.scalar() or 0)
    
    # Contar entregas completadas (transacciones de tipo PAGO_ENTREGA)
    deliveries_count_result = await db.execute(
        select(func.count(Financial.id)).where(
            Financial.rider_id == rider.id,
            Financial.transaction_type == TransactionType.PAGO_ENTREGA
        )
    )
    completed_deliveries = deliveries_count_result.scalar() or 0

    # El saldo pendiente es lo ganado menos lo que ya se ha retirado (procesado)
    pending_payout = total_earned - total_withdrawn

    return {
        "rider_id": str(rider.id),
        "rider_name": f"{rider.user.first_name} {rider.user.last_name}",
        "total_earned": total_earned,
        "completed_deliveries": completed_deliveries,
        "pending_payout": max(0, pending_payout) # Evitar negativos
    }

@router.get("/summary")
async def get_financial_summary(
    period: str = Query("today", description="today, week, month"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.GERENTE, UserRole.SUPERADMIN)),
):
    """Resumen financiero global para gerentes basado en datos reales de BD."""
    now = datetime.utcnow()
    period = (period or "today").lower().strip()

    if period == "today":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        start_date = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    elif period == "month":
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        raise HTTPException(status_code=400, detail="Periodo inválido")

    paid_statuses = ["PAGADO", "PAID", "COMPLETADO", "COMPLETADA", "PROCESADO"]
    order_period_date = func.coalesce(Order.delivered_at, Order.updated_at, Order.created_at, Order.ordered_at)

    revenue_result = await db.execute(
        select(
            func.coalesce(func.sum(Order.delivery_fee), 0).label("total_revenue"),
            func.count(Order.id).label("completed_deliveries"),
            func.coalesce(func.sum(Order.total), 0).label("gross_order_value"),
        ).where(
            Order.status == OrderStatus.ENTREGADO,
            order_period_date >= start_date,
            func.upper(func.coalesce(Order.payment_status, "")).in_(paid_statuses),
        )
    )
    revenue_row = revenue_result.one()
    total_revenue = float(revenue_row.total_revenue or 0)
    completed_deliveries = int(revenue_row.completed_deliveries or 0)
    gross_order_value = float(revenue_row.gross_order_value or 0)

    financial_period_filters = [Financial.created_at >= start_date]

    transactions_result = await db.execute(
        select(func.count(Financial.id)).where(*financial_period_filters)
    )
    total_transactions = int(transactions_result.scalar() or 0)

    rider_earnings_result = await db.execute(
        select(func.coalesce(func.sum(Financial.amount), 0)).where(
            *financial_period_filters,
            Financial.transaction_type.in_([TransactionType.PAGO_ENTREGA, TransactionType.BONO]),
            Financial.status.in_([PaymentStatus.PROCESADO, PaymentStatus.PAGADO]),
        )
    )
    earned_rider_payouts = float(rider_earnings_result.scalar() or 0)

    deductions_result = await db.execute(
        select(func.coalesce(func.sum(Financial.amount), 0)).where(
            *financial_period_filters,
            Financial.transaction_type == TransactionType.DESCUENTO,
            Financial.status.in_([PaymentStatus.PROCESADO, PaymentStatus.PAGADO]),
        )
    )
    rider_deductions = float(deductions_result.scalar() or 0)

    adjustments_result = await db.execute(
        select(func.coalesce(func.sum(Financial.amount), 0)).where(
            *financial_period_filters,
            Financial.transaction_type == TransactionType.AJUSTE,
            Financial.status.in_([PaymentStatus.PROCESADO, PaymentStatus.PAGADO]),
        )
    )
    operational_adjustments = float(adjustments_result.scalar() or 0)

    payout_period_date = func.coalesce(Payout.processed_at, Payout.requested_at)
    processed_payouts_result = await db.execute(
        select(func.coalesce(func.sum(Payout.amount), 0)).where(
            payout_period_date >= start_date,
            Payout.status == PayoutStatus.PROCESADO,
        )
    )
    processed_cash_payouts = float(processed_payouts_result.scalar() or 0)

    # PAGO_ENTREGA/BONO representa el costo operativo devengado por rider.
    # Payout representa salida de caja. Se usa el mayor para soportar instalaciones
    # que aún no registran ambas capas y evitar doble conteo cuando sí existen.
    total_rider_payouts = max(0, max(earned_rider_payouts - rider_deductions, processed_cash_payouts))
    other_costs = max(0, operational_adjustments)
    total_costs = total_rider_payouts + other_costs
    net_margin = total_revenue - total_costs

    return {
        "period": period,
        "period_start": start_date.isoformat(),
        "period_end": now.isoformat(),
        "total_revenue": round(total_revenue, 2),
        "gross_order_value": round(gross_order_value, 2),
        "completed_deliveries": completed_deliveries,
        "total_transactions": total_transactions,
        "total_costs": round(total_costs, 2),
        "net_margin": round(net_margin, 2),
        "total_rider_payouts": round(total_rider_payouts, 2),
        "other_costs": round(other_costs, 2),
        "avg_per_delivery": round(total_revenue / completed_deliveries, 2) if completed_deliveries > 0 else 0,
        "cash_payouts_processed": round(processed_cash_payouts, 2),
        "rider_earnings_accrued": round(earned_rider_payouts, 2),
        "rider_deductions": round(rider_deductions, 2),
    }


@router.get("/reports/orders")
async def get_orders_financial_report(
    date_from: Optional[str] = Query(None, description="Fecha inicial ISO o YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="Fecha final ISO o YYYY-MM-DD"),
    limit: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.GERENTE, UserRole.SUPERADMIN)),
):
    """Reporte financiero/exportable de órdenes basado en datos reales de BD."""
    start_date = _parse_report_datetime(date_from, "date_from", end_of_day=False) if date_from else None
    end_date = _parse_report_datetime(date_to, "date_to", end_of_day=True) if date_to else None

    date_column = func.coalesce(Order.delivered_at, Order.created_at, Order.ordered_at)
    filters = []

    if start_date:
        filters.append(date_column >= start_date)
    if end_date:
        filters.append(date_column <= end_date)

    base_stmt = select(Order)
    if filters:
        base_stmt = base_stmt.where(*filters)

    orders_result = await db.execute(
        base_stmt.order_by(date_column.desc()).offset(offset).limit(limit)
    )
    orders = orders_result.scalars().all()

    stats_stmt = select(
        func.coalesce(func.sum(Order.delivery_fee), 0).label("total_revenue"),
        func.coalesce(func.sum(Order.total), 0).label("gross_order_value"),
        func.count(Order.id).label("total_orders"),
        func.coalesce(
            func.sum(
                case((Order.status == OrderStatus.ENTREGADO, 1), else_=0)
            ),
            0,
        ).label("completed_orders"),
        func.count(
            func.distinct(
                func.coalesce(Order.customer_email, Order.customer_phone, Order.customer_name)
            )
        ).label("active_customers"),
    )
    if filters:
        stats_stmt = stats_stmt.where(*filters)

    stats_result = await db.execute(stats_stmt)
    stats = stats_result.one()

    status_result = await db.execute(
        (select(Order.status, func.count(Order.id)).where(*filters) if filters else select(Order.status, func.count(Order.id)))
        .group_by(Order.status)
    )

    rows = [_serialize_order_report_row(order) for order in orders]

    return {
        "period_start": start_date.isoformat() if start_date else None,
        "period_end": end_date.isoformat() if end_date else None,
        "total_revenue": float(stats.total_revenue or 0),
        "gross_order_value": float(stats.gross_order_value or 0),
        "total_orders": int(stats.total_orders or 0),
        "completed_orders": int(stats.completed_orders or 0),
        "active_customers": int(stats.active_customers or 0),
        "status_counts": {
            _enum_value(status): count for status, count in status_result.all()
        },
        "rows": rows,
    }

@router.get("/transactions")
async def get_transactions(
    rider_id: Optional[str] = Query(None, description="Filtrar por ID de repartidor"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    transaction_type: Optional[TransactionType] = Query(None, alias="type"),
    status: Optional[PaymentStatus] = Query(None),
    date_from: Optional[str] = Query(None, description="Fecha inicial ISO"),
    date_to: Optional[str] = Query(None, description="Fecha final ISO"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Obtener lista de transacciones financieras.
    - Repartidores solo pueden ver sus propias transacciones.
    - Admin/Gerente pueden ver todas o filtrar por rider_id.
    """
    rider_filter = await _resolve_transaction_rider_filter(db, current_user, rider_id)

    stmt = select(Financial)

    if rider_filter:
        stmt = stmt.where(Financial.rider_id == rider_filter)

    if transaction_type:
        stmt = stmt.where(Financial.transaction_type == transaction_type)

    if status:
        stmt = stmt.where(Financial.status == status)

    if date_from:
        stmt = stmt.where(Financial.created_at >= _parse_datetime_param(date_from, "date_from"))

    if date_to:
        stmt = stmt.where(Financial.created_at <= _parse_datetime_param(date_to, "date_to"))

    stmt = stmt.order_by(Financial.created_at.desc()).offset(offset).limit(limit)

    result = await db.execute(stmt)
    transactions = result.scalars().all()

    return [_serialize_transaction(t) for t in transactions]

@router.get("/transactions/{transaction_id}")
async def get_transaction_detail(
    transaction_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Obtener una transacción financiera real por ID respetando permisos."""
    transaction_uuid = _parse_uuid(transaction_id)

    result = await db.execute(select(Financial).where(Financial.id == transaction_uuid))
    transaction = result.scalar_one_or_none()

    if not transaction:
        raise HTTPException(status_code=404, detail="Transacción no encontrada")

    if current_user.role == UserRole.REPARTIDOR:
        rider_filter = await _resolve_transaction_rider_filter(db, current_user, None)
        if transaction.rider_id != rider_filter:
            raise HTTPException(status_code=403, detail="No tienes permiso para ver esta transacción")
    elif current_user.role not in [UserRole.GERENTE, UserRole.SUPERADMIN]:
        raise HTTPException(status_code=403, detail="Acceso denegado")

    return _serialize_transaction(transaction)


def _serialize_order_report_row(order: Order):
    status = _enum_value(order.status)
    return {
        "id": str(order.id),
        "external_id": order.external_id,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "ordered_at": order.ordered_at.isoformat() if order.ordered_at else None,
        "delivered_at": order.delivered_at.isoformat() if order.delivered_at else None,
        "customer_name": order.customer_name,
        "customer_phone": order.customer_phone,
        "customer_email": order.customer_email,
        "pickup_address": order.pickup_address,
        "delivery_address": order.delivery_address,
        "status": status,
        "priority": _enum_value(order.priority),
        "subtotal": float(order.subtotal or 0),
        "delivery_fee": float(order.delivery_fee or 0),
        "total": float(order.total or 0),
        "payment_method": order.payment_method,
        "payment_status": order.payment_status,
        "rider_id": str(order.assigned_rider_id) if order.assigned_rider_id else None,
    }


def _parse_report_datetime(value: str, field_name: str, end_of_day: bool = False):
    try:
        normalized = value.strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        parsed = parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
        if len(value.strip()) == 10:
            parsed = parsed.replace(
                hour=23 if end_of_day else 0,
                minute=59 if end_of_day else 0,
                second=59 if end_of_day else 0,
                microsecond=999999 if end_of_day else 0,
            )
        return parsed
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field_name} inválida")

async def _resolve_transaction_rider_filter(
    db: AsyncSession,
    current_user: User,
    rider_id: Optional[str],
):
    if current_user.role == UserRole.REPARTIDOR:
        result = await db.execute(select(Rider).where(Rider.user_id == current_user.id))
        rider = result.scalar_one_or_none()
        if not rider:
            raise HTTPException(status_code=404, detail="Perfil de repartidor no encontrado")
        return rider.id

    if current_user.role not in [UserRole.GERENTE, UserRole.SUPERADMIN]:
        raise HTTPException(status_code=403, detail="Acceso denegado")

    return _parse_uuid(rider_id) if rider_id else None

def _serialize_transaction(transaction: Financial):
    transaction_type = _enum_value(transaction.transaction_type)
    status = _enum_value(transaction.status)

    return {
        "id": str(transaction.id),
        "rider_id": str(transaction.rider_id),
        "amount": float(transaction.amount or 0),
        "balance_after": float(transaction.balance_after or 0),
        "transaction_type": transaction_type,
        "type": transaction_type,
        "description": transaction.description or "Sin descripción",
        "reference_id": transaction.reference_id,
        "status": status,
        "created_at": transaction.created_at.isoformat() if transaction.created_at else None,
        "updated_at": transaction.updated_at.isoformat() if transaction.updated_at else None,
    }

def _enum_value(value):
    return value.value if hasattr(value, "value") else value

def _parse_datetime_param(value: str, field_name: str):
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field_name} inválida")

def _parse_uuid(value: str):
    import uuid
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID inválido")