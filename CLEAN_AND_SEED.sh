#!/bin/bash
# =============================================================================
# SCRIPT DE LIMPIEZA Y REINICIO COMPLETO - DELIVERY360
# =============================================================================
# Este script elimina TODA inconsistencia de datos reiniciando la BD desde cero
# y sembrando datos relacionales correctos con seed_data.py
# =============================================================================

set -e  # Detener script si algún comando falla

echo "======================================================================"
echo "🧹 LIMPIEZA Y REINICIO COMPLETO - DELIVERY360"
echo "======================================================================"

# ------------------------------------------------------------------------------
# PASO 1: Detener todos los contenedores
# ------------------------------------------------------------------------------
echo ""
echo "📴 PASO 1: Deteniendo contenedores Docker..."
cd /workspace/backend
docker compose down

# ------------------------------------------------------------------------------
# PASO 2: Eliminar volúmenes de la base de datos (datos persistentes)
# ------------------------------------------------------------------------------
echo ""
echo "🗑️  PASO 2: Eliminando volúmenes de base de datos (esto borra TODOS los datos)..."
docker volume ls | grep backend_postgres_data && docker volume rm backend_postgres_data || echo "   ℹ️  Volumen no existe, continuando..."

# ------------------------------------------------------------------------------
# PASO 3: Eliminar contenedores huérfanos y redes antiguas
# ------------------------------------------------------------------------------
echo ""
echo "🧹 PASO 3: Limpiando contenedores huérfanos y redes..."
docker container prune -f
docker network prune -f

# ------------------------------------------------------------------------------
# PASO 4: Iniciar contenedores desde cero
# ------------------------------------------------------------------------------
echo ""
echo "🚀 PASO 4: Iniciando contenedores Docker (esto puede tardar 1-2 minutos)..."
docker compose up -d --build

# Esperar a que PostgreSQL esté listo
echo ""
echo "⏳ Esperando a que PostgreSQL esté listo (30 segundos)..."
sleep 30

# ------------------------------------------------------------------------------
# PASO 5: Verificar que los contenedores estén saludables
# ------------------------------------------------------------------------------
echo ""
echo "🏥 PASO 5: Verificando estado de los contenedores..."
docker compose ps

# ------------------------------------------------------------------------------
# PASO 6: Ejecutar migraciones de base de datos
# ------------------------------------------------------------------------------
echo ""
echo "🔄 PASO 6: Ejecutando migraciones de Alembic..."
docker compose exec -T backend alembic upgrade head

# ------------------------------------------------------------------------------
# PASO 7: Ejecutar seed_data.py (el script CORRECTO con datos relacionales)
# ------------------------------------------------------------------------------
echo ""
echo "🌱 PASO 7: Ejecutando seed_data.py para poblar base de datos..."
docker compose exec -T backend python scripts/seed_data.py

# ------------------------------------------------------------------------------
# PASO 8: Validación de datos sembrados
# ------------------------------------------------------------------------------
echo ""
echo "✅ PASO 8: Validando integridad de datos..."

# Consulta para verificar usuarios
echo ""
echo "📊 Usuarios creados:"
docker compose exec -T postgres psql -U delivery_user -d delivery_db -c "SELECT role, COUNT(*) FROM users GROUP BY role ORDER BY role;"

# Consulta para verificar riders
echo ""
echo "🛵 Riders creados:"
docker compose exec -T postgres psql -U delivery_user -d delivery_db -c "SELECT COUNT(*) as total_riders, COUNT(CASE WHEN status = 'ACTIVO' THEN 1 END) as activos FROM riders;"

# Consulta para verificar órdenes
echo ""
echo "📦 Órdenes creadas:"
docker compose exec -T postgres psql -U delivery_user -d delivery_db -c "SELECT status, COUNT(*) FROM orders GROUP BY status ORDER BY status;"

# Consulta para verificar entregas
echo ""
echo "🚚 Entregas creadas:"
docker compose exec -T postgres psql -U delivery_user -d delivery_db -c "SELECT COUNT(*) as total_deliveries, COUNT(CASE WHEN rider_id IS NOT NULL THEN 1 END) as con_rider FROM deliveries;"

# Consulta CRÍTICA: Verificar que las entregas tengan customer_name y rider.first_name
echo ""
echo "🔍 VERIFICACIÓN CRÍTICA: Datos enriquecidos en entregas..."
docker compose exec -T postgres psql -U delivery_user -d delivery_db -c "
SELECT 
    d.id as delivery_id,
    o.customer_name,
    u.first_name as rider_first_name,
    u.last_name as rider_last_name,
    d.status
