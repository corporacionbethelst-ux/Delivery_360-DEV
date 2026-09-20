# 🧪 CÓMO PROBAR LA FASE 7 - Delivery360

## RESUMEN RÁPIDO (5 MINUTOS)

Si quieres probar **inmediatamente** todo lo implementado en la Fase 7, ejecuta:

```bash
cd /workspace/backend
./scripts/run_fase7_tests.sh
```

Este script automatiza todas las verificaciones y pruebas.

---

## 📋 GUÍA PASO A PASO

### PRERREQUISITOS

1. **Docker corriendo:**
   ```bash
   docker compose up -d
   ```

2. **Base de datos con datos seed (Fases 1-6):**
   ```bash
   cd /workspace/backend
   python scripts/seed_data.py
   ```

---

### PASO 1: Verificar Migración

```bash
cd /workspace/backend
python -m alembic current
```

**Salida esperada:** `20260817 (head)`

Si no muestra esto, ejecuta:
```bash
python -m alembic upgrade head
```

---

### PASO 2: Verificar Tablas en PostgreSQL

```bash
docker compose exec db psql -U admin -d delivery360 << 'EOF'
-- Verificar tablas de Fase 7
SELECT table_name 
FROM information_schema.tables 
WHERE table_name IN ('rider_wallets', 'financial_transactions', 'payout_requests')
ORDER BY table_name;
EOF
```

**Salida esperada:** Las 3 tablas deben estar listadas.

---

### PASO 3: Inicializar Wallets para Riders

Si aún no hay wallets creadas:

```bash
docker compose exec db psql -U admin -d delivery360 << 'EOF'
-- Crear wallets para todos los riders sin wallet
INSERT INTO rider_wallets (rider_id, balance_cents, currency, is_active)
SELECT 
    r.id,
    0,
    'USD',
    true
FROM riders r
WHERE r.id NOT IN (SELECT rider_id FROM rider_wallets)
ON CONFLICT (rider_id) DO NOTHING;

-- Verificar
SELECT COUNT(*) AS total_wallets FROM rider_wallets;
SELECT COUNT(*) AS total_riders FROM riders;
EOF
```

---

### PASO 4: Ejecutar Pruebas Automatizadas

#### Opción A: Script Bash Completo
```bash
cd /workspace/backend
./scripts/run_fase7_tests.sh
```

#### Opción B: Script Python de Servicio
```bash
cd /workspace/backend
python scripts/test_wallet_service.py
```

**Lo que prueba este script:**
- ✅ Obtener/Crear wallet
- ✅ Crédito por entrega ($5.50)
- ✅ Débito por penalización ($2.00)
- ✅ Solicitud de retiro ($3.00)
- ✅ Historial de transacciones
- ✅ Saldo actual
- ✅ Idempotencia (misma key no duplica)

---

### PASO 5: Probar Endpoints API (Opcional)

1. **Iniciar backend:**
   ```bash
   cd /workspace/backend
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
   ```

2. **Obtener token de admin:**
   ```bash
   curl -X POST "http://localhost:8000/api/v1/auth/login" \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "username=admin@delivery360.com&password=TU_PASSWORD"
   ```
   
   Guarda el `access_token` de la respuesta.

3. **Probar endpoints:**

   **Obtener saldo:**
   ```bash
   RIDER_ID="uuid-del-rider"  # Reemplazar con UUID real
   TOKEN="tu-access-token"
   
   curl -X GET "http://localhost:8000/api/v1/wallet/rider/${RIDER_ID}/balance" \
     -H "Authorization: Bearer ${TOKEN}" | jq
   ```

   **Historial de transacciones:**
   ```bash
   curl -X GET "http://localhost:8000/api/v1/wallet/rider/${RIDER_ID}/transactions?limit=10" \
     -H "Authorization: Bearer ${TOKEN}" | jq
   ```

   **Solicitar retiro:**
   ```bash
   curl -X POST "http://localhost:8000/api/v1/wallet/rider/${RIDER_ID}/payout-request" \
     -H "Authorization: Bearer ${TOKEN}" \
     -H "Content-Type: application/json" \
     -d '{"amount_cents": 300, "payout_method": "bank_transfer"}' | jq
   ```

---

### PASO 6: Verificación Directa en DB

