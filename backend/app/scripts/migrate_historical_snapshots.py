"""
SCRIPT DE MIGRACIÓN DE DATOS HISTÓRICOS - FASE 3 (Snapshot Financiero Inmutable)

Este script congela los valores de bonos para todas las entregas ya finalizadas
(COMPLETADA o FALLIDA) que aún no tienen el snapshot financiero.

Ejecutar DESPUÉS de aplicar la migración Alembic 20260614.

Uso:
    docker compose run --rm backend python -m app.scripts.migrate_historical_snapshots
    
Nota: Este script debe ejecutarse UNA SOLA VEZ, inmediatamente después de desplegar
la nueva versión con el snapshot financiero. Las entregas futuras ya tendrán el
snapshot automático gracias a los cambios en delivery_service.py.
"""
import asyncio
import sys
from datetime import datetime
from pathlib import Path
import re

# Agregar el root del proyecto al path para imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.delivery import Delivery, DeliveryStatus, LockedBonusType
from app.models.platform_setting import PlatformSetting


def ensure_async_driver(db_url: str) -> str:
    """
    Asegura que la URL de conexión use el driver asyncpg.
    Convierte:
      postgresql://... -> postgresql+asyncpg://...
      postgresql+psycopg2://... -> postgresql+asyncpg://...
    """
    if db_url.startswith("postgresql+asyncpg://"):
        return db_url
    
    # Reemplazo seguro para cualquier variante de postgresql
    return re.sub(r"^postgresql(\+.*)?://", "postgresql+asyncpg://", db_url)


