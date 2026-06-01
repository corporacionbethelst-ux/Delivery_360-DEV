"""Audit Logger for tracking all system actions."""

import logging
from typing import Optional, Dict, Any
from datetime import datetime
from sqlalchemy import select
from app.models.audit_log import AuditLog, AuditAction
from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


class AuditLogger:
    """Logger de auditoría para registrar todas las acciones del sistema"""
    
    @staticmethod
    async def log_action(
        user_id: Optional[int],
        action: AuditAction,
        resource_type: str,
        resource_id: Optional[int],
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Optional[AuditLog]:
        """
        Registrar una acción de auditoría
        
        Args:
            user_id: ID del usuario que realizó la acción
            action: Tipo de acción (CREATE, READ, UPDATE, DELETE, LOGIN, LOGOUT)
            resource_type: Tipo de recurso (user, order, delivery, etc.)
            resource_id: ID del recurso afectado
            details: Detalles adicionales en JSON
            ip_address: IP del cliente
            user_agent: User agent del cliente
            
        Returns:
            AuditLog creado o None si falló
        """
        try:
            audit_log = AuditLog(
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                details=details or {},
                ip_address=ip_address,
                user_agent=user_agent,
                timestamp=datetime.utcnow()
            )
            
            async with AsyncSessionLocal() as session:
                session.add(audit_log)
                await session.commit()
                await session.refresh(audit_log)
                
            logger.info(f"Audit log created: {action.value} on {resource_type}:{resource_id}")
            return audit_log
            
        except Exception as e:
            logger.error(f"Failed to create audit log: {str(e)}")
            # No raise exception to avoid breaking the main flow
            return None
    
    @staticmethod
    async def get_user_history(
        user_id: int,
        limit: int = 100,
        offset: int = 0
    ) -> list:
        """Obtener historial de acciones de un usuario"""
        async with AsyncSessionLocal() as session:
            stmt = select(AuditLog).where(AuditLog.user_id == user_id)\
                .order_by(AuditLog.timestamp.desc())\
                .limit(limit).offset(offset)
            result = await session.execute(stmt)
            return result.scalars().all()
    
    @staticmethod
    async def get_resource_history(
        resource_type: str,
        resource_id: int,
        limit: int = 100
    ) -> list:
        """Obtener historial de cambios de un recurso"""
        async with AsyncSessionLocal() as session:
            stmt = select(AuditLog)\
                .where(AuditLog.resource_type == resource_type)\
                .where(AuditLog.resource_id == resource_id)\
                .order_by(AuditLog.timestamp.desc())\
                .limit(limit)
            result = await session.execute(stmt)
            return result.scalars().all()
    
    @staticmethod
    async def search_logs(
        action: Optional[AuditAction] = None,
        resource_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100
    ) -> list:
        """Buscar logs de auditoría con filtros"""
        async with AsyncSessionLocal() as session:
            stmt = select(AuditLog)
            
            if action:
                stmt = stmt.where(AuditLog.action == action)
            if resource_type:
                stmt = stmt.where(AuditLog.resource_type == resource_type)
            if start_date:
                stmt = stmt.where(AuditLog.timestamp >= start_date)
            if end_date:
                stmt = stmt.where(AuditLog.timestamp <= end_date)
            
            stmt = stmt.order_by(AuditLog.timestamp.desc()).limit(limit)
            result = await session.execute(stmt)
            return result.scalars().all()


audit_logger = AuditLogger()
