#!/bin/bash
# =====================================================
# SCRIPT DE RECUPERACIÓN - FASE 7 (Delivery360)
# =====================================================
# Este script automatiza el proceso de limpieza y 
# re-ejecución de la migración Fase 7
#
# Uso: ./scripts/recover_fase7.sh
# =====================================================

set -e  # Salir ante cualquier error

echo "🚀 INICIANDO RECUPERACIÓN FASE 7"
echo "=========================================="

cd "$(dirname "$0")/.."  # Ir al directorio backend

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Paso 1: Limpieza de objetos huérfanos
echo -e "${YELLOW}🧹 PASO 1: Limpiando objetos huérfanos de Fase 7...${NC}"
docker compose exec -T db psql -U admin -d delivery360 << 'EOF'
BEGIN;
DROP TABLE IF EXISTS payout_requests CASCADE;
DROP TABLE IF EXISTS financial_transactions CASCADE;
DROP TABLE IF EXISTS rider_wallets CASCADE;
DROP TYPE IF EXISTS payoutstatus_fase7;
DROP TYPE IF EXISTS transactionstatus_fase7;
DROP TYPE IF EXISTS transactiontype_fase7;
COMMIT;
EOF
echo -e "${GREEN}✅ Limpieza completada${NC}"

# Paso 2: Resetear marcador de Alembic
echo -e "${YELLOW}🔄 PASO 2: Reseteando marcador de Alembic a 20260816...${NC}"
alembic stamp 20260816
echo -e "${GREEN}✅ Marcador reseteado${NC}"

# Paso 3: Ejecutar migración
echo -e "${YELLOW}⬆️  PASO 3: Ejecutando migración Fase 7...${NC}"
alembic upgrade head
echo -e "${GREEN}✅ Migración ejecutada${NC}"

# Paso 4: Verificación
echo -e "${YELLOW}✔️  PASO 4: Verificando migración...${NC}"
CURRENT=$(alembic current | grep -o '[a-f0-9]\+' | head -1)
if [ "$CURRENT" = "20260817" ]; then
    echo -e "${GREEN}✅ VERIFICACIÓN EXITOSA: Migración 20260817 aplicada correctamente${NC}"
else
    echo -e "${RED}❌ VERIFICACIÓN FALLIDA: Migración actual es $CURRENT, se esperaba 20260817${NC}"
    exit 1
fi

# Paso 5: Verificar tablas en DB
echo -e "${YELLOW}📊 PASO 5: Verificando tablas en PostgreSQL...${NC}"
docker compose exec -T db psql -U admin -d delivery360 -c "\dt rider_wallets" > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Tabla rider_wallets existe${NC}"
else
    echo -e "${RED}❌ Tabla rider_wallets NO existe${NC}"
    exit 1
fi

echo ""
echo "=========================================="
echo -e "${GREEN}🎉 RECUPERACIÓN FASE 7 COMPLETADA${NC}"
echo "=========================================="
echo ""
echo "Próximos pasos recomendados:"
echo "1. Inicializar wallets para riders existentes"
echo "2. Probar endpoints de wallet API"
echo "3. Continuar con integración Stripe Connect"
echo ""
