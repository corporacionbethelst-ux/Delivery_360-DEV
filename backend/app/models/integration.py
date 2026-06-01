"""Integration model for external system connections."""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from sqlalchemy import Column, String, Boolean, DateTime, Enum as SQLEnum, Integer, Text, text, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import enum

from app.core.database import Base

def utc_now_naive():
    """Devuelve la hora actual en UTC sin zona horaria (naive) para compatibilidad con PostgreSQL."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

class IntegrationType(str, enum.Enum):
    ERP = "ERP"
    POS = "POS"
    PAYMENT = "PAYMENT"
    MAPS = "MAPS"
    SMS = "SMS"
    EMAIL = "EMAIL"


class IntegrationStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    ERROR = "ERROR"


class Integration(Base):
    """External system integration configuration."""
    
    __tablename__ = "integrations"
    
    # ID como UUID
    id = Column(
        UUID(as_uuid=True), 
        primary_key=True, 
        index=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()")  # <-- Clave para que PG genere el ID
    )
    name = Column(String(100), nullable=False)
    integration_type: Any = Column(SQLEnum(IntegrationType), nullable=False)
    provider = Column(String(50))
    
    # Connection
    api_url = Column(String(500))
    api_version = Column(String(20))
    auth_type = Column(String(20))
    credentials = Column(Text)  # JSON string or encrypted
    token_expires_at = Column(DateTime)
    
    # Status
    status: Any = Column(SQLEnum(IntegrationStatus), default=IntegrationStatus.INACTIVE)
    last_sync_at = Column(DateTime)
    last_error_at = Column(DateTime)
    last_error_message = Column(Text)
    consecutive_failures = Column(Integer, default=0)
    
    # Config
    config = Column(Text)  # JSON string
    webhook_url = Column(String(500))
    webhook_secret = Column(String(255))
    
    # Sync
    sync_enabled = Column(Boolean, default=False)
    sync_frequency_minutes = Column(Integer, default=60)
    sync_last_run = Column(DateTime)
    sync_next_run = Column(DateTime)
    
    # Timestamps - CORREGIDOS PARA USAR TIMEZONE AWARE
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)
    
    # created_by como UUID para coincidir con User.id
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    
    # Relationships
    creator = relationship("User")
    
    def __repr__(self):
        return f"<Integration(id={self.id}, name={self.name}, type={self.integration_type})>"