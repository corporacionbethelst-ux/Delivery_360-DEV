"""Read-only, bounded reports from verified customer payments and refunds."""

from datetime import date
import re
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, Query, Request, HTTPException
from pydantic import BeforeValidator
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.api.v1.auth import require_role
from app.api.v1.customer_collections import CollectionInput
from app.models.user import User, UserRole
from app.services import customer_cashbook as service

router = APIRouter(prefix="/customer-cashbook", tags=["Customer Cashbook"])


def civil_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Usa una fecha YYYY-MM-DD de Caracas")
    return date.fromisoformat(value)


def source(value):
    result = CollectionInput.canonical_key(value)
    if len(result) > 80:
        raise ValueError("El alias de caja/cuenta admite hasta 80 caracteres")
    return result


CivilDate = Annotated[date, BeforeValidator(civil_date)]
SourceKey = Annotated[str, BeforeValidator(source)]


@router.get("/report")
async def report(
    request: Request,
    date_from: Annotated[CivilDate | None, Query()] = None,
    date_to: Annotated[CivilDate | None, Query()] = None,
    method: Annotated[
        Literal["EFECTIVO", "TRANSFERENCIA", "PAGO_MOVIL"] | None, Query()
    ] = None,
    currency: Annotated[Literal["USD", "VES"] | None, Query()] = None,
    source_key: Annotated[SourceKey | None, Query(max_length=80)] = None,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(
        require_role(UserRole.SUPERADMIN, UserRole.GERENTE, UserRole.AUDITOR)
    ),
):
    allowed = {"date_from", "date_to", "method", "currency", "source_key"}
    if set(request.query_params) - allowed or any(
        len(request.query_params.getlist(key)) != 1 for key in request.query_params
    ):
        raise HTTPException(
            422, "Los filtros del reporte son desconocidos o están repetidos"
        )
    return await service.report(db, date_from, date_to, method, currency, source_key)