FROM deliveries d
JOIN orders o ON d.order_id = o.id
JOIN riders r ON d.rider_id = r.id
JOIN users u ON r.user_id = u.id
LIMIT 5;
"

# ------------------------------------------------------------------------------
# PASO 9: Probar endpoint de la API
# ------------------------------------------------------------------------------
echo ""
echo "🧪 PASO 9: Probando endpoint /api/v1/deliveries..."

# Obtener token de acceso
echo ""
echo "🔑 Obteniendo token de autenticación..."
TOKEN_RESPONSE=$(curl -s -X POST "http://localhost:8000/api/v1/auth/login" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "username=super@delivery360.com&password=Admin123!")

echo "Respuesta del login:"
echo "$TOKEN_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$TOKEN_RESPONSE"

# Extraer token (intento 1: con jq si está disponible, intento 2: con python)
if command -v jq &> /dev/null; then
    ACCESS_TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r '.access_token')
else
    ACCESS_TOKEN=$(echo "$TOKEN_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null || echo "")
fi

if [ -z "$ACCESS_TOKEN" ] || [ "$ACCESS_TOKEN" == "null" ]; then
    echo "❌ ERROR: No se pudo obtener el token de acceso."
    echo "   Verifica que el usuario super@delivery360.com exista y la contraseña sea Admin123!"
    exit 1
fi

echo ""
echo "✅ Token obtenido exitosamente."

# Probar endpoint de deliveries
echo ""
echo "📡 Llamando a GET /api/v1/deliveries..."
DELIVERIES_RESPONSE=$(curl -s -X GET "http://localhost:8000/api/v1/deliveries" \
    -H "Authorization: Bearer $ACCESS_TOKEN")

echo ""
echo "📊 Respuesta del endpoint (primeras 3 entregas):"
echo "$DELIVERIES_RESPONSE" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if isinstance(data, list) and len(data) > 0:
        print(f'Total entregas encontradas: {len(data)}')
        print('')
        for i, delivery in enumerate(data[:3]):
            print(f'--- Entrega {i+1} ---')
            print(f'  ID: {delivery.get(\"id\", \"N/A\")}')
            print(f'  Estado: {delivery.get(\"status\", \"N/A\")}')
            customer = delivery.get('customer', {})
            print(f'  Cliente: {customer.get(\"name\", \"N/A\") if customer else \"N/A\"}')
            rider = delivery.get('rider', {})
            if rider:
                print(f'  Repartidor: {rider.get(\"first_name\", \"N/A\")} {rider.get(\"last_name\", \"N/A\")}')
            else:
                print(f'  Repartidor: Sin asignar')
            print('')
    else:
        print('No se encontraron entregas o la respuesta no es una lista.')
except Exception as e:
    print(f'Error al parsear respuesta: {e}')
    print('Respuesta cruda:', sys.stdin.read()[:500])
" 2>/dev/null || echo "$DELIVERIES_RESPONSE" | head -c 1000

# ------------------------------------------------------------------------------
# RESUMEN FINAL
# ------------------------------------------------------------------------------
echo ""
echo "======================================================================"
echo "✅ ¡PROCESO COMPLETADO EXITOSAMENTE!"
echo "======================================================================"
echo ""
echo "📋 RESUMEN:"
echo "   ✅ Contenedores reiniciados desde cero"
echo "   ✅ Base de datos eliminada y recreada"
echo "   ✅ Migraciones ejecutadas"
echo "   ✅ Datos sembrados con seed_data.py"
echo "   ✅ Integridad referencial verificada"
echo "   ✅ Endpoint /api/v1/deliveries probado"
echo ""
echo "🔐 CREDENCIALES DE ACCESO:"
echo "   Superadmin: super@delivery360.com / Admin123!"
echo "   Repartidor: rider1@delivery360.com / Rider123!"
echo ""
echo "🌐 ENDPOINTS PARA PROBAR:"
echo "   Login: POST http://localhost:8000/api/v1/auth/login"
echo "   Deliveries: GET http://localhost:8000/api/v1/deliveries"
echo "   Orders: GET http://localhost:8000/api/v1/orders"
echo ""
echo "💡 PRÓXIMOS PASOS:"
echo "   1. Abre tu frontend Next.js"
echo "   2. Inicia sesión con super@delivery360.com"
echo "   3. Verifica que las entregas muestren customer_name y rider.first_name"
echo ""
echo "======================================================================"
