"""add wallet version for optimistic locking and transaction audit trail

Revision ID: 20260615
Revises: 20260614
Create Date: 2026-07-29

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260615'
down_revision = '20260614'  # <--- CRÍTICO: Depende de la migración de deliveries
branch_labels = None
depends_on = None

def upgrade() -> None:
    # 1. Agregar columna 'version' a wallets para Optimistic Locking
    # Esto previene race conditions cuando dos procesos modifican el saldo a la vez
    op.add_column(
        'wallets',
        sa.Column(
            'version',
            sa.Integer(),
            nullable=False,
            server_default='0',
            comment='Contador de versión para bloqueo optimista. Se incrementa en cada update.'
        )
    )

    # 2. Agregar columna 'balance_after' a transactions para Auditoría (Doble Libro)
    # Permite verificar instantáneamente si el cálculo histórico coincide con el saldo actual
    op.add_column(
        'transactions',
        sa.Column(
            'balance_after',
            sa.Numeric(12, 2),
            nullable=True,
            comment='Saldo exacto de la wallet después de aplicar esta transacción. Para auditoría forense.'
        )
    )

    # 3. (Opcional pero recomendado) Índice para mejorar performance en consultas de auditoría
    op.create_index(
        op.f('ix_transactions_balance_after'),
        'transactions',
        ['balance_after'],
        unique=False
    ) 

def downgrade() -> None:
    # Eliminar índice
    op.drop_index(op.f('ix_transactions_balance_after'), table_name='transactions')
    
    # Eliminar columnas en orden inverso
    op.drop_column('transactions', 'balance_after')
    op.drop_column('wallets', 'version')