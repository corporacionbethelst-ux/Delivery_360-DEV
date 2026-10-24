"""API for the existing alternative wallet; no bank transfers are executed here."""

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user, require_role
from app.core.database import get_db
from app.core.exceptions import AppException
from app.models.financial import FinancialTransaction, PayoutRequest
from app.models.user import User, UserRole
from app.schemas.wallet import (
    PayoutApprovalRequest,
    PayoutRequestCreate,
    PayoutRequestResponse,
    TransactionResponse,
    WalletResponse,
)
from app.services.wallet_service import WalletService

router = APIRouter()


def get_wallet_service(db: AsyncSession = Depends(get_db)) -> WalletService:
    return WalletService(db)


async def _rider_id(user: User, service: WalletService) -> UUID:
    if user.role != UserRole.REPARTIDOR:
        raise HTTPException(
            status_code=403, detail="Solo los repartidores pueden acceder a su wallet"
        )
    return await service.rider_id_for_user(user.id)


def _transaction_out(transaction: FinancialTransaction) -> TransactionResponse:
    return TransactionResponse.model_validate(
        {
            **{
                name: getattr(transaction, name)
                for name in TransactionResponse.model_fields
                if hasattr(transaction, name)
            },
            "transaction_type": transaction.transaction_type.value,
            "status": transaction.status.value,
            "amount_decimal": abs(transaction.amount_cents) / 100,
            "balance_after_decimal": transaction.balance_after_cents / 100,
        }
    )


def _payout_out(payout: PayoutRequest) -> PayoutRequestResponse:
    return PayoutRequestResponse.model_validate(
        {
            **{
                name: getattr(payout, name)
                for name in PayoutRequestResponse.model_fields
                if hasattr(payout, name)
            },
            "amount_decimal": payout.amount_cents / 100,
        }
    )


@router.get("/wallet", response_model=WalletResponse, tags=["Wallet"])
async def get_my_wallet(
    current_user: User = Depends(get_current_user),
    wallet_service: WalletService = Depends(get_wallet_service),
):
    try:
        rider_id = await _rider_id(current_user, wallet_service)
        wallet = await wallet_service.get_or_create_wallet(rider_id)
        return WalletResponse.model_validate(wallet)
    except AppException as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get(
    "/wallet/transactions", response_model=list[TransactionResponse], tags=["Wallet"]
)
async def get_wallet_transactions(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    wallet_service: WalletService = Depends(get_wallet_service),
):
    try:
        rider_id = await _rider_id(current_user, wallet_service)
        wallet = await wallet_service.get_wallet_by_rider(rider_id)
        if wallet is None:
            raise HTTPException(status_code=404, detail="Wallet no encontrada")
        return [
            _transaction_out(row)
            for row in await wallet_service.get_transactions(wallet.id, limit, offset)
        ]
    except AppException as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post(
    "/wallet/payout-requests", response_model=PayoutRequestResponse, tags=["Wallet"]
)
async def create_payout_request(
    payout_data: PayoutRequestCreate,
    current_user: User = Depends(get_current_user),
    wallet_service: WalletService = Depends(get_wallet_service),
):
    try:
        rider_id = await _rider_id(current_user, wallet_service)
        payout = await wallet_service.create_payout_request(
            rider_id=rider_id,
            amount_cents=payout_data.amount_cents,
            bank_account_last4=payout_data.bank_account_last4,
            bank_name=payout_data.bank_name,
            account_holder_name=payout_data.account_holder_name,
            idempotency_key=payout_data.idempotency_key,
        )
        return _payout_out(payout)
    except AppException as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get(
    "/wallet/payout-requests",
    response_model=list[PayoutRequestResponse],
    tags=["Wallet"],
)
async def get_my_payout_requests(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    wallet_service: WalletService = Depends(get_wallet_service),
):
    try:
        rider_id = await _rider_id(current_user, wallet_service)
        return [
            _payout_out(row)
            for row in await wallet_service.get_payout_requests(rider_id, limit, offset)
        ]
    except AppException as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get(
    "/admin/payout-requests/pending",
    response_model=list[PayoutRequestResponse],
    tags=["Admin - Payouts"],
)
async def get_pending_payout_requests(
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE)),
    wallet_service: WalletService = Depends(get_wallet_service),
):
    return [_payout_out(row) for row in await wallet_service.get_pending_payouts()]


@router.post(
    "/admin/payout-requests/{payout_id}/approve",
    response_model=PayoutRequestResponse,
    tags=["Admin - Payouts"],
)
async def approve_payout_request(
    payout_id: UUID,
    approval_data: PayoutApprovalRequest | None = None,
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE)),
    wallet_service: WalletService = Depends(get_wallet_service),
):
    try:
        return _payout_out(
            await wallet_service.approve_payout(
                payout_id, approval_data.provider_payout_id if approval_data else None
            )
        )
    except AppException as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post(
    "/admin/payout-requests/{payout_id}/complete",
    response_model=PayoutRequestResponse,
    tags=["Admin - Payouts"],
)
async def complete_payout_request(
    payout_id: UUID,
    provider_response: dict[str, object] | None = None,
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE)),
    wallet_service: WalletService = Depends(get_wallet_service),
):
    try:
        response = (
            json.dumps(provider_response) if provider_response is not None else None
        )
        return _payout_out(await wallet_service.complete_payout(payout_id, response))
    except AppException as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post(
    "/admin/payout-requests/{payout_id}/reject",
    response_model=PayoutRequestResponse,
    tags=["Admin - Payouts"],
)
async def reject_payout_request(
    payout_id: UUID,
    rejection_data: dict[str, str],
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE)),
    wallet_service: WalletService = Depends(get_wallet_service),
):
    try:
        return _payout_out(
            await wallet_service.reject_payout(
                payout_id, rejection_data.get("reason", "Sin motivo especificado")
            )
        )
    except AppException as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
