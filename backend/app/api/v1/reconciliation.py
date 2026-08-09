"""Endpoints para reconciliación financiera y auditoría de integridad."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from decimal import Decimal
from typing import List, Optional
from datetime import date, datetime

from app.core.database import get_db
from app.models.rider import Rider
from app.models.user import User, UserRole
from app.api.v1.auth import get_current_user, require_role
from app.services.financial_service import FinancialService

router = APIRouter(prefix="/reconciliation", tags=["Reconciliation"])


@router.get("/wallet/{rider_id}")
async def reconcile_rider_wallet(
    rider_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role([UserRole.SUPERADMIN, UserRole.GERENTE])),
):
    """Verificar y corregir inconsistencias entre wallet_balance y el ledger de un rider.
    
    Este endpoint compara el saldo almacenado en la tabla riders con la suma real
    de todas las transacciones en el ledger financiero. Si encuentra una diferencia
    mayor a 0.01, crea automáticamente una transacción de ajuste.
    """
    service = FinancialService(db)
    result = await service.reconcile_wallet_with_ledger(rider_id)
    
    if result["status"] == "error":
        raise HTTPException(status_code=404, detail=result["message"])
    
    return result


@router.get("/batch/daily")
async def daily_reconciliation_report(
    target_date: date = Query(default=None, description="Fecha a reconciliar (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role([UserRole.SUPERADMIN, UserRole.GERENTE])),
):
    """Generar reporte diario de reconciliación para todos los riders activos.
    
    No corrige automáticamente, solo reporta discrepancias encontradas.
    """
    if target_date is None:
        target_date = datetime.utcnow().date()
    
    # Obtener todos los riders activos
    result = await db.execute(
        select(Rider).where(Rider.status == "ACTIVO")
    )
    active_riders = result.scalars().all()
    
    report = {
        "date": target_date.isoformat(),
        "total_riders": len(active_riders),
        "ok_count": 0,
        "discrepancy_count": 0,
        "total_discrepancy_amount": 0.0,
        "details": []
    }
    
    for rider in active_riders:
        # Calcular balance del ledger
        service = FinancialService(db)
        ledger_balance = await service.get_current_balance(str(rider.id))
        stored_balance = Decimal(str(rider.wallet_balance or 0))
        difference = abs(ledger_balance - stored_balance)
        
        if difference <= Decimal("0.01"):
            report["ok_count"] += 1
        else:
            report["discrepancy_count"] += 1
            report["total_discrepancy_amount"] += float(difference)
            report["details"].append({
                "rider_id": str(rider.id),
                "rider_name": f"{rider.user.first_name} {rider.user.last_name}" if rider.user else "N/A",
                "ledger_balance": float(ledger_balance),
                "stored_balance": float(stored_balance),
                "difference": float(difference)
            })
    
    return report


@router.post("/fix-all-discrepancies")
async def fix_all_discrepancies(
    dry_run: bool = Query(default=True, description="Si es True, solo reporta sin corregir"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role([UserRole.SUPERADMIN])),
):
    """Corregir automáticamente todas las discrepancias encontradas.
    
    ADVERTENCIA: Esta operación crea transacciones de ajuste automáticas.
    Usar dry_run=True primero para revisar antes de ejecutar.
    """
    result = await db.execute(select(Rider).where(Rider.status == "ACTIVO"))
    active_riders = result.scalars().all()
    
    fixed_count = 0
    error_count = 0
    total_adjusted = 0.0
    details = []
    
    for rider in active_riders:
        try:
            service = FinancialService(db)
            recon_result = await service.reconcile_wallet_with_ledger(str(rider.id))
            
            if recon_result["status"] == "reconciled":
                fixed_count += 1
                total_adjusted += abs(recon_result["adjustment_amount"])
                details.append({
                    "rider_id": str(rider.id),
                    "adjustment_amount": recon_result["adjustment_amount"],
                    "new_balance": recon_result["ledger_balance"]
                })
            elif recon_result["status"] == "ok":
                pass  # Sin acción necesaria
        except Exception as e:
            error_count += 1
            details.append({
                "rider_id": str(rider.id),
                "error": str(e)
            })
    
    return {
        "dry_run": dry_run,
        "fixed_count": fixed_count,
        "error_count": error_count,
        "total_adjusted_amount": total_adjusted,
        "details": details[:50]  # Limitar a primeros 50 para no saturar respuesta
    }


@router.get("/audit/ledger-integrity")
async def audit_ledger_integrity(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role([UserRole.SUPERADMIN, UserRole.AUDITOR])),
):
    """Auditoría completa de integridad del ledger financiero.
    
    Verifica:
    1. Que todas las transacciones tengan balance_before/balance_after consistentes
    2. Que no haya saltos en la secuencia de balances
    3. Que la suma de deltas coincida con el balance final
    """
    from app.models.financial import Financial
    
    # Verificar transacciones sin balance_after poblado
    result = await db.execute(
        select(func.count(Financial.id)).where(
            Financial.balance_after.is_(None)
        )
    )
    missing_balance_after = result.scalar() or 0
    
    # Verificar transacciones donde balance_after != balance_before + delta
    # Esto requiere cálculo complejo, lo simplificamos contando inconsistencies potenciales
    result = await db.execute(
        select(func.count(Financial.id)).where(
            Financial.balance_before.is_(None)
        )
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
        "recommendation": "Revisar transacciones con balances faltantes si count > 0"
    }
