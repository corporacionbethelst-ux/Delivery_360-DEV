# 🚀 SOLUCIÓN DE BLOQUEO DE MIGRACIÓN - FASE 7 (Delivery360)

## 🔍 DIAGNÓSTICO DEL PROBLEMA

**Error Original:** `asyncpg.exceptions.DuplicateObjectError: type "transactiontype_fase7" already exists`

**Causa Raíz:** Ejecuciones parciales anteriores dejaron los tipos ENUM creados en PostgreSQL, pero Alembic no los registró en su tabla `alembic_version`. La DB está en estado inconsistente.

---

## ✅ PASO 1: Script de Migración Corregido

El archivo `backend/alembic/versions/20260817_fase7_wallets_payouts.py` ha sido modificado para ser **IDEMPOTENTE**:

### Cambios Clave Implementados:

1. **ENUMs idempotentes con SQL crudo:**
   - Se usa `op.execute()` con bloques `DO $$ BEGIN ... END $$`
   - Verifica existencia con `IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '...')`
   - Solo crea si no existe

2. **Columnas con `sa.Enum()` inline:**
   - Las columnas que usan ENUM ahora referencian directamente `sa.Enum(..., name='...')`
   - No depende de variables Python que podrían fallar

3. **Importaciones limpias:**
   ```python
   from alembic import op
   import sqlalchemy as sa
   import uuid
   ```

---

## 🧹 PASO 2: Limpieza de Objetos Huérfanos (SQL)

**⚠️ ADVERTENCIA:** Este script elimina SOLO objetos de la Fase 7. NO afecta datos de Fases 1-6.

Ejecuta esto vía `psql` dentro del contenedor de PostgreSQL:

```bash
docker compose exec db psql -U admin -d delivery360 << 'EOF'
-- =====================================================
-- LIMPIEZA DE OBJETOS HUÉRFANOS FASE 7
-- =====================================================

-- 1. Eliminar tablas de Fase 7 (si existen)
DROP TABLE IF EXISTS payout_requests CASCADE;
DROP TABLE IF EXISTS financial_transactions CASCADE;
DROP TABLE IF EXISTS rider_wallets CASCADE;

-- 2. Eliminar ENUMs huérfanos de Fase 7 (si existen)
DROP TYPE IF EXISTS payoutstatus_fase7;
DROP TYPE IF EXISTS transactionstatus_fase7;
DROP TYPE IF EXISTS transactiontype_fase7;

-- 3. Verificar limpieza
SELECT 'Tablas existentes:' AS info;
\dt

SELECT 'Tipos ENUM existentes:' AS info;
SELECT typname FROM pg_type WHERE typtype = 'e' ORDER BY typname;
EOF
```

---

## 🔄 PASO 3: Sincronización de Alembic

Ejecuta estos comandos en orden estricto desde `/workspace/backend`:

```bash
# ============================================
# COMANDOS DE SINCRONIZACIÓN
# ============================================

cd /workspace/backend

# A) Limpiar caché de Python (opcional pero recomendado)
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true

# B) Resetear el marcador de Alembic a la versión ANTERIOR (20260816)
# Esto le dice a Alembic: "La DB está limpia hasta esta migración"
alembic stamp 20260816

# C) Ejecutar la migración corregida (ahora es idempotente)
alembic upgrade head

# D) Verificar que la migración se registró correctamente
alembic current
```

**Salida esperada de `alembic current`:**
```
20260817 (head)
```

---

## ✔️ PASO 4: Verificación Post-Fix

### Opción A: Verificación vía SQL

```bash
docker compose exec db psql -U admin -d delivery360 << 'EOF'
-- Verificar que las tablas de Fase 7 existen
SELECT 
    table_name, 
    table_schema 
FROM information_schema.tables 
WHERE table_name IN ('rider_wallets', 'financial_transactions', 'payout_requests')
ORDER BY table_name;

-- Verificar estructura de rider_wallets
\d rider_wallets

-- Verificar que un rider tiene wallet inicializada (ejemplo con primer rider)
SELECT 
    rw.id AS wallet_id,
    rw.rider_id,
    rw.balance_cents,
    rw.balance_cents::numeric / 100 AS balance_usd,
    rw.currency,
    rw.is_active,
    r.name AS rider_name
FROM rider_wallets rw
JOIN riders r ON r.id = rw.rider_id
LIMIT 5;
EOF
```

