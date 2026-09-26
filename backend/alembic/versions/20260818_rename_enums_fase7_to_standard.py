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
    # FIX FASE 7: Si ya existe un tipo 'payoutstatus' LEGACY heredado del esquema
    # inicial (a617d286d3d0 / schema_completo.sql) con los 4 valores antiguos
    # ('PENDIENTE','PROCESADO','RECHAZADO','CANCELADO'), debe ser REEMPLAZADO por
    # el estándar de Fase 7 con los 6 valores en español. Esto corrige el error:
    #   asyncpg.exceptions.InvalidTextRepresentationError:
    #   invalid input value for enum payoutstatus: "APROBADO"
    op.execute("""
        DO $$
        DECLARE
            legacy_dependents INTEGER;
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'payoutstatus') THEN
                -- Detectar si el tipo existente NO es el estándar de Fase 7
                IF (SELECT array_agg(e.enumlabel::text ORDER BY e.enumsortorder)
                    FROM pg_type t JOIN pg_enum e ON t.oid = e.enumtypid
                    WHERE t.typname = 'payoutstatus')
                   IS DISTINCT FROM
                   ARRAY['PENDIENTE','APROBADO','EN_PROCESO','COMPLETADO','RECHAZADO','FALLIDO']::text[]
                THEN
                    -- Contar dependencias fuera de payout_requests (vistas, otras tablas).
                    -- Nota: COUNT(*) sobre 0 filas devuelve 0, nunca NULL.
                    SELECT COUNT(*) INTO legacy_dependents
                    FROM pg_depend d
                    JOIN pg_class rel ON rel.oid = d.refobjid
                    WHERE d.classid = 'pg_type'::regclass
                      AND d.objid = 'payoutstatus'::regtype
                      AND d.deptype IN ('n', 'a')
                      AND rel.relname <> 'payout_requests';

                    IF legacy_dependents > 0 THEN
                        RAISE EXCEPTION
                            'El enum legacy payoutstatus tiene dependencias externas (%) en la tabla %. '
                            'Refuérzalas manualmente antes de ejecutar esta migración.',
                            legacy_dependents,
                            (SELECT string_agg(DISTINCT rel.relname, ', ')
                             FROM pg_depend d
                             JOIN pg_class rel ON rel.oid = d.refobjid
                             WHERE d.classid = 'pg_type'::regclass
                               AND d.objid = 'payoutstatus'::regtype
                               AND d.deptype IN ('n', 'a')
                               AND rel.relname <> 'payout_requests');
                    END IF;

                    -- Eliminar el enum legacy y TODAS sus columnas legacy asociadas
                    DROP TYPE payoutstatus CASCADE;
                END IF;
            ELSE
                CREATE TYPE payoutstatus AS ENUM (
                    'PENDIENTE', 'APROBADO', 'EN_PROCESO', 'COMPLETADO', 'RECHAZADO', 'FALLIDO'
                );
            END IF;
        END $$;
    """)

    # Asegurar que el tipo payoutstatus exista con los 6 valores en español
    # (cubre el caso en que existía legacy y fue eliminado arriba con CASCADE)
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

    # Actualizar payout_requests.status con traducción al español.
    # FIX FASE 7: si la columna 'status' no existe (porque el enum legacy fue
    # eliminado arriba con CASCADE), recrearla como TEXT antes de manipularla.
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'payout_requests' AND column_name = 'status'
            ) THEN
                ALTER TABLE payout_requests ADD COLUMN status TEXT;
            END IF;
        END $$;
    """)

    op.execute("""
        ALTER TABLE payout_requests 
        ALTER COLUMN status DROP DEFAULT;
    """)

    # FIX FASE 7: Normalizar valores a los 6 estados estándar en español.
    # Se hace SIEMPRE vía reconversión a TEXT porque la columna puede venir de:
    #   a) payoutstatus_fase7 (flujo normal 20260817 -> 20260818), o
    #   b) payoutstatus legacy de 4 valores ya eliminado con CASCADE (columna recreada TEXT), o
    #   c) TEXT por re-ejecuciones parciales anteriores.
    op.execute("""
        ALTER TABLE payout_requests 
        ALTER COLUMN status TYPE TEXT 
        USING CASE status::text
            WHEN 'PENDING'     THEN 'PENDIENTE'
            WHEN 'PENDIENTE'   THEN 'PENDIENTE'
            WHEN 'APPROVED'    THEN 'APROBADO'
            WHEN 'APROBADO'    THEN 'APROBADO'
            WHEN 'PROCESSING'  THEN 'EN_PROCESO'
            WHEN 'EN_PROCESO'  THEN 'EN_PROCESO'
            WHEN 'PROCESADO'   THEN 'EN_PROCESO'
            WHEN 'COMPLETED'   THEN 'COMPLETADO'
            WHEN 'COMPLETADO'  THEN 'COMPLETADO'
            WHEN 'REJECTED'    THEN 'RECHAZADO'
            WHEN 'RECHAZADO'   THEN 'RECHAZADO'
            WHEN 'FAILED'      THEN 'FALLIDO'
            WHEN 'FALLIDO'     THEN 'FALLIDO'
            WHEN 'CANCELADO'   THEN 'RECHAZADO'
            WHEN 'CANCELLED'   THEN 'RECHAZADO'
            ELSE 'PENDIENTE'
        END;
    """)

    op.execute("""
        ALTER TABLE payout_requests 
        ALTER COLUMN status TYPE payoutstatus 
        USING status::text::payoutstatus;
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

    # === 5. FIX FASE 7: Reconstruir el índice UNIQUE de status ===
    # El índice 'ix_payout_requests_status' creado en 20260817 era UNIQUE (por la
    # constraint del esquema inicial). Con los 6 estados actuales eso provoca
    # "duplicate key value violates unique constraint" al sembrar varios payouts
    # con el mismo estado (p. ej. dos 'PENDIENTE'). Se reemplaza por un índice NO
    # UNIQUE, que es lo correcto para una columna de estado.
    op.execute("DROP INDEX IF EXISTS ix_payout_requests_status")
    op.create_index(
        'ix_payout_requests_status', 'payout_requests', ['status'], unique=False
    )


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
    # FIX: quitar defaults antes de reconvertir (PG no puede castear defaults
    # entre tipos enum automáticamente)
    op.execute("ALTER TABLE financial_transactions ALTER COLUMN status DROP DEFAULT;")

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
        ALTER TABLE financial_transactions 
        ALTER COLUMN status SET DEFAULT 'PENDING'::transactionstatus_fase7;
    """)

    op.execute("ALTER TABLE payout_requests ALTER COLUMN status DROP DEFAULT;")

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

    # Restaurar default en inglés para el enum antiguo (era 'PENDING')
    op.execute("""
        ALTER TABLE payout_requests 
        ALTER COLUMN status SET DEFAULT 'PENDING'::payoutstatus_fase7;
    """)

    # === 3. Eliminar columnas agregadas (solo si existen) ===
    # Nota: No eliminamos las columnas en downgrade para preservar datos,
    # solo revertimos los ENUMs
    
    # === 4. Eliminar ENUMs nuevos ===
    op.execute("DROP TYPE IF EXISTS payoutstatus")
    op.execute("DROP TYPE IF EXISTS transactionstatus")
    op.execute("DROP TYPE IF EXISTS transactiontype")
