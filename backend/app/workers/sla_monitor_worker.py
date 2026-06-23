from backend.app.workers.celery_app import celery_app
from sqlalchemy import select
from datetime import datetime, timezone, timedelta
import asyncio
import logging

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.sla_monitor_worker.check_sla_breaches")
def check_sla_breaches():
    """Marca como SLA incumplido los pedidos que superaron su tiempo estimado y genera alertas."""
    asyncio.run(_check_sla())


async def _check_sla():
    from app.core.database import AsyncSessionLocal
    from app.models.order import Order, OrderStatus
    from app.models.delivery import Delivery, DeliveryStatus
    from app.services.notification_service import NotificationService
    from app.services.alert_service import AlertService
    from app.services.redis_audit_service import get_redis_audit_logger

    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        
        # Buscar entregas EN_CAMINO/EN_RUTA que han excedido el SLA
        result = await db.execute(
            select(Delivery, Order)
            .join(Order, Delivery.order_id == Order.id)
            .where(
                Delivery.status.in_([DeliveryStatus.EN_ROUTE, DeliveryStatus.EN_DESTINO, DeliveryStatus.INICIADA]),
                Delivery.sla_expected_minutes.isnot(None),
            )
        )
        rows = result.all()
        
        alerts_created = 0
        breaches_logged = 0
        
        for delivery, order in rows:
            if not delivery.started_at:
                continue
                
            elapsed_minutes = int((now - delivery.started_at).total_seconds() / 60)
            sla_expected = delivery.sla_expected_minutes or 60
            
            # Verificar si excedió el SLA
            if elapsed_minutes > sla_expected and not delivery.sla_compliant:
                # Marcar como no compliant
                delivery.sla_compliant = False
                delivery.sla_actual_minutes = elapsed_minutes
                breaches_logged += 1
                
                # Calcular minutos de exceso
                minutes_over = elapsed_minutes - sla_expected
                
                # REDIS AUDIT: Log de violación de SLA
                try:
                    redis_logger = get_redis_audit_logger()
                    if redis_logger.connected:
                        await redis_logger.log_sla_breach(
                            order_id=str(delivery.order_id),
                            rider_id=str(delivery.rider_id),
                            minutes_over=minutes_over,
                        )
                except Exception as e:
                    logger.error(f"Error logging SLA breach to Redis: {e}")
                
                # ALERTA: Crear alerta para el manager
                try:
                    alert_service = AlertService()
                    
                    # Obtecer managers para notificar
                    from app.models.user import User, UserRole
                    managers_result = await db.execute(
                        select(User).where(User.role == UserRole.GERENTE)
                    )
                    managers = managers_result.scalars().all()
                    manager_ids = [m.id for m in managers]
                    
                    await alert_service.create_alert(
                        db=db,
                        alert_type="SLA_BREACH",
                        severity="high",
                        title=f"⚠️ SLA Excedido - Orden #{order.external_id or str(order.id)[:8]}",
                        message=f"La entrega ha excedido el SLA por {minutes_over} minutos. Tiempo esperado: {sla_expected} min, Actual: {elapsed_minutes} min",
                        related_entity_id=int(delivery.id) if hasattr(delivery.id, '__int__') else None,
                        related_entity_type="delivery",
                        recipient_user_ids=manager_ids,
                    )
                    alerts_created += 1
                    logger.info(f"Alerta SLA creada para orden {order.id}")
                except Exception as e:
                    logger.error(f"Error creando alerta SLA: {e}")
                
                # NOTIFICACIÓN al rider (advertencia)
                try:
                    notification_service = NotificationService(db)
                    await notification_service.notify_sla_warning(
                        rider_id=int(delivery.rider_id) if hasattr(delivery.rider_id, '__int__') else None,
                        delivery_id=int(delivery.id) if hasattr(delivery.id, '__int__') else None,
                        minutes_remaining=0,  # Ya excedió
                    )
                except Exception as e:
                    logger.error(f"Error notificando SLA al rider: {e}")
        
        if breaches_logged:
            await db.commit()
            logger.info(f"[SLA Monitor] {breaches_logged} entregas marcadas como SLA incumplido, {alerts_created} alertas creadas")

