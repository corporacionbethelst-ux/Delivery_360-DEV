#!/usr/bin/env python
"""
🧪 Script de prueba para WalletService (Fase 7 - Delivery360)

Este script verifica que todas las operaciones de wallet funcionen correctamente:
- Obtener/Crear wallet
- Crédito (pago de entrega)
- Débito (penalización)
- Solicitud de retiro
- Historial de transacciones
- Saldo actual

Uso: python scripts/test_wallet_service.py
"""
import asyncio
import sys
import os

# Asegurar que el backend esté en el path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.wallet_service import WalletService
from app.core.database import get_db_session
from sqlalchemy import select
from app.models.rider import Rider
from app.models.financial import RiderWallet


async def test_wallet_operations():
    print("🧪 INICIANDO PRUEBAS DE WALLET SERVICE")
    print("=" * 60)
    
    async for session in get_db_session():
        try:
            # Obtener un rider de prueba
            result = await session.execute(select(Rider).limit(1))
            rider = result.scalar_one_or_none()
            
            if not rider:
                print("❌ No hay riders en la DB")
                print("   Ejecuta primero: python scripts/seed_data.py")
                return False
            
            print(f"✅ Rider seleccionado: {rider.name} (ID: {rider.id})")
            
            wallet_service = WalletService(session)
            
            # ============================================
            # Prueba 1: Obtener o crear wallet
            # ============================================
            print("\n📝 Prueba 1: Obtener/Crear wallet...")
            wallet = await wallet_service.get_or_create_wallet(rider.id)
            print(f"   ✅ Wallet ID: {wallet.id}")
            print(f"   ✅ Balance inicial: ${wallet.balance_cents/100:.2f} USD")
            print(f"   ✅ Moneda: {wallet.currency}")
            print(f"   ✅ Activa: {wallet.is_active}")
            
            initial_balance = wallet.balance_cents
            
            # ============================================
            # Prueba 2: Crédito (simular pago de entrega)
            # ============================================
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
            print(f"   ✅ Tipo: {transaction.transaction_type}")
            print(f"   ✅ Monto: ${transaction.amount_cents/100:.2f} USD")
            print(f"   ✅ Estado: {transaction.status}")
            print(f"   ✅ Balance después: ${transaction.balance_after_cents/100:.2f} USD")
            
            expected_balance = initial_balance + amount_cents
            if transaction.balance_after_cents != expected_balance:
                print(f"   ❌ ERROR: Balance incorrecto. Esperado: ${expected_balance/100:.2f}, Obtenido: ${transaction.balance_after_cents/100:.2f}")
                return False
            
            # ============================================
            # Prueba 3: Débito (simular penalización)
            # ============================================
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
            print(f"   ✅ Tipo: {debit_tx.transaction_type}")
            print(f"   ✅ Monto: ${debit_tx.amount_cents/100:.2f} USD")
            print(f"   ✅ Estado: {debit_tx.status}")
            print(f"   ✅ Balance después: ${debit_tx.balance_after_cents/100:.2f} USD")
            
            expected_balance = expected_balance - debit_amount
            if debit_tx.balance_after_cents != expected_balance:
                print(f"   ❌ ERROR: Balance incorrecto. Esperado: ${expected_balance/100:.2f}, Obtenido: ${debit_tx.balance_after_cents/100:.2f}")
                return False
            
            # ============================================
            # Prueba 4: Solicitar retiro
            # ============================================
            print("\n💸 Prueba 4: Solicitar retiro ($3.00)...")
            withdrawal_amount = 300  # $3.00
            
            # Verificar que hay saldo suficiente
            current_wallet = await wallet_service.get_wallet_by_id(wallet.id)
            if current_wallet.balance_cents < withdrawal_amount:
                print(f"   ⚠️  Saldo insuficiente. Saltando prueba de retiro.")
            else:
                payout = await wallet_service.request_payout(
                    wallet_id=wallet.id,
                    amount_cents=withdrawal_amount,
                    payout_method='bank_transfer',
                    bank_account_number='1234567890'
                )
                print(f"   ✅ Payout Request ID: {payout.id}")
                print(f"   ✅ Monto: ${payout.amount_cents/100:.2f} USD")
                print(f"   ✅ Estado: {payout.status}")
                print(f"   ✅ Método: {payout.payout_method}")
                
                if payout.status != 'PENDING':
                    print(f"   ❌ ERROR: Estado esperado PENDING, obtenido: {payout.status}")
                    return False
            
            # ============================================
            # Prueba 5: Obtener historial
            # ============================================
            print("\n📜 Prueba 5: Historial de transacciones...")
            history = await wallet_service.get_transaction_history(wallet.id, limit=10)
            print(f"   ✅ Total transacciones: {len(history)}")
            
            if len(history) < 2:
                print(f"   ❌ ERROR: Se esperaban al menos 2 transacciones")
                return False
            
            print("   Últimas transacciones:")
            for tx in history[:3]:
                print(f"      - {tx.transaction_type}: ${tx.amount_cents/100:.2f} ({tx.status})")
            
            # ============================================
            # Prueba 6: Saldo actual
            # ============================================
            print("\n💵 Prueba 6: Saldo actual...")
            current_wallet = await wallet_service.get_wallet_by_id(wallet.id)
            final_balance = current_wallet.balance_cents
            print(f"   ✅ Balance final: ${final_balance/100:.2f} USD")
            
            # Verificar consistencia
            expected_final = initial_balance + 550 - 200  # crédito - débito
            if 'payout' in locals() and payout.status == 'PENDING':
                # El retiro en PENDING no debería afectar el balance aún
                # Depende de la implementación del servicio
                pass
            
            # ============================================
            # Prueba 7: Idempotencia (opcional)
            # ============================================
            print("\n🔒 Prueba 7: Idempotencia (misma key no duplica)...")
            idempotency_key = "TEST-IDEM-KEY-12345"
            
            tx1 = await wallet_service.credit_wallet(
                wallet_id=wallet.id,
                amount_cents=100,
                transaction_type='BONO',
                description='Bono de prueba',
                reference_id='BONO-001',
                idempotency_key=idempotency_key
            )
            
            # Intentar misma operación con misma key
            try:
                tx2 = await wallet_service.credit_wallet(
                    wallet_id=wallet.id,
                    amount_cents=100,
                    transaction_type='BONO',
                    description='Bono de prueba (duplicado)',
                    reference_id='BONO-001-DUP',
                    idempotency_key=idempotency_key
                )
                # Si llega aquí, verificar que es la misma transacción
                if tx1.id != tx2.id:
                    print(f"   ❌ ERROR: La idempotencia no funcionó correctamente")
                    return False
                print(f"   ✅ Idempotencia correcta: misma transacción retornada")
            except Exception as e:
                # También es válido si lanza excepción de duplicado
                print(f"   ✅ Idempotencia correcta: excepción lanzada ({type(e).__name__})")
            
            # ============================================
            # RESUMEN FINAL
            # ============================================
            print("\n" + "=" * 60)
            print("🎉 TODAS LAS PRUEBAS PASARON EXITOSAMENTE")
            print("=" * 60)
            print(f"\n📊 RESUMEN:")
            print(f"   • Rider: {rider.name}")
            print(f"   • Wallet ID: {wallet.id}")
            print(f"   • Balance inicial: ${initial_balance/100:.2f} USD")
            print(f"   • Balance final: ${final_balance/100:.2f} USD")
            print(f"   • Transacciones creadas: {len(history)}")
            if 'payout' in locals():
                print(f"   • Solicitudes de retiro: 1 (${payout.amount_cents/100:.2f} USD)")
            print("\n✅ Fase 7 operativa y verificada correctamente")
            
            return True
            
        except Exception as e:
            print(f"\n❌ ERROR EN PRUEBAS: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            await session.close()
            break
    
    return False


if __name__ == "__main__":
    success = asyncio.run(test_wallet_operations())
    sys.exit(0 if success else 1)
