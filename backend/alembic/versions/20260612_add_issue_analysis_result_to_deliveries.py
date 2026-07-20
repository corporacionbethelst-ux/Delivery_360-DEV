"""add issue_analysis_result to deliveries

Revision ID: 20260612
Revises: 20260611
Create Date: 2026-07-20

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260612'
down_revision = '20260611'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add issue_analysis_result column to deliveries table
    op.add_column('deliveries', sa.Column('issue_analysis_result', sa.String(), nullable=True))


def downgrade() -> None:
    # Remove issue_analysis_result column from deliveries table
    op.drop_column('deliveries', 'issue_analysis_result')
