# 🧪 GUÍA DE PRUEBAS - FASE 7 (Delivery360)

## ✅ OBJETIVO
Verificar que la migración de Fase 7 (Wallets & Pagos) está funcionando correctamente y todos los componentes están operativos.

---

## 📋 PRERREQUISITOS

Antes de comenzar, asegúrate de:
1. ✅ Tener Docker corriendo (`docker compose up -d`)
2. ✅ Haber ejecutado la migración `alembic upgrade head` exitosamente
3. ✅ Tener datos seed de riders (Fases 1-6)

---

## 🔧 PASO 1: VERIFICAR MIGRACIÓN

### 1.1 Verificar estado de Alembic
```bash
cd /workspace/backend
python -m alembic current
```
**Salida esperada:** `20260817 (head)`

### 1.2 Verificar tablas en PostgreSQL
```bash
docker compose exec db psql -U admin -d delivery360 -c "\dt rider_wallets"
docker compose exec db psql -U admin -d delivery360 -c "\dt financial_transactions"
docker compose exec db psql -U admin -d delivery360 -c "\dt payout_requests"
```
**Salida esperada:** Las 3 tablas deben existir

### 1.3 Verificar ENUMs
```bash
docker compose exec db psql -U admin -d delivery360 << 'EOF'
SELECT typname AS enum_name
FROM pg_type 
WHERE typtype = 'e' 
  AND typname IN ('transactiontype_fase7', 'transactionstatus_fase7', 'payoutstatus_fase7')
ORDER BY typname;
EOF
```
**Salida esperada:** Los 3 ENUMs deben estar listados

---

## 💰 PASO 2: INICIALIZAR WALLETS DE RIDERS

Si aún no existen wallets para los riders existentes:

### Opción A: Script automático (Recomendado)
```bash
cd /workspace/backend
python scripts/seed_data.py --init-wallets
```

### Opción B: SQL directo
```bash
docker compose exec db psql -U admin -d delivery360 << 'EOF'
-- Insertar wallets para riders sin wallet
INSERT INTO rider_wallets (rider_id, balance_cents, currency, is_active)
SELECT 
    r.id,
    0,  -- balance inicial
    'USD',
    true
FROM riders r
WHERE r.id NOT IN (SELECT rider_id FROM rider_wallets)
ON CONFLICT (rider_id) DO NOTHING;

-- Verificar wallets creadas
SELECT COUNT(*) AS total_wallets FROM rider_wallets;
SELECT COUNT(*) AS total_riders FROM riders;
EOF
```

---

## 🧪 PASO 3: PRUEBAS DE SERVICIO WALLET

### 3.1 Crear script de prueba Python
Crea el archivo `/workspace/backend/scripts/test_wallet_service.py`:

```python
#!/usr/bin/env python
"""
Script de prueba para WalletService (Fase 7)
"""
import asyncio
import sys
sys.path.insert(0, '/workspace/backend')

from app.services.wallet_service import WalletService
from app.core.database import get_db_session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.rider import Rider
from app.models.financial import RiderWallet

async def test_wallet_operations():
    print("🧪 INICIANDO PRUEBAS DE WALLET SERVICE")
    print("=" * 50)
    
    async for session in get_db_session():
        try:
            # Obtener un rider de prueba
            result = await session.execute(select(Rider).limit(1))
            rider = result.scalar_one_or_none()
            
            if not rider:
                print("❌ No hay riders en la DB")
                return
            
            print(f"✅ Rider seleccionado: {rider.name} (ID: {rider.id})")
            
            wallet_service = WalletService(session)
            
            # Prueba 1: Obtener o crear wallet
            print("\n📝 Prueba 1: Obtener/Crear wallet...")
            wallet = await wallet_service.get_or_create_wallet(rider.id)
            print(f"   ✅ Wallet ID: {wallet.id}")
            print(f"   ✅ Balance: ${wallet.balance_cents/100:.2f} USD")
            
            # Prueba 2: Crédito (simular pago de entrega)
            print("\n💰 Prueba 2: Crédito por entrega ($5.50)...")
            amount_cents = 550  # $5.50
            transaction = await wallet_service.credit_wallet(
                wallet_id=wallet.id,
                amount_cents=amount_cents,
                transaction_type='PAGO_ENTREGA',
                description='Pago de entrega #ORD-12345',
                reference_id='ORD-12345'
            )
            print(f"   ✅ Transacción ID: {transaction.id}")
            print(f"   ✅ Nuevo balance: ${transaction.balance_after_cents/100:.2f} USD")
            
            # Prueba 3: Débito (simular penalización)
            print("\n➖ Prueba 3: Débito por penalización ($2.00)...")
            debit_amount = 200  # $2.00
            debit_tx = await wallet_service.debit_wallet(
                wallet_id=wallet.id,
                amount_cents=debit_amount,
                transaction_type='PENALIZACION',
                description='Penalización por entrega tardía',
                reference_id='PEN-001'
            )
            print(f"   ✅ Transacción ID: {debit_tx.id}")
            print(f"   ✅ Nuevo balance: ${debit_tx.balance_after_cents/100:.2f} USD")
            
            # Prueba 4: Solicitar retiro
            print("\n💸 Prueba 4: Solicitar retiro ($3.00)...")
            withdrawal_amount = 300  # $3.00
            payout = await wallet_service.request_payout(
                wallet_id=wallet.id,
                amount_cents=withdrawal_amount,
                payout_method='bank_transfer'
            )
            print(f"   ✅ Payout Request ID: {payout.id}")
            print(f"   ✅ Estado: {payout.status}")
            
            # Prueba 5: Obtener historial
            print("\n📜 Prueba 5: Historial de transacciones...")
            history = await wallet_service.get_transaction_history(wallet.id, limit=10)
            print(f"   ✅ Total transacciones: {len(history)}")
            for tx in history[:3]:
                print(f"      - {tx.transaction_type}: ${tx.amount_cents/100:.2f} ({tx.status})")
            
            # Prueba 6: Saldo actual
            print("\n💵 Prueba 6: Saldo actual...")
            current_wallet = await wallet_service.get_wallet_by_id(wallet.id)
            print(f"   ✅ Balance final: ${current_wallet.balance_cents/100:.2f} USD")
            
            print("\n" + "=" * 50)
            print("🎉 TODAS LAS PRUEBAS PASARON EXITOSAMENTE")
            print("=" * 50)
            
        except Exception as e:
            print(f"\n❌ ERROR EN PRUEBAS: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await session.close()
            break

if __name__ == "__main__":
    asyncio.run(test_wallet_operations())
```

