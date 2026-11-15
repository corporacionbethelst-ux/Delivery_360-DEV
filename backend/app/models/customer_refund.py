"""Immutable requests and events for independently reviewed manual refunds."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4
from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Boolean,
    UniqueConstraint,
    CheckConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class CustomerRefund(Base):
    __tablename__ = "customer_refunds"
    __table_args__ = (
        Index(
            "ix_customer_refunds_collection_created",
            "collection_id",
            "created_at",
            "id",
        ),
        CheckConstraint(
            "prior_refunded_usd >= 0 AND prior_refunded_paid >= 0 AND amount_usd > 0 AND amount_usd <= 99999999.99 AND return_amount > 0 AND return_amount < 1000000000000000000000",
            name="ck_customer_refund_amounts",
        ),
        CheckConstraint(
            "return_currency IN ('USD','VES') AND length(btrim(reason)) BETWEEN 10 AND 500 AND reason !~ '[[:cntrl:]]'",
            name="ck_customer_refund_reason",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    request_key: Mapped[UUID] = mapped_column(unique=True)
    collection_id: Mapped[UUID] = mapped_column(
        ForeignKey("customer_collections.id", ondelete="RESTRICT")
    )
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    return_amount: Mapped[Decimal] = mapped_column(Numeric(24, 2))
    return_currency: Mapped[str] = mapped_column(String(3))
    prior_refunded_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    prior_refunded_paid: Mapped[Decimal] = mapped_column(Numeric(24, 2))
    reason: Mapped[str] = mapped_column(String(500))
    requested_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime)


class CustomerRefundEvent(Base):
    __tablename__ = "customer_refund_events"
    __table_args__ = (
        Index(
            "ix_refund_events_verified_at",
            "created_at",
            "id",
            postgresql_where=text("kind='VERIFICAR_DEVOLUCION'"),
        ),
        UniqueConstraint(
            "refund_id", "revision", name="uq_customer_refund_event_revision"
        ),
        Index(
            "ix_customer_refund_event_reference",
            "source_key",
            "reference_key",
            unique=True,
            postgresql_where=text("kind='DECLARAR_EJECUCION'"),
        ),
        CheckConstraint(
            "revision BETWEEN 1 AND 2147483647 AND length(btrim(note)) BETWEEN 10 AND 500 AND note !~ '[[:cntrl:]]'",
            name="ck_customer_refund_event_note",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    request_key: Mapped[UUID] = mapped_column(unique=True)
    refund_id: Mapped[UUID] = mapped_column(
        ForeignKey("customer_refunds.id", ondelete="RESTRICT")
    )
    revision: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    note: Mapped[str] = mapped_column(String(500))
    verified_evidence: Mapped[bool] = mapped_column(Boolean)
    confirmed_no_execution: Mapped[bool] = mapped_column(Boolean)
    confirmed_execution: Mapped[bool] = mapped_column(Boolean)
    method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reference_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    paid_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 2), nullable=True)
    paid_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    executed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime)
