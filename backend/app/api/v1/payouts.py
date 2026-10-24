from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select, func, case, cast, String, or_, and_
from typing import Optional
from decimal import Decimal
import asyncio
import uuid
import logging

from app.core.database import get_db
from app.models.payout import Payout, PayoutStatus, PayoutMethod, PayoutStatusHistory
from app.models.financial import Financial, TransactionType, PaymentStatus
from app.services.financial_service import (
    FinancialService,
    CREDIT_TYPES,
    processed_ledger_filter,
)
from app.services.redis_audit_service import get_redis_audit_logger
from app.services.audit_service import get_audit_service
from app.models.rider import Rider
from app.models.user import User, UserRole
from app.models.order import Order, OrderStatus
from app.api.v1.auth import get_current_user, require_role
from app.models.rider import utc_now_naive
from app.models.audit_log import ActionType

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/payouts", tags=["Payouts"])


def _enum_value(value):
    """Obtiene el valor del enum (soporta enums de SQLAlchemy y strings)."""
    return value.value if hasattr(value, "value") else value


def _order_earning_amount_expr():
    return case(
        (Order.delivery_fee > 0, Order.delivery_fee),
        (Order.total > 0, Order.total),
        else_=Order.subtotal,
    )


class PayoutRequestBody(BaseModel):
    amount: Decimal = Field(
        ..., gt=0, le=Decimal("99999999.99"), max_digits=10, decimal_places=2
    )
    method: PayoutMethod = PayoutMethod.TRANSFERENCIA
    bank_account_last4: Optional[str] = Field(None, pattern=r"^[0-9]{4}$")
    idempotency_key: Optional[str] = Field(None, min_length=1, max_length=100)

    @field_validator("idempotency_key")
    @classmethod
    def nonblank_key(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError("La clave de idempotencia no puede estar vacía")
        return value


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
        raise HTTPException(
            status_code=404, detail="Perfil de repartidor no encontrado"
        )
    return rider


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def _float_money(value) -> float:
    return float(_money(value))


def _serialize_payout(payout: Payout):
    amount = _float_money(payout.amount)
    requested_at = payout.requested_at.isoformat() if payout.requested_at else None
    processed_at = payout.processed_at.isoformat() if payout.processed_at else None
    updated_at = (
        payout.updated_at.isoformat()
        if getattr(payout, "updated_at", None)
        else processed_at or requested_at
    )

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
        "updated_at": updated_at,
        "processed_at": processed_at,
        "bank_account_last4": payout.bank_account_last4,
        "reference_code": payout.reference_code,
        "rejection_reason": payout.rejection_reason,
        "balance_before": _float_money(payout.balance_before),
        "balance_after": _float_money(payout.balance_after),
        "requested_by_user_id": (
            str(payout.requested_by_user_id) if payout.requested_by_user_id else None
        ),
        "processed_by_user_id": (
            str(payout.processed_by_user_id) if payout.processed_by_user_id else None
        ),
        "idempotency_key": payout.idempotency_key,
        "orders_count": 0,
        "period": "Periodo no especificado",
        "period_start": None,
        "period_end": None,
    }


