"""Append-only BCV references and USD/VES quotation receipts.

Revision ID: 20261114_bcv_currency
Revises: 20261113_runtime_schema
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "20261114_bcv_currency"
down_revision = "20261113_runtime_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "bcv_rates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("request_key", UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column(
            "previous_rate_id",
            UUID(as_uuid=True),
            sa.ForeignKey("bcv_rates.id", ondelete="RESTRICT"),
        ),
        sa.Column("valid_on", sa.Date, nullable=False),
        sa.Column("reference_date", sa.Date, nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("ves_per_usd", sa.Numeric(18, 8), nullable=False),
        sa.Column("note", sa.String(500), nullable=False),
        sa.Column(
            "recorded_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("recorded_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("valid_on", "revision", name="uq_bcv_rate_day_revision"),
        sa.CheckConstraint(
            "ves_per_usd > 0 AND ves_per_usd < 1000000000", name="ck_bcv_rate_positive"
        ),
        sa.CheckConstraint("reference_date <= valid_on", name="ck_bcv_reference_date"),
        sa.CheckConstraint("revision > 0", name="ck_bcv_revision_positive"),
        sa.CheckConstraint(
            "(revision = 1 AND previous_rate_id IS NULL) OR (revision > 1 AND previous_rate_id IS NOT NULL AND previous_rate_id <> id)",
            name="ck_bcv_revision_parent",
        ),
    )
    op.create_index("ix_bcv_rates_valid_on", "bcv_rates", ["valid_on"])
    op.create_table(
        "usd_ves_quotes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("request_key", UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column(
            "rate_id",
            UUID(as_uuid=True),
            sa.ForeignKey("bcv_rates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount_usd", sa.Numeric(14, 2), nullable=False),
        sa.Column("amount_ves", sa.Numeric(24, 2), nullable=False),
        sa.Column("reference", sa.String(120), nullable=False),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.CheckConstraint(
            "amount_usd >= 0 AND amount_usd < 1000000000000", name="ck_quote_usd_amount"
        ),
        sa.CheckConstraint(
            "amount_ves >= 0 AND amount_ves < 1000000000000000000000",
            name="ck_quote_ves_amount",
        ),
    )
    op.create_index("ix_usd_ves_quotes_rate_id", "usd_ves_quotes", ["rate_id"])
    op.create_index("ix_usd_ves_quotes_created_by", "usd_ves_quotes", ["created_by"])
    op.execute(
        """CREATE FUNCTION currency_history_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Currency references and quotation receipts are append-only'; END; $$"""
    )
    for table in ("bcv_rates", "usd_ves_quotes"):
        op.execute(
            f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION currency_history_immutable()"
        )
        op.execute(
            f"CREATE TRIGGER immutable_truncate_{table} BEFORE TRUNCATE ON {table} EXECUTE FUNCTION currency_history_immutable()"
        )


def downgrade():
    for table in ("usd_ves_quotes", "bcv_rates"):
        op.execute(sa.text("LOCK TABLE " + table + " IN ACCESS EXCLUSIVE MODE"))
    for table in ("bcv_rates", "usd_ves_quotes"):
        if (
            op.get_bind()
            .execute(sa.text("SELECT EXISTS (SELECT 1 FROM " + table + ")"))
            .scalar()
        ):
            raise RuntimeError("Downgrade refused: preserve currency history first")
    op.drop_table("usd_ves_quotes")
    op.drop_table("bcv_rates")
    op.execute("DROP FUNCTION currency_history_immutable()")
