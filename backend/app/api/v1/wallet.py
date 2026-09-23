"""
API Endpoints para Wallet y Pagos - Fase 7 Enterprise
Gestión de billeteras, transacciones y retiros para riders.
Sincronizado con enums de estado en español.
"""
from typing import List, Optional, Dict, Any
from uuid import UUID
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, RoleChecker
from app.models.user import User, UserRole
from app.models.financial import TransactionType, TransactionStatus, PayoutStatus
from app.services.wallet_service import WalletService
from app.schemas.wallet import (
    WalletResponse,
    TransactionResponse,
    PayoutRequestCreate,
    PayoutRequestResponse,
    PayoutApprovalRequest,
    PayoutStatusEnum
)
from app.core.exceptions import NotFoundError, ValidationError, InsufficientFundsError

router = APIRouter()


def get_wallet_service(db: Session = Depends(get_db)) -> WalletService:
    """Dependency para obtener WalletService."""
    return WalletService(db)


@router.get("/wallet", response_model=WalletResponse, tags=["Wallet"])
async def get_my_wallet(
    current_user: User = Depends(get_current_user),
    wallet_service: WalletService = Depends(get_wallet_service)
):
    """
    Obtiene la wallet del rider autenticado.
    
    Requiere rol: RIDER
    """
    if current_user.role != UserRole.RIDER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo los riders pueden acceder a su wallet"
        )

    # Obtener ID del rider desde el usuario
    rider_id = current_user.rider.id if hasattr(current_user, 'rider') and current_user.rider else current_user.id

    wallet = wallet_service.get_wallet_by_rider(rider_id)
    
    if not wallet:
        # Crear wallet si no existe
        wallet = wallet_service.get_or_create_wallet(rider_id)

    return WalletResponse(
        id=wallet.id,
        rider_id=wallet.rider_id,
        balance_cents=wallet.balance_cents,
        balance_decimal=float(wallet.balance_decimal),
        currency=wallet.currency,
        is_active=wallet.is_active,
        last_transaction_at=wallet.last_transaction_at,
        created_at=wallet.created_at,
        updated_at=wallet.updated_at
    )


@router.get("/wallet/transactions", response_model=List[TransactionResponse], tags=["Wallet"])
async def get_wallet_transactions(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    wallet_service: WalletService = Depends(get_wallet_service)
):
    """
    Obtiene el historial de transacciones de la wallet del rider.
    
    Requiere rol: RIDER
    """
    if current_user.role != UserRole.RIDER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo los riders pueden acceder a sus transacciones"
        )

    rider_id = current_user.rider.id if hasattr(current_user, 'rider') and current_user.rider else current_user.id
    wallet = wallet_service.get_wallet_by_rider(rider_id)

    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Wallet no encontrada"
        )

    transactions = wallet_service.get_transactions(wallet.id, limit=limit, offset=offset)

    return [
        TransactionResponse(
            id=t.id,
            wallet_id=t.wallet_id,
            transaction_type=t.transaction_type.value,
            amount_cents=t.amount_cents,
            amount_decimal=abs(t.amount_cents) / 100,
            description=t.description,
            reference_id=t.reference_id,
            status=t.status.value,
            balance_after_cents=t.balance_after_cents,
            balance_after_decimal=t.balance_after_cents / 100,
            created_at=t.created_at
        )
        for t in transactions
    ]


@router.post("/wallet/payout-requests", response_model=PayoutRequestResponse, tags=["Wallet"])
async def create_payout_request(
    payout_data: PayoutRequestCreate,
    current_user: User = Depends(get_current_user),
    wallet_service: WalletService = Depends(get_wallet_service)
):
    """
    Crea una solicitud de retiro hacia cuenta bancaria.
    
    Requiere rol: RIDER
    """
    if current_user.role != UserRole.RIDER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo los riders pueden solicitar retiros"
        )

    rider_id = current_user.rider.id if hasattr(current_user, 'rider') and current_user.rider else current_user.id

    try:
        payout_request = wallet_service.create_payout_request(
            rider_id=rider_id,
            amount_cents=payout_data.amount_cents,
            bank_account_last4=payout_data.bank_account_last4,
            bank_name=payout_data.bank_name,
            account_holder_name=payout_data.account_holder_name
        )

        return PayoutRequestResponse(
            id=payout_request.id,
            wallet_id=payout_request.wallet_id,
            rider_id=payout_request.rider_id,
            amount_cents=payout_request.amount_cents,
            amount_decimal=payout_request.amount_cents / 100,
            currency=payout_request.currency,
            bank_account_last4=payout_request.bank_account_last4,
            bank_name=payout_request.bank_name,
            account_holder_name=payout_request.account_holder_name,
            status=payout_request.status.value,
            rejection_reason=payout_request.rejection_reason,
            created_at=payout_request.created_at,
            approved_at=payout_request.approved_at,
            processed_at=payout_request.processed_at,
            completed_at=payout_request.completed_at
        )

    except InsufficientFundsError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/wallet/payout-requests", response_model=List[PayoutRequestResponse], tags=["Wallet"])
async def get_my_payout_requests(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    wallet_service: WalletService = Depends(get_wallet_service)
):
    """
    Obtiene las solicitudes de retiro del rider autenticado.
    
    Requiere rol: RIDER
    """
    if current_user.role != UserRole.RIDER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo los riders pueden ver sus retiros"
        )

    rider_id = current_user.rider.id if hasattr(current_user, 'rider') and current_user.rider else current_user.id
    payout_requests = wallet_service.get_payout_requests(rider_id, limit=limit, offset=offset)

    return [
        PayoutRequestResponse(
            id=p.id,
            wallet_id=p.wallet_id,
            rider_id=p.rider_id,
            amount_cents=p.amount_cents,
            amount_decimal=p.amount_cents / 100,
            currency=p.currency,
            bank_account_last4=p.bank_account_last4,
            bank_name=p.bank_name,
            account_holder_name=p.account_holder_name,
            provider_payout_id=p.provider_payout_id,
            status=p.status.value,
            rejection_reason=p.rejection_reason,
            created_at=p.created_at,
            approved_at=p.approved_at,
            processed_at=p.processed_at,
            completed_at=p.completed_at
        )
        for p in payout_requests
    ]