### 3.2 Ejecutar pruebas
```bash
cd /workspace/backend
python scripts/test_wallet_service.py
```

**Salida esperada:**
```
🧪 INICIANDO PRUEBAS DE WALLET SERVICE
==================================================
✅ Rider seleccionado: Juan Pérez (ID: xxx-xxx-xxx)

📝 Prueba 1: Obtener/Crear wallet...
   ✅ Wallet ID: xxx-xxx-xxx
   ✅ Balance: $0.00 USD

💰 Prueba 2: Crédito por entrega ($5.50)...
   ✅ Transacción ID: xxx-xxx-xxx
   ✅ Nuevo balance: $5.50 USD

➖ Prueba 3: Débito por penalización ($2.00)...
   ✅ Transacción ID: xxx-xxx-xxx
   ✅ Nuevo balance: $3.50 USD

💸 Prueba 4: Solicitar retiro ($3.00)...
   ✅ Payout Request ID: xxx-xxx-xxx
   ✅ Estado: PENDING

📜 Prueba 5: Historial de transacciones...
   ✅ Total transacciones: 2
      - PAGO_ENTREGA: $5.50 (COMPLETED)
      - PENALIZACION: $2.00 (COMPLETED)

💵 Prueba 6: Saldo actual...
   ✅ Balance final: $3.50 USD

==================================================
🎉 TODAS LAS PRUEBAS PASARON EXITOSAMENTE
==================================================
```

---

## 🌐 PASO 4: PRUEBAS DE API (Endpoints REST)

### 4.1 Iniciar el backend
```bash
cd /workspace/backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
```

### 4.2 Obtener token de admin (para autenticación)
```bash
# Primero necesitas un usuario admin
# Usa las credenciales de seed data o crea uno
curl -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin@delivery360.com&password=TU_PASSWORD"
```

Guarda el `access_token` de la respuesta.

### 4.3 Probar endpoints de wallet

#### Endpoint 1: Obtener saldo de rider
```bash
RIDER_ID="uuid-del-rider"  # Reemplazar con UUID real
TOKEN="tu-access-token"

curl -X GET "http://localhost:8000/api/v1/wallet/rider/${RIDER_ID}/balance" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" | jq
```

**Respuesta esperada:**
```json
{
  "wallet_id": "xxx-xxx-xxx",
  "rider_id": "xxx-xxx-xxx",
  "balance_cents": 350,
  "balance_usd": 3.50,
  "currency": "USD",
  "is_active": true
}
```

#### Endpoint 2: Historial de transacciones
```bash
curl -X GET "http://localhost:8000/api/v1/wallet/rider/${RIDER_ID}/transactions?limit=10" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" | jq
```

