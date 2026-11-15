"""Requests, authorization and independent confirmation of manual refunds."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    BeforeValidator,
    field_validator,
    model_validator,
)
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.auth import require_role
from app.api.v1.customer_collections import paid_input, CollectionInput
from app.core.database import get_db
from app.models.user import User, UserRole
from app.services import customer_refunds as service
from app.services.order_pricing import MoneyInput

router = APIRouter(prefix="/customer-refunds", tags=["Customer Refunds"])
read_role = require_role(
    UserRole.SUPERADMIN, UserRole.GERENTE, UserRole.OPERADOR, UserRole.AUDITOR
)
request_role = require_role(UserRole.SUPERADMIN, UserRole.GERENTE, UserRole.OPERADOR)
review_role = require_role(UserRole.SUPERADMIN, UserRole.GERENTE)


def note_input(value):
    value = value.strip()
    if len(value) < 10 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(
            "Explica el motivo o la comprobación sin caracteres de control"
        )
    return value


class RefundRequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    collection_id: UUID
    expected_book_revision: int = Field(ge=0, le=2147483647, strict=True)
    amount_usd: MoneyInput = Field(gt=0)
    reason: str = Field(min_length=10, max_length=500)
    confirmed_request: Literal[True]

    @field_validator("confirmed_request", mode="before")
    @classmethod
    def confirmation(cls, value):
        if value is not True:
            raise ValueError("Confirma la solicitud de devolución")
        return value

    @field_validator("reason")
    @classmethod
    def visible_reason(cls, value):
        return note_input(value)


class RefundEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    expected_revision: int = Field(ge=0, le=2147483646, strict=True)
    kind: Literal[
        "APROBAR",
        "RECHAZAR",
        "DECLARAR_EJECUCION",
        "VERIFICAR_DEVOLUCION",
        "OBSERVAR_EJECUCION",
        "CONFIRMAR_NO_EJECUTADA",
        "ANULAR_APROBACION",
    ]
    note: str = Field(min_length=10, max_length=500)
    verified_evidence: bool = Field(strict=True)
    confirmed_no_execution: bool = Field(default=False, strict=True)
    confirmed_execution: bool = Field(default=False, strict=True)
    method: Literal["EFECTIVO", "TRANSFERENCIA", "PAGO_MOVIL"] | None = None
    source_key: str | None = Field(default=None, min_length=1, max_length=80)
    reference_key: str | None = Field(default=None, min_length=1, max_length=120)
    paid_amount: Annotated[Decimal, BeforeValidator(paid_input)] | None = None
    paid_currency: Literal["USD", "VES"] | None = None
    executed_on: date | None = None

    @field_validator("note")
    @classmethod
    def visible_note(cls, value):
        return note_input(value)

    @field_validator("source_key", "reference_key")
    @classmethod
    def canonical(cls, value):
        return CollectionInput.canonical_key(value) if value is not None else None

    @model_validator(mode="after")
    def coherent(self):
        execution = self.kind == "DECLARAR_EJECUCION"
        fields = (
            self.method,
            self.source_key,
            self.reference_key,
            self.paid_amount,
            self.paid_currency,
            self.executed_on,
        )
        if execution and (
            any(x is None for x in fields) or not self.confirmed_execution
        ):
            raise ValueError(
                "Indica y confirma el importe realmente devuelto, su medio, fecha y referencia"
            )
        if not execution and any(x is not None for x in fields):
            raise ValueError("Solo una declaración de ejecución admite datos de salida")
        if self.confirmed_execution != execution:
            raise ValueError(
                "La confirmación de ejecución corresponde solo a su declaración"
            )
        no_execution = self.kind in ("CONFIRMAR_NO_EJECUTADA", "ANULAR_APROBACION")
        if self.confirmed_no_execution != no_execution:
            raise ValueError("Confirma explícitamente que no hubo salida de dinero")
        evidence = self.kind in (
            "VERIFICAR_DEVOLUCION",
            "CONFIRMAR_NO_EJECUTADA",
            "ANULAR_APROBACION",
        )
        if self.verified_evidence != evidence:
            raise ValueError(
                "La comprobación de evidencia no corresponde a esta acción"
            )
        if self.method == "PAGO_MOVIL" and self.paid_currency != "VES":
            raise ValueError("Pago móvil debe registrarse en VES")
        return self


@router.get("/orders/{order_id}")
async def context(
    order_id: UUID, db: AsyncSession = Depends(get_db), actor: User = Depends(read_role)
):
    return await service.context(db, actor, order_id)


@router.post("/orders/{order_id}", status_code=201)
async def request_refund(
    order_id: UUID,
    body: RefundRequestInput,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(request_role),
):
    return await service.request_refund(db, actor, order_id, body)


@router.get("/{refund_id}")
async def receipt(
    refund_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(read_role),
):
    return await service.get_receipt(db, actor, refund_id)


@router.get("/{refund_id}/events")
async def events(
    refund_id: UUID,
    before_revision: int | None = Query(default=None, ge=1, le=2147483647),
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(read_role),
):
    return await service.event_page(db, actor, refund_id, before_revision)


@router.post("/{refund_id}/events", status_code=201)
async def event(
    refund_id: UUID,
    body: RefundEventInput,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(review_role),
):
    return await service.add_event(db, actor, refund_id, body)
