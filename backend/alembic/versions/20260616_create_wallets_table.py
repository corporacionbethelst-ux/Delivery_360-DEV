"""create wallets table for rider financial management

Revision ID: 20260616
Revises: 20260614
Create Date: 2026-07-29

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260616'
down_revision = '20260614'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ======================================================================
    # 1. CREAR TABLA wallets DESDE CERO
    # ======================================================================
    op.create_table(
        'wallets',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('rider_id', sa.UUID(), nullable=False),
        sa.Column('balance', sa.Numeric(precision=12, scale=2), nullable=False, default=0.00),
        sa.Column('currency', sa.String(length=3), nullable=False, default='COP'),
        sa.Column('status', sa.Enum('ACTIVE', 'INACTIVE', 'BLOCKED', name='walletstatus'), nullable=False, default='ACTIVE'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['rider_id'], ['riders.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('rider_id', name='uq_wallets_rider_id')
    )
    
    # Índices para wallets
    op.create_index(op.f('ix_wallets_id'), 'wallets', ['id'], unique=False)
    op.create_index(op.f('ix_wallets_rider_id'), 'wallets', ['rider_id'], unique=False)
    op.create_index(op.f('ix_wallets_status'), 'wallets', ['status'], unique=False)

    # ======================================================================
    # 2. AGREGAR COLUMNA version PARA OPTIMISTIC LOCKING
    # ======================================================================
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

    # ======================================================================
    # 3. AGREGAR balance_after A financials SI NO EXISTE
    # ======================================================================
    # Nota: financials ya tiene balance_after en el schema inicial,
    # pero agregamos por seguridad en caso de que falte
    op.execute("""
        ALTER TABLE financials 
        ADD COLUMN IF NOT EXISTS balance_after NUMERIC(12, 2)
    """)
    
    # Asegurar índice en balance_after para auditoría
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_financials_balance_after 
        ON financials (balance_after)
    """)


def downgrade() -> None:
    # Eliminar índice de balance_after
    op.execute("DROP INDEX IF EXISTS ix_financials_balance_after")
    
    # Eliminar columna version de wallets
    op.drop_column('wallets', 'version')
    
    # Eliminar tabla wallets
    op.drop_table('wallets')
