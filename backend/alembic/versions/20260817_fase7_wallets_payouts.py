"""fase7_wallets_payouts

Revision ID: 20260817
Revises: 20260816
Create Date: 2026-09-16 23:58:08.337332

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import uuid


# revision identifiers, used by Alembic.
revision: str = '20260817'
down_revision: Union[str, None] = '20260816'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None



def upgrade():
    # === 1. Crear ENUM types (IDEMPOTENTE) ===
    # Usamos execute() con SQL crudo para verificar existencia antes de crear
    
    # TransactionType enum
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'transactiontype_fase7') THEN
                CREATE TYPE transactiontype_fase7 AS ENUM (
                    'PAGO_ENTREGA', 'PAGO_INTENTO_FALLIDO', 'BONO_RENDIMIENTO',
                    'PENALIZACION', 'AJUSTE_MANUAL', 'INGRESO', 'RETIRO',
                    'BONO', 'DESCUENTO', 'AJUSTE',
                    'DELIVERY_BONUS', 'FAILED_ATTEMPT_BONUS',
                    'WITHDRAWAL_REQUEST', 'WITHDRAWAL_COMPLETION',
                    'STRIPE_PAYOUT', 'STRIPE_INSTANT', 'BANK_TRANSFER', 'WALLET_ADJUSTMENT'
                );
            END IF;
        END $$;
    """)

    # TransactionStatus enum
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'transactionstatus_fase7') THEN
                CREATE TYPE transactionstatus_fase7 AS ENUM (
                    'PENDING', 'COMPLETED', 'FAILED', 'CANCELLED', 'PROCESSING'
                );
            END IF;
        END $$;
    """)

    # PayoutStatus enum
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'payoutstatus_fase7') THEN
                CREATE TYPE payoutstatus_fase7 AS ENUM (
                    'PENDING', 'APPROVED', 'PROCESSING', 'COMPLETED', 'REJECTED', 'FAILED'
                );
            END IF;
        END $$;
    """)

    # === 2. Crear tabla rider_wallets ===
    op.create_table(
        'rider_wallets',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('rider_id', UUID(as_uuid=True), sa.ForeignKey('riders.id', ondelete='CASCADE'), unique=True, nullable=False, index=True),
        sa.Column('balance_cents', sa.Integer, default=0, nullable=False),
        sa.Column('currency', sa.String(3), default='USD', nullable=False),
        sa.Column('is_active', sa.Boolean, default=True, nullable=False),
        sa.Column('last_transaction_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    # === 3. Crear tabla financial_transactions ===
    op.create_table(
        'financial_transactions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('wallet_id', UUID(as_uuid=True), sa.ForeignKey('rider_wallets.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('transaction_type', sa.Enum('PAGO_ENTREGA', 'PAGO_INTENTO_FALLIDO', 'BONO_RENDIMIENTO', 'PENALIZACION', 'AJUSTE_MANUAL', 'INGRESO', 'RETIRO', 'BONO', 'DESCUENTO', 'AJUSTE', 'DELIVERY_BONUS', 'FAILED_ATTEMPT_BONUS', 'WITHDRAWAL_REQUEST', 'WITHDRAWAL_COMPLETION', 'STRIPE_PAYOUT', 'STRIPE_INSTANT', 'BANK_TRANSFER', 'WALLET_ADJUSTMENT', name='transactiontype_fase7'), nullable=False),
        sa.Column('amount_cents', sa.Integer, nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('reference_id', sa.String(255), nullable=True),
        sa.Column('metadata_json', sa.Text, nullable=True),
        sa.Column('status', sa.Enum('PENDING', 'COMPLETED', 'FAILED', 'CANCELLED', 'PROCESSING', name='transactionstatus_fase7'), default='PENDING', nullable=False),
        sa.Column('balance_after_cents', sa.Integer, nullable=False),
        sa.Column('created_by_user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('idempotency_key', sa.String(100), unique=True, index=True, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
    )

    # === 4. Crear tabla payout_requests ===
    op.create_table(
        'payout_requests',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('wallet_id', UUID(as_uuid=True), sa.ForeignKey('rider_wallets.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('rider_id', UUID(as_uuid=True), sa.ForeignKey('riders.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('amount_cents', sa.Integer, nullable=False),
        sa.Column('currency', sa.String(3), default='USD', nullable=False),
        sa.Column('bank_account_last4', sa.String(4), nullable=True),
        sa.Column('bank_name', sa.String(100), nullable=True),
        sa.Column('account_holder_name', sa.String(255), nullable=True),
        sa.Column('provider_payout_id', sa.String(255), nullable=True),
        sa.Column('provider_response_json', sa.Text, nullable=True),
        sa.Column('status', sa.Enum('PENDING', 'APPROVED', 'PROCESSING', 'COMPLETED', 'REJECTED', 'FAILED', name='payoutstatus_fase7'), default='PENDING', nullable=False, index=True),
        sa.Column('rejection_reason', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('failed_at', sa.DateTime(timezone=True), nullable=True),
    )

    # === 5. Índices adicionales para performance ===
    op.create_index('ix_rider_wallets_rider_id', 'rider_wallets', ['rider_id'])
    op.create_index('ix_financial_transactions_wallet_id', 'financial_transactions', ['wallet_id'])
    op.create_index('ix_financial_transactions_created_at', 'financial_transactions', ['created_at'])
    op.create_index('ix_payout_requests_rider_id', 'payout_requests', ['rider_id'])
    op.create_index('ix_payout_requests_status', 'payout_requests', ['status'])


def downgrade():
    # Eliminar tablas en orden inverso (respetando foreign keys)
    op.drop_table('payout_requests')
    op.drop_table('financial_transactions')
    op.drop_table('rider_wallets')

    # Eliminar ENUM types
    op.execute("DROP TYPE IF EXISTS payoutstatus_fase7")
    op.execute("DROP TYPE IF EXISTS transactionstatus_fase7")
    op.execute("DROP TYPE IF EXISTS transactiontype_fase7")