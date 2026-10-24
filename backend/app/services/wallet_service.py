"""Async wallet operations for the existing cent-based wallet subsystem.

This is independent of the decimal financials/payouts ledger. Reservation and
administrative payout states do not perform or attest a bank transfer.
"""

from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncIterator
from uuid import UUID
import json

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    DuplicateTransactionError,
    InsufficientFundsError,
    NotFoundError,
    ValidationError,
)
from app.models.financial import (
    FinancialTransaction,
    PayoutRequest,
    PayoutStatus,
    RiderWallet,
    TransactionStatus,
    TransactionType,
)
from app.models.rider import Rider

MAX_CENTS = 2_147_483_647  # Existing PostgreSQL INTEGER columns.


class WalletService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @asynccontextmanager
    async def _write(self) -> AsyncIterator[None]:
        # Authentication may already have started this session's transaction.
        # Do not nest begin() or commit part of a balance change separately.
        try:
            yield
            await self.db.commit()
        except BaseException:
            await self.db.rollback()
            raise

    @staticmethod
    def _amount(amount_cents: int) -> None:
        if type(amount_cents) is not int or not 0 < amount_cents <= MAX_CENTS:
            raise ValidationError(
                "El monto debe ser un entero positivo de centavos válido"
            )

    @staticmethod
    def _key(key: str | None) -> None:
        if key is not None and (not key.strip() or len(key) > 100):
            raise ValidationError(
                "La clave de idempotencia debe tener entre 1 y 100 caracteres"
            )

    async def rider_id_for_user(self, user_id: UUID) -> UUID:
        rider_id = await self.db.scalar(
            select(Rider.id).where(Rider.user_id == user_id)
        )
        if rider_id is None:
            raise NotFoundError("Perfil de repartidor no encontrado")
        return rider_id

    async def get_or_create_wallet(self, rider_id: UUID) -> RiderWallet:
        async with self._write():
            # Serialize wallet creation on the existing parent, including when
            # there is no wallet row yet. Never use users.id as a rider ID.
            parent = await self.db.scalar(
                select(Rider.id).where(Rider.id == rider_id).with_for_update()
            )
            if parent is None:
                raise NotFoundError("Perfil de repartidor no encontrado")
            wallet = await self.get_wallet_by_rider(rider_id)
            if wallet is None:
                wallet = RiderWallet(
                    rider_id=rider_id, balance_cents=0, currency="USD", is_active=True
                )
                self.db.add(wallet)
                await self.db.flush()
        return wallet

    async def get_wallet_by_id(self, wallet_id: UUID) -> RiderWallet | None:
        return await self.db.scalar(
            select(RiderWallet).where(RiderWallet.id == wallet_id)
        )

    async def get_wallet_by_rider(self, rider_id: UUID) -> RiderWallet | None:
        return await self.db.scalar(
            select(RiderWallet).where(RiderWallet.rider_id == rider_id)
        )

    async def _lock_wallet(self, wallet_id: UUID) -> RiderWallet:
        wallet = await self.db.scalar(
            select(RiderWallet)
            .where(RiderWallet.id == wallet_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if wallet is None:
            raise NotFoundError("Wallet no encontrada")
        return wallet

    async def _lock_payout(self, payout_id: UUID) -> PayoutRequest:
        payout = await self.db.scalar(
            select(PayoutRequest)
            .where(PayoutRequest.id == payout_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if payout is None:
            raise NotFoundError("Solicitud de retiro no encontrada")
        return payout

    async def _move(
        self,
        wallet_id: UUID,
        signed_cents: int,
        transaction_type: TransactionType,
        description: str,
        reference_id: str | None,
        metadata_json: dict[str, object] | None,
        created_by_user_id: UUID | None,
        idempotency_key: str | None,
    ) -> FinancialTransaction:
        self._key(idempotency_key)
        try:
            metadata = (
                json.dumps(metadata_json, sort_keys=True, allow_nan=False)
                if metadata_json is not None
                else None
            )
        except (TypeError, ValueError) as exc:
            raise ValidationError("La metadata debe ser JSON válido") from exc

        async def existing_transaction() -> FinancialTransaction | None:
            if idempotency_key is None:
                return None
            existing = await self.db.scalar(
                select(FinancialTransaction).where(
                    FinancialTransaction.idempotency_key == idempotency_key
                )
            )
            if existing is not None and (
                existing.wallet_id != wallet_id
                or existing.amount_cents != signed_cents
                or existing.transaction_type != transaction_type
                or existing.reference_id != reference_id
                or existing.description != description
                or existing.metadata_json != metadata
                or existing.created_by_user_id != created_by_user_id
            ):
                raise DuplicateTransactionError(
                    "La clave de idempotencia ya identifica otra operación"
                )
            return existing

        try:
            async with self._write():
                wallet = await self._lock_wallet(wallet_id)
                existing = await existing_transaction()
                if existing is not None:
                    return existing
                if not wallet.is_active:
                    raise ValidationError("Wallet inactiva")
                new_balance = wallet.balance_cents + signed_cents
                if new_balance < 0:
                    raise InsufficientFundsError("Fondos insuficientes")
                if new_balance > MAX_CENTS:
                    raise ValidationError("El saldo excede el límite de la wallet")
                transaction = FinancialTransaction(
                    wallet_id=wallet_id,
                    transaction_type=transaction_type,
                    amount_cents=signed_cents,
                    description=description,
                    reference_id=reference_id,
                    metadata_json=metadata,
                    status=TransactionStatus.COMPLETED,
                    balance_after_cents=new_balance,
                    created_by_user_id=created_by_user_id,
                    idempotency_key=idempotency_key,
                )
                wallet.balance_cents = new_balance
                wallet.last_transaction_at = datetime.utcnow()
                self.db.add(transaction)
                await self.db.flush()
            return transaction
        except IntegrityError:
            # A key is unique globally, even when requests lock different wallets.
            # _write has already rolled back the entire losing transaction.
            existing = await existing_transaction()
            if existing is not None:
                return existing
            raise

    async def add_funds(
        self,
        wallet_id: UUID,
        amount_cents: int,
        transaction_type: TransactionType,
        description: str,
        reference_id: str | None = None,
        metadata_json: dict[str, object] | None = None,
        created_by_user_id: UUID | None = None,
        idempotency_key: str | None = None,
    ) -> FinancialTransaction:
        self._amount(amount_cents)
        return await self._move(
            wallet_id,
            amount_cents,
            transaction_type,
            description,
            reference_id,
            metadata_json,
            created_by_user_id,
            idempotency_key,
        )

    async def withdraw_funds(
        self,
        wallet_id: UUID,
        amount_cents: int,
        transaction_type: TransactionType,
        description: str,
        reference_id: str | None = None,
        metadata_json: dict[str, object] | None = None,
        created_by_user_id: UUID | None = None,
        idempotency_key: str | None = None,
    ) -> FinancialTransaction:
        self._amount(amount_cents)
        return await self._move(
            wallet_id,
            -amount_cents,
            transaction_type,
            description,
            reference_id,
            metadata_json,
            created_by_user_id,
            idempotency_key,
        )

    async def create_payout_request(
        self,
        rider_id: UUID,
        amount_cents: int,
        bank_account_last4: str,
        bank_name: str,
        account_holder_name: str,
        idempotency_key: str | None = None,
    ) -> PayoutRequest:
        self._amount(amount_cents)
        self._key(idempotency_key)
        wallet_id: UUID | None = None

        async def existing_payout() -> PayoutRequest | None:
            if idempotency_key is None:
                return None
            existing = await self.db.scalar(
                select(PayoutRequest).where(
                    PayoutRequest.idempotency_key == idempotency_key
                )
            )
            if existing is not None and (
                existing.rider_id != rider_id
                or existing.wallet_id != wallet_id
                or existing.amount_cents != amount_cents
                or existing.bank_account_last4 != bank_account_last4
                or existing.bank_name != bank_name
                or existing.account_holder_name != account_holder_name
            ):
                raise DuplicateTransactionError(
                    "La clave de idempotencia ya identifica otra solicitud"
                )
            return existing

        try:
            async with self._write():
                wallet = await self.get_wallet_by_rider(rider_id)
                if wallet is None:
                    raise NotFoundError("Wallet no encontrada")
                wallet_id = wallet.id
                wallet = await self._lock_wallet(wallet_id)
                existing = await existing_payout()
                if existing is not None:
                    return existing
                if not wallet.is_active:
                    raise ValidationError("Wallet inactiva")
                if wallet.balance_cents < amount_cents:
                    raise InsufficientFundsError("Fondos insuficientes para retiro")
                wallet.balance_cents -= amount_cents
                wallet.last_transaction_at = datetime.utcnow()
                payout = PayoutRequest(
                    wallet_id=wallet.id,
                    rider_id=rider_id,
                    amount_cents=amount_cents,
                    currency=wallet.currency,
                    bank_account_last4=bank_account_last4,
                    bank_name=bank_name,
                    account_holder_name=account_holder_name,
                    status=PayoutStatus.PENDIENTE,
                    idempotency_key=idempotency_key,
                )
                self.db.add(payout)
                await self.db.flush()
            return payout
        except IntegrityError:
            existing = await existing_payout()
            if existing is not None:
                return existing
            raise

    async def approve_payout(
        self, payout_id: UUID, provider_payout_id: str | None = None
    ) -> PayoutRequest:
        async with self._write():
            payout = await self._lock_payout(payout_id)
            if payout.status != PayoutStatus.PENDIENTE:
                raise ValidationError(
                    f"No se puede aprobar retiro en estado {payout.status.value}"
                )
            payout.status = PayoutStatus.APROBADO
            payout.approved_at = datetime.utcnow()
            if provider_payout_id:
                payout.provider_payout_id = provider_payout_id
        return payout

    async def complete_payout(
        self, payout_id: UUID, provider_response_json: str | None = None
    ) -> PayoutRequest:
        async with self._write():
            payout = await self._lock_payout(payout_id)
            if payout.status not in (PayoutStatus.APROBADO, PayoutStatus.EN_PROCESO):
                raise ValidationError(
                    f"No se puede completar retiro en estado {payout.status.value}"
                )
            payout.status = PayoutStatus.COMPLETADO
            payout.completed_at = datetime.utcnow()
            if provider_response_json:
                payout.provider_response_json = provider_response_json
        return payout

    async def reject_payout(self, payout_id: UUID, reason: str) -> PayoutRequest:
        async with self._write():
            payout = await self._lock_payout(payout_id)
            if payout.status != PayoutStatus.PENDIENTE:
                raise ValidationError(
                    f"No se puede rechazar retiro en estado {payout.status.value}"
                )
            wallet = await self._lock_wallet(payout.wallet_id)
            if wallet.balance_cents + payout.amount_cents > MAX_CENTS:
                raise ValidationError("El reintegro excede el límite de la wallet")
            wallet.balance_cents += payout.amount_cents
            wallet.last_transaction_at = datetime.utcnow()
            payout.status = PayoutStatus.RECHAZADO
            payout.rejection_reason = reason
            payout.failed_at = datetime.utcnow()
        return payout

    async def get_transactions(
        self, wallet_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[FinancialTransaction]:
        result = await self.db.scalars(
            select(FinancialTransaction)
            .where(FinancialTransaction.wallet_id == wallet_id)
            .order_by(
                FinancialTransaction.created_at.desc(), FinancialTransaction.id.desc()
            )
            .offset(offset)
            .limit(limit)
        )
        return list(result.all())

    async def get_payout_requests(
        self, rider_id: UUID, limit: int = 20, offset: int = 0
    ) -> list[PayoutRequest]:
        result = await self.db.scalars(
            select(PayoutRequest)
            .where(PayoutRequest.rider_id == rider_id)
            .order_by(PayoutRequest.created_at.desc(), PayoutRequest.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.all())

    async def get_pending_payouts(self) -> list[PayoutRequest]:
        result = await self.db.scalars(
            select(PayoutRequest)
            .where(PayoutRequest.status == PayoutStatus.PENDIENTE)
            .order_by(PayoutRequest.created_at, PayoutRequest.id)
        )
        return list(result.all())
