"""
Servicio de Auditoría en Tiempo Real con Redis para Delivery360

Este servicio escribe eventos de auditoría tanto en PostgreSQL (persistencia)
como en Redis (tiempo real para dashboards y monitoreo operacional).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TypedDict
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class AuditEvent(TypedDict):
    """Tipo para evento de auditoría"""
    event_id: str
    event_type: str
    resource_type: str
    resource_id: str
    user_id: Optional[str]
    details: Optional[str]
    timestamp: str
    created_at: float


class RedisAuditLogger:
    """
    Logger de auditoría que escribe en Redis para visualización en tiempo real.
    
    Los eventos se almacenan en:
    - Redis Stream: 'audit:stream' para consumo en tiempo real
    - Redis List: 'audit:recent' para últimos N eventos
    - Redis Sorted Set: 'audit:by_resource:{resource_type}:{resource_id}' para historial por recurso
    """
    
    def __init__(self, redis_client=None):
        self.redis = redis_client
        self.connected = redis_client is not None
    
    async def connect(self, redis_url: str = "redis://localhost:6379/0") -> bool:
        """Conectar a Redis"""
        try:
            import redis.asyncio as redis
            self.redis = redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
            await self.redis.ping()
            self.connected = True
            logger.info("✅ Redis Audit Logger conectado")
            return True
        except Exception as e:
            logger.warning(f"⚠️ No se pudo conectar a Redis para audit: {e}")
            self.connected = False
            return False
    
    async def log_event(
        self,
        event_type: str,
        resource_type: str,
        resource_id: str,
        user_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None,
    ) -> bool:
        """
        Registrar un evento de auditoría en Redis.
        
        Args:
            event_type: Tipo de evento (ASSIGNED, COMPLETED, WITHDRAWAL_REQUESTED, etc.)
            resource_type: Tipo de recurso (ORDER, DELIVERY, PAYOUT, etc.)
            resource_id: ID del recurso
            user_id: ID del usuario que realizó la acción
            details: Datos adicionales del evento
            timestamp: Timestamp del evento (default: now)
        """
        if not self.connected or not self.redis:
            return False
        
        try:
            ts = timestamp or datetime.now(timezone.utc)
            event = {
                "event_id": str(uuid.uuid4()),
                "event_type": event_type,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "user_id": user_id,
                "details": json.dumps(details) if details else None,
                "timestamp": ts.isoformat(),
                "created_at": ts.timestamp(),
            }
            
            # 1. Escribir a Redis Stream para consumo en tiempo real
            await self.redis.xadd("audit:stream", event, maxlen=10000)
            
            # 2. Añadir a lista de recientes (últimos 100 eventos)
            await self.redis.lpush("audit:recent", json.dumps(event))
            await self.redis.ltrim("audit:recent", 0, 99)
            
            # 3. Indexar por recurso para consultas rápidas de historial
            resource_key = f"audit:by_resource:{resource_type}:{resource_id}"
            await self.redis.zadd(resource_key, {json.dumps(event): ts.timestamp()})
            await self.redis.expire(resource_key, 86400 * 30)  # 30 días
            
            # 4. Publicar para subscribers (websockets, etc.)
            await self.redis.publish("audit:events", json.dumps(event))
            
            logger.debug(f"Audit event logged to Redis: {event_type} on {resource_type}:{resource_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error writing audit event to Redis: {e}")
            return False
    
    async def log_order_assigned(
        self,
        order_id: str,
        rider_id: str,
        assigned_by: Optional[str] = None,
    ) -> bool:
        """Log específico para asignación de orden"""
        return await self.log_event(
            event_type="ORDER_ASSIGNED",
            resource_type="ORDER",
            resource_id=order_id,
            user_id=assigned_by,
            details={
                "rider_id": rider_id,
                "action": "assign",
            },
        )
    
    async def log_order_completed(
        self,
        order_id: str,
        rider_id: str,
        completed_by: Optional[str] = None,
        delivery_time_minutes: Optional[int] = None,
        sla_compliant: Optional[bool] = None,
    ) -> bool:
        """Log específico para completado de orden"""
        return await self.log_event(
            event_type="ORDER_COMPLETED",
            resource_type="ORDER",
            resource_id=order_id,
            user_id=completed_by,
            details={
                "rider_id": rider_id,
                "delivery_time_minutes": delivery_time_minutes,
                "sla_compliant": sla_compliant,
                "action": "complete",
            },
        )
    
    async def log_delivery_started(
        self,
        delivery_id: str,
        order_id: str,
        rider_id: str,
    ) -> bool:
        """Log específico para inicio de entrega"""
        return await self.log_event(
            event_type="DELIVERY_STARTED",
            resource_type="DELIVERY",
            resource_id=delivery_id,
            details={
                "order_id": order_id,
                "rider_id": rider_id,
                "action": "start",
            },
        )
    
    async def log_withdrawal_requested(
        self,
        payout_id: str,
        rider_id: str,
        amount: float,
        requested_by: Optional[str] = None,
    ) -> bool:
        """Log específico para solicitud de retiro"""
        return await self.log_event(
            event_type="WITHDRAWAL_REQUESTED",
            resource_type="PAYOUT",
            resource_id=payout_id,
            user_id=requested_by,
            details={
                "rider_id": rider_id,
                "amount": amount,
                "action": "request",
            },
        )
    
    async def log_withdrawal_approved(
        self,
        payout_id: str,
        rider_id: str,
        approved_by: Optional[str] = None,
    ) -> bool:
        """Log específico para aprobación de retiro"""
        return await self.log_event(
            event_type="WITHDRAWAL_APPROVED",
            resource_type="PAYOUT",
            resource_id=payout_id,
            user_id=approved_by,
            details={
                "rider_id": rider_id,
                "action": "approve",
            },
        )
    
    async def log_sla_breach(
        self,
        order_id: str,
        rider_id: str,
        minutes_over: int,
    ) -> bool:
        """Log específico para violación de SLA"""
        return await self.log_event(
            event_type="SLA_BREACH",
            resource_type="ORDER",
            resource_id=order_id,
            details={
                "rider_id": rider_id,
                "minutes_over": minutes_over,
                "severity": "HIGH",
                "action": "sla_breach",
            },
        )
    
    async def get_recent_events(self, limit: int = 50) -> List[AuditEvent]:
        """Obtener eventos recientes"""
        if not self.connected or not self.redis:
            return []
        
        try:
            events = await self.redis.lrange("audit:recent", 0, limit - 1)
            return [json.loads(e) for e in events]
        except Exception as e:
            logger.error(f"Error getting recent audit events: {e}")
            return []
    
    async def get_resource_history(
        self,
        resource_type: str,
        resource_id: str,
        limit: int = 100,
    ) -> List[AuditEvent]:
        """Obtener historial de un recurso específico"""
        if not self.connected or not self.redis:
            return []
        
        try:
            key = f"audit:by_resource:{resource_type}:{resource_id}"
            events = await self.redis.zrange(key, 0, -1, withscores=False)
            return [json.loads(e) for e in events[-limit:]]
        except Exception as e:
            logger.error(f"Error getting resource audit history: {e}")
            return []


# Instancia global
redis_audit_logger = RedisAuditLogger()


def get_redis_audit_logger():
    """Factory para obtener el logger de auditoría en Redis"""
    return redis_audit_logger
