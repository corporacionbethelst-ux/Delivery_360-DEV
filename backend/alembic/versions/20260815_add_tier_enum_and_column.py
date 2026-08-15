"""add_tier_column_to_riders

Revision ID: 20260815
Revises: 20260619
Create Date: 2026-08-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260815'
down_revision = '20260619'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Crear el tipo ENUM rider_tier explícitamente
    op.execute("CREATE TYPE rider_tier AS ENUM ('BRONCE', 'PLATA', 'ORO', 'PLATINO')")
    
    # Agregar la columna tier con valor por defecto 'BRONCE'
    # Usamos create_type=False porque ya creamos el ENUM manualmente arriba
    op.add_column('riders', sa.Column('tier', sa.Enum('BRONCE', 'PLATA', 'ORO', 'PLATINO', name='rider_tier', create_type=False), nullable=False, server_default='BRONCE'))


def downgrade() -> None:
    # Eliminar la columna tier
    op.drop_column('riders', 'tier')
    
    # Eliminar el tipo ENUM rider_tier
    op.execute("DROP TYPE IF EXISTS rider_tier")
