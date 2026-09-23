"""rename_enums_fase7_to_standard

Revision ID: 20260818
Revises: 20260817
Create Date: 2026-09-20 10:00:00.000000

Esta migración renombra los ENUMs de la Fase 7 para eliminar el sufijo '_fase7'
y estandarizar los nombres según las convenciones del proyecto.
También traduce los valores de payoutstatus al español.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260818'
down_revision: Union[str, None] = '20260817'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # === 1. Crear nuevos ENUMs con nombres estándar ===
    
    # TransactionType (sin _fase7, mantiene valores en inglés por ser códigos internos)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'transactiontype') THEN
                CREATE TYPE transactiontype AS ENUM (
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

    # TransactionStatus (sin _fase7, mantiene valores en inglés por ser códigos internos)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'transactionstatus') THEN
                CREATE TYPE transactionstatus AS ENUM (
                    'PENDING', 'COMPLETED', 'FAILED', 'CANCELLED', 'PROCESSING'
                );
            END IF;
        END $$;
    """)

    # PayoutStatus (sin _fase7, con valores TRADUCIDOS AL ESPAÑOL)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'payoutstatus') THEN
                CREATE TYPE payoutstatus AS ENUM (
                    'PENDIENTE', 'APROBADO', 'EN_PROCESO', 'COMPLETADO', 'RECHAZADO', 'FALLIDO'
                );
            END IF;
        END $$;
    """)

    # === 2. Migrar datos: Actualizar columnas para usar nuevos ENUMs ===
    
    # Actualizar financial_transactions.transaction_type
    op.execute("""
        ALTER TABLE financial_transactions 
        ALTER COLUMN transaction_type TYPE transactiontype 
        USING transaction_type::text::transactiontype;
    """)

    # Actualizar financial_transactions.status (primero quitar default, luego cambiar tipo, luego restaurar default)
    op.execute("""
        ALTER TABLE financial_transactions 
        ALTER COLUMN status DROP DEFAULT;
    """)
    
    op.execute("""
        ALTER TABLE financial_transactions 
        ALTER COLUMN status TYPE transactionstatus 
        USING status::text::transactionstatus;
    """)
    
    op.execute("""
        ALTER TABLE financial_transactions 
        ALTER COLUMN status SET DEFAULT 'PENDING'::transactionstatus;
    """)

    # Actualizar payout_requests.status con traducción al español (primero quitar default)
    op.execute("""
        ALTER TABLE payout_requests 
        ALTER COLUMN status DROP DEFAULT;
    """)
    
    op.execute("""
        ALTER TABLE payout_requests 
        ALTER COLUMN status TYPE payoutstatus 
        USING CASE 
            WHEN status::text = 'PENDING' THEN 'PENDIENTE'
            WHEN status::text = 'APPROVED' THEN 'APROBADO'
            WHEN status::text = 'PROCESSING' THEN 'EN_PROCESO'
            WHEN status::text = 'COMPLETED' THEN 'COMPLETADO'
            WHEN status::text = 'REJECTED' THEN 'RECHAZADO'
            WHEN status::text = 'FAILED' THEN 'FALLIDO'
            ELSE 'PENDIENTE'
        END::payoutstatus;
    """)
    
    op.execute("""
        ALTER TABLE payout_requests 
        ALTER COLUMN status SET DEFAULT 'PENDIENTE'::payoutstatus;
    """)

    # === 3. Agregar columnas faltantes en payout_requests ===
    
    # Agregar failure_reason si no existe
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'payout_requests' AND column_name = 'failure_reason'
            ) THEN
                ALTER TABLE payout_requests ADD COLUMN failure_reason TEXT;
            END IF;
        END $$;
    """)
    
    # Agregar idempotency_key si no existe
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'payout_requests' AND column_name = 'idempotency_key'
            ) THEN
                ALTER TABLE payout_requests ADD COLUMN idempotency_key VARCHAR(100);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_payout_requests_idempotency_key ON payout_requests(idempotency_key);
            END IF;
        END $$;
    """)
    
    # Agregar approved_at, processed_at, completed_at, failed_at si no existen
    for col_name in ['approved_at', 'processed_at', 'completed_at', 'failed_at']:
        op.execute(f"""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'payout_requests' AND column_name = '{col_name}'
                ) THEN
                    ALTER TABLE payout_requests ADD COLUMN {col_name} TIMESTAMP;
                END IF;
            END $$;
        """)

    # === 4. Eliminar ENUMs antiguos (_fase7) ===
    op.execute("DROP TYPE IF EXISTS payoutstatus_fase7")
    op.execute("DROP TYPE IF EXISTS transactionstatus_fase7")
    op.execute("DROP TYPE IF EXISTS transactiontype_fase7")


def downgrade():
    # === 1. Recrear ENUMs antiguos (_fase7) ===
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

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'transactionstatus_fase7') THEN
                CREATE TYPE transactionstatus_fase7 AS ENUM (
                    'PENDING', 'COMPLETED', 'FAILED', 'CANCELLED', 'PROCESSING'
                );
            END IF;
        END $$;
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'payoutstatus_fase7') THEN
                CREATE TYPE payoutstatus_fase7 AS ENUM (
                    'PENDING', 'APPROVED', 'PROCESSING', 'COMPLETED', 'REJECTED', 'FAILED'
                );
            END IF;
        END $$;
    """)

    # === 2. Revertir columnas a ENUMs antiguos ===
    op.execute("""
        ALTER TABLE financial_transactions 
        ALTER COLUMN transaction_type TYPE transactiontype_fase7 
        USING transaction_type::text::transactiontype_fase7;
    """)

    op.execute("""
        ALTER TABLE financial_transactions 
        ALTER COLUMN status TYPE transactionstatus_fase7 
        USING status::text::transactionstatus_fase7;
    """)

    op.execute("""
        ALTER TABLE payout_requests 
        ALTER COLUMN status TYPE payoutstatus_fase7 
        USING CASE 
            WHEN status::text = 'PENDIENTE' THEN 'PENDING'
            WHEN status::text = 'APROBADO' THEN 'APPROVED'
            WHEN status::text = 'EN_PROCESO' THEN 'PROCESSING'
            WHEN status::text = 'COMPLETADO' THEN 'COMPLETED'
            WHEN status::text = 'RECHAZADO' THEN 'REJECTED'
            WHEN status::text = 'FALLIDO' THEN 'FAILED'
            ELSE 'PENDING'
        END::payoutstatus_fase7;
    """)

    # === 3. Eliminar columnas agregadas (solo si existen) ===
    # Nota: No eliminamos las columnas en downgrade para preservar datos,
    # solo revertimos los ENUMs
    
    # === 4. Eliminar ENUMs nuevos ===
    op.execute("DROP TYPE IF EXISTS payoutstatus")
    op.execute("DROP TYPE IF EXISTS transactionstatus")
    op.execute("DROP TYPE IF EXISTS transactiontype")
