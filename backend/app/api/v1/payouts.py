from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional
from decimal import Decimal
import uuid
import logging

from app.core.database import get_db
from app.models.payout import Payout, PayoutStatus, PayoutMethod, PayoutStatusHistory
from app.models.financial import Financial, TransactionType, PaymentStatus
from app.models.rider import Rider
from app.models.user import User, UserRole
from app.api.v1.auth import get_current_user, require_role
from app.models.rider import utc_now_naive

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/payouts", tags=["Payouts"])


class PayoutRequestBody(BaseModel):
    amount: float = Field(..., gt=0)
    method: PayoutMethod = PayoutMethod.TRANSFERENCIA
    bank_account_last4: Optional[str] = Field(None, max_length=10)


class PayoutRejectBody(BaseModel):
    reason: Optional[str] = Field(None, max_length=500)
    rejection_reason: Optional[str] = Field(None, max_length=500)


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


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _serialize_payout(payout: Payout):
    amount = float(payout.amount or 0)
    requested_at = payout.requested_at.isoformat() if payout.requested_at else None
    processed_at = payout.processed_at.isoformat() if payout.processed_at else None

    return {
        "id": str(payout.id),
        "rider_id": str(payout.rider_id),
        "amount": amount,
        "total_amount": amount,
        "status": _enum_value(payout.status),
        "method": _enum_value(payout.method),
        "payment_method": _enum_value(payout.method),
        "requested_at": requested_at,
        "created_at": requested_at,
        "updated_at": processed_at or requested_at,
        "processed_at": processed_at,
        "bank_account_last4": payout.bank_account_last4,
        "reference_code": payout.reference_code,
        "rejection_reason": payout.rejection_reason,
        "orders_count": 0,
        "period": "Periodo no especificado",
        "period_start": None,
        "period_end": None,
    }


async def _calculate_available_balance(db: AsyncSession, rider_id) -> dict:
    earnings_result = await db.execute(
        select(func.sum(Financial.amount)).where(
            Financial.rider_id == rider_id,
            Financial.transaction_type.in_([TransactionType.PAGO_ENTREGA, TransactionType.BONO]),
            Financial.status.in_([PaymentStatus.PROCESADO, PaymentStatus.PAGADO]),
        )
    )
    total_earned = float(earnings_result.scalar() or 0)

    pending_result = await db.execute(
        select(func.sum(Payout.amount)).where(
            Payout.rider_id == rider_id,
            Payout.status == PayoutStatus.PENDIENTE,
        )
    )
    pending = float(pending_result.scalar() or 0)

    processed_result = await db.execute(
        select(func.sum(Payout.amount)).where(
            Payout.rider_id == rider_id,
            Payout.status == PayoutStatus.PROCESADO,
        )
    )
    processed = float(processed_result.scalar() or 0)

    available = max(0, total_earned - pending - processed)
    return {
        "available": round(available, 2),
        "pending": round(pending, 2),
        "processed": round(processed, 2),
        "total_earned": round(total_earned, 2),
        "currency": "COP",
    }


