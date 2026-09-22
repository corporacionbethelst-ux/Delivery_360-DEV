-- ============================================
-- SCRIPT DE CORRECCIÓN MANUAL DEL ENUM payoutstatus
-- ============================================
-- Este script actualiza el tipo ENUM payoutstatus para usar valores en español.
-- Ejecutar cuando la migración 20260818 falla o no se aplicó completamente.
--
-- Uso: 
--   docker compose exec db psql -U admin -d delivery360 -f /tmp/fix_payoutstatus_enum.sql
-- ============================================

BEGIN;

-- 1. Verificar si existe el tipo payoutstatus
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'payoutstatus') THEN
        RAISE NOTICE 'El tipo payoutstatus NO existe. Creándolo desde cero...';
        
        CREATE TYPE payoutstatus AS ENUM (
            'PENDIENTE',
            'APROBADO',
            'EN_PROCESO',
            'COMPLETADO',
            'RECHAZADO',
            'FALLIDO'
        );
        
        RAISE NOTICE 'Tipo payoutstatus creado exitosamente.';
    ELSE
        RAISE NOTICE 'El tipo payoutstatus YA existe. Verificando valores...';
    END IF;
END $$;

-- 2. Verificar valores actuales del enum
SELECT unnest(enum_range(NULL::payoutstatus)) AS valores_actuales;

-- 3. Si el enum existe pero tiene valores incorrectos, necesitamos recrearlo
-- Esto solo funciona si NO hay columnas usándolo aún, o si ya fueron migradas
DO $$
DECLARE
    valor_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO valor_count 
    FROM unnest(enum_range(NULL::payoutstatus)) AS v
    WHERE v IN ('PENDIENTE', 'APROBADO', 'EN_PROCESO', 'COMPLETADO', 'RECHAZADO', 'FALLIDO');
    
    IF valor_count < 6 THEN
        RAISE WARNING 'El enum payoutstatus tiene valores incorrectos o incompletos.';
        RAISE WARNING 'Valores esperados: PENDIENTE, APROBADO, EN_PROCESO, COMPLETADO, RECHAZADO, FALLIDO';
        RAISE WARNING 'Por favor ejecuta la migración 20260818 nuevamente o recrea el enum manualmente.';
    ELSE
        RAISE NOTICE 'El enum payoutstatus tiene los valores correctos en español.';
    END IF;
END $$;

-- 4. Verificar si la tabla payout_requests usa el enum correcto
DO $$
DECLARE
    col_type TEXT;
BEGIN
    SELECT data_type INTO col_type
    FROM information_schema.columns
    WHERE table_name = 'payout_requests' AND column_name = 'status';
    
    IF col_type IS NULL THEN
        RAISE NOTICE 'La tabla payout_requests aún no existe.';
    ELSIF col_type = 'USER-DEFINED' THEN
        RAISE NOTICE 'La columna status de payout_requests usa un tipo ENUM personalizado.';
    ELSE
        RAISE NOTICE 'Tipo de dato de status: %', col_type;
    END IF;
END $$;

COMMIT;

-- ============================================
-- RESULTADO ESPERADO:
-- ============================================
-- Deberías ver 6 filas con los valores:
--   PENDIENTE
--   APROBADO
--   EN_PROCESO
--   COMPLETADO
--   RECHAZADO
--   FALLIDO
-- ============================================