**Respuesta esperada:**
```json
[
  {
    "id": "xxx-xxx-xxx",
    "transaction_type": "PAGO_ENTREGA",
    "amount_cents": 550,
    "description": "Pago de entrega #ORD-12345",
    "status": "COMPLETED",
    "balance_after_cents": 550,
    "created_at": "2026-09-19T..."
  },
  {
    "id": "xxx-xxx-xxx",
    "transaction_type": "PENALIZACION",
    "amount_cents": 200,
    "description": "Penalización por entrega tardía",
    "status": "COMPLETED",
    "balance_after_cents": 350,
    "created_at": "2026-09-19T..."
  }
]
```

#### Endpoint 3: Solicitar retiro
```bash
curl -X POST "http://localhost:8000/api/v1/wallet/rider/${RIDER_ID}/payout-request" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "amount_cents": 300,
    "payout_method": "bank_transfer",
    "bank_account": "1234567890"
  }' | jq
```

**Respuesta esperada:**
```json
{
  "id": "xxx-xxx-xxx",
  "wallet_id": "xxx-xxx-xxx",
  "amount_cents": 300,
  "status": "PENDING",
  "payout_method": "bank_transfer",
  "created_at": "2026-09-19T..."
}
```

---

## 🗄️ PASO 5: VERIFICACIÓN DIRECTA EN DB

### 5.1 Verificar wallets y balances
```bash
docker compose exec db psql -U admin -d delivery360 << 'EOF'
SELECT 
    rw.id AS wallet_id,
    r.name AS rider_name,
    rw.balance_cents,
    rw.balance_cents::numeric / 100 AS balance_usd,
    rw.is_active,
    rw.created_at
FROM rider_wallets rw
JOIN riders r ON r.id = rw.rider_id
ORDER BY rw.created_at DESC
LIMIT 10;
EOF
```

### 5.2 Verificar transacciones recientes
```bash
docker compose exec db psql -U admin -d delivery360 << 'EOF'
SELECT 
    ft.id AS tx_id,
    ft.transaction_type,
    ft.amount_cents,
    ft.amount_cents::numeric / 100 AS amount_usd,
    ft.status,
    ft.balance_after_cents::numeric / 100 AS balance_after_usd,
    ft.description,
    ft.created_at
FROM financial_transactions ft
JOIN rider_wallets rw ON ft.wallet_id = rw.id
JOIN riders r ON rw.rider_id = r.id
ORDER BY ft.created_at DESC
LIMIT 10;
EOF
```

### 5.3 Verificar solicitudes de retiro
```bash
docker compose exec db psql -U admin -d delivery360 << 'EOF'
SELECT 
    pr.id AS payout_id,
    r.name AS rider_name,
    pr.amount_cents,
    pr.amount_cents::numeric / 100 AS amount_usd,
    pr.status,
    pr.payout_method,
    pr.created_at
FROM payout_requests pr
JOIN rider_wallets rw ON pr.wallet_id = rw.id
JOIN riders r ON rw.rider_id = r.id
ORDER BY pr.created_at DESC
LIMIT 10;
EOF
```

---

## ✅ CHECKLIST FINAL

Marca cada ítem completado:

- [ ] Migración `20260817` aplicada exitosamente (`alembic current` muestra `20260817 (head)`)
- [ ] Tablas `rider_wallets`, `financial_transactions`, `payout_requests` existen
- [ ] ENUMs `transactiontype_fase7`, `transactionstatus_fase7`, `payoutstatus_fase7` creados
- [ ] Wallets inicializadas para riders existentes
- [ ] Pruebas de servicio wallet pasaron (crédito, débito, retiro)
- [ ] Endpoints API responden correctamente
- [ ] Transacciones se registran con balance correcto
- [ ] Solicitudes de retiro cambian a estado PENDING
- [ ] Idempotencia funciona (misma key no duplica transacción)

---

## 🐛 SOLUCIÓN DE PROBLEMAS

### Error: "Connection refused" a PostgreSQL
```bash
# Verificar que Docker esté corriendo
docker compose ps

# Si no, iniciar
docker compose up -d db

# Esperar 10 segundos y reintentar
sleep 10
```

### Error: "No module named 'psycopg2'"
```bash
pip install psycopg2-binary
```

### Error: "alembic: command not found"
```bash
pip install alembic sqlalchemy
```

### Error: "type already exists"
```bash
# Ejecutar limpieza
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

---

## 📊 MÉTRICAS DE ÉXITO

| Métrica | Valor Esperado |
|---------|---------------|
| Migración aplicada | ✅ `20260817 (head)` |
| Tablas creadas | ✅ 3 tablas |
| ENUMs creados | ✅ 3 tipos |
| Wallets por rider | ✅ 1 wallet única |
| Balance inicial | ✅ $0.00 USD |
| Transacciones inmutables | ✅ Solo INSERT |
| Idempotencia | ✅ Key única |

---

**Documento generado:** 2026  
**Autor:** Delivery360 Engineering Team  
**Fase:** 7 (Wallets & Pagos)  
**Estado:** ✅ LISTO PARA EJECUCIÓN
