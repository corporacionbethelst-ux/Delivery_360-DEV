"""add_bonus_breakdown_fields

Revision ID: 20260816
Revises: 20260815
Create Date: 2024-01-15

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260816'
down_revision = '20260815'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add columns for bonus breakdown (FASE 5)
    op.add_column('deliveries', sa.Column('locked_bonus_base', sa.Numeric(10, 2), nullable=True,
                comment='Bono base configurado al momento del cálculo. Para desglose frontend.'))
    op.add_column('deliveries', sa.Column('locked_bonus_zone_multiplier', sa.Numeric(4, 2), nullable=True,
                comment='Multiplicador de zona aplicado. Para desglose frontend.'))
    op.add_column('deliveries', sa.Column('locked_bonus_tier_multiplier', sa.Numeric(4, 2), nullable=True,
                comment='Multiplicador de tier aplicado. Para desglose frontend.'))
    op.add_column('deliveries', sa.Column('locked_bonus_tier_level', sa.String(20), nullable=True,
                comment='Nivel del rider (BRONCE/PLATA/ORO/PLATINO) al momento del cálculo.'))


def downgrade() -> None:
    op.drop_column('deliveries', 'locked_bonus_tier_level')
    op.drop_column('deliveries', 'locked_bonus_tier_multiplier')
    op.drop_column('deliveries', 'locked_bonus_zone_multiplier')
    op.drop_column('deliveries', 'locked_bonus_base')
