#!/bin/bash
# ============================================
# Script de Corrección del ENUM payoutstatus
# ============================================
# Este script verifica y corrige el tipo ENUM payoutstatus en la base de datos.
# Úsalo cuando la migración 20260818 falla o el seed_data.py reporta errores de enum.
#
# Uso:
#   cd /workspace/backend
#   ./scripts/fix_enum_payoutstatus.sh
# ============================================

set -e

echo "🔍 Verificando el ENUM payoutstatus en la base de datos..."

# Ejecutar script SQL de verificación/corrección
docker compose exec -T db psql -U admin -d delivery360 << 'EOF'
-- Verificar si existe el tipo payoutstatus
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
        
        RAISE NOTICE '✅ Tipo payoutstatus creado exitosamente.';
    ELSE
        RAISE NOTICE 'ℹ️  El tipo payoutstatus YA existe.';
    END IF;
END $$;

-- Mostrar valores actuales
SELECT unnest(enum_range(NULL::payoutstatus)) AS valores_actuales;
EOF

echo ""
echo "✅ Verificación completada."
echo ""
echo "📋 Próximos pasos:"
echo "   1. Si ves los 6 valores en español (PENDIENTE, APROBADO, etc.), todo está correcto."
echo "   2. Ejecuta nuevamente el seed data:"
echo "      docker compose exec backend python -m scripts.seed_data"
echo ""
