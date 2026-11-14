"""Venezuelan BCV reference registry and preserved USD/VES quotations."""

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import require_role
from app.core.database import get_db
from app.models.currency import UsdVesQuote, BcvRate
from app.models.order_currency_quote import OrderCurrencyQuote
from app.services import order_currency_quote as order_quotes
from app.models.user import User, UserRole
from app.services import bcv_currency as service

router = APIRouter(prefix="/currency", tags=["Currency"])


class BcvRateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    previous_rate_id: UUID | None
    valid_on: date
    reference_date: date
    ves_per_usd: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,8})?$")
    note: str = Field(min_length=1, max_length=500)
    confirmed_bcv: Literal[True]

    @field_validator("confirmed_bcv", mode="before")
    @classmethod
    def strict_confirmation(cls, value):
        if value is not True:
            raise ValueError("Confirma explícitamente la referencia BCV")
        return value

    @field_validator("ves_per_usd")
    @classmethod
    def positive_rate(cls, value):
        if Decimal(value) <= 0:
            raise ValueError("La tasa debe ser positiva")
        return value

    @field_validator("note")
    @classmethod
    def clean_note(cls, value):
        value = value.strip()
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError("Escribe una referencia visible sin caracteres de control")
        return value


class UsdVesQuoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    rate_id: UUID
    amount_usd: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,2})?$")
    reference: str = Field(min_length=1, max_length=120)

    @field_validator("reference")
    @classmethod
    def clean_reference(cls, value):
        return BcvRateInput.clean_note(value)


@router.get("/context")
async def currency_context(
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(
        require_role(*sorted(service.READ_ROLES, key=lambda role: role.value))
    ),
):
    return await service.context_view(db)


@router.post("/rates", status_code=201)
async def save_bcv_rate(
    body: BcvRateInput,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE)),
):
    return await service.record_rate(db, actor, body)


@router.post("/quotes", status_code=201)
async def save_usd_ves_quote(
    body: UsdVesQuoteInput,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(
        require_role(UserRole.SUPERADMIN, UserRole.GERENTE, UserRole.OPERADOR)
    ),
):
    return await service.create_quote(db, actor, body)


@router.get("/quotes/{quote_id}")
async def get_usd_ves_quote(
    quote_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(
        require_role(*sorted(service.READ_ROLES, key=lambda role: role.value))
    ),
):
    row = await db.get(UsdVesQuote, quote_id)
    if row is None:
        raise HTTPException(404, "Cotización no encontrada")
    if actor.role == UserRole.OPERADOR and row.created_by != actor.id:
        raise HTTPException(403, "La cotización pertenece a otra cuenta")
    return await service.receipt_view(db, row)


class OrderQuoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    rate_id: UUID
    expected_pricing_revision: int = Field(ge=1, le=2147483647, strict=True)


@router.get("/orders/{order_id}/quotes")
async def order_quote_context(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(
        require_role(*sorted(service.READ_ROLES, key=lambda role: role.value))
    ),
):
    return await order_quotes.context_view(db, actor, order_id)


@router.post("/orders/{order_id}/quotes", status_code=201)
async def save_order_quote(
    order_id: UUID,
    body: OrderQuoteInput,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(
        require_role(UserRole.SUPERADMIN, UserRole.GERENTE, UserRole.OPERADOR)
    ),
):
    return await order_quotes.create(db, actor, order_id, body)


@router.get("/order-quotes/{quote_id}")
async def get_order_quote(
    quote_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(
        require_role(*sorted(service.READ_ROLES, key=lambda role: role.value))
    ),
):
    row = await db.get(OrderCurrencyQuote, quote_id)
    if row is None:
        raise HTTPException(404, "Comprobante de cotización no encontrado")
    if actor.role == UserRole.OPERADOR and row.created_by != actor.id:
        raise HTTPException(403, "El comprobante pertenece a otra cuenta")
    return await order_quotes.receipt_view(db, row)
