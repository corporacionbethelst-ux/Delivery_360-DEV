"""fase7_wallets_payouts

Revision ID: 20260817
Revises: 20260816
Create Date: 2026-09-16 23:58:08.337332

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
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

    # === 2. Crear tabla rider_wallets (usando SQL crudo para evitar auto-creación de ENUMs) ===
    op.execute("""
        CREATE TABLE rider_wallets (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            rider_id UUID UNIQUE NOT NULL REFERENCES riders(id) ON DELETE CASCADE,
            balance_cents INTEGER NOT NULL DEFAULT 0,
            currency VARCHAR(3) NOT NULL DEFAULT 'USD',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            last_transaction_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
        )
    """)

    # === 3. Crear tabla financial_transactions ===
    op.execute("""
        CREATE TABLE financial_transactions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            wallet_id UUID NOT NULL REFERENCES rider_wallets(id) ON DELETE CASCADE,
            transaction_type transactiontype_fase7 NOT NULL,
            amount_cents INTEGER NOT NULL,
            description TEXT,
            reference_id VARCHAR(255),
            metadata_json TEXT,
            status transactionstatus_fase7 NOT NULL DEFAULT 'PENDING',
            balance_after_cents INTEGER NOT NULL,
            created_by_user_id UUID REFERENCES users(id),
            idempotency_key VARCHAR(100) UNIQUE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
        )
    """)

    # === 4. Crear tabla payout_requests ===
    op.execute("""
        CREATE TABLE payout_requests (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            wallet_id UUID NOT NULL REFERENCES rider_wallets(id) ON DELETE CASCADE,
            rider_id UUID NOT NULL REFERENCES riders(id) ON DELETE CASCADE,
            amount_cents INTEGER NOT NULL,
            currency VARCHAR(3) NOT NULL DEFAULT 'USD',
            bank_account_last4 VARCHAR(4),
            bank_name VARCHAR(100),
            account_holder_name VARCHAR(255),
            provider_payout_id VARCHAR(255),
            provider_response_json TEXT,
            status payoutstatus_fase7 NOT NULL DEFAULT 'PENDING',
            rejection_reason TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
            approved_at TIMESTAMP WITH TIME ZONE,
            processed_at TIMESTAMP WITH TIME ZONE,
            completed_at TIMESTAMP WITH TIME ZONE,
            failed_at TIMESTAMP WITH TIME ZONE
        )
    """)

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