```bash
docker compose exec db psql -U admin -d delivery360 << 'EOF'
-- Ver wallets y balances
SELECT 
    rw.id AS wallet_id,
    r.name AS rider_name,
    rw.balance_cents,
    rw.balance_cents::numeric / 100 AS balance_usd,
    rw.is_active
FROM rider_wallets rw
JOIN riders r ON r.id = rw.rider_id
ORDER BY rw.created_at DESC
LIMIT 10;

-- Ver transacciones recientes
SELECT 
    ft.transaction_type,
    ft.amount_cents::numeric / 100 AS amount_usd,
    ft.status,
    ft.balance_after_cents::numeric / 100 AS balance_after_usd,
    ft.description,
    ft.created_at
FROM financial_transactions ft
ORDER BY ft.created_at DESC
LIMIT 10;
EOF
```

---

## ✅ CHECKLIST DE VERIFICACIÓN

Marca cada ítem completado:

- [ ] Docker está corriendo (`docker compose ps`)
- [ ] Migración `20260817` aplicada (`alembic current`)
- [ ] Tablas `rider_wallets`, `financial_transactions`, `payout_requests` existen
- [ ] ENUMs creados (`transactiontype_fase7`, etc.)
- [ ] Wallets inicializadas para riders
- [ ] Prueba de crédito funciona
- [ ] Prueba de débito funciona
- [ ] Prueba de retiro funciona
- [ ] Historial muestra transacciones
- [ ] Balances son correctos
- [ ] Idempotencia previene duplicados

---

## 🐛 SOLUCIÓN DE PROBLEMAS

### Error: "Connection refused" a PostgreSQL
```bash
docker compose up -d db
sleep 10
```

### Error: "No module named 'psycopg2'"
```bash
pip install psycopg2-binary
```

### Error: "DuplicateObjectError: type already exists"
```bash
# Limpiar objetos huérfanos
docker compose exec db psql -U admin -d delivery360 << 'EOF'
DROP TABLE IF EXISTS payout_requests CASCADE;
DROP TABLE IF EXISTS financial_transactions CASCADE;
DROP TABLE IF EXISTS rider_wallets CASCADE;
DROP TYPE IF EXISTS payoutstatus_fase7;
DROP TYPE IF EXISTS transactionstatus_fase7;
DROP TYPE IF EXISTS transactiontype_fase7;
EOF

# Resetear Alembic
cd /workspace/backend
python -m alembic stamp 20260816

# Re-ejecutar migración
python -m alembic upgrade head
```

### Error: "No riders found"
```bash
# Ejecutar seed data
cd /workspace/backend
python scripts/seed_data.py
```

---

## 📊 RESULTADOS ESPERADOS

Después de ejecutar las pruebas, deberías ver:

```
🎉 TODAS LAS PRUEBAS PASARON EXITOSAMENTE

📊 RESUMEN:
   • Rider: Juan Pérez
   • Wallet ID: xxx-xxx-xxx
   • Balance inicial: $0.00 USD
   • Balance final: $3.50 USD
   • Transacciones creadas: 3
   • Solicitudes de retiro: 1 ($3.00 USD)

✅ Fase 7 operativa y verificada correctamente
```

---

## 🚀 PRÓXIMOS PASOS

Una vez verificada la Fase 7:

1. **Integración Stripe Connect**
   - Configurar webhooks
   - Implementar payouts reales

2. **Frontend Wallet Rider**
   - Componente React para mostrar saldo
   - Formulario de solicitud de retiro
   - Historial de transacciones

3. **Fase 8: Mapas & Tracking**
   - Migrar a Google Maps Platform
   - Implementar WebSockets para tracking en tiempo real

---

## 📁 ARCHIVOS DE PRUEBA CREADOS

| Archivo | Descripción |
|---------|-------------|
| `scripts/test_wallet_service.py` | Pruebas unitarias del servicio |
| `scripts/run_fase7_tests.sh` | Script bash de pruebas completas |
| `scripts/TESTING_GUIDE_FASE7.md` | Guía detallada de pruebas |
| `scripts/cleanup_fase7_orphans.sql` | Limpieza de objetos huérfanos |
| `scripts/verify_fase7_migration.sql` | Verificación post-migración |
| `scripts/recover_fase7.sh` | Recuperación automática |

---

**Documento generado:** 2026  
**Autor:** Delivery360 Engineering Team  
**Fase:** 7 (Wallets & Pagos)  
**Estado:** ✅ LISTO PARA EJECUCIÓN
