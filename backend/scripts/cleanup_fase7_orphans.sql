-- =====================================================
-- LIMPIEZA DE OBJETOS HUÉRFANOS FASE 7 - Delivery360
-- =====================================================
-- Ejecutar este script SOLO si hubo intentos fallidos previos
-- de la migración 20260817_fase7_wallets_payouts
--
-- Uso: 
--   docker compose exec db psql -U admin -d delivery360 -f /ruta/a/este/script.sql
-- =====================================================

BEGIN;

-- 1. Eliminar tablas de Fase 7 (si existen)
--    CASCADE elimina dependencias automáticamente
DROP TABLE IF EXISTS payout_requests CASCADE;
DROP TABLE IF EXISTS financial_transactions CASCADE;
DROP TABLE IF EXISTS rider_wallets CASCADE;

-- 2. Eliminar ENUMs huérfanos de Fase 7 (si existen)
--    Estos tipos pueden haber quedado creados en ejecuciones parciales
DROP TYPE IF EXISTS payoutstatus_fase7;
DROP TYPE IF EXISTS transactionstatus_fase7;
DROP TYPE IF EXISTS transactiontype_fase7;

-- 3. Verificar limpieza (output informativo)
SELECT '=== TABLAS EXISTENTES ===' AS info;
SELECT table_name, table_schema 
FROM information_schema.tables 
WHERE table_schema = 'public' 
ORDER BY table_name;

SELECT '=== TIPOS ENUM EXISTENTES ===' AS info;
SELECT typname 
FROM pg_type 
WHERE typtype = 'e' 
ORDER BY typname;

COMMIT;

-- =====================================================
-- NOTAS IMPORTANTES:
-- =====================================================
-- ✅ Este script NO afecta datos de Fases 1-6
-- ✅ Solo elimina objetos específicos de la Fase 7
-- ✅ Después de ejecutar, correr: alembic stamp 20260816
-- ✅ Luego ejecutar: alembic upgrade head
-- =====================================================
