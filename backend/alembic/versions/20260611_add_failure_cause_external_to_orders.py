"""add failure_cause_external to orders

Revision ID: 20260611
Revises: 20260610_finance_features
Create Date: 2026-06-11

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260611'
down_revision = '20260610'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add failure_cause_external column to orders table
    op.add_column('orders', sa.Column('failure_cause_external', sa.Boolean(), nullable=True))


def downgrade() -> None:
    # Remove failure_cause_external column from orders table
    op.drop_column('orders', 'failure_cause_external')
