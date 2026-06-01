#!/bin/bash
# ============================================================
# DELIVERY360 - COMANDOS DE VALIDACIÓN POST-REPARACIÓN
# ============================================================

echo "🔧 DELIVERY360 - Validación de Reparación"
echo "=========================================="

# 1. RE-SEMEBRAR DATOS (Opcional, si necesitas limpiar)
echo ""
echo "📦 PASO 1: Re-sembrar datos (opcional)"
echo "----------------------------------------"
echo "Si necesitas limpiar la BD primero, ejecuta:"
echo "  python /workspace/backend/scripts/seed_data.py"
echo ""

# 2. PROBAR LOGIN SUPERADMIN
echo "🔐 PASO 2: Probar login de superadmin"
echo "---------------------------------------"
echo "Ejecuta este comando y guarda el access_token:"
echo ""
echo 'curl -X POST "http://localhost:8000/api/v1/auth/login" \'
echo '  -H "Content-Type: application/x-www-form-urlencoded" \'
echo '  -d "username=super@delivery360.com&password=Admin123!" | jq'
echo ""
echo "⚠️  Copia el valor de 'access_token' del resultado"
echo ""

# 3. PROBAR ENDPOINT DELIVERIES
echo "📋 PASO 3: Probar endpoint GET /api/v1/deliveries"
echo "---------------------------------------------------"
echo "Reemplaza <TOKEN> con el token obtenido arriba:"
echo ""
echo 'curl -H "Authorization: Bearer <TOKEN>" \'
echo '  "http://localhost:8000/api/v1/deliveries?limit=5" | jq'
echo ""
echo "✅ RESULTADO ESPERADO:"
echo "  - customer_name: Debe mostrar nombres como 'Juan Pérez', 'María Rodríguez'"
echo "  - rider.first_name: Debe mostrar 'Repartidor' o nombres reales"
echo "  - NO debe mostrar 'Desconocido' ni 'Sin Nombre'"
echo ""

# 4. PROBAR LOGIN REPARTIDOR
echo "🚴 PASO 4: Probar login de repartidor"
echo "--------------------------------------"
echo 'curl -X POST "http://localhost:8000/api/v1/auth/login" \'
echo '  -H "Content-Type: application/x-www-form-urlencoded" \'
echo '  -d "username=rider1@delivery360.com&password=Rider123!" | jq'
echo ""
echo "⚠️  Si falla con 'cuenta pendiente de aprobación', el rider no está ACTIVO"
echo "   Ejecuta el seed_data.py nuevamente para crear riders ACTIVOS"
echo ""

# 5. COMANDO CURL ROBUSTO CON MANEJO DE ERRORES
echo "🛠️  PASO 5: Script completo de prueba con manejo de errores"
echo "------------------------------------------------------------"
cat << 'SCRIPT'
#!/bin/bash
# Guardar como test_api.sh y ejecutar

BASE_URL="http://localhost:8000"

echo "🔐 Obteniendo token..."
RESPONSE=$(curl -s -X POST "${BASE_URL}/api/v1/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=super@delivery360.com&password=Admin123!")

# Verificar si hay error en el login
if echo "$RESPONSE" | grep -q "detail"; then
    echo "❌ Error en login: $RESPONSE"
    exit 1
fi

# Extraer token
TOKEN=$(echo "$RESPONSE" | jq -r '.access_token')

if [ "$TOKEN" == "null" ] || [ -z "$TOKEN" ]; then
    echo "❌ No se pudo extraer el token"
    echo "Respuesta: $RESPONSE"
    exit 1
fi

echo "✅ Token obtenido: ${TOKEN:0:20}..."

# Probar endpoint deliveries
echo ""
echo "📋 Probando GET /api/v1/deliveries..."
DELIVERIES=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "${BASE_URL}/api/v1/deliveries?limit=3")

echo "$DELIVERIES" | jq '.'

# Verificar campos críticos
echo ""
echo "🔍 Verificando integridad de datos..."
NULL_CUSTOMER=$(echo "$DELIVERIES" | jq '[.[] | select(.customer_name == "Desconocido" or .customer_name == null)] | length')
NULL_RIDER=$(echo "$DELIVERIES" | jq '[.[] | select(.rider.first_name == "Sin Nombre" or .rider.first_name == null)] | length')

if [ "$NULL_CUSTOMER" -gt 0 ]; then
    echo "⚠️  ALERTA: $NULL_CUSTOMER entregas con customer_name nulo o 'Desconocido'"
else
    echo "✅ customer_name: Todos los valores son válidos"
fi

if [ "$NULL_RIDER" -gt 0 ]; then
    echo "⚠️  ALERTA: $NULL_RIDER entregas con rider.first_name nulo o 'Sin Nombre'"
else
    echo "✅ rider.first_name: Todos los valores son válidos"
fi

echo ""
echo "✅ Prueba completada!"
SCRIPT
echo ""

# 6. VERIFICACIÓN SQL DIRECTA (si tienes acceso a psql)
echo "🗄️  PASO 6: Verificación SQL directa (si tienes acceso a la BD)"
echo "----------------------------------------------------------------"
echo "Si puedes acceder a PostgreSQL, ejecuta:"
echo ""
echo "psql -h localhost -U admin -d delivery360 -f /workspace/SQL_VERIFICATION.sql"
echo ""
echo "O copia las consultas del archivo SQL_VERIFICATION.sql"
echo ""


# 7. Limpia la caché de Python
echo "🗄️  Limpia la caché de Python dentro del contenedor para evitar que cargue versiones viejas"
echo "----------------------------------------------------------------"
docker compose exec backend find . -type d -name __pycache__ -exec rm -rf {} +
docker compose exec backend find . -name "*.pyc" -delete



echo "=========================================="
echo "✅ FIN DE LA GUÍA DE VALIDACIÓN"
echo "=========================================="