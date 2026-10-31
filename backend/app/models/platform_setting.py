"""Platform settings key-value model."""

from datetime import datetime, timezone
from typing import Any
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, JSON, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.core.database import Base


def utc_now_naive():
    """Return current UTC datetime without timezone for DB compatibility."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PlatformSetting(Base):
    """Persisted platform configuration stored as JSON values by key."""

    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True, index=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, server_default=text("NOW()"), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=True
    )

    updated_by = relationship("User")

    def __repr__(self):
        return f"<PlatformSetting(key={self.key})>"
