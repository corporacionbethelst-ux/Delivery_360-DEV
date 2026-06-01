"""Servicio para operaciones financieras del sistema Delivery360."""

from typing import Optional, Dict, Any
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from app.models.financial import Financial, TransactionType, PaymentStatus
import logging

logger = logging.getLogger(__name__)

# Alias para consistencia interna
FinancialTransaction = Financial 

class FinancialService:
    """Servicio para operaciones financieras"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_transaction(
        self,
        rider_id: str,
        amount: Decimal,
        transaction_type: TransactionType,
        description: Optional[str] = None,
        reference_id: Optional[str] = None
    ) -> Financial:
        """Crear una nueva transacción financiera"""
        transaction = Financial(
            rider_id=rider_id,
            amount=amount,
            transaction_type=transaction_type,
            description=description,
            reference_id=reference_id,
            status=PaymentStatus.PENDIENTE
        )
        self.db.add(transaction)
        await self.db.commit()
        await self.db.refresh(transaction)
        logger.info(f"Transacción creada: {transaction.id} para rider {rider_id}")
        return transaction
    
    async def calculate_delivery_earnings(
        self,
        distance_km: float,
        base_rate: float = 2.50, # Tarifa base por defecto
        is_sla_compliant: bool = True,
        is_night_shift: bool = False,
        is_rainy_day: bool = False
    ) -> Dict[str, Any]:
        """
        Calcula ganancias simplificadas.
        NOTA: Se eliminó la dependencia de PaymentRule ya que esa tabla no existe aún.
        Usa valores por defecto o lógica simple.
        """
        total = base_rate
        
        # Lógica simple de bonos
        if distance_km > 5:
            total += (distance_km - 5) * 0.5 # Bonus por distancia extra
            
        if is_night_shift:
            total += 1.0 # Bonus nocturno fijo
            
        if is_rainy_day:
            total += 1.5 # Bonus lluvia fijo
            
        if not is_sla_compliant:
            total = max(0, total - 1.0) # Penalización por retraso
            
        final_amount = Decimal(str(max(0, total)))
        
        return {
            "base_amount": Decimal(str(base_rate)),
            "bonuses": Decimal(str(total - base_rate)) if total >= base_rate else Decimal('0'),
            "deductions": Decimal('0') if total >= base_rate else Decimal(str(base_rate - total)),
            "total": final_amount
        }
    
    async def create_daily_liquidation(self, rider_id: str, liquidation_date: date) -> Optional[Dict[str, Any]]:
        """
        Simula la creación de liquidación devolviendo un diccionario.
        NOTA: No crea objeto Liquidation porque la tabla no existe.
        Solo calcula totales.
        """
        start_dt = datetime.combine(liquidation_date, datetime.min.time())
        end_dt = datetime.combine(liquidation_date, datetime.max.time())

        result = await self.db.execute(
            select(
                func.sum(Financial.amount).label('total'),
                func.count(Financial.id).label('count')
            ).where(
                and_(
                    Financial.rider_id == rider_id,
                    Financial.created_at >= start_dt,
                    Financial.created_at <= end_dt,
                    Financial.transaction_type.in_([
                        TransactionType.PAGO_ENTREGA,
                        TransactionType.BONO
                    ])
                )
            )
        )
        row = result.first()
        total_amount = row.total or Decimal('0')
        transaction_count = row.count or 0
        
        # Devolvemos un dict en lugar de un objeto de modelo inexistente
        return {
            "rider_id": rider_id,
            "total_amount": total_amount,
            "period_start": start_dt,
            "period_end": end_dt,
            "transaction_count": transaction_count,
            "status": "calculated"
        } 
    
    async def get_rider_earnings(
        self,
        rider_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, Any]:
        """Obtener resumen de ganancias de un repartidor en un período"""
        result = await self.db.execute(
            select(
                func.sum(Financial.amount).label('total_earnings'),
                func.count(Financial.id).label('transaction_count'),
                func.avg(Financial.amount).label('avg_transaction')
            ).where(
                and_(
                    Financial.rider_id == rider_id,
                    Financial.created_at >= start_date,
                    Financial.created_at <= end_date,
                    Financial.transaction_type.in_([
                        TransactionType.PAGO_ENTREGA,
                        TransactionType.BONO
                    ])
                )
            )
        )
        row = result.first()
        
        return {
            "total_earnings": row.total_earnings or Decimal('0'),
            "transaction_count": row.transaction_count or 0,
            "avg_transaction": row.avg_transaction or Decimal('0'),
            "period_start": start_date,
            "period_end": end_date
        }
    
    async def consolidate_financial_period(
        self,
        start_date: date,
        end_date: date
    ) -> Dict[str, Any]:
        """Consolidar datos financieros de un período"""
        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())

        result = await self.db.execute(
            select(
                func.sum(Financial.amount).label('total_amount'),
                func.count(Financial.id).label('total_transactions'),
                func.count(func.distinct(Financial.rider_id)).label('active_riders')
            ).where(
                and_(
                    Financial.created_at >= start_dt,
                    Financial.created_at <= end_dt
                )
            )
        )
        row = result.first()
        
        by_type = {}
        for t_type in TransactionType:
            type_result = await self.db.execute(
                select(func.sum(Financial.amount)).where(
                    and_(
                        Financial.transaction_type == t_type,
                        Financial.created_at >= start_dt,
                        Financial.created_at <= end_dt
                    )
                )
            )
            amount = type_result.scalar() or Decimal('0')
            by_type[t_type.value] = amount
        
        return {
            "total_amount": row.total_amount or Decimal('0'),
            "total_transactions": row.total_transactions or 0,
            "active_riders": row.active_riders or 0,
            "by_transaction_type": by_type,
            "period_start": start_date,
            "period_end": end_date
        }