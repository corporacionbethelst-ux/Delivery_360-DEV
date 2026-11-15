"""Index verification-time reads without changing customer monetary history."""

from alembic import op
import sqlalchemy as sa

revision = "20261115_cashbook_indexes"
down_revision = "20261114_customer_refunds"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_collection_reviews_verified_at",
        "customer_collection_reviews",
        ["reviewed_at", "id"],
        postgresql_where=sa.text("decision='VERIFICADO'"),
    )
    op.create_index(
        "ix_refund_events_verified_at",
        "customer_refund_events",
        ["created_at", "id"],
        postgresql_where=sa.text("kind='VERIFICAR_DEVOLUCION'"),
    )


def downgrade():
    op.drop_index("ix_refund_events_verified_at", table_name="customer_refund_events")
    op.drop_index(
        "ix_collection_reviews_verified_at", table_name="customer_collection_reviews"
    )
