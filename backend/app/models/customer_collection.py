"""Customer collection declarations and independent, immutable manual reviews."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Boolean,
    CheckConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from app.core.json_types import JsonValue


class CustomerCollection(Base):
    __tablename__ = "customer_collections"
    __table_args__ = (
        Index("ix_customer_collections_order_created", "order_id", "created_at", "id"),
        Index("ix_customer_collections_reference", "source_key", "reference_key"),
        CheckConstraint(
            "pricing_revision BETWEEN 1 AND 2147483647 AND amount_usd > 0 AND amount_usd <= 99999999.99 AND paid_amount > 0 AND paid_amount < 1000000000000000000000",
            name="ck_collection_amounts",
        ),
        CheckConstraint(
            "paid_currency IN ('USD','VES') AND method IN ('EFECTIVO','TRANSFERENCIA','PAGO_MOVIL') AND (method <> 'PAGO_MOVIL' OR paid_currency='VES') AND ((paid_currency='VES') = (quote_id IS NOT NULL))",
            name="ck_collection_currency",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    request_key: Mapped[UUID] = mapped_column(unique=True, nullable=False)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"))
    quote_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("order_currency_quotes.id", ondelete="RESTRICT"), nullable=True
    )
    pricing_revision: Mapped[int] = mapped_column(Integer)
    pricing_snapshot: Mapped[JsonValue] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(24, 2))
    paid_currency: Mapped[str] = mapped_column(String(3))
    method: Mapped[str] = mapped_column(String(20))
    source_key: Mapped[str] = mapped_column(String(80))
    reference_key: Mapped[str] = mapped_column(String(120))
    received_on: Mapped[date] = mapped_column(Date)
    declared_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime)


class CustomerCollectionReview(Base):
    __tablename__ = "customer_collection_reviews"
    __table_args__ = (
        Index(
            "ix_collection_reviews_verified_at",
            "reviewed_at",
            "id",
            postgresql_where=text("decision='VERIFICADO'"),
        ),
        CheckConstraint(
            "decision IN ('VERIFICADO','RECHAZADO') AND verified_evidence = (decision='VERIFICADO') AND length(btrim(note)) BETWEEN 10 AND 500 AND note !~ '[[:cntrl:]]'",
            name="ck_collection_review_decision",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    request_key: Mapped[UUID] = mapped_column(unique=True, nullable=False)
    collection_id: Mapped[UUID] = mapped_column(
        ForeignKey("customer_collections.id", ondelete="RESTRICT"), unique=True
    )
    decision: Mapped[str] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(String(500))
    verified_evidence: Mapped[bool] = mapped_column(Boolean)
    acknowledge_refund_due: Mapped[bool] = mapped_column(Boolean)
    reviewed_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    reviewed_at: Mapped[datetime] = mapped_column(DateTime)
