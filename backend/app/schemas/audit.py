"""
Schemas para auditoría
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum


class AuditAction(str, Enum):
    """Tipos de acciones de auditoría"""
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    VIEW = "VIEW"
    EXPORT = "EXPORT"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    ASSIGN = "ASSIGN"
    COMPLETE = "COMPLETE"


class AuditLogBase(BaseModel):
    """Schema base para logs de auditoría"""
    action: AuditAction
    resource_type: str
    resource_id: Optional[int] = None
    details: Optional[Dict[str, Any]] = {}
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


class AuditLogCreate(AuditLogBase):
    """Schema para crear log de auditoría"""
    user_id: int


class AuditLogResponse(AuditLogBase):
    """Schema para respuesta de log de auditoría"""
    id: int
    user_id: int
    timestamp: datetime
    
    class Config:
        from_attributes = True


class AuditLogFilter(BaseModel):
    """Filtros para búsqueda de logs"""
    user_id: Optional[int] = None
    action: Optional[AuditAction] = None
    resource_type: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)
