from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional
from decimal import Decimal
import uuid
import logging

from app.core.database import get_db
from app.models.payout import Payout, PayoutStatus, PayoutMethod
from app.models.financial import Financial, TransactionType, PaymentStatus
from app.models.rider import Rider
from app.models.user import User, UserRole
from app.api.v1.auth import get_current_user, require_role
from app.models.rider import utc_now_naive

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/payouts", tags=["Payouts"])

def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID inválido")

async def _get_rider_from_user(db: AsyncSession, user: User) -> Rider:
    result = await db.execute(select(Rider).where(Rider.user_id == user.id))
    rider = result.scalar_one_or_none()
    if not rider:
        raise HTTPException(status_code=404, detail="Perfil de repartidor no encontrado")
    return rider

@router.get("/")
async def list_payouts(
    limit: int = Query(50, ge=1, le=100),
    status_filter: Optional[PayoutStatus] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Listar retiros del usuario actual (o todos si es admin)."""
    rider = None
    if current_user.role == UserRole.REPARTIDOR:
        rider = await _get_rider_from_user(db, current_user)
        stmt = select(Payout).where(Payout.rider_id == rider.id)
    else:
        # Admin ve todos
        stmt = select(Payout)

    if status_filter:
        stmt = stmt.where(Payout.status == status_filter)

    stmt = stmt.order_by(Payout.requested_at.desc()).limit(limit)
    
    result = await db.execute(stmt)
    payouts = result.scalars().all()

    return [
        {
            "id": str(p.id),
            "rider_id": str(p.rider_id),
            "amount": float(p.amount),
            "status": p.status.value,
            "method": p.method.value,
            "requested_at": p.requested_at.isoformat() if p.requested_at else None,
            "processed_at": p.processed_at.isoformat() if p.processed_at else None,
            "bank_account_last4": p.bank_account_last4,
            "reference_code": p.reference_code,
            "rejection_reason": p.rejection_reason,
            "orders_count": 0,
            "period": "Semana actual",
        }
        for p in payouts
    ]

@router.post("/request", status_code=201)
async def request_payout(
    amount: float,
    method: PayoutMethod = PayoutMethod.TRANSFERENCIA,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Solicitar un nuevo retiro."""
    if current_user.role != UserRole.REPARTIDOR:
        raise HTTPException(status_code=403, detail="Solo repartidores pueden solicitar retiros")

    rider = await _get_rider_from_user(db, current_user)
    
    # Calcular saldo disponible (Total ganado - Total retirado procesado)
    # 1. Sumar transacciones positivas (entregas, bonos)
    earnings_result = await db.execute(
        select(func.sum(Financial.amount)).where(
            Financial.rider_id == rider.id,
            Financial.transaction_type.in_([TransactionType.PAGO_ENTREGA, TransactionType.BONO]),
            Financial.status == PaymentStatus.PROCESADO
        )
    )
    total_earned = float(earnings_result.scalar() or 0)

    # 2. Sumar retiros ya procesados o pendientes (dinero que ya salió o está saliendo)
    payouts_result = await db.execute(
        select(func.sum(Payout.amount)).where(
            Payout.rider_id == rider.id,
            Payout.status.in_([PayoutStatus.PROCESADO, PayoutStatus.PENDIENTE])
        )
    )
    total_withdrawn = float(payouts_result.scalar() or 0)

    available_balance = total_earned - total_withdrawn

    if amount > available_balance:
        raise HTTPException(
            status_code=400, 
            detail=f"Saldo insuficiente. Disponible: {available_balance:.2f}"
        )
    
    if amount < 10:
        raise HTTPException(status_code=400, detail="El monto mínimo de retiro es 10.00")

    payout = Payout(
        rider_id=rider.id,
        amount=Decimal(str(amount)),
        method=method,
        status=PayoutStatus.PENDIENTE
        # Aquí podrías agregar lógica para obtener los últimos 4 dígitos de la cuenta
    )
    
    db.add(payout)
    await db.commit()
    await db.refresh(payout)

    logger.info(f"Retiro solicitado: {payout.id} por rider {rider.id}")
    
    return {
        "id": str(payout.id),
        "rider_id": str(payout.rider_id),
        "amount": float(payout.amount),
        "status": payout.status.value,
        "method": payout.method.value,
        "requested_at": payout.requested_at.isoformat(),
        "reference_code": payout.reference_code,
        "rejection_reason": payout.rejection_reason,
    }

@router.get("/{payout_id}")
async def get_payout(
    payout_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Obtener detalle de un retiro específico por su ID.
    - Repartidores solo pueden ver sus propios retiros.
    - Admin/Gerente pueden ver todos los retiros.
    """
    payout_id_uuid = _parse_uuid(payout_id)
    
    result = await db.execute(select(Payout).where(Payout.id == payout_id_uuid))
    payout = result.scalar_one_or_none()
    
    if not payout:
        raise HTTPException(status_code=404, detail="Retiro no encontrado")
    
    # Validar permisos: REPARTIDOR solo puede ver sus propios retiros
    if current_user.role == UserRole.REPARTIDOR:
        rider = await _get_rider_from_user(db, current_user)
        if payout.rider_id != rider.id:
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso para acceder a este retiro"
            )
    
    return {
        "id": str(payout.id),
        "rider_id": str(payout.rider_id),
        "amount": float(payout.amount),
        "status": payout.status.value,
        "method": payout.method.value,
        "requested_at": payout.requested_at.isoformat() if payout.requested_at else None,
        "processed_at": payout.processed_at.isoformat() if payout.processed_at else None,
        "bank_account_last4": payout.bank_account_last4,
        "reference_code": payout.reference_code,
        "rejection_reason": payout.rejection_reason,
    }

@router.patch("/{payout_id}/approve")
async def approve_payout(
    payout_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.GERENTE, UserRole.SUPERADMIN)),
):
    """Aprobar un retiro (Admin)."""
    result = await db.execute(select(Payout).where(Payout.id == _parse_uuid(payout_id)))
    payout = result.scalar_one_or_none()
    if not payout:
        raise HTTPException(status_code=404, detail="Retiro no encontrado")

    payout.status = PayoutStatus.PROCESADO
    payout.processed_at = utc_now_naive()
    # Generar código de referencia simulado
    import random
    payout.reference_code = f"REF-{random.randint(10000, 99999)}"

    # Registrar transacción de salida
    transaction = Financial(
        rider_id=payout.rider_id,
        amount=payout.amount,
        transaction_type=TransactionType.RETIRO,
        description=f"Retiro aprobado: {payout.reference_code}",
        reference_id=str(payout.id),
        status=PaymentStatus.PROCESADO
    )
    db.add(transaction)
    await db.commit()

    return {"message": "Retiro aprobado", "reference_code": payout.reference_code}

@router.patch("/{payout_id}/reject")
async def reject_payout(
    payout_id: str,
    reason: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.GERENTE, UserRole.SUPERADMIN)),
):
    """Rechazar un retiro (Admin)."""
    result = await db.execute(select(Payout).where(Payout.id == _parse_uuid(payout_id)))
    payout = result.scalar_one_or_none()
    if not payout:
        raise HTTPException(status_code=404, detail="Retiro no encontrado")

    payout.status = PayoutStatus.RECHAZADO
    payout.rejection_reason = reason
    payout.processed_at = utc_now_naive()

    await db.commit()
    return {"message": "Retiro rechazado", "reason": reason}