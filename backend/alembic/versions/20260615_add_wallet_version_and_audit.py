"""add wallet version for optimistic locking and transaction audit trail

Revision ID: 20260615
Revises: 20260616
Create Date: 2026-07-29

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260615'
down_revision = '20260616'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # NOTA: La columna 'version' ya fue agregada en la migración 20260616
    # Esta migración ahora solo se encarga del índice adicional si es necesario
    
    # 1. Verificar que la columna 'version' existe en wallets (ya creada en 20260616)
    # No necesitamos hacer nada aquí porque version ya fue agregada
    
    # 2. La columna 'balance_after' ya existe en financials desde el schema inicial
    # y fue verificada en la migración 20260616
    
    pass

def downgrade() -> None:
    # No hay nada que hacer aquí porque las columnas fueron creadas en 20260616
    pass