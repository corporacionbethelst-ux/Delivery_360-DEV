"""add_tier_column_to_riders

Revision ID: 20260815_add_tier_enum_and_column
Revises: 20260619_add_vehicle_ownership_fields
Create Date: 2026-08-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260815_add_tier_enum_and_column'
down_revision: Union[str, None] = '20260619_add_vehicle_ownership_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Crear el tipo ENUM rider_tier
    rider_tier_enum = sa.Enum('BRONCE', 'PLATA', 'ORO', 'PLATINO', name='rider_tier')
    rider_tier_enum.create(op.get_bind())
    
    # Agregar la columna tier con valor por defecto 'BRONCE'
    op.add_column('riders', sa.Column('tier', rider_tier_enum, nullable=False, server_default='BRONCE'))


def downgrade() -> None:
    # Eliminar la columna tier
    op.drop_column('riders', 'tier')
    
    # Eliminar el tipo ENUM
    rider_tier_enum = sa.Enum(name='rider_tier')
    rider_tier_enum.drop(op.get_bind())
