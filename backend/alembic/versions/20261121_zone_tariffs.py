"""Add explicit prospective USD zone tariffs without rewriting legacy rates."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261121_zone_tariffs"
down_revision = "20261117_bonus_currency"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "zones", sa.Column("tariff_base_usd", sa.Numeric(10, 2), nullable=True)
    )
    op.add_column(
        "zones", sa.Column("tariff_per_km_usd", sa.Numeric(10, 2), nullable=True)
    )
    op.add_column(
        "zones",
        sa.Column("tariff_revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "zones",
        sa.Column("tariff_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "zones",
        sa.Column("tariff_updated_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_zones_exact_tariff",
        "zones",
        "(tariff_revision = 0 AND tariff_base_usd IS NULL AND tariff_per_km_usd IS NULL AND tariff_updated_at IS NULL AND tariff_updated_by IS NULL) OR "
        "(tariff_revision > 0 AND tariff_base_usd IS NOT NULL AND tariff_per_km_usd IS NOT NULL AND tariff_base_usd BETWEEN 0 AND 99999999.99 AND tariff_per_km_usd BETWEEN 0 AND 99999999.99 AND tariff_updated_at IS NOT NULL AND tariff_updated_by IS NOT NULL)",
    )


def downgrade():
    op.execute("LOCK TABLE zones IN ACCESS EXCLUSIVE MODE NOWAIT")
    if (
        op.get_bind()
        .execute(
            sa.text("SELECT EXISTS(SELECT 1 FROM zones WHERE tariff_revision > 0)")
        )
        .scalar()
    ):
        raise RuntimeError("Downgrade refused: preserve explicit USD zone tariffs")
    op.drop_constraint("ck_zones_exact_tariff", "zones", type_="check")
    for column in (
        "tariff_updated_by",
        "tariff_updated_at",
        "tariff_revision",
        "tariff_per_km_usd",
        "tariff_base_usd",
    ):
        op.drop_column("zones", column)