@router.get("/admin/payout-requests/pending", response_model=List[PayoutRequestResponse], tags=["Admin - Payouts"])
async def get_pending_payout_requests(
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN, UserRole.GERENTE])),
    wallet_service: WalletService = Depends(get_wallet_service)
):
    """
    Obtiene todas las solicitudes de retiro pendientes de aprobación.
    
    Requiere rol: ADMIN o SUPERADMIN
    """
    pending_payouts = wallet_service.get_pending_payouts()

    return [
        PayoutRequestResponse(
            id=p.id,
            wallet_id=p.wallet_id,
            rider_id=p.rider_id,
            amount_cents=p.amount_cents,
            amount_decimal=p.amount_cents / 100,
            currency=p.currency,
            bank_account_last4=p.bank_account_last4,
            bank_name=p.bank_name,
            account_holder_name=p.account_holder_name,
            provider_payout_id=p.provider_payout_id,
            status=p.status.value,
            rejection_reason=p.rejection_reason,
            created_at=p.created_at,
            approved_at=p.approved_at,
            processed_at=p.processed_at,
            completed_at=p.completed_at
        )
        for p in pending_payouts
    ]


@router.post("/admin/payout-requests/{payout_id}/approve", response_model=PayoutRequestResponse, tags=["Admin - Payouts"])
async def approve_payout_request(
    payout_id: UUID,
    approval_data: Optional[PayoutApprovalRequest] = None,
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN, UserRole.GERENTE])),
    wallet_service: WalletService = Depends(get_wallet_service)
):
    """
    Aprueba una solicitud de retiro.
    
    Requiere rol: ADMIN o SUPERADMIN
    """
    try:
        provider_payout_id = approval_data.provider_payout_id if approval_data else None
        payout = wallet_service.approve_payout(payout_id, provider_payout_id)

        return PayoutRequestResponse(
            id=payout.id,
            wallet_id=payout.wallet_id,
            rider_id=payout.rider_id,
            amount_cents=payout.amount_cents,
            amount_decimal=payout.amount_cents / 100,
            currency=payout.currency,
            bank_account_last4=payout.bank_account_last4,
            bank_name=payout.bank_name,
            account_holder_name=payout.account_holder_name,
            provider_payout_id=payout.provider_payout_id,
            status=payout.status.value,
            rejection_reason=payout.rejection_reason,
            created_at=payout.created_at,
            approved_at=payout.approved_at,
            processed_at=payout.processed_at,
            completed_at=payout.completed_at
        )

    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/admin/payout-requests/{payout_id}/complete", response_model=PayoutRequestResponse, tags=["Admin - Payouts"])
async def complete_payout_request(
    payout_id: UUID,
    provider_response: Optional[Dict[str, Any]] = None,
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN, UserRole.GERENTE])),
    wallet_service: WalletService = Depends(get_wallet_service)
):
    """
    Marca un retiro como completado (después de procesarse en la pasarela/banco).
    
    Requiere rol: ADMIN o SUPERADMIN
    """
    try:
        import json
        provider_response_json = json.dumps(provider_response) if provider_response else None
        payout = wallet_service.complete_payout(payout_id, provider_response_json)

        return PayoutRequestResponse(
            id=payout.id,
            wallet_id=payout.wallet_id,
            rider_id=payout.rider_id,
            amount_cents=payout.amount_cents,
            amount_decimal=payout.amount_cents / 100,
            currency=payout.currency,
            bank_account_last4=payout.bank_account_last4,
            bank_name=payout.bank_name,
            account_holder_name=payout.account_holder_name,
            provider_payout_id=payout.provider_payout_id,
            provider_response_json=payout.provider_response_json,
            status=payout.status.value,
            rejection_reason=payout.rejection_reason,
            created_at=payout.created_at,
            approved_at=payout.approved_at,
            processed_at=payout.processed_at,
            completed_at=payout.completed_at
        )

    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/admin/payout-requests/{payout_id}/reject", response_model=PayoutRequestResponse, tags=["Admin - Payouts"])
async def reject_payout_request(
    payout_id: UUID,
    rejection_data: Dict[str, str],
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN, UserRole.GERENTE])),
    wallet_service: WalletService = Depends(get_wallet_service)
):
    """
    Rechaza una solicitud de retiro y devuelve los fondos al rider.
    
    Requiere rol: ADMIN o SUPERADMIN
    """
    reason = rejection_data.get("reason", "Sin motivo especificado")

    try:
        payout = wallet_service.reject_payout(payout_id, reason)

        return PayoutRequestResponse(
            id=payout.id,
            wallet_id=payout.wallet_id,
            rider_id=payout.rider_id,
            amount_cents=payout.amount_cents,
            amount_decimal=payout.amount_cents / 100,
            currency=payout.currency,
            bank_account_last4=payout.bank_account_last4,
            bank_name=payout.bank_name,
            account_holder_name=payout.account_holder_name,
            status=payout.status.value,
            rejection_reason=payout.rejection_reason,
            created_at=payout.created_at,
            approved_at=payout.approved_at,
            processed_at=payout.processed_at,
            completed_at=payout.completed_at,
            failed_at=payout.failed_at
        )

    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
