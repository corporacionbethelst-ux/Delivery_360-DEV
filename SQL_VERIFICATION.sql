-- ============================================================
-- DELIVERY360 - SCRIPT SQL DE VERIFICACIÓN DE INTEGRIDAD
-- ============================================================
-- Ejecutar en psql o cualquier cliente PostgreSQL
-- ============================================================

-- 1. VERIFICAR ENTREGAS HUÉRFANAS (sin order_id válido)
-- Debería retornar 0 filas. Si hay filas, hay integridad rota.
SELECT 
    d.id AS delivery_id, 
    d.order_id AS expected_order,
    d.rider_id AS assigned_rider,
    d.status AS delivery_status
FROM deliveries d
LEFT JOIN orders o ON d.order_id = o.id
WHERE o.id IS NULL
ORDER BY d.created_at DESC;

-- 2. VERIFICAR RIDERS SIN USUARIO PADRE
-- Debería retornar 0 filas. Cada rider DEBE tener un user_id válido.
SELECT 
    r.id AS rider_id, 
    r.user_id AS expected_user,
    r.status AS rider_status,
    r.vehicle_type
FROM riders r
LEFT JOIN users u ON r.user_id = u.id
WHERE u.id IS NULL OR r.user_id IS NULL;

-- 3. VERIFICAR INTEGRIDAD COMPLETA DE JOINS (DELIVERIES -> RIDERS -> USERS -> ORDERS)
-- Esta es la consulta CRÍTICA que replica lo que hace el endpoint
-- Debería mostrar customer_name y first_name para cada entrega
SELECT 
    d.id AS delivery_id,
    r.id AS rider_id,
    u.id AS user_id,
    o.id AS order_id,
    u.first_name AS rider_first_name,
    u.last_name AS rider_last_name,
    o.customer_name AS customer_name,
    o.external_id AS order_external_id,
    d.status AS delivery_status,
    r.status AS rider_status
FROM deliveries d
LEFT JOIN riders r ON d.rider_id = r.id
LEFT JOIN users u ON r.user_id = u.id
LEFT JOIN orders o ON d.order_id = o.id
ORDER BY d.created_at DESC
LIMIT 20;

-- 4. CONTAR RIDERS POR ESTADO
-- Importante: Solo riders ACTIVOS pueden loguearse y ser asignados
SELECT status, COUNT(*) as total_riders
FROM riders 
GROUP BY status
ORDER BY total_riders DESC;

-- 5. VERIFICAR SI SUPERADMIN EXISTE
-- Este usuario DEBE existir para poder administrar el sistema
SELECT 
    id, 
    email, 
    first_name, 
    last_name, 
    role, 
    is_active,
    created_at
FROM users 
WHERE email = 'super@delivery360.com';

-- 6. VERIFICAR USUARIOS CON ROL REPARTIDOR
-- Todos los repartidores deben tener rol=REPARTIDOR y un registro en riders
SELECT 
    u.id AS user_id,
    u.email,
    u.first_name,
    u.last_name,
    u.role,
    u.is_active,
    r.id AS rider_profile_exists,
    r.status AS rider_status
FROM users u
LEFT JOIN riders r ON u.id = r.user_id
WHERE u.role = 'REPARTIDOR'
ORDER BY u.created_at DESC;

-- 7. CONTAR ÓRDENES POR ESTADO
-- Para entender la distribución de datos en el sistema
SELECT status, COUNT(*) as total_orders
FROM orders 
GROUP BY status
ORDER BY total_orders DESC;

-- 8. VERIFICAR ENTREGAS SIN RIDER ASIGNADO
-- Todas las entregas deberían tener rider_id (es NOT NULL en el modelo)
SELECT 
    d.id AS delivery_id,
    d.order_id,
    d.rider_id,
    d.status,
    CASE 
        WHEN d.rider_id IS NULL THEN 'SIN RIDER - ERROR!'
        ELSE 'OK'
    END AS integrity_check
FROM deliveries d
WHERE d.rider_id IS NULL;

-- 9. DIAGNÓSTICO COMPLETO DE UNA ENTREGA ESPECÍFICA
-- Reemplaza <DELIVERY_ID> con un ID real para depurar
-- SELECT 
--     d.id AS delivery_id,
--     d.status AS delivery_status,
--     o.id AS order_id,
--     o.external_id,
--     o.customer_name,
--     o.items,
--     r.id AS rider_id,
--     r.status AS rider_status,
--     r.vehicle_type,
--     u.id AS user_id,
--     u.email AS rider_email,
--     u.first_name,
--     u.last_name,
--     u.role
-- FROM deliveries d
-- LEFT JOIN orders o ON d.order_id = o.id
-- LEFT JOIN riders r ON d.rider_id = r.id
-- LEFT JOIN users u ON r.user_id = u.id
-- WHERE d.id = '<DELIVERY_ID_AQUI>';

-- ============================================================
-- RESUMEN DE RESULTADOS ESPERADOS
-- ============================================================
-- Query 1: 0 filas (sin entregas huérfanas)
-- Query 2: 0 filas (todos los riders tienen usuario)
-- Query 3: Todas las filas deben tener rider_first_name y customer_name NO NULL
-- Query 4: Debe haber al menos algunos riders con status='ACTIVO'
-- Query 5: 1 fila con super@delivery360.com, is_active=true
-- Query 6: Todos los usuarios REPARTIDOR deben tener rider_profile_exists NO NULL
-- Query 7: Distribución variada de estados (mayoría ENTREGADO)
-- Query 8: 0 filas (todas las entregas tienen rider)
-- ============================================================
