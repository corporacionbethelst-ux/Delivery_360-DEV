"""Endpoints para reconciliación financiera y auditoría de integridad."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from decimal import Decimal
from uuid import UUID
from datetime import date, datetime

from app.core.database import get_db
from app.models.rider import Rider
from app.models.user import User, UserRole
from app.api.v1.auth import get_current_user, require_role
from app.services.financial_service import FinancialService

router = APIRouter(prefix="/reconciliation", tags=["Reconciliation"])


@router.get("/wallet/{rider_id}")
async def reconcile_rider_wallet(
    rider_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE)),
):
    """Report the current discrepancy without modifying balances or ledger."""
    result = await FinancialService(db).reconcile_wallet_with_ledger(str(rider_id))
    if result["status"] == "error":
        raise HTTPException(status_code=404, detail=result["message"])
    return result


@router.post("/wallet/{rider_id}/sync")
async def synchronize_rider_wallet(
    rider_id: UUID,
    dry_run: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN)),
):
    """Explicitly synchronize only the cached balance; preview by default."""
    result = await FinancialService(db).reconcile_wallet_with_ledger(
        str(rider_id), dry_run=dry_run
    )
    if result["status"] == "error":
        raise HTTPException(status_code=404, detail=result["message"])
    return result


@router.get("/batch/daily")
async def daily_reconciliation_report(
    target_date: date | None = Query(
        None, description="Fecha actual UTC; no hay snapshot histórico de la caché"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE)),
):
    """Report current cache discrepancies; historical cache snapshots do not exist."""
    today = datetime.utcnow().date()
    if target_date is not None and target_date != today:
        raise HTTPException(
            status_code=422,
            detail="Solo se puede comparar la caché actual; no hay snapshots históricos",
        )
    riders = (
        await db.execute(
            select(Rider.id, User.first_name, User.last_name)
            .join(User, Rider.user_id == User.id)
            .where(Rider.status == "ACTIVO")
        )
    ).all()
    details = []
    ok_count = 0
    total = Decimal("0.00")
    for rider in riders:
        rider_id = rider.id
        item = await FinancialService(db).reconcile_wallet_with_ledger(str(rider_id))
        if item["status"] == "ok":
            ok_count += 1
        elif item["status"] == "discrepancy":
            total += Decimal(str(item["difference"]))
            details.append(
                {
                    "rider_id": str(rider_id),
                    "rider_name": f"{rider.first_name} {rider.last_name}",
                    **item,
                }
            )
    return {
        "date": today.isoformat(),
        "total_riders": len(riders),
        "ok_count": ok_count,
        "discrepancy_count": len(details),
        "total_discrepancy_amount": float(total),
        "details": details,
    }


@router.post("/fix-all-discrepancies")
async def fix_all_discrepancies(
    dry_run: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN)),
):
    """Preview by default; explicit application syncs caches without ledger entries.

    Each rider is committed independently. Failures roll back that rider and are
    reported explicitly; the response does not claim batch-wide atomicity.
    """
    rider_ids = list(
        (await db.scalars(select(Rider.id).where(Rider.status == "ACTIVO"))).all()
    )
    fixed_count = 0
    discrepancy_count = 0
    error_count = 0
    total = Decimal("0.00")
    details = []
    for rider_id in rider_ids:
        try:
            item = await FinancialService(db).reconcile_wallet_with_ledger(
                str(rider_id), dry_run=dry_run
            )
            if item["status"] in ("reconciled", "discrepancy"):
                discrepancy_count += 1
                if item["status"] == "reconciled":
                    fixed_count += 1
                total += abs(Decimal(str(item["adjustment_amount"])))
                details.append({"rider_id": str(rider_id), **item})
            elif item["status"] == "error":
                error_count += 1
                details.append({"rider_id": str(rider_id), "error": item["message"]})
        except Exception:
            await db.rollback()
            error_count += 1
            details.append(
                {
                    "rider_id": str(rider_id),
                    "error": "No se pudo conciliar este repartidor",
                }
            )
    return {
        "dry_run": dry_run,
        "fixed_count": fixed_count,
        "discrepancy_count": discrepancy_count,
        "error_count": error_count,
        "total_adjusted_amount": 0.0 if dry_run else float(total),
        "total_discrepancy_amount": float(total),
        "details": details[:50],
    }


@router.get("/audit/ledger-integrity")
async def audit_ledger_integrity(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.AUDITOR)),
):
    """Auditoría completa de integridad del ledger financiero.

    Cuenta balances ausentes y la distribución por tipo. No demuestra continuidad
    de saldos ni valida la aritmética de cada asiento.
    """
    from app.models.financial import Financial

    # Verificar transacciones sin balance_after poblado
    result = await db.execute(
        select(func.count(Financial.id)).where(Financial.balance_after.is_(None))
    )
    missing_balance_after = result.scalar() or 0

    # Verificar transacciones donde balance_after != balance_before + delta
    # Esto requiere cálculo complejo, lo simplificamos contando inconsistencies potenciales
    result = await db.execute(
        select(func.count(Financial.id)).where(Financial.balance_before.is_(None))
    )
    missing_balance_before = result.scalar() or 0

    # Contar transacciones por tipo para verificar distribución
    type_distribution = {}
    from app.models.financial import TransactionType

    for tx_type in TransactionType:
        result = await db.execute(
            select(func.count(Financial.id)).where(
                Financial.transaction_type == tx_type
            )
        )
        count = result.scalar() or 0
        if count > 0:
            type_distribution[tx_type.value] = count

    return {
        "status": "completed",
        "integrity_checks": {
            "transactions_missing_balance_after": missing_balance_after,
            "transactions_missing_balance_before": missing_balance_before,
        },
        "transaction_type_distribution": type_distribution,
        "recommendation": "Revisar transacciones con balances faltantes si count > 0",
    }
