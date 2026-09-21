"""
Wallet Service - Fase 7 Enterprise
Gestión de billeteras virtuales, transacciones y retiros para riders.
"""
from decimal import Decimal
from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, desc

from app.models.financial import (
    RiderWallet, 
    FinancialTransaction, 
    PayoutRequest,
    TransactionType, 
    TransactionStatus, 
    PayoutStatus
)
from app.models.rider import Rider
from app.core.exceptions import NotFoundError, ValidationError, InsufficientFundsError


class WalletService:
    """Servicio para gestión de wallets y transacciones financieras."""

    def __init__(self, db: Session):
        self.db = db

    def get_or_create_wallet(self, rider_id: UUID) -> RiderWallet:
        """Obtiene o crea la wallet de un rider."""
        wallet = self.db.query(RiderWallet).filter(
            RiderWallet.rider_id == rider_id
        ).first()

        if not wallet:
            # Crear nueva wallet
            wallet = RiderWallet(
                rider_id=rider_id,
                balance_cents=0,
                currency="USD",
                is_active=True
            )
            self.db.add(wallet)
            self.db.commit()
            self.db.refresh(wallet)

        return wallet

    def get_wallet_by_id(self, wallet_id: UUID) -> Optional[RiderWallet]:
        """Obtiene una wallet por ID."""
        return self.db.query(RiderWallet).filter(
            RiderWallet.id == wallet_id
        ).first()

    def get_wallet_by_rider(self, rider_id: UUID) -> Optional[RiderWallet]:
        """Obtiene la wallet de un rider."""
        return self.db.query(RiderWallet).filter(
            RiderWallet.rider_id == rider_id
        ).first()

    def add_funds(
        self,
        wallet_id: UUID,
        amount_cents: int,
        transaction_type: TransactionType,
        description: str,
        reference_id: Optional[str] = None,
        metadata_json: Optional[Dict[str, Any]] = None,
        created_by_user_id: Optional[UUID] = None,
        idempotency_key: Optional[str] = None
    ) -> FinancialTransaction:
        """
        Agrega fondos a la wallet del rider.
        
        Args:
            wallet_id: ID de la wallet
            amount_cents: Monto en centavos (debe ser positivo)
            transaction_type: Tipo de transacción
            description: Descripción de la transacción
            reference_id: ID de referencia (ej. delivery_id)
            metadata_json: Metadata adicional en formato JSON
            created_by_user_id: ID del usuario que crea la transacción
            idempotency_key: Clave para evitar duplicados
        
        Returns:
            FinancialTransaction creada
        """
        if amount_cents <= 0:
            raise ValidationError("El monto debe ser positivo")

        # Verificar idempotencia
        if idempotency_key:
            existing = self.db.query(FinancialTransaction).filter(
                FinancialTransaction.idempotency_key == idempotency_key
            ).first()
            if existing:
                return existing

        # Obtener wallet
        wallet = self.get_wallet_by_id(wallet_id)
        if not wallet:
            raise NotFoundError("Wallet no encontrada")

        # Calcular nuevo balance
        new_balance_cents = wallet.balance_cents + amount_cents

        # Crear transacción
        transaction = FinancialTransaction(
            wallet_id=wallet_id,
            transaction_type=transaction_type,
            amount_cents=amount_cents,
            description=description,
            reference_id=reference_id,
            metadata_json=str(metadata_json) if metadata_json else None,
            status=TransactionStatus.COMPLETED,
            balance_after_cents=new_balance_cents,
            created_by_user_id=created_by_user_id,
            idempotency_key=idempotency_key
        )

        # Actualizar wallet
        wallet.balance_cents = new_balance_cents
        wallet.last_transaction_at = datetime.utcnow()

        self.db.add(transaction)
        self.db.commit()
        self.db.refresh(transaction)

        return transaction

    def withdraw_funds(
        self,
        wallet_id: UUID,
        amount_cents: int,
        transaction_type: TransactionType,
        description: str,
        reference_id: Optional[str] = None,
        metadata_json: Optional[Dict[str, Any]] = None,
        created_by_user_id: Optional[UUID] = None,
        idempotency_key: Optional[str] = None
    ) -> FinancialTransaction:
        """
        Retira fondos de la wallet del rider.
        
        Args:
            wallet_id: ID de la wallet
            amount_cents: Monto en centavos (debe ser positivo, se restará)
            transaction_type: Tipo de transacción
            description: Descripción de la transacción
            reference_id: ID de referencia
            metadata_json: Metadata adicional
            created_by_user_id: ID del usuario que crea la transacción
            idempotency_key: Clave para evitar duplicados
        
        Returns:
            FinancialTransaction creada
        """
        if amount_cents <= 0:
            raise ValidationError("El monto debe ser positivo")

        # Verificar idempotencia
        if idempotency_key:
            existing = self.db.query(FinancialTransaction).filter(
                FinancialTransaction.idempotency_key == idempotency_key
            ).first()
            if existing:
                return existing

        # Obtener wallet
        wallet = self.get_wallet_by_id(wallet_id)
        if not wallet:
            raise NotFoundError("Wallet no encontrada")

        # Verificar fondos suficientes
        if wallet.balance_cents < amount_cents:
            raise InsufficientFundsError(
                f"Fondos insuficientes. Balance: ${wallet.balance_cents/100}, "
                f"Requerido: ${amount_cents/100}"
            )

        # Calcular nuevo balance
        new_balance_cents = wallet.balance_cents - amount_cents

        # Crear transacción (monto negativo para egreso)
        transaction = FinancialTransaction(
            wallet_id=wallet_id,
            transaction_type=transaction_type,
            amount_cents=-amount_cents,  # Negativo para indicar egreso
            description=description,
            reference_id=reference_id,
            metadata_json=str(metadata_json) if metadata_json else None,
            status=TransactionStatus.COMPLETED,
            balance_after_cents=new_balance_cents,
            created_by_user_id=created_by_user_id,
            idempotency_key=idempotency_key
        )

        # Actualizar wallet
        wallet.balance_cents = new_balance_cents
        wallet.last_transaction_at = datetime.utcnow()

        self.db.add(transaction)
        self.db.commit()
        self.db.refresh(transaction)

        return transaction

    def create_payout_request(
        self,
        rider_id: UUID,
        amount_cents: int,
        bank_account_last4: str,
        bank_name: str,
        account_holder_name: str
    ) -> PayoutRequest:
        """
        Crea una solicitud de retiro hacia cuenta bancaria.
        
        Args:
            rider_id: ID del rider
            amount_cents: Monto a retirar en centavos
            bank_account_last4: Últimos 4 dígitos de la cuenta
            bank_name: Nombre del banco
            account_holder_name: Nombre del titular
        
        Returns:
            PayoutRequest creada
        """
        if amount_cents <= 0:
            raise ValidationError("El monto debe ser positivo")

        # Obtener wallet del rider
        wallet = self.get_wallet_by_rider(rider_id)
        if not wallet:
            raise NotFoundError("Wallet no encontrada")

        # Verificar fondos suficientes
        if wallet.balance_cents < amount_cents:
            raise InsufficientFundsError(
                f"Fondos insuficientes para retiro. Balance: ${wallet.balance_cents/100}, "
                f"Requerido: ${amount_cents/100}"
            )

        # Reservar fondos (restar temporalmente)
        wallet.balance_cents -= amount_cents
        wallet.last_transaction_at = datetime.utcnow()

        # Crear solicitud de retiro
        payout_request = PayoutRequest(
            wallet_id=wallet.id,
            rider_id=rider_id,
            amount_cents=amount_cents,
            currency=wallet.currency,
            bank_account_last4=bank_account_last4,
            bank_name=bank_name,
            account_holder_name=account_holder_name,
            status=PayoutStatus.PENDIENTE
        )

        self.db.add(payout_request)
        self.db.commit()
        self.db.refresh(payout_request)

        return payout_request

    def approve_payout(self, payout_id: UUID, provider_payout_id: Optional[str] = None) -> PayoutRequest:
        """Aprueba una solicitud de retiro."""
        payout = self.db.query(PayoutRequest).filter(
            PayoutRequest.id == payout_id
        ).first()

        if not payout:
            raise NotFoundError("Solicitud de retiro no encontrada")

        if payout.status != PayoutStatus.PENDIENTE:
            raise ValidationError(f"No se puede aprobar retiro en estado {payout.status}")

        payout.status = PayoutStatus.APROBADO
        payout.approved_at = datetime.utcnow()
        if provider_payout_id:
            payout.provider_payout_id = provider_payout_id

        self.db.commit()
        self.db.refresh(payout)

        return payout

    def complete_payout(self, payout_id: UUID, provider_response_json: Optional[str] = None) -> PayoutRequest:
        """Marca un retiro como completado."""
        payout = self.db.query(PayoutRequest).filter(
            PayoutRequest.id == payout_id
        ).first()

        if not payout:
            raise NotFoundError("Solicitud de retiro no encontrada")

        if payout.status not in [PayoutStatus.APROBADO, PayoutStatus.EN_PROCESO]:
            raise ValidationError(f"No se puede completar retiro en estado {payout.status}")

        payout.status = PayoutStatus.COMPLETADO
        payout.completed_at = datetime.utcnow()
        if provider_response_json:
            payout.provider_response_json = provider_response_json

        self.db.commit()
        self.db.refresh(payout)

        return payout

    def reject_payout(self, payout_id: UUID, reason: str) -> PayoutRequest:
        """Rechaza un retiro y devuelve los fondos a la wallet."""
        payout = self.db.query(PayoutRequest).filter(
            PayoutRequest.id == payout_id
        ).first()

        if not payout:
            raise NotFoundError("Solicitud de retiro no encontrada")

        if payout.status != PayoutStatus.PENDIENTE:
            raise ValidationError(f"No se puede rechazar retiro en estado {payout.status}")

        # Devolver fondos a la wallet
        wallet = self.get_wallet_by_id(payout.wallet_id)
        if wallet:
            wallet.balance_cents += payout.amount_cents
            wallet.last_transaction_at = datetime.utcnow()

        payout.status = PayoutStatus.RECHAZADO
        payout.rejection_reason = reason
        payout.failed_at = datetime.utcnow()

        self.db.commit()
        self.db.refresh(payout)

        return payout

    def get_transactions(
        self,
        wallet_id: UUID,
        limit: int = 50,
        offset: int = 0
    ) -> List[FinancialTransaction]:
        """Obtiene el historial de transacciones de una wallet."""
        return self.db.query(FinancialTransaction).filter(
            FinancialTransaction.wallet_id == wallet_id
        ).order_by(
            desc(FinancialTransaction.created_at)
        ).offset(offset).limit(limit).all()

    def get_payout_requests(
        self,
        rider_id: UUID,
        limit: int = 20,
        offset: int = 0
    ) -> List[PayoutRequest]:
        """Obtiene las solicitudes de retiro de un rider."""
        return self.db.query(PayoutRequest).filter(
            PayoutRequest.rider_id == rider_id
        ).order_by(
            desc(PayoutRequest.created_at)
        ).offset(offset).limit(limit).all()

    def get_pending_payouts(self) -> List[PayoutRequest]:
        """Obtiene todas las solicitudes de retiro pendientes de aprobación."""
        return self.db.query(PayoutRequest).filter(
            PayoutRequest.status == PayoutStatus.PENDIENTE
        ).order_by(PayoutRequest.created_at).all()
