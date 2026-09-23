"""
Pydantic Schemas para Wallet y Pagos - Fase 7 Enterprise
Sincronizado con enums de estado en español.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any, List
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from app.models.financial import PayoutStatus


class PayoutStatusEnum(str, Enum):
    """Enum de estados de retiro en español para validación Pydantic."""
    PENDIENTE = "PENDIENTE"
    APROBADO = "APROBADO"
    EN_PROCESO = "EN_PROCESO"
    COMPLETADO = "COMPLETADO"
    RECHAZADO = "RECHAZADO"
    FALLIDO = "FALLIDO"


class WalletResponse(BaseModel):
    """Respuesta de información de wallet."""
    id: UUID
    rider_id: UUID
    balance_cents: int
    balance_decimal: float
    currency: str
    is_active: bool
    last_transaction_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TransactionResponse(BaseModel):
    """Respuesta de transacción individual."""
    id: UUID
    wallet_id: UUID
    transaction_type: str
    amount_cents: int
    amount_decimal: float
    description: Optional[str] = None
    reference_id: Optional[str] = None
    status: str
    balance_after_cents: int
    balance_after_decimal: float
    created_at: datetime

    class Config:
        from_attributes = True


class PayoutRequestCreate(BaseModel):
    """Schema para crear solicitud de retiro."""
    amount_cents: int = Field(..., gt=0, description="Monto en centavos (debe ser positivo)")
    bank_account_last4: str = Field(..., min_length=4, max_length=4, description="Últimos 4 dígitos de la cuenta")
    bank_name: str = Field(..., min_length=1, max_length=100, description="Nombre del banco")
    account_holder_name: str = Field(..., min_length=1, max_length=255, description="Nombre del titular")

    @field_validator('bank_account_last4')
    @classmethod
    def validate_bank_account(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError('Los últimos 4 dígitos deben ser numéricos')
        return v


class PayoutApprovalRequest(BaseModel):
    """Schema para aprobar retiro con ID de proveedor."""
    provider_payout_id: Optional[str] = Field(None, max_length=255, description="ID del payout en la pasarela (Stripe, etc.)")


class PayoutRequestResponse(BaseModel):
    """Respuesta de solicitud de retiro con estados en español."""
    id: UUID
    wallet_id: UUID
    rider_id: UUID
    amount_cents: int
    amount_decimal: float
    currency: str
    bank_account_last4: Optional[str] = None
    bank_name: Optional[str] = None
    account_holder_name: Optional[str] = None
    provider_payout_id: Optional[str] = None
    provider_response_json: Optional[str] = None
    status: PayoutStatusEnum  # Usa enum en español
    rejection_reason: Optional[str] = None
    failure_reason: Optional[str] = None  # Razón del fallo cuando status=FALLIDO
    created_at: datetime
    approved_at: Optional[datetime] = None
    processed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class WalletSummary(BaseModel):
    """Resumen de wallet para dashboard."""
    total_balance_cents: int
    total_balance_decimal: float
    pending_payouts_cents: int
    pending_payouts_decimal: float
    available_balance_cents: int
    available_balance_decimal: float
    currency: str
    transactions_count: int
    last_transaction_at: Optional[datetime] = None


class TransactionCreate(BaseModel):
    """Schema para crear transacción manual (admin)."""
    rider_id: UUID
    amount_cents: int = Field(..., description="Monto en centavos (positivo=ingreso, negativo=egreso)")
    transaction_type: str
    description: str
    reference_id: Optional[str] = None
    metadata_json: Optional[Dict[str, Any]] = None
