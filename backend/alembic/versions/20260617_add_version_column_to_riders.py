"""add version column to riders for optimistic locking

Revision ID: 20260617
Revises: 20260615
Create Date: 2026-08-09

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260617'
down_revision = '20260615'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Agregar columna version para bloqueo optimista en riders
    op.add_column(
        'riders',
        sa.Column(
            'version',
            sa.Integer(),
            nullable=False,
            server_default='0',
            comment='Versión para bloqueo optimista (concurrencia financiera)'
        )
    )


def downgrade() -> None:
    op.drop_column('riders', 'version')
