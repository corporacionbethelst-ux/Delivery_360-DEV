"""Append-only BCV references and USD/VES quotation receipts, not payments."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class BcvRate(Base):
    __tablename__ = "bcv_rates"
    __table_args__ = (
        UniqueConstraint("valid_on", "revision", name="uq_bcv_rate_day_revision"),
        CheckConstraint(
            "ves_per_usd > 0 AND ves_per_usd < 1000000000", name="ck_bcv_rate_positive"
        ),
        CheckConstraint("reference_date <= valid_on", name="ck_bcv_reference_date"),
        CheckConstraint("revision > 0", name="ck_bcv_revision_positive"),
        CheckConstraint(
            "(revision = 1 AND previous_rate_id IS NULL) OR (revision > 1 AND previous_rate_id IS NOT NULL AND previous_rate_id <> id)",
            name="ck_bcv_revision_parent",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    request_key: Mapped[UUID] = mapped_column(unique=True, nullable=False)
    previous_rate_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("bcv_rates.id", ondelete="RESTRICT")
    )
    valid_on: Mapped[date] = mapped_column(Date, index=True)
    reference_date: Mapped[date] = mapped_column(Date)
    revision: Mapped[int] = mapped_column(Integer)
    ves_per_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    note: Mapped[str] = mapped_column(String(500))
    recorded_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime)


class UsdVesQuote(Base):
    __tablename__ = "usd_ves_quotes"
    __table_args__ = (
        CheckConstraint(
            "amount_usd >= 0 AND amount_usd < 1000000000000", name="ck_quote_usd_amount"
        ),
        CheckConstraint(
            "amount_ves >= 0 AND amount_ves < 1000000000000000000000",
            name="ck_quote_ves_amount",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    request_key: Mapped[UUID] = mapped_column(unique=True, nullable=False)
    rate_id: Mapped[UUID] = mapped_column(
        ForeignKey("bcv_rates.id", ondelete="RESTRICT"), index=True
    )
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    amount_ves: Mapped[Decimal] = mapped_column(Numeric(24, 2))
    reference: Mapped[str] = mapped_column(String(120))
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime)
