"""Immutable USD/VES quotations bound to an exact order price revision."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.json_types import JsonValue


class OrderCurrencyQuote(Base):
    __tablename__ = "order_currency_quotes"
    __table_args__ = (
        CheckConstraint(
            "pricing_revision BETWEEN 1 AND 2147483647 AND amount_usd BETWEEN 0 AND 99999999.99 AND amount_ves >= 0 AND amount_ves < 1000000000000000000000",
            name="ck_order_quote_amounts",
        ),
        Index("ix_order_currency_quotes_order_created", "order_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    request_key: Mapped[UUID] = mapped_column(unique=True, nullable=False)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"))
    order_external_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pricing_revision: Mapped[int] = mapped_column(Integer)
    pricing_snapshot: Mapped[JsonValue] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    rate_id: Mapped[UUID] = mapped_column(
        ForeignKey("bcv_rates.id", ondelete="RESTRICT")
    )
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    amount_ves: Mapped[Decimal] = mapped_column(Numeric(24, 2))
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime)
