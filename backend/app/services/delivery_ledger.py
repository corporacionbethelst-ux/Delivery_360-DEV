"""Delivery bonus calculation boundaries and consistent order-before-delivery locks."""

from decimal import Decimal, InvalidOperation
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import (
    AppException,
    DuplicateTransactionError,
    NotFoundError,
    ValidationError,
)
from app.models.delivery import Delivery
from app.models.order import Order
from app.models.user import User
from app.core.operation_permissions import ensure_rider_resource_access
from app.models.financial import Financial, PaymentStatus, TransactionType
from app.services.financial_service import money
from app.services.legacy_ledger import MAX_BALANCE, exact_money
from app.services.order_cancellation import ensure_order_not_cancelled


def bonus_component(value: object) -> Decimal:
    """Validate a configured component before multiplying or rounding it."""
    try:
        if isinstance(value, bool):
            raise InvalidOperation
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount > MAX_BALANCE:
            raise InvalidOperation
        return amount
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValidationError("Configuración o cálculo de bono inválido") from exc


def calculated_bonus(value: object) -> Decimal:
    """Round an explicitly calculated reward, never an incoming ledger amount."""
    return money(bonus_component(value))


def validate_bonus_receipt(
    entry: Financial, rider_id: UUID, order_id: UUID, kind: TransactionType
) -> None:
    """An existing frozen order bonus cannot silently belong to another operation."""
    amount = exact_money(entry.amount)
    if (
        entry.rider_id != rider_id
        or entry.transaction_type != kind
        or entry.reference_id != str(order_id)
        or entry.status not in (PaymentStatus.PROCESADO, PaymentStatus.PAGADO)
        or amount is None
        or amount <= 0
    ):
        raise DuplicateTransactionError("La clave del bono identifica otro movimiento")


async def lock_delivery_transition(
    db: AsyncSession, delivery_id: UUID, *, actor_id: UUID | None = None
) -> Delivery:
    order_id = await db.scalar(
        select(Delivery.order_id).where(Delivery.id == delivery_id)
    )
    if order_id is None:
        raise NotFoundError("Entrega no encontrada")
    parent = await db.scalar(
        select(Order.id).where(Order.id == order_id).with_for_update()
    )
    if parent is None:
        raise AppException("La orden de la entrega requiere revisión", 409)
    await ensure_order_not_cancelled(db, order_id)
    delivery = await db.scalar(
        select(Delivery)
        .where(Delivery.id == delivery_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if delivery is None or delivery.order_id != order_id:
        raise AppException("La entrega cambió; vuelva a consultar su estado", 409)
    if actor_id is not None:
        # A handler may have authenticated/read ownership before waiting for the
        # parent lock. Recheck current account and assignment after that wait.
        actor = await db.scalar(
            select(User)
            .where(User.id == actor_id)
            .execution_options(populate_existing=True)
        )
        if actor is None or not actor.is_active:
            raise AppException("La cuenta ya no está vigente", 401)
        await ensure_rider_resource_access(db, actor, delivery.rider_id, write=True)
    return delivery


async def ensure_bonus_outcome(
    db: AsyncSession, order_id: UUID, *, success: bool
) -> None:
    """Do not pay opposite outcomes left by inconsistent historical workflows."""
    opposite = ("pago_fallido_" if success else "pago_entrega_") + str(order_id)
    if (
        await db.scalar(
            select(Financial.id).where(Financial.idempotency_key == opposite)
        )
        is not None
    ):
        raise AppException(
            "La orden ya registra un bono de resultado contrario; requiere revisión",
            409,
        )