def _serialize_status_history(row: PayoutStatusHistory):
    return {
        "id": str(row.id),
        "payout_id": str(row.payout_id),
        "old_status": row.old_status,
        "new_status": row.new_status,
        "reason": row.reason,
        "changed_by_user_id": (
            str(row.changed_by_user_id) if row.changed_by_user_id else None
        ),
        "balance_before": _float_money(row.balance_before),
        "balance_after": _float_money(row.balance_after),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def _calculate_available_balance(
    db: AsyncSession, rider_id, exclude_payout_id=None
) -> dict:
    rider_uuid = uuid.UUID(str(rider_id))
    ledger_balance = await FinancialService(db).get_current_balance(rider_uuid)
    earnings_result = await db.execute(
        select(func.sum(func.abs(Financial.amount))).where(
            Financial.rider_id == rider_uuid,
            Financial.transaction_type.in_(list(CREDIT_TYPES)),
            processed_ledger_filter(),
        )
    )
    total_earned = _money(earnings_result.scalar())
    # A recorded withdrawal already reduced the ledger. Only unposted
    # requests reserve more money; legacy completed payouts remain held until
    # a matching debit is reconciled, so completion never restores funds.
    payout_ref = func.lower(func.replace(cast(Payout.id, String), "-", ""))
    posted = (
        select(Financial.id)
        .where(
            Financial.rider_id == Payout.rider_id,
            Financial.transaction_type == TransactionType.RETIRO,
            processed_ledger_filter(),
            func.abs(Financial.amount) == Payout.amount,
            or_(
                and_(
                    Financial.source_type == "PAYOUT",
                    func.lower(func.replace(Financial.source_id, "-", ""))
                    == payout_ref,
                ),
                func.lower(func.replace(Financial.reference_id, "-", "")) == payout_ref,
            ),
        )
        .exists()
    )
    statement = select(Payout.status, Payout.amount, posted.label("posted")).where(
        Payout.rider_id == rider_uuid,
        or_(
            Payout.status.is_(None),
            Payout.status.in_(
                [
                    PayoutStatus.PENDIENTE,
                    PayoutStatus.APROBADO,
                    PayoutStatus.EN_PROCESO,
                    PayoutStatus.COMPLETADO,
                ]
            ),
        ),
    )
    if exclude_payout_id:
        statement = statement.where(Payout.id != uuid.UUID(str(exclude_payout_id)))
    rows = (await db.execute(statement)).all()
    pending = Decimal("0.00")
    processed = Decimal("0.00")
    reserved = Decimal("0.00")
    for row in rows:
        amount = _money(row.amount)
        if not amount.is_finite() or amount <= 0:
            raise HTTPException(
                status_code=409, detail="Una reserva histórica requiere revisión"
            )
        if row.status in (None, PayoutStatus.PENDIENTE, PayoutStatus.APROBADO):
            pending += amount
        else:
            processed += amount
        if not row.posted:
            reserved += amount
    return {
        "available": _float_money(max(Decimal("0.00"), ledger_balance - reserved)),
        "pending": _float_money(pending),
        "processed": _float_money(processed),
        "total_earned": _float_money(total_earned),
        "currency": "COP",
        "ledger_balance": _float_money(ledger_balance),
        "reserved": _float_money(reserved),
    }


async def _lock_payout_rider(db: AsyncSession, rider_id: uuid.UUID | str) -> None:
    if (
        await db.scalar(
            select(Rider.id)
            .where(Rider.id == uuid.UUID(str(rider_id)))
            .with_for_update()
        )
        is None
    ):
        raise HTTPException(
            status_code=404, detail="Perfil de repartidor no encontrado"
        )


async def _notify_requested(
    payout_id: uuid.UUID, user_id: uuid.UUID, amount: Decimal
) -> None:
    """Best-effort inbox record on an independent session; never commit business state."""
    from app.core.database import AsyncSessionLocal
    from app.models.notification import (
        Notification,
        NotificationType,
        NotificationStatus,
    )
    import json

    try:
        async with AsyncSessionLocal() as session:
            session.add(
                Notification(
                    user_id=user_id,
                    notification_type=NotificationType.RETIRO_SOLICITADO,
                    title="Solicitud de retiro creada",
                    message=f"Se ha solicitado un retiro de ${amount:.2f}",
                    data=json.dumps(
                        {"payout_id": str(payout_id), "amount": str(amount)}
                    ),
                    channel="push",
                    status=NotificationStatus.PENDING,
                )
            )
            await session.commit()
    except Exception:
        logger.warning("No se pudo registrar la notificación de solicitud de retiro")


def _add_status_history(
    db: AsyncSession,
    payout: Payout,
    old_status: Optional[PayoutStatus],
    new_status: PayoutStatus,
    user: User,
    reason: Optional[str],
    balance_before,
    balance_after,
) -> None:
    db.add(
        PayoutStatusHistory(
            payout_id=payout.id,
            old_status=_enum_value(old_status) if old_status else None,
            new_status=_enum_value(new_status),
            reason=reason,
            changed_by_user_id=user.id,
            balance_before=_money(balance_before),
            balance_after=_money(balance_after),
        )
    )


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
    rider_id: Optional[str] = Query(
        None, description="ID de repartidor para gerentes/superadmins"
    ),
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

    try:
        return await _calculate_available_balance(db, target_rider_id)
    except Exception:
        logger.exception(
            "No se pudo calcular el saldo disponible para rider %s", target_rider_id
        )
        # Do not break rider-facing screens if a legacy database has an
        # inconsistent enum/index state. Returning a safe zero balance is
        # preferable to a 500 that browsers surface as a CORS/network error.
        return {
            "available": 0.0,
            "pending": 0.0,
            "processed": 0.0,
            "total_earned": 0.0,
            "currency": "COP",
            "degraded": True,
            "detail": "No se pudo calcular el saldo disponible temporalmente",
        }


@router.get("/request-status")
async def get_request_status(
    idempotency_key: str = Query(..., min_length=1, max_length=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Read only the caller's request; a key is not an authorization token.

    404 is a point-in-time observation, not proof an in-flight POST cannot
    commit later. Clients must retain the original key when retrying.
    """
    if current_user.role != UserRole.REPARTIDOR:
        raise HTTPException(
            status_code=403, detail="Solo repartidores pueden consultar su solicitud"
        )
    key = idempotency_key.strip()
    if not key:
        raise HTTPException(status_code=422, detail="Clave de solicitud inválida")
    payout = await db.scalar(
        select(Payout)
        .join(Rider, Payout.rider_id == Rider.id)
        .where(
            Rider.user_id == current_user.id,
            Payout.idempotency_key == key,
        )
    )
    if payout is None:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    return _serialize_payout(payout)


@router.post("/request", status_code=201)
async def request_payout(
    body: PayoutRequestBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Solicitar un nuevo retiro con payload JSON real e idempotencia opcional."""
    if current_user.role != UserRole.REPARTIDOR:
        raise HTTPException(
            status_code=403, detail="Solo repartidores pueden solicitar retiros"
        )

    user_id = current_user.id
    rider_id = await db.scalar(select(Rider.id).where(Rider.user_id == user_id))
    if rider_id is None:
        raise HTTPException(
            status_code=404, detail="Perfil de repartidor no encontrado"
        )
    await _lock_payout_rider(db, rider_id)
    key = body.idempotency_key
    requested_amount = _money(body.amount)

    async def existing_request():
        if key is None:
            return None
        existing = await db.scalar(select(Payout).where(Payout.idempotency_key == key))
        if existing is not None and (
            existing.rider_id != rider_id
            or _money(existing.amount) != requested_amount
            or existing.method != body.method
            or existing.bank_account_last4 != body.bank_account_last4
            or existing.requested_by_user_id != user_id
        ):
            raise HTTPException(
                status_code=409, detail="La clave identifica otra solicitud de retiro"
            )
        return existing

    existing = await existing_request()
    if existing is not None:
        return _serialize_payout(existing)
    balance = await _calculate_available_balance(db, rider_id)
    available = _money(balance["available"])
    if requested_amount > available:
        raise HTTPException(
            status_code=400, detail=f"Saldo insuficiente. Disponible: {available:.2f}"
        )
    if requested_amount < Decimal("10.00"):
        raise HTTPException(
            status_code=400, detail="El monto mínimo de retiro es 10.00"
        )
    payout = Payout(
        rider_id=rider_id,
        amount=requested_amount,
        method=body.method,
        bank_account_last4=body.bank_account_last4,
        status=PayoutStatus.PENDIENTE,
        balance_before=available,
        balance_after=available - requested_amount,
        requested_by_user_id=user_id,
        idempotency_key=key,
    )
    try:
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
            available - requested_amount,
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await existing_request()
        if existing is not None:
            return _serialize_payout(existing)
        raise
    # No side effects can confirm/poison the request's database session.
    response = _serialize_payout(payout)
    asyncio.create_task(
        _notify_requested(uuid.UUID(str(payout.id)), user_id, requested_amount)
    )
    try:
        redis_logger = get_redis_audit_logger()
        if redis_logger.connected:
            await redis_logger.log_withdrawal_requested(
                payout_id=str(payout.id),
                rider_id=str(rider_id),
                amount=float(requested_amount),
                requested_by=str(user_id),
            )
    except Exception:
        logger.warning("No se pudo escribir la auditoría Redis de la solicitud")
    return response


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
            raise HTTPException(
                status_code=403, detail="No tienes permiso para acceder a este retiro"
            )
    elif current_user.role not in [UserRole.GERENTE, UserRole.SUPERADMIN]:
        raise HTTPException(status_code=403, detail="Acceso denegado")

    return _serialize_payout(payout)


@router.get("/{payout_id}/history")
async def get_payout_history(
    payout_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Consultar historial auditable de estados de un retiro."""
    payout_id_uuid = _parse_uuid(payout_id)
    payout_result = await db.execute(select(Payout).where(Payout.id == payout_id_uuid))
    payout = payout_result.scalar_one_or_none()

    if not payout:
        raise HTTPException(status_code=404, detail="Retiro no encontrado")

    if current_user.role == UserRole.REPARTIDOR:
        rider = await _get_rider_from_user(db, current_user)
        if payout.rider_id != rider.id:
            raise HTTPException(
                status_code=403, detail="No tienes permiso para acceder a este retiro"
            )
    elif current_user.role not in [UserRole.GERENTE, UserRole.SUPERADMIN]:
        raise HTTPException(status_code=403, detail="Acceso denegado")

    history_result = await db.execute(
        select(PayoutStatusHistory)
        .where(PayoutStatusHistory.payout_id == payout_id_uuid)
        .order_by(PayoutStatusHistory.created_at.asc())
    )
    return [_serialize_status_history(row) for row in history_result.scalars().all()]


@router.patch("/{payout_id}/approve")
async def approve_payout(
    payout_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.GERENTE, UserRole.SUPERADMIN)),
):
    """Aprobar un retiro y registrar salida contable de forma atómica."""
    payout_uuid = _parse_uuid(payout_id)
    result = await db.execute(
        select(Payout)
        .where(Payout.id == payout_uuid)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    payout = result.scalar_one_or_none()
    if not payout:
        raise HTTPException(status_code=404, detail="Retiro no encontrado")

    await _lock_payout_rider(db, str(payout.rider_id))

    if payout.status != PayoutStatus.PENDIENTE:
        raise HTTPException(
            status_code=400, detail="Solo se pueden aprobar retiros pendientes"
        )

    balance_before_data = await _calculate_available_balance(
        db, payout.rider_id, exclude_payout_id=payout.id
    )
    balance_before = _money(balance_before_data["available"])
    payout_amount = _money(payout.amount)

    if balance_before < payout_amount:
        raise HTTPException(
            status_code=409,
            detail="Saldo insuficiente al momento de aprobar. Revise conciliación antes de procesar.",
        )

    balance_after = balance_before - payout_amount
    old_status = payout.status
    payout.status = PayoutStatus.EN_PROCESO
    payout.processed_at = utc_now_naive()
    payout.updated_at = payout.processed_at
    payout.processed_by_user_id = current_user.id
    payout.balance_before = balance_before
    payout.balance_after = balance_after
    payout.reference_code = (
        f"PAY-{payout.processed_at.strftime('%Y%m%d')}-{str(payout.id)[:8].upper()}"
    )

    await FinancialService(db).create_ledger_entry(
        rider_id=payout.rider_id,
        amount=payout_amount,
        # The payout snapshot is availability after reservations; the ledger
        # must derive its own canonical balance while holding the rider lock.
        transaction_type=TransactionType.RETIRO,
        description=f"Retiro aprobado: {payout.reference_code}",
        reference_id=str(payout.id),
        source_type="PAYOUT",
        source_id=str(payout.id),
        idempotency_key=f"payout-approve-{payout.id}",
        created_by_user_id=current_user.id,
        status=PaymentStatus.PROCESADO,
        commit=False,
    )
    _add_status_history(
        db,
        payout,
        old_status,
        PayoutStatus.EN_PROCESO,
        current_user,
        f"Retiro aprobado: {payout.reference_code}",
        balance_before,
        balance_after,
    )

    # Use the existing post-commit hook with its own session; a legacy
    # NotificationService call here would commit the financial unit early.
    # FASE 9 (hook omnicanal): payout → plantilla 'payout_aprobado'.
    # Se resuelve el destinatario AHÍ (antes del commit) pero el dispatch se
    # lanza DESPUÉS de commitear, con sesión propia efímera dentro de
    # notify_event: un fallo de notificación jamás revierte la operación.
    _fase9_approve_ctx = None
    try:
        from app.services.notification_hooks import (
            notify_event,
            resolve_payout_recipient,
            payout_context,
        )

        recipient_user_id = await resolve_payout_recipient(db, payout)
        if recipient_user_id:
            _fase9_approve_ctx = (recipient_user_id, payout_context(payout))
    except Exception as e:
        logger.warning(f"Hook Fase 9 payout_aprobado omitido: {e}")

    # REDIS AUDIT (Tiempo Real): Publicar evento para dashboards
    try:
        redis_logger = get_redis_audit_logger()
        if redis_logger.connected:
            await redis_logger.log_withdrawal_approved(
                payout_id=str(payout.id),
                rider_id=str(payout.rider_id),
                approved_by=str(current_user.id),
            )
    except Exception as e:
        logger.warning(f"No se pudo escribir audit en Redis: {e}")

    await db.commit()
    await db.refresh(payout)

    # FASE 9: dispatch post-commit (asyncio.create_task no bloquea la respuesta;
    # notify_event jamás propaga excepciones al caller).
    if _fase9_approve_ctx is not None:
        try:
            asyncio.create_task(
                notify_event(
                    "payout_aprobado",
                    _fase9_approve_ctx[0],
                    _fase9_approve_ctx[1],
                    payout_id=payout.id,
                )
            )
        except Exception as e:
            logger.warning(f"Dispatch Fase 9 payout_aprobado omitido: {e}")

    return _serialize_payout(payout)


@router.patch("/{payout_id}/reject")
async def reject_payout(
    payout_id: str,
    body: PayoutRejectBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.GERENTE, UserRole.SUPERADMIN)),
):
    """Rechazar un retiro pendiente con motivo enviado en JSON y liberar reserva de saldo."""
    reason = (body.rejection_reason or body.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Motivo de rechazo requerido")

    payout_uuid = _parse_uuid(payout_id)
    result = await db.execute(
        select(Payout)
        .where(Payout.id == payout_uuid)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    payout = result.scalar_one_or_none()
    if not payout:
        raise HTTPException(status_code=404, detail="Retiro no encontrado")

    await _lock_payout_rider(db, str(payout.rider_id))

    if payout.status != PayoutStatus.PENDIENTE:
        raise HTTPException(
            status_code=400, detail="Solo se pueden rechazar retiros pendientes"
        )

    balance_before_data = await _calculate_available_balance(db, payout.rider_id)
    balance_before = _money(balance_before_data["available"])
    released = await _calculate_available_balance(
        db, payout.rider_id, exclude_payout_id=payout.id
    )
    balance_after = _money(released["available"])
    old_status = payout.status

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

    # Use the existing post-commit hook with its own session; a legacy
    # NotificationService call here would commit the financial unit early.
    # FASE 9 (hook omnicanal): payout RECHAZADO → plantilla 'payout_rechazado'.
    # Se resuelve el destinatario AHÍ (antes del commit) pero el dispatch se
    # lanza DESPUÉS de commitear, con sesión propia efímera: un fallo de
    # notificación jamás revierte la operación de negocio.
    _fase9_reject_ctx = None
    try:
        from app.services.notification_hooks import (
            notify_event,
            resolve_payout_recipient,
            payout_context,
        )

        recipient_user_id = await resolve_payout_recipient(db, payout)
        if recipient_user_id:
            _fase9_reject_ctx = (
                recipient_user_id,
                payout_context(payout, extra={"reason": reason}),
            )
    except Exception as e:
        logger.warning(f"Hook Fase 9 payout_rechazado omitido: {e}")

    # REDIS AUDIT (Tiempo Real): Publicar evento para dashboards
    try:
        redis_logger = get_redis_audit_logger()
        if redis_logger.connected:
            await redis_logger.log_event(
                event_type="WITHDRAWAL_REJECTED",
                resource_type="PAYOUT",
                resource_id=str(payout.id),
                user_id=str(current_user.id),
                details={
                    "rider_id": str(payout.rider_id),
                    "reason": reason,
                    "action": "reject",
                },
            )
    except Exception as e:
        logger.warning(f"No se pudo escribir audit en Redis: {e}")

    await db.commit()
    await db.refresh(payout)

    # FASE 9: dispatch post-commit (sesión propia efímera dentro de notify_event).
    if _fase9_reject_ctx is not None:
        try:
            asyncio.create_task(
                notify_event(
                    "payout_rechazado",
                    _fase9_reject_ctx[0],
                    _fase9_reject_ctx[1],
                    payout_id=payout.id,
                )
            )
        except Exception as e:
            logger.warning(f"Dispatch Fase 9 payout_rechazado omitido: {e}")

    return _serialize_payout(payout)
