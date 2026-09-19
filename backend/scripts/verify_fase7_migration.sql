-- =====================================================
-- VERIFICACIÓN POST-MIGRACIÓN FASE 7 - Delivery360
-- =====================================================
-- Ejecutar después de 'alembic upgrade head' exitoso
--
-- Uso: 
--   docker compose exec db psql -U admin -d delivery360 -f verify_fase7.sql
-- =====================================================

-- 1. Verificar que las tablas de Fase 7 existen
SELECT '=== TABLAS FASE 7 ===' AS info;
SELECT 
    table_name, 
    table_schema,
    CASE 
        WHEN table_name = 'rider_wallets' THEN '✅ Wallet del Rider'
        WHEN table_name = 'financial_transactions' THEN '✅ Historial Transacciones'
        WHEN table_name = 'payout_requests' THEN '✅ Solicitudes Retiro'
        ELSE '⚠️ Otra tabla'
    END AS descripcion
FROM information_schema.tables 
WHERE table_name IN ('rider_wallets', 'financial_transactions', 'payout_requests')
ORDER BY table_name;

-- 2. Verificar estructura de rider_wallets
SELECT '=== ESTRUCTURA rider_wallets ===' AS info;
\d rider_wallets

-- 3. Verificar ENUMs creados correctamente
SELECT '=== TIPOS ENUM FASE 7 ===' AS info;
SELECT 
    typname AS nombre_enum,
    pg_catalog.array_to_string(
        ARRAY(
            SELECT enumlabel 
            FROM pg_enum 
            WHERE enumtypid = pt.oid 
            ORDER BY enumsortorder
        ),
        ', '
    ) AS valores
FROM pg_type pt
WHERE typname IN ('transactiontype_fase7', 'transactionstatus_fase7', 'payoutstatus_fase7')
ORDER BY typname;

-- 4. Verificar wallets inicializadas (primeros 5 riders)
SELECT '=== WALLETS DE RIDERS (primeros 5) ===' AS info;
SELECT 
    rw.id AS wallet_id,
    rw.rider_id,
    rw.balance_cents,
    rw.balance_cents::numeric / 100 AS balance_usd,
    rw.currency,
    rw.is_active,
    r.name AS rider_name,
    r.status AS rider_status
FROM rider_wallets rw
JOIN riders r ON r.id = rw.rider_id
ORDER BY rw.created_at DESC
LIMIT 5;

-- 5. Contar wallets totales vs riders totales
SELECT '=== ESTADÍSTICAS ===' AS info;
SELECT 
    (SELECT COUNT(*) FROM riders) AS total_riders,
    (SELECT COUNT(*) FROM rider_wallets) AS total_wallets,
    (SELECT COUNT(*) FROM riders WHERE id NOT IN (SELECT rider_id FROM rider_wallets)) AS riders_sin_wallet;

-- 6. Verificar índices de performance
SELECT '=== ÍNDICES FASE 7 ===' AS info;
SELECT 
    indexname,
    tablename,
    indexdef
FROM pg_indexes
WHERE tablename IN ('rider_wallets', 'financial_transactions', 'payout_requests')
ORDER BY tablename, indexname;

-- =====================================================
-- QUERY PARA VERIFICAR UN RIDER ESPECÍFICO
-- =====================================================
-- Reemplazar {rider_id} con el UUID del rider a verificar:
-- SELECT * FROM rider_wallets WHERE rider_id = '{rider_id}';
-- SELECT * FROM financial_transactions WHERE wallet_id = (SELECT id FROM rider_wallets WHERE rider_id = '{rider_id}') LIMIT 10;
-- =====================================================
