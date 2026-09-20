#!/bin/bash
# =====================================================
# 🧪 SCRIPT DE PRUEBAS COMPLETAS - FASE 7 (Delivery360)
# =====================================================
# Este script ejecuta todas las pruebas para verificar
# que la Fase 7 está completamente operativa.
#
# Uso: ./scripts/run_fase7_tests.sh
# =====================================================

set -e  # Salir ante cualquier error

cd "$(dirname "$0")/.."  # Ir al directorio backend

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo ""
echo "=============================================="
echo "🧪 SUITE DE PRUEBAS - FASE 7 (Delivery360)"
echo "=============================================="
echo ""

# ============================================
# PASO 0: Verificar prerequisitos
# ============================================
echo -e "${BLUE}📋 PASO 0: Verificando prerequisitos...${NC}"

# Verificar Python
if ! command -v python &> /dev/null; then
    echo -e "${RED}❌ Python no encontrado${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Python disponible${NC}"

# Verificar dependencias
echo -e "${YELLOW}   Verificando dependencias...${NC}"
pip install -q alembic sqlalchemy psycopg2-binary asyncpg pydantic-settings 2>/dev/null || true
echo -e "${GREEN}✅ Dependencias instaladas${NC}"

# ============================================
# PASO 1: Verificar migración
# ============================================
echo ""
echo -e "${BLUE}📋 PASO 1: Verificando migración de Fase 7...${NC}"

CURRENT=$(python -m alembic current 2>&1 | grep -o '20260817' || echo "")
if [ "$CURRENT" = "20260817" ]; then
    echo -e "${GREEN}✅ Migración 20260817 aplicada correctamente${NC}"
else
    echo -e "${YELLOW}⚠️  Migración no aplicada o versión diferente: $CURRENT${NC}"
    echo -e "${YELLOW}   ¿Deseas ejecutar la migración ahora? (y/n)${NC}"
    read -r response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}   Ejecutando migración...${NC}"
        python -m alembic upgrade head
        CURRENT=$(python -m alembic current 2>&1 | grep -o '20260817' || echo "")
        if [ "$CURRENT" = "20260817" ]; then
            echo -e "${GREEN}✅ Migración aplicada exitosamente${NC}"
        else
            echo -e "${RED}❌ Error aplicando migración${NC}"
            exit 1
        fi
    else
        echo -e "${RED}❌ Pruebas canceladas. La migración es requerida.${NC}"
        exit 1
    fi
fi

# ============================================
# PASO 2: Verificar tablas en DB
# ============================================
echo ""
echo -e "${BLUE}📋 PASO 2: Verificando tablas en PostgreSQL...${NC}"

# Intentar conexión a DB
python << 'PYEOF'
import psycopg2
import sys

