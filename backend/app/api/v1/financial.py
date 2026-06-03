from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from typing import List, Optional
from decimal import Decimal
from datetime import datetime, timedelta

from app.core.database import get_db
from app.models.financial import Financial, TransactionType, PaymentStatus
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
    """Resumen financiero global para gerentes."""
    now = datetime.utcnow()
    start_date = None
    
    if period == "today":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        start_date = now - timedelta(days=now.weekday())
        start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "month":
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    if not start_date:
        raise HTTPException(status_code=400, detail="Periodo inválido")

    # Calcular métricas básicas
    result = await db.execute(
        select(
            func.sum(Financial.amount).label('total_revenue'),
            func.count(Financial.id).label('total_transactions')
        ).where(
            Financial.created_at >= start_date,
            Financial.transaction_type.in_([TransactionType.PAGO_ENTREGA, TransactionType.BONO])
        )
    )
    row = result.first()
    
    total_revenue = float(row.total_revenue or 0)
    total_transactions = row.total_transactions or 0

    return {
        "period": period,
        "total_revenue": total_revenue,
        "total_transactions": total_transactions,
        "total_costs": 0, # Implementar lógica de costos si existe
        "net_margin": total_revenue, # Simplificado
        "total_rider_payouts": 0, # Implementar suma de retiros
        "avg_per_delivery": total_revenue / total_transactions if total_transactions > 0 else 0
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