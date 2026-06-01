from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from decimal import Decimal


class TransactionType(str, Enum):
    PAYMENT = "payment"
    REFUND = "refund"
    COMMISSION = "commission"
    PENALTY = "penalty"
    REWARD = "reward"
    WITHDRAWAL = "withdrawal"


class FinancialTransactionBase(BaseModel):
    amount: Decimal = Field(..., description="Monto de la transacción")
    transaction_type: TransactionType = Field(..., description="Tipo de transacción")
    description: Optional[str] = Field(None, max_length=255)
    reference_id: Optional[str] = Field(None, max_length=100)


class FinancialTransactionCreate(FinancialTransactionBase):
    rider_id: int
    order_id: Optional[int] = None


class FinancialTransactionUpdate(BaseModel):
    amount: Optional[Decimal] = None
    description: Optional[str] = Field(None, max_length=255)


class FinancialTransactionResponse(FinancialTransactionBase):
    id: int
    rider_id: int
    order_id: Optional[int]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PaymentRuleBase(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    commission_rate: Decimal = Field(..., ge=0, le=1, description="Porcentaje de comisión (0-1)")
    min_amount: Decimal = Field(..., ge=0)
    max_amount: Optional[Decimal] = None


class PaymentRuleCreate(PaymentRuleBase):
    """Schema para crear una regla de pago"""
    pass


class PaymentRuleUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    commission_rate: Optional[Decimal] = Field(None, ge=0, le=1)
    min_amount: Optional[Decimal] = Field(None, ge=0)
    max_amount: Optional[Decimal] = None


class PaymentRuleResponse(PaymentRuleBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class LiquidationBase(BaseModel):
    total_amount: Decimal
    period_start: datetime
    period_end: datetime
    status: str = Field(default="pending", pattern=r"^(pending|processing|completed|failed)$")


class LiquidationCreate(LiquidationBase):
    rider_id: int


class LiquidationUpdate(BaseModel):
    status: Optional[str] = Field(None, pattern=r"^(pending|processing|completed|failed)$")


class LiquidationResponse(LiquidationBase):
    id: int
    rider_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FinancialConsolidated(BaseModel):
    total_earnings: Decimal
    total_commissions: Decimal
    total_penalties: Decimal
    net_amount: Decimal
    transaction_count: int
    period_start: datetime
    period_end: datetime
