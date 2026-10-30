"""Safe integration registry. No provider credentials, probes, or activation API."""

from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.auth import require_role
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models.integration import IntegrationType, IntegrationStatus
from app.models.user import User, UserRole
from app.schemas.integration import (
    IntegrationCreate,
    IntegrationPatch,
    IntegrationRead,
    IntegrationDiagnostic,
)
from app.services.integration_service import IntegrationService

router = APIRouter()
reader = require_role(UserRole.SUPERADMIN, UserRole.GERENTE)
writer = require_role(UserRole.SUPERADMIN)


@router.get("", response_model=list[IntegrationRead])
@router.get("/", response_model=list[IntegrationRead], include_in_schema=False)
@router.get(
    "/integrations", response_model=list[IntegrationRead], include_in_schema=False
)
async def list_integrations(
    integration_type: IntegrationType | None = None,
    status: IntegrationStatus | None = None,
    skip: int = Query(0, ge=0, le=10000),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(reader),
):
    return await IntegrationService(db).list_integrations(
        integration_type, status, skip=skip, limit=limit
    )


@router.post("", response_model=IntegrationRead, status_code=201)
async def create_integration(
    payload: IntegrationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(writer),
):
    service = IntegrationService(db)
    row = await service.create_integration(**payload.model_dump(), actor=current_user)
    return await service.get_summary(row.id)


@router.get("/{integration_id}", response_model=IntegrationRead)
async def get_integration(
    integration_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(reader),
):
    result = await IntegrationService(db).get_summary(integration_id)
    if result is None:
        raise NotFoundError("Integración no encontrada")
    return result


@router.patch("/{integration_id}", response_model=IntegrationRead)
async def patch_integration(
    integration_id: UUID,
    payload: IntegrationPatch,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(writer),
):
    return await IntegrationService(db).patch_metadata(
        integration_id, payload, actor=current_user
    )


@router.post("/{integration_id}/pause", response_model=IntegrationRead)
async def pause_integration(
    integration_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(writer),
):
    return await IntegrationService(db).pause(integration_id, actor=current_user)


@router.get("/{integration_id}/diagnostics", response_model=IntegrationDiagnostic)
async def integration_diagnostics(
    integration_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(reader),
):
    return await IntegrationService(db).diagnostics(integration_id)
