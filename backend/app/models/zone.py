# app/models/zone.py
"""Zone model for delivery operating areas."""

import uuid
from decimal import Decimal
from datetime import datetime, timezone
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    String,
    Text,
    text,
    Numeric,
    Integer,
    CheckConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.core.database import Base


def utc_now_naive() -> datetime:
    """Return the current UTC datetime without timezone info for DB consistency."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Zone(Base):
    """Operational delivery zone with pricing and display metadata."""

    __tablename__ = "zones"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
        index=True,
    )
    name = Column(String(100), nullable=False)
    code = Column(String(20), unique=True, index=True, nullable=False)
    description = Column(Text, nullable=True)

    # Tarifas base existentes
    delivery_fee_base = Column(Float, nullable=False, default=0.0)
    cost_per_km = Column(Float, nullable=False, default=0.0)
    # Explicit dimensionless bonus factor; legacy Float remains untouched.
    bonus_factor_exact: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 18), nullable=True
    )
    bonus_factor_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    bonus_factor_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    bonus_factor_updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    # Explicit prospective USD configuration; historical Float values stay untouched.
    tariff_base_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    tariff_per_km_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    tariff_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    tariff_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    tariff_updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    estimated_time_min = Column(Float, nullable=False, default=30.0)

    # FASE 3: Multiplicador de bono para repartidores (Default 1.0 = sin cambio)
    bonus_multiplier = Column(Float, nullable=False, default=1.0)

    is_priority = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    color_hex = Column(String(7), nullable=False, default="#6b7280")

    center_lat = Column(Float, nullable=True)
    center_lng = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=False), default=utc_now_naive, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False),
        default=utc_now_naive,
        onupdate=utc_now_naive,
        nullable=True,
    )

    riders = relationship("Rider", back_populates="zone", foreign_keys="Rider.zone_id")

    __table_args__ = (
        Index("ix_zones_active_priority", "is_active", "is_priority"),
        CheckConstraint(
            "(bonus_factor_revision = 0 AND bonus_factor_exact IS NULL AND bonus_factor_updated_at IS NULL AND bonus_factor_updated_by IS NULL) OR (bonus_factor_revision > 0 AND bonus_factor_exact IS NOT NULL AND bonus_factor_exact BETWEEN 0.1 AND 5 AND bonus_factor_updated_at IS NOT NULL AND bonus_factor_updated_by IS NOT NULL)",
            name="ck_zones_exact_bonus_factor",
        ),
        CheckConstraint(
            "(tariff_revision = 0 AND tariff_base_usd IS NULL AND tariff_per_km_usd IS NULL AND tariff_updated_at IS NULL AND tariff_updated_by IS NULL) OR "
            "(tariff_revision > 0 AND tariff_base_usd IS NOT NULL AND tariff_per_km_usd IS NOT NULL AND tariff_base_usd BETWEEN 0 AND 99999999.99 AND tariff_per_km_usd BETWEEN 0 AND 99999999.99 AND tariff_updated_at IS NOT NULL AND tariff_updated_by IS NOT NULL)",
            name="ck_zones_exact_tariff",
        ),
    )