@router.get("")
@router.get("/")
async def list_payouts(
    rider_id: Optional[str] = Query(None, description="Filtrar por ID de repartidor"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status_filter: Optional[PayoutStatus] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Listar retiros reales. Riders ven solo sus retiros; gerentes/superadmins ven todos."""
    if current_user.role == UserRole.REPARTIDOR:
        rider = await _get_rider_from_user(db, current_user)
        stmt = select(Payout).where(Payout.rider_id == rider.id)
    elif current_user.role in [UserRole.GERENTE, UserRole.SUPERADMIN]:
        stmt = select(Payout)
        if rider_id:
            stmt = stmt.where(Payout.rider_id == _parse_uuid(rider_id))
    else:
        raise HTTPException(status_code=403, detail="Acceso denegado")

    if status_filter:
        stmt = stmt.where(Payout.status == status_filter)

    stmt = stmt.order_by(Payout.requested_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    payouts = result.scalars().all()

    return [_serialize_payout(p) for p in payouts]


@router.get("/balance")
async def get_available_balance(
    rider_id: Optional[str] = Query(None, description="ID de repartidor para gerentes/superadmins"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Obtener saldo real disponible para retiro."""
    if current_user.role == UserRole.REPARTIDOR:
        rider = await _get_rider_from_user(db, current_user)
        target_rider_id = rider.id
    elif current_user.role in [UserRole.GERENTE, UserRole.SUPERADMIN]:
        if not rider_id:
            raise HTTPException(status_code=400, detail="rider_id es requerido")
        target_rider_id = _parse_uuid(rider_id)
    else:
        raise HTTPException(status_code=403, detail="Acceso denegado")

    return await _calculate_available_balance(db, target_rider_id)


@router.post("/request", status_code=201)
async def request_payout(
    body: PayoutRequestBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Solicitar un nuevo retiro con payload JSON real."""
    if current_user.role != UserRole.REPARTIDOR:
        raise HTTPException(status_code=403, detail="Solo repartidores pueden solicitar retiros")

    rider = await _get_rider_from_user(db, current_user)
    balance = await _calculate_available_balance(db, rider.id)

    if body.amount > balance["available"]:
        raise HTTPException(
            status_code=400,
            detail=f"Saldo insuficiente. Disponible: {balance['available']:.2f}",
        )

    if body.amount < 10:
        raise HTTPException(status_code=400, detail="El monto mínimo de retiro es 10.00")

    balance_after = available - requested_amount
    payout = Payout(
        rider_id=rider.id,
        amount=Decimal(str(body.amount)),
        method=body.method,
        bank_account_last4=body.bank_account_last4,
        status=PayoutStatus.PENDIENTE,
    )

    db.add(payout)
    await db.flush()
    _add_status_history(
        db,
        payout,
        None,
        PayoutStatus.PENDIENTE,
        current_user,
        "Solicitud de retiro creada",
        available,
        balance_after,
    )
    await db.commit()
    await db.refresh(payout)

    logger.info("Retiro solicitado: %s por rider %s", payout.id, rider.id)
    return _serialize_payout(payout)


@router.get("/{payout_id}")
async def get_payout(
    payout_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Obtener detalle real de un retiro por ID respetando permisos."""
    payout_id_uuid = _parse_uuid(payout_id)

    result = await db.execute(select(Payout).where(Payout.id == payout_id_uuid))
    payout = result.scalar_one_or_none()

    if not payout:
        raise HTTPException(status_code=404, detail="Retiro no encontrado")

    if current_user.role == UserRole.REPARTIDOR:
        rider = await _get_rider_from_user(db, current_user)
        if payout.rider_id != rider.id:
            raise HTTPException(status_code=403, detail="No tienes permiso para acceder a este retiro")
    elif current_user.role not in [UserRole.GERENTE, UserRole.SUPERADMIN]:
        raise HTTPException(status_code=403, detail="Acceso denegado")

    return _serialize_payout(payout)


@router.patch("/{payout_id}/approve")
async def approve_payout(
    payout_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.GERENTE, UserRole.SUPERADMIN)),
):
    """Aprobar un retiro y registrar la transacción financiera de salida."""
    result = await db.execute(select(Payout).where(Payout.id == _parse_uuid(payout_id)))
    payout = result.scalar_one_or_none()
    if not payout:
        raise HTTPException(status_code=404, detail="Retiro no encontrado")

    if payout.status != PayoutStatus.PENDIENTE:
        raise HTTPException(status_code=400, detail="Solo se pueden aprobar retiros pendientes")

    payout.status = PayoutStatus.PROCESADO
    payout.processed_at = utc_now_naive()
    payout.reference_code = f"PAY-{payout.processed_at.strftime('%Y%m%d')}-{str(payout.id)[:8].upper()}"

    transaction = Financial(
        rider_id=payout.rider_id,
        amount=payout_amount,
        balance_before=balance_before,
        balance_after=balance_after,
        transaction_type=TransactionType.RETIRO,
        description=f"Retiro aprobado: {payout.reference_code}",
        reference_id=str(payout.id),
        status=PaymentStatus.PROCESADO,
    )
    db.add(transaction)
    _add_status_history(
        db,
        payout,
        old_status,
        PayoutStatus.PROCESADO,
        current_user,
        f"Retiro aprobado: {payout.reference_code}",
        balance_before,
        balance_after,
    )
    await db.commit()
    await db.refresh(payout)

    return _serialize_payout(payout)


@router.patch("/{payout_id}/reject")
async def reject_payout(
    payout_id: str,
    body: PayoutRejectBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.GERENTE, UserRole.SUPERADMIN)),
):
    """Rechazar un retiro pendiente con motivo enviado en JSON."""
    reason = (body.rejection_reason or body.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Motivo de rechazo requerido")

    result = await db.execute(select(Payout).where(Payout.id == _parse_uuid(payout_id)))
    payout = result.scalar_one_or_none()
    if not payout:
        raise HTTPException(status_code=404, detail="Retiro no encontrado")

    if payout.status != PayoutStatus.PENDIENTE:
        raise HTTPException(status_code=400, detail="Solo se pueden rechazar retiros pendientes")

    payout.status = PayoutStatus.RECHAZADO
    payout.rejection_reason = reason
    payout.processed_at = utc_now_naive()
    payout.updated_at = payout.processed_at
    payout.processed_by_user_id = current_user.id
    payout.balance_before = balance_before
    payout.balance_after = balance_after

    _add_status_history(
        db,
        payout,
        old_status,
        PayoutStatus.RECHAZADO,
        current_user,
        reason,
        balance_before,
        balance_after,
    )
    await db.commit()
    await db.refresh(payout)
    return _serialize_payout(payout)