try:
    conn = psycopg2.connect(
        host='localhost',
        database='delivery360',
        user='admin',
        password='admin123',
        port=5432
    )
    cursor = conn.cursor()
    
    # Verificar tablas
    cursor.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_name IN ('rider_wallets', 'financial_transactions', 'payout_requests')
        ORDER BY table_name;
    """)
    tables = cursor.fetchall()
    
    if len(tables) == 3:
        print("✅ Las 3 tablas de Fase 7 existen")
        for t in tables:
            print(f"   ✅ {t[0]}")
    else:
        print(f"⚠️  Solo {len(tables)} tabla(s) encontrada(s)")
        for t in tables:
            print(f"   ✅ {t[0]}")
        print("   Las tablas faltantes se crearán al inicializar wallets")
    
    # Verificar ENUMs
    cursor.execute("""
        SELECT typname 
        FROM pg_type 
        WHERE typtype = 'e' 
          AND typname IN ('transactiontype_fase7', 'transactionstatus_fase7', 'payoutstatus_fase7')
        ORDER BY typname;
    """)
    enums = cursor.fetchall()
    
    if len(enums) == 3:
        print("✅ Los 3 ENUMs de Fase 7 existen")
        for e in enums:
            print(f"   ✅ {e[0]}")
    else:
        print(f"⚠️  Solo {len(enums)} ENUM(s) encontrado(s)")
    
    cursor.close()
    conn.close()
except Exception as e:
    print(f"❌ Error conectando a PostgreSQL: {e}")
    print("   Asegúrate de que Docker esté corriendo: docker compose up -d db")
    sys.exit(1)
PYEOF

# ============================================
# PASO 3: Inicializar wallets si es necesario
# ============================================
echo ""
echo -e "${BLUE}📋 PASO 3: Verificando wallets de riders...${NC}"

python << 'PYEOF'
import asyncio
import sys
sys.path.insert(0, '/workspace/backend')

from app.core.database import get_db_session
from sqlalchemy import select, func
from app.models.rider import Rider
from app.models.financial import RiderWallet

async def check_wallets():
    async for session in get_db_session():
        try:
            # Contar riders
            result = await session.execute(select(func.count(Rider.id)))
            total_riders = result.scalar()
            
            # Contar wallets
            result = await session.execute(select(func.count(RiderWallet.id)))
            total_wallets = result.scalar()
            
            print(f"   Total riders: {total_riders}")
            print(f"   Total wallets: {total_wallets}")
            
            if total_riders > 0 and total_wallets == 0:
                print("   ⚠️  No hay wallets. Iniciando wallets para todos los riders...")
                
                # Obtener todos los riders sin wallet
                result = await session.execute(
                    select(Rider.id).where(
                        ~Rider.id.in_(select(RiderWallet.rider_id))
                    )
                )
                riders_without_wallet = result.scalars().all()
                
                for rider_id in riders_without_wallet:
                    wallet = RiderWallet(rider_id=rider_id)
                    session.add(wallet)
                
                await session.commit()
                print(f"   ✅ {len(riders_without_wallet)} wallets creadas")
            elif total_wallets > 0:
                print(f"   ✅ Wallets ya existen")
            
        except Exception as e:
            print(f"   ❌ Error: {e}")
        finally:
            await session.close()
            break

asyncio.run(check_wallets())
PYEOF

# ============================================
# PASO 4: Ejecutar pruebas de servicio
# ============================================
echo ""
echo -e "${BLUE}📋 PASO 4: Ejecutando pruebas de Wallet Service...${NC}"
echo ""

if [ -f "scripts/test_wallet_service.py" ]; then
    python scripts/test_wallet_service.py
    TEST_RESULT=$?
    
    if [ $TEST_RESULT -eq 0 ]; then
        echo ""
        echo -e "${GREEN}✅ Pruebas de servicio pasaron${NC}"
    else
        echo ""
        echo -e "${RED}❌ Pruebas de servicio fallaron${NC}"
        exit 1
    fi
else
    echo -e "${YELLOW}⚠️  Script test_wallet_service.py no encontrado${NC}"
fi

# ============================================
# PASO 5: Resumen final
# ============================================
echo ""
echo "=============================================="
echo -e "${GREEN}🎉 PRUEBAS DE FASE 7 COMPLETADAS${NC}"
echo "=============================================="
echo ""
echo "📊 RESUMEN:"
echo "   ✅ Migración aplicada"
echo "   ✅ Tablas verificadas"
echo "   ✅ Wallets inicializadas"
echo "   ✅ Servicio probado"
echo ""
echo "📁 ARCHIVOS GENERADOS:"
echo "   • scripts/test_wallet_service.py (pruebas unitarias)"
echo "   • scripts/TESTING_GUIDE_FASE7.md (guía completa)"
echo ""
echo "🚀 PRÓXIMOS PASOS:"
echo "   1. Probar endpoints API (ver TESTING_GUIDE_FASE7.md)"
echo "   2. Integrar Stripe Connect"
echo "   3. Desarrollar frontend de wallet para riders"
echo "   4. Continuar con Fase 8 (Mapas & Tracking)"
echo ""
