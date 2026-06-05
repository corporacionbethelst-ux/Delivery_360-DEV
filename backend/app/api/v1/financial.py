from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from typing import List, Optional
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
    result = await db.execute(select(Rider).where(Rider.user_id == current_user.id))
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
    
    # Opcional: Sumar retiros pendientes para mostrarlos como "no disponibles"
    pending_payouts_result = await db.execute(
        select(func.sum(Financial.amount)).where(
            Financial.rider_id == rider.id,
            Financial.transaction_type == TransactionType.RETIRO,
            Financial.status == PaymentStatus.PENDIENTE
        )
    )
    # En realidad, lo más fácil es calcularlo desde la tabla Payouts directamente en el endpoint de payout
    # Pero para este ejemplo, diremos que pending_payout es lo ganado menos lo ya retirado
    
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

@router.get("/transactions")
async def get_transactions(
    rider_id: Optional[str] = Query(None, description="Filtrar por ID de repartidor"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    transaction_type: Optional[TransactionType] = Query(None, alias="type"),
    status: Optional[PaymentStatus] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Obtener lista de transacciones financieras.
    - Repartidores solo pueden ver sus propias transacciones.
    - Admin/Gerente pueden ver todas o filtrar por rider_id.
    """
    # Validar permisos y determinar filtro de rider
    if current_user.role == UserRole.REPARTIDOR:
        # Repartidor solo ve las suyas
        result = await db.execute(select(Rider).where(Rider.user_id == current_user.id))
        rider = result.scalar_one_or_none()
        if not rider:
            raise HTTPException(status_code=404, detail="Perfil de repartidor no encontrado")
        rider_filter = rider.id
    elif rider_id:
        # Admin puede filtrar por un rider específico
        rider_filter = _parse_uuid(rider_id)
    else:
        # Admin ve todas
        rider_filter = None
    
    # Construir query
    stmt = select(Financial)
    
    if rider_filter:
        stmt = stmt.where(Financial.rider_id == rider_filter)
    
    if transaction_type:
        stmt = stmt.where(Financial.transaction_type == transaction_type)
    
    if status:
        stmt = stmt.where(Financial.status == status)
    
    stmt = stmt.order_by(Financial.created_at.desc()).offset(offset).limit(limit)
    
    result = await db.execute(stmt)
    transactions = result.scalars().all()
    
    return [
        {
            "id": str(t.id),
            "rider_id": str(t.rider_id),
            "amount": float(t.amount),
            "transaction_type": t.transaction_type.value,
            "description": t.description,
            "reference_id": t.reference_id,
            "status": t.status.value,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in transactions
    ]

def _parse_uuid(value: str):
    import uuid
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID inválido")