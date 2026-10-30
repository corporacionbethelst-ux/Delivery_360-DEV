"""Canonical operational dashboard URLs; legacy double-prefix aliases retained."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.auth import require_role
from app.core.database import get_db
from app.models.user import User, UserRole
from app.schemas.operational_dashboard import DashboardSnapshot
from app.services.dashboard_service import DashboardService

router = APIRouter()


@router.get("/manager", response_model=DashboardSnapshot)
@router.get(
    "/dashboard/manager", response_model=DashboardSnapshot, include_in_schema=False
)
async def manager_dashboard(
    days: int = Query(1, ge=1, le=31),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE)),
):
    return await DashboardService(db).snapshot(days)


@router.get("/operator", response_model=DashboardSnapshot)
@router.get(
    "/dashboard/operator", response_model=DashboardSnapshot, include_in_schema=False
)
async def operator_dashboard(
    days: int = Query(1, ge=1, le=31),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.SUPERADMIN, UserRole.GERENTE, UserRole.OPERADOR)
    ),
):
    return await DashboardService(db).snapshot(days, operator=True)
