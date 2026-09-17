"""fase7_wallets_payouts

Revision ID: 20260817
Revises: 20260816
Create Date: 2026-09-16 23:58:08.337332

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260817'
down_revision: Union[str, None] = '20260816'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # 1. Crear tabla rider_wallets
    op.create_table('rider_wallets',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('rider_id', sa.UUID(), nullable=False),
        sa.Column('balance_cents', sa.BigInteger(), nullable=False, default=0),
        sa.Column('currency', sa.String(length=3), nullable=False, default='USD'),
        sa.Column('status', sa.Enum('ACTIVE', 'FROZEN', 'CLOSED', name='walletstatus'), nullable=False, default='ACTIVE'),
        sa.Column('last_transaction_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('rider_id')
    )
    op.create_index(op.f('ix_rider_wallets_rider_id'), 'rider_wallets', ['rider_id'], unique=True)

    # 2. Crear tabla financial_transactions
    op.create_table('financial_transactions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('wallet_id', sa.UUID(), nullable=False),
        sa.Column('type', sa.Enum('CREDIT', 'DEBIT', 'PAYOUT', 'ADJUSTMENT', name='transactiontype'), nullable=False),
        sa.Column('amount_cents', sa.BigInteger(), nullable=False),
        sa.Column('balance_after_cents', sa.BigInteger(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('reference_id', sa.String(length=255), nullable=True), # ID entrega o payout
        sa.Column('reference_type', sa.String(length=50), nullable=True), # 'DELIVERY', 'PAYOUT'
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('idempotency_key', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=True), # Usuario sistema o admin
        sa.ForeignKeyConstraint(['wallet_id'], ['rider_wallets.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_financial_transactions_wallet_id'), 'financial_transactions', ['wallet_id'], unique=False)
    op.create_index(op.f('ix_financial_transactions_reference_id'), 'financial_transactions', ['reference_id'], unique=False)
    op.create_index(op.f('ix_financial_transactions_idempotency_key'), 'financial_transactions', ['idempotency_key'], unique=True)

    # 3. Crear tabla payout_requests
    op.create_table('payout_requests',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('wallet_id', sa.UUID(), nullable=False),
        sa.Column('amount_cents', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.Enum('PENDING', 'APPROVED', 'PROCESSING', 'COMPLETED', 'REJECTED', name='payoutstatus'), nullable=False, default='PENDING'),
        sa.Column('payment_method_type', sa.String(length=50), nullable=False), # 'BANK_TRANSFER', 'STRIPE'
        sa.Column('bank_account_number', sa.String(length=50), nullable=True),
        sa.Column('bank_name', sa.String(length=100), nullable=True),
        sa.Column('stripe_transfer_id', sa.String(length=255), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('processed_by', sa.UUID(), nullable=True),
        sa.Column('requested_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['wallet_id'], ['rider_wallets.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_payout_requests_wallet_id'), 'payout_requests', ['wallet_id'], unique=False)
    op.create_index(op.f('ix_payout_requests_status'), 'payout_requests', ['status'], unique=False)

    # 4. Agregar columna stripe_account_id a users (si no existe)
    # Nota: En producción verificar si ya existe para evitar error
    op.add_column('users', sa.Column('stripe_account_id', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('stripe_payout_enabled', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    op.drop_column('users', 'stripe_payout_enabled')
    op.drop_column('users', 'stripe_account_id')
    
    op.drop_index(op.f('ix_payout_requests_status'), table_name='payout_requests')
    op.drop_index(op.f('ix_payout_requests_wallet_id'), table_name='payout_requests')
    op.drop_table('payout_requests')
    
    op.drop_index(op.f('ix_financial_transactions_idempotency_key'), table_name='financial_transactions')
    op.drop_index(op.f('ix_financial_transactions_reference_id'), table_name='financial_transactions')
    op.drop_index(op.f('ix_financial_transactions_wallet_id'), table_name='financial_transactions')
    op.drop_table('financial_transactions')
    
    op.drop_index(op.f('ix_rider_wallets_rider_id'), table_name='rider_wallets')
    op.drop_table('rider_wallets')
    
    # Eliminar enums si es necesario (cuidado en Postgres)
    op.execute("DROP TYPE IF EXISTS payoutstatus")
    op.execute("DROP TYPE IF EXISTS transactiontype")
    op.execute("DROP TYPE IF EXISTS walletstatus")