"""Bounded previews and explicit, versioned reconciliation of the legacy Rider cache."""

from datetime import date, datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.auth import require_role
from app.core.database import get_db
from app.core.exceptions import AppException
from app.models.rider import RiderStatus
from app.models.user import User, UserRole
from app.schemas.cache_reconciliation import (
    CachePreview,
    CacheSyncRequest,
    CacheSyncResult,
    CachePreviewPage,
    LedgerAuditPage,
)
from app.services.cache_reconciliation import CacheReconciliationService

router = APIRouter(prefix="/reconciliation", tags=["Reconciliation"])
reader = require_role(UserRole.SUPERADMIN, UserRole.GERENTE)
writer = require_role(UserRole.SUPERADMIN)
auditor = require_role(UserRole.SUPERADMIN, UserRole.AUDITOR)


@router.get("/wallet/{rider_id}", response_model=CachePreview)
async def reconcile_rider_wallet(
    rider_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(reader),
):
    return await CacheReconciliationService(db).preview(rider_id)


@router.post("/wallet/{rider_id}/sync", response_model=CachePreview | CacheSyncResult)
async def synchronize_rider_wallet(
    rider_id: UUID,
    payload: CacheSyncRequest | None = None,
    dry_run: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(writer),
):
    service = CacheReconciliationService(db)
    if dry_run:
        return await service.preview(rider_id)
    if payload is None:
        raise AppException(
            "Se requiere previsualización, versión, huella y motivo antes de sincronizar",
            428,
        )
    return await service.apply(rider_id, payload, current_user)


@router.get("/batch/daily", response_model=CachePreviewPage)
async def daily_reconciliation_report(
    target_date: date | None = Query(
        None, description="Estado actual UTC; no existen snapshots históricos de caché"
    ),
    limit: int = Query(25, ge=1, le=25),
    after_id: UUID | None = None,
    rider_status: RiderStatus | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(reader),
):
    if target_date is not None and target_date != datetime.now(timezone.utc).date():
        raise AppException("Solo puede consultarse el estado actual de la caché", 422)
    return await CacheReconciliationService(db).preview_page(
        limit, after_id, rider_status
    )


@router.post("/fix-all-discrepancies", response_model=CachePreviewPage)
async def fix_all_discrepancies(
    dry_run: bool = Query(True),
    limit: int = Query(25, ge=1, le=25),
    after_id: UUID | None = None,
    rider_status: RiderStatus | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(writer),
):
    if not dry_run:
        raise AppException(
            "La aplicación masiva requiere revisiones individuales con versión, huella y motivo",
            409,
        )
    return await CacheReconciliationService(db).preview_page(
        limit, after_id, rider_status
    )


@router.get("/audit/ledger-integrity", response_model=LedgerAuditPage)
async def audit_ledger_integrity(
    limit: int = Query(25, ge=1, le=25),
    after_id: UUID | None = None,
    rider_status: RiderStatus | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(auditor),
):
    return await CacheReconciliationService(db).audit_page(
        limit, after_id, rider_status
    )