### Opción B: Verificación vía API (curl)

```bash
# Obtener saldo de wallet de un rider (reemplaza {rider_id} con un ID real)
curl -X GET "http://localhost:8000/api/v1/wallet/rider/{rider_id}/balance" \
  -H "Authorization: Bearer TU_TOKEN_ADMIN" \
  -H "Content-Type: application/json"

# Obtener historial de transacciones
curl -X GET "http://localhost:8000/api/v1/wallet/rider/{rider_id}/transactions?limit=10" \
  -H "Authorization: Bearer TU_TOKEN_ADMIN" \
  -H "Content-Type: application/json"
```

---

## 📋 RESUMEN DE COMANDOS (COPY-PASTE RÁPIDO)

```bash
# === 1. LIMPIAR DB ===
docker compose exec db psql -U admin -d delivery360 -c "DROP TABLE IF EXISTS payout_requests CASCADE; DROP TABLE IF EXISTS financial_transactions CASCADE; DROP TABLE IF EXISTS rider_wallets CASCADE; DROP TYPE IF EXISTS payoutstatus_fase7; DROP TYPE IF EXISTS transactionstatus_fase7; DROP TYPE IF EXISTS transactiontype_fase7;"

# === 2. RESETEAR ALEMBIC ===
cd /workspace/backend
alembic stamp 20260816

# === 3. EJECUTAR MIGRACIÓN ===
alembic upgrade head

# === 4. VERIFICAR ===
alembic current
docker compose exec db psql -U admin -d delivery360 -c "\dt rider_wallets"
```

---

## 🎯 PRÓXIMOS PASOS (Post-Desbloqueo)

Una vez confirmada la migración exitosa:

1. **Inicializar wallets para riders existentes:**
   ```python
   # Script en backend/scripts/init_rider_wallets.py
   # Crea una wallet con balance_cents=0 para cada rider sin wallet
   ```

2. **Integración Stripe Connect:**
   - Configurar webhooks en `backend/app/api/v1/stripe_webhooks.py`
   - Implementar `PayoutService.process_stripe_payout()`

3. **Frontend Wallet Rider:**
   - Componente React para mostrar saldo y historial
   - Formulario de solicitud de retiro

4. **Fase 8: Mapas & Tracking:**
   - Migrar de Leaflet a Google Maps Platform
   - Implementar WebSockets para tracking en tiempo real

---

## 🛡️ SEGURIDAD FINANCIERA (RECORDATORIO)

- ✅ **Centavos vs Decimales:** Todos los montos en `INTEGER` (centavos)
- ✅ **Idempotencia:** Columna `idempotency_key` única en `financial_transactions`
- ✅ **Inmutabilidad:** Las transacciones nunca se modifican, solo se crean
- ✅ **Auditoría:** `balance_after_cents` snapshot en cada transacción
- ✅ **Foreign Keys:** `ON DELETE CASCADE` para integridad referencial

---

## 📁 ARCHIVOS CREADOS/MODIFICADOS

| Archivo | Estado | Descripción |
|---------|--------|-------------|
| `alembic/versions/20260817_fase7_wallets_payouts.py` | ✅ MODIFICADO | Migración idempotente corregida |
| `alembic.ini` | ✅ MODIFICADO | Connection string actualizado a delivery360 |
| `scripts/cleanup_fase7_orphans.sql` | ✅ CREADO | Script SQL de limpieza |
| `scripts/verify_fase7_migration.sql` | ✅ CREADO | Script SQL de verificación |
| `scripts/recover_fase7.sh` | ✅ CREADO | Script bash automatizado |
| `SOLUCION_BLOQUEO_FASE7.md` | ✅ CREADO | Documentación completa |

---

**Documento generado:** 2026
**Autor:** Delivery360 Engineering Team
**Fase:** 7 (Pagos & Wallets)
**Estado:** ✅ LISTO PARA EJECUCIÓN
