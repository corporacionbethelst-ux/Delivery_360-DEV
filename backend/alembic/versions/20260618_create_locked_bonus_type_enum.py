"""create locked_bonus_type enum type for deliveries

Revision ID: 20260618
Revises: 20260617
Create Date: 2026-08-09

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260618'
down_revision = '20260617'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Crear el tipo ENUM lockedbonustype en PostgreSQL
    op.execute("""
        CREATE TYPE lockedbonustype AS ENUM ('SUCCESS', 'FAILED_ATTEMPT')
    """)
    
    # Convertir la columna existing de VARCHAR a ENUM
    op.execute("""
        ALTER TABLE deliveries 
        ALTER COLUMN locked_bonus_type TYPE lockedbonustype 
        USING locked_bonus_type::lockedbonustype
    """)


def downgrade() -> None:
    # Revertir a VARCHAR
    op.execute("""
        ALTER TABLE deliveries 
        ALTER COLUMN locked_bonus_type TYPE VARCHAR(50)
        USING locked_bonus_type::text
    """)
    
    # Eliminar el tipo ENUM
    op.execute("DROP TYPE IF EXISTS lockedbonustype")