async def migrate_historical_snapshots():
    """
    Migrar entregas históricas congelando sus valores de bono actuales.
    
    Estrategia:
    1. Para entregas COMPLETADAS: congelar el valor vigente de rider_delivery_bonus
    2. Para entregas FALLIDAS bonificables: congelar el valor vigente de rider_failed_attempt_bonus
    3. Para entregas FALLIDAS no bonificables: congelar 0.0 explícitamente
    4. Registrar alerta si la configuración actual es inválida
    """
    print("=" * 80)
    print("MIGRACIÓN DE SNAPSHOTS FINANCIEROS HISTÓRICOS")
    print("=" * 80)
    print(f"Fecha de ejecución: {datetime.utcnow().isoformat()}")
    print()
    
    # =========================================================================
    # CONFIGURACIÓN DE MOTOR ASÍNCRONO
    # =========================================================================
    original_url = settings.DATABASE_URL
    async_url = ensure_async_driver(original_url)
    
    print(f"[CONFIG] URL Original: {original_url}")
    print(f"[CONFIG] URL Asíncrona: {async_url}")
    print()

    try:
        engine = create_async_engine(
            async_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10
        )
        
        async_session = sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
    except Exception as e:
        print(f"✗ ERROR CRÍTICO al crear el motor DB: {str(e)}")
        print("Asegúrate de que 'asyncpg' esté instalado en requirements.txt")
        return

    async with async_session() as db:
        try:
            # =========================================================================
            # PASO 1: Obtener configuración actual de bonos
            # =========================================================================
            print("[1/4] Obteniendo configuración actual de bonos...")
            result = await db.execute(
                select(PlatformSetting.key, PlatformSetting.value).where(
                    PlatformSetting.key.in_([
                        "rider_delivery_bonus",
                        "rider_failed_attempt_bonus"
                    ])
                )
            )
            settings_rows = result.fetchall()
            settings_map = {row.key: row.value for row in settings_rows}
            
            delivery_bonus_value = settings_map.get("rider_delivery_bonus")
            failed_bonus_value = settings_map.get("rider_failed_attempt_bonus")
            
            # Convertir a float o None
            delivery_bonus = None
            failed_bonus = None
            
            if delivery_bonus_value:
                try:
                    delivery_bonus = float(delivery_bonus_value)
                except (ValueError, TypeError):
                    print(f"  ⚠️  WARNING: 'rider_delivery_bonus' tiene valor inválido: {delivery_bonus_value}")
            
            if failed_bonus_value:
                try:
                    failed_bonus = float(failed_bonus_value)
                except (ValueError, TypeError):
                    print(f"  ⚠️  WARNING: 'rider_failed_attempt_bonus' tiene valor inválido: {failed_bonus_value}")
            
            config_warning = None
            if delivery_bonus is None or failed_bonus is None:
                config_warning = "Configuración de bonos incompleta o inválida al momento de la migración."
                print(f"  ⚠️  ALERTA CRÍTICA: {config_warning}")
                print("  Se asignará $0.0 a las entregas históricas por seguridad.")
            else:
                print(f"  ✓ rider_delivery_bonus: ${delivery_bonus}")
                print(f"  ✓ rider_failed_attempt_bonus: ${failed_bonus}")
            
            print()
            
            # =========================================================================
            # PASO 2: Contar entregas que necesitan migración
            # =========================================================================
            print("[2/4] Buscando entregas finalizadas sin snapshot...")
            
            result = await db.execute(
                select(Delivery).where(
                    Delivery.status.in_([DeliveryStatus.COMPLETADA, DeliveryStatus.FALLIDA]),
                    Delivery.locked_bonus_amount.is_(None)  # Solo las que NO tienen snapshot
                )
            )
            deliveries_to_migrate = result.scalars().all()
            
            total_count = len(deliveries_to_migrate)
            completed_count = sum(1 for d in deliveries_to_migrate if d.status == DeliveryStatus.COMPLETADA)
            failed_count = sum(1 for d in deliveries_to_migrate if d.status == DeliveryStatus.FALLIDA)
            
            print(f"  Total entregas a migrar: {total_count}")
            print(f"    - COMPLETADAS: {completed_count}")
            print(f"    - FALLIDAS: {failed_count}")
            print()
            
            if total_count == 0:
                print("✓ No hay entregas históricas que migrar. Terminando.")
                await engine.dispose()
                return
            
            # =========================================================================
            # PASO 3: Ejecutar migración por lotes
            # =========================================================================
            print("[3/4] Migrando snapshots financieros...")
            
            migrated_count = 0
            error_count = 0
            now = datetime.utcnow()
            
            # Importación local para evitar ciclos si los hubiera
            from app.models.delivery import get_bonificable_causes
            
            bonificable_causes = get_bonificable_causes()

            for delivery in deliveries_to_migrate:
                try:
                    locked_amount = 0.0
                    locked_type = None
                    
                    if delivery.status == DeliveryStatus.COMPLETADA:
                        # Entrega completada: aplicar bono de éxito
                        if delivery_bonus is not None:
                            locked_amount = delivery_bonus
                            locked_type = LockedBonusType.SUCCESS
                        else:
                            locked_amount = 0.0
                            locked_type = None
                    
                    elif delivery.status == DeliveryStatus.FALLIDA:
                        # Entrega fallida: verificar si es bonificable
                        is_bonificable = False
                        
                        # Lógica robusta de detección
                        if hasattr(delivery, 'failure_cause') and delivery.failure_cause:
                            is_bonificable = delivery.failure_cause.value in bonificable_causes
                        elif hasattr(delivery, 'issue_analysis_result') and delivery.issue_analysis_result:
                            is_bonificable = 'Bonificable: True' in delivery.issue_analysis_result
                        elif hasattr(delivery, 'issue_type') and delivery.issue_type:
                            # Fallback: verificar keywords comunes en mayúsculas
                            issue_upper = delivery.issue_type.upper()
                            # Usamos las causas conocidas del sistema como referencia
                            is_bonificable = any(kw in issue_upper for kw in bonificable_causes)
                        
                        if is_bonificable:
                            if failed_bonus is not None:
                                locked_amount = failed_bonus
                                locked_type = LockedBonusType.FAILED_ATTEMPT
                            else:
                                locked_amount = 0.0
                                locked_type = None
                        else:
                            locked_amount = 0.0
                            locked_type = None
                    
                    # Ejecutar actualización
                    await db.execute(
                        update(Delivery)
                        .where(Delivery.id == delivery.id)
                        .values(
                            locked_bonus_amount=locked_amount,
                            locked_bonus_type=locked_type,
                            bonus_snapshot_date=now,
                            bonus_config_warning_snapshot=config_warning,
                        )
                    )
                    
                    migrated_count += 1
                    
                    # Commit cada 50 registros para feedback visual y seguridad
                    if migrated_count % 50 == 0:
                        await db.commit()
                        print(f"  ... {migrated_count}/{total_count} migradas")
                
                except Exception as e:
                    error_count += 1
                    print(f"  ✗ ERROR migrando entrega {delivery.id}: {str(e)}")
                    continue
            
            # Commit final de los restantes
            await db.commit()
            
            print()
            print(f"  ✓ Migración completada: {migrated_count} entregas actualizadas")
            if error_count > 0:
                print(f"  ⚠️  Errores: {error_count} entregas fallaron")
            
            print()
            
            # =========================================================================
            # PASO 4: Verificación final
            # =========================================================================
            print("[4/4] Verificando migración...")
            
            result = await db.execute(
                select(Delivery).where(
                    Delivery.status.in_([DeliveryStatus.COMPLETADA, DeliveryStatus.FALLIDA]),
                    Delivery.locked_bonus_amount.is_(None)
                )
            )
            remaining = result.scalars().all()
            
            if len(remaining) == 0:
                print("  ✓ VERIFICACIÓN EXITOSA: Todas las entregas tienen snapshot")
            else:
                print(f"  ⚠️  ATENCIÓN: {len(remaining)} entregas aún sin snapshot")
                print("     Esto puede deberse a errores durante la migración.")
            
            print()
            print("=" * 80)
            print("MIGRACIÓN FINALIZADA CORRECTAMENTE")
            print("=" * 80)
            print()
            print("PRÓXIMOS PASOS:")
            print("  1. Reiniciar contenedores: docker compose up -d")
            print("  2. Verificar en frontend que las órdenes muestran valores históricos")
            print("  3. Las entregas FUTURAS ya tendrán snapshot automático")
            print()
            
        except Exception as e:
            await db.rollback()
            print(f"\n✗ ERROR CRÍTICO DURANTE LA TRANSACCIÓN: {str(e)}")
            print("La transacción ha sido revertida. Ningún dato fue modificado.")
            raise
        finally:
            await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(migrate_historical_snapshots())
    except KeyboardInterrupt:
        print("\n\n⚠️  Migración interrumpida por el usuario.")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Migración fallida: {str(e)}")
        sys.exit(1)