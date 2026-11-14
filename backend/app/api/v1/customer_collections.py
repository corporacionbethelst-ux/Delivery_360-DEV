"""Manual declarations and verification; no bank execution or rider wallet writes."""

from datetime import date
from decimal import Decimal
import re
from typing import Literal, Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
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
from app.core.database import get_db
from app.models.user import User, UserRole
from app.services import customer_collections as service
from app.services.order_pricing import MoneyInput

router = APIRouter(prefix="/customer-collections", tags=["Customer Collections"])


def paid_input(value):
    if (
        isinstance(value, bool)
        or not isinstance(value, (str, int, float, Decimal))
        or not re.fullmatch(r"(?:0|[1-9][0-9]{0,20})(?:\.[0-9]{1,2})?", str(value))
    ):
        raise ValueError("Importe recibido inválido: usa dos decimales, sin exponentes")
    amount = Decimal(str(value))
    if not 0 < amount < Decimal("1000000000000000000000"):
        raise ValueError("El importe recibido debe ser positivo")
    return amount.quantize(Decimal("0.01"))


class CollectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    expected_pricing_revision: int = Field(ge=1, le=2147483647, strict=True)
    expected_collection_revision: int = Field(ge=0, le=2147483647, strict=True)
    amount_usd: MoneyInput = Field(gt=0)
    paid_amount: Annotated[Decimal, BeforeValidator(paid_input)]
    paid_currency: Literal["USD", "VES"]
    method: Literal["EFECTIVO", "TRANSFERENCIA", "PAGO_MOVIL"]
    source_key: str = Field(min_length=1, max_length=80)
    reference_key: str = Field(min_length=1, max_length=120)
    received_on: date
    quote_id: UUID | None = None
    confirmed_received: Literal[True]

    @field_validator("confirmed_received", mode="before")
    @classmethod
    def strict_confirmation(cls, value):
        if value is not True:
            raise ValueError("Confirma explícitamente el cobro declarado")
        return value

    @field_validator("source_key", "reference_key")
    @classmethod
    def canonical_key(cls, value):
        value = re.sub(" +", " ", value.strip()).upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9 ._/#:\-]*", value):
            raise ValueError(
                "Usa un identificador completo con letras, números y separadores simples"
            )
        return value

    @model_validator(mode="after")
    def coherent_currency(self):
        if self.method == "PAGO_MOVIL" and self.paid_currency != "VES":
            raise ValueError("Pago móvil debe declararse en bolívares")
        if (self.paid_currency == "VES") != (self.quote_id is not None):
            raise ValueError(
                "VES requiere cotización de la orden; USD no utiliza cotización"
            )
        return self


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    expected_collection_revision: int = Field(ge=1, le=2147483647, strict=True)
    decision: Literal["VERIFICADO", "RECHAZADO"]
    note: str = Field(min_length=10, max_length=500)
    verified_evidence: bool = Field(strict=True)
    acknowledge_refund_due: bool = Field(default=False, strict=True)

    @field_validator("note")
    @classmethod
    def visible_note(cls, value):
        value = value.strip()
        if len(value) < 10 or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError(
                "Describe la comprobación o el rechazo sin caracteres de control"
            )
        return value

    @model_validator(mode="after")
    def evidence_required(self):
        if self.verified_evidence != (self.decision == "VERIFICADO"):
            raise ValueError(
                "Una verificación exige confirmar la evidencia; un rechazo no la confirma"
            )
        return self


@router.get("/orders/{order_id}")
async def context(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(
        require_role(
            UserRole.SUPERADMIN, UserRole.GERENTE, UserRole.OPERADOR, UserRole.AUDITOR
        )
    ),
):
    return await service.context(db, actor, order_id)


@router.post("/orders/{order_id}", status_code=201)
async def declare(
    order_id: UUID,
    body: CollectionInput,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(
        require_role(UserRole.SUPERADMIN, UserRole.GERENTE, UserRole.OPERADOR)
    ),
):
    return await service.declare(db, actor, order_id, body)


@router.post("/{collection_id}/review", status_code=201)
async def review(
    collection_id: UUID,
    body: ReviewInput,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE)),
):
    return await service.review(db, actor, collection_id, body)


@router.get("/{collection_id}")
async def get_receipt(
    collection_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(
        require_role(
            UserRole.SUPERADMIN, UserRole.GERENTE, UserRole.OPERADOR, UserRole.AUDITOR
        )
    ),
):
    return await service.get_receipt(db, actor, collection_id)
