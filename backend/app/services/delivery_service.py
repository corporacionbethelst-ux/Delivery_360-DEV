"""
Servicio de Gestión de Entregas
"""
from datetime import datetime
import uuid
import re
import logging
from typing import Optional, List, Tuple
from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.models.delivery import Delivery, DeliveryStatus, LockedBonusType
from app.models.order import OrderStatus
from app.schemas.delivery import ProofOfDeliveryCreate
from app.crud.delivery import delivery as delivery_crud
from app.crud.order import order as order_crud
from app.models.platform_setting import PlatformSetting
from app.services.financial_service import FinancialService 
from app.models.rider import Rider

# Configurar logger para asegurar que los mensajes se vean siempre
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

class DeliveryService:
    """Servicio para gestión de entregas"""

    # Palabras clave para identificar causas externas (Cliente / Sitio / Seguridad)
    EXTERNAL_CAUSE_KEYWORDS = [
        "cliente no estaba", "no habia nadie", "casa cerrada", "porton cerrado",
        "direccion incorrecta", "direccion mala", "no existe la direccion",
        "cliente no contesta", "no responde", "telefono apagado",
        "zona peligrosa", "inseguro", "atraco", "perro", "mascota agresiva",
        "edificio cerrado", "recepcion cerrada", "no dejan entrar",
        "cliente cancelo", "cliente anuló", "pedido cancelado por cliente",
        "lluvia fuerte", "inundacion", "via bloqueada", "accidente vial"
    ]

    # Palabras clave para identificar culpas del repartidor (Internas)
    RIDER_FAULT_KEYWORDS = [
        "se me cayo", "se cayó", "derrame", "producto dañado", "roto",
        "llegue tarde", "llegué tarde", "retraso mio", "olvido", "olvidé",
        "me equivoque", "me equivocé", "direccion mal tomada",
        "moto se daño", "moto falló", "sin gasolina", "pierde tiempo",
        "no quise ir", "pereza", "cansancio"
    ]

    @staticmethod
    def _ensure_status_transition(
        delivery: Delivery,
        *,
        allowed_from: tuple[DeliveryStatus, ...],
        action: str,
    ) -> None:
        if delivery.status not in allowed_from:
            allowed = ", ".join(s.value for s in allowed_from)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se puede {action}. Estado actual: {delivery.status.value}. Estados permitidos: {allowed}",
            )

    @staticmethod
    def _analyze_failure_cause(description: str) -> Tuple[bool, str]:
        """
        Analiza la descripción del fallo para determinar si es causa externa o culpa del repartidor.
        Retorna: (es_causa_externa, razon_detectada)
        """
        if not description:
            return False, "Sin descripción"

        text = description.lower()

        # 1. Verificar si hay indicios de culpa del repartidor (Prioridad alta para denegar bono)
        for keyword in DeliveryService.RIDER_FAULT_KEYWORDS:
            if keyword in text:
                return False, f"Causa interna detectada: '{keyword}'"

        # 2. Verificar si hay indicios de causa externa
        for keyword in DeliveryService.EXTERNAL_CAUSE_KEYWORDS:
            if keyword in text:
                return True, f"Causa externa detectada: '{keyword}'"

        # 3. Por defecto, si no es claro, asumimos que no es bonificable para evitar fraudes,
        # o podríamos retornar True si la política es 'beneficio de la duda'.
        # Aquí optamos por ser estrictos: si no menciona una causa externa clara, no hay bono.
        return False, "No se identificó causa externa clara"

    async def _get_bonus_config_and_snapshot(
        self,
        db: AsyncSession,
        bonus_type: LockedBonusType,
        delivery_id: uuid.UUID,
        rider_id: uuid.UUID
    ) -> Tuple[Optional[float], Optional[str]]:
        """
        Obtiene la configuración de bonos vigente y retorna el monto aplicable.
        
        FÓRMULA DE CÁLCULO COMPLETA (Fases 1-4):
        - Bono Base: valor configurable en platform_settings
        - Multiplicador Zona: valor de bonus_multiplier en la zona del rider
        - Multiplicador Nivel: valor según tier del rider (BRONCE=1.0, PLATA=1.05, ORO=1.10, PLATINO=1.15)
        - Fórmula: Bono Final = (Bono Base × Multiplicador Zona) × Multiplicador Nivel
        
        Args:
            db: Sesión de base de datos
            bonus_type: Tipo de bono (SUCCESS o FAILED_ATTEMPT)
            delivery_id: ID de la entrega
            rider_id: ID del repartidor
            
        Returns:
            Tuple[monto_a_congelar, alerta_configuracion]
            - Si la config es válida: retorna el monto y None
            - Si la config es inválida: retorna 0.0 y mensaje de alerta
        """
        from app.models.zone import Zone
        from app.models.rider import RiderTier
        
        # Mapa de multiplicadores por nivel de repartidor (Fase 4)
        TIER_MULTIPLIERS = {
            RiderTier.BRONCE: 1.00,    # Sin bonificación extra
            RiderTier.PLATA: 1.05,     # +5%
            RiderTier.ORO: 1.10,       # +10%
            RiderTier.PLATINO: 1.15,   # +15%
        }
        
        # 1. Obtener configuración de bonos base
        result = await db.execute(
            select(PlatformSetting.key, PlatformSetting.value).where(
                PlatformSetting.key.in_(["rider_delivery_bonus", "rider_failed_attempt_bonus"])
            )
        )
        settings_rows = result.fetchall()
        settings_map = {row.key: row.value for row in settings_rows}
        
        # 2. Determinar qué key usar según el tipo de bono
        if bonus_type == LockedBonusType.SUCCESS:
            bonus_key = "rider_delivery_bonus"
        else:  # FAILED_ATTEMPT
            bonus_key = "rider_failed_attempt_bonus"
        
        bonus_value = settings_map.get(bonus_key)
        
        # Validar si la configuración existe y es numérica
        if bonus_value is None:
            # Configuración faltante
            warning = f"Configuración '{bonus_key}' no encontrada en PlatformSetting. Bono congelado en $0."
            return 0.0, warning
        
        try:
            base_bonus_amount = float(bonus_value)
        except (ValueError, TypeError):
            warning = f"Configuración '{bonus_key}' tiene valor inválido '{bonus_value}'. Bono congelado en $0."
            return 0.0, warning
        
        # 3. Obtener la zona del rider para aplicar multiplicador
        rider_result = await db.execute(
            select(Rider.zone_id, Rider.tier).where(Rider.id == rider_id)
        )
        rider_row = rider_result.first()
        rider_zone_id = rider_row[0] if rider_row else None
        rider_tier = rider_row[1] if rider_row else RiderTier.BRONCE
        
        zone_multiplier = 1.0  # Valor por defecto si no hay zona o multiplicador
        
        if rider_zone_id:
            zone_result = await db.execute(
                select(Zone.bonus_multiplier).where(Zone.id == rider_zone_id)
            )
            zone_multiplier_value = zone_result.scalar_one_or_none()
            if zone_multiplier_value is not None:
                zone_multiplier = float(zone_multiplier_value)
        
        # 4. Obtener multiplicador por nivel del rider (Fase 4)
        tier_multiplier = TIER_MULTIPLIERS.get(rider_tier, 1.0)
        
        # 5. Aplicar fórmula completa: Bono Final = (Bono Base × Multiplicador Zona) × Multiplicador Nivel
        final_bonus_amount = (base_bonus_amount * zone_multiplier) * tier_multiplier
        
        # Logging para depuración - USANDO LOGGER PARA ASEGURAR VISIBILIDAD
        logger.info(f"[BONUS_CALC] Base: ${base_bonus_amount}, Zona: {zone_multiplier}x, Tier ({rider_tier}): {tier_multiplier}x, Final: ${final_bonus_amount}")
        print(f"[BONUS_CALC] Base: ${base_bonus_amount}, Zona: {zone_multiplier}x, Tier ({rider_tier}): {tier_multiplier}x, Final: ${final_bonus_amount}", flush=True)
        
        return final_bonus_amount, None

    async def _create_financial_snapshot(
        self,
        db: AsyncSession,
        delivery: Delivery,
        bonus_type: LockedBonusType,
        bonus_amount: float,
        config_warning: Optional[str] = None
    ) -> None:
        """
        Crea el snapshot financiero inmutable en la entrega.
        Este método debe llamarse SOLO una vez, al momento de transición a estado terminal.
        
        Args:
            db: Sesión de base de datos
            delivery: Objeto Delivery a actualizar
            bonus_type: Tipo de bono aplicado
            bonus_amount: Monto exacto a congelar
            config_warning: Mensaje de alerta si la configuración era inválida
        """
        now = datetime.utcnow()
        
        # Actualizar campos de snapshot en el objeto delivery
        delivery.locked_bonus_amount = bonus_amount
        delivery.locked_bonus_type = bonus_type
        delivery.bonus_snapshot_date = now
        delivery.bonus_config_warning_snapshot = config_warning
        
        # Nota: No hacemos commit aquí, se espera que el caller haga commit
        # para mantener atomicidad con el cambio de estado

    async def _grant_failed_attempt_bonus(
        self, 
        db: AsyncSession, 
        rider_id: uuid.UUID, 
        delivery_id: uuid.UUID, 
        failure_cause_enum_value: str
    ) -> None:
        """Registra el bono por entrega fallida si la causa es bonificable y la configuración lo permite"""
        try:
            # 1. Importar el Enum para validar la causa
            from app.models.enums import DeliveryFailureCause
            
            # 2. Validar si el valor recibido es una causa válida y bonificable
            try:
                cause = DeliveryFailureCause(failure_cause_enum_value)
            except ValueError:
                print(f"[WARNING] Causa de fallo desconocida: {failure_cause_enum_value}. No se aplica bono.")
                return

            if not cause.is_bonificable:
                print(f"[INFO] La causa '{cause.value}' no es bonificable según la regla de negocio.")
                return

            # 3. Obtener el valor del setting DESDE LA BASE DE DATOS (Dinámico)
            result = await db.execute(
                select(PlatformSetting.value).where(PlatformSetting.key == "rider_failed_attempt_bonus")
            )
            bonus_value = result.scalar_one_or_none()
            
            if not bonus_value:
                print(f"[WARNING] Setting 'rider_failed_attempt_bonus' no encontrado en DB. Se omite el bono.")
                return

            try:
                bonus_amount = float(bonus_value)
            except (ValueError, TypeError):
                print(f"[ERROR] El valor del setting '{bonus_value}' no es numérico válido.")
                return
            
            if bonus_amount <= 0:
                print(f"[INFO] El bono por intento fallido está configurado en 0. No se registra transacción.")
                return

            # 4. Crear instancia del servicio financiero y registrar en el ledger
            from app.models.financial import TransactionType, PaymentStatus
            financial_svc = FinancialService(db)
            await financial_svc.create_transaction(
                rider_id=str(rider_id),
                amount=bonus_amount,
                transaction_type=TransactionType.PAGO_INTENTO_FALLIDO,
                description=f"Bono por entrega fallida ({cause.value}). ID Entrega: {str(delivery_id)[:8]}",
                reference_id=str(delivery_id),
                source_type="delivery_failed",
                source_id=str(delivery_id),
                status=PaymentStatus.PROCESADO,
            )
            
            print(f"[INFO] Bono DINÁMICO de ${bonus_amount} asignado al rider {rider_id} por causa '{cause.value}'.")
            
        except Exception as e:
            print(f"[ERROR] Fallo al asignar bono por entrega fallida: {str(e)}")
            # No lanzamos excepción para no fallar el proceso de marcado como fallida

    async def get_delivery(self, db: AsyncSession, delivery_id: uuid.UUID) -> Delivery:
        """Obtiene entrega por ID"""
        delivery = await delivery_crud.get(db, delivery_id)
        if not delivery:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Entrega no encontrada"
            )
        return delivery
    
    async def create_delivery(
        self, 
        db: AsyncSession, 
        order_id: uuid.UUID,
        created_by: int
    ) -> Delivery:
        """Crea una nueva entrega vinculada a un pedido"""
        order = await order_crud.get(db, order_id)
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pedido no encontrado"
            )
        
        if order.status not in [OrderStatus.ASIGNADO, OrderStatus.EN_RECOLECCION]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se puede crear entrega. Estado del pedido: {order.status.value}"
            )
        if not order.assigned_rider_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El pedido no tiene repartidor asignado"
            )
        
        delivery = await delivery_crud.create(
            db,
            obj_in={
                "order_id": order_id,
                "rider_id": order.assigned_rider_id,
                "status": DeliveryStatus.PENDIENTE,
            }
        )
        return delivery
    
    async def start_delivery(
        self, 
        db: AsyncSession, 
        delivery_id: uuid.UUID,
        rider_id: uuid.UUID,
        started_by: int
    ) -> Delivery:
        """Inicia entrega (marcado de salida)"""
        delivery = await self.get_delivery(db, delivery_id)
        self._ensure_status_transition(
            delivery,
            allowed_from=(DeliveryStatus.PENDIENTE, DeliveryStatus.INICIADA, DeliveryStatus.EN_PICKUP),
            action="iniciar entrega",
        )
        
        if delivery.rider_id != rider_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para iniciar esta entrega"
            )
        
        delivery = await delivery_crud.update(
            db,
            db_obj=delivery,
            obj_in={
                "status": DeliveryStatus.EN_ROUTE,
                "started_at": datetime.utcnow(),
            }
        )
        return delivery
    
    async def complete_delivery(
        self, 
        db: AsyncSession, 
        delivery_id: uuid.UUID,
        proof_data: ProofOfDeliveryCreate,
        completed_by: int
    ) -> Delivery:
        """Completa entrega con prueba de entrega.
        
        IMPORTANTE: En el momento de completar, se congela el bono aplicable
        según la configuración vigente en ESE instante. Este valor NUNCA cambiará.
        """
        delivery = await self.get_delivery(db, delivery_id)
        self._ensure_status_transition(
            delivery,
            allowed_from=(DeliveryStatus.INICIADA, DeliveryStatus.EN_ROUTE, DeliveryStatus.EN_DESTINO),
            action="completar entrega",
        )
        now = datetime.utcnow()
        
        # =========================================================================
        # FASE 1: Capturar Snapshot Financiero ANTES de cambiar el estado
        # =========================================================================
        bonus_amount, config_warning = await self._get_bonus_config_and_snapshot(
            db=db,
            bonus_type=LockedBonusType.SUCCESS,
            delivery_id=delivery_id,
            rider_id=delivery.rider_id
        )
        
        # Preparar datos de actualización incluyendo el snapshot financiero
        update_data = {
            "status": DeliveryStatus.COMPLETADA,
            "completed_at": now,
            "proof_photo_url": proof_data.photo_url,
            "proof_signature": proof_data.signature_base64,
            "proof_otp": proof_data.otp_code,
            "proof_notes": proof_data.notes,
            "customer_name_received": proof_data.customer_name,
            "current_latitude": proof_data.delivery_latitude,
            "current_longitude": proof_data.delivery_longitude,
            # Snapshot financiero inmutable
            "locked_bonus_amount": bonus_amount,
            "locked_bonus_type": LockedBonusType.SUCCESS,
            "bonus_snapshot_date": now,
            "bonus_config_warning_snapshot": config_warning,
        }
        
        delivery = await delivery_crud.update(
            db,
            db_obj=delivery,
            obj_in=update_data
        )
        
        # =========================================================================
        # FASE 2: Registrar transacción financiera con el valor CONGELADO
        # =========================================================================
        if delivery.rider_id and bonus_amount > 0:
            try:
                from app.models.financial import TransactionType, PaymentStatus
                financial_svc = FinancialService(db)
                await financial_svc.create_transaction(
                    rider_id=str(delivery.rider_id),
                    amount=bonus_amount,
                    transaction_type=TransactionType.PAGO_ENTREGA,
                    description=f"Bono por entrega completada. ID Entrega: {str(delivery_id)[:8]}",
                    reference_id=str(delivery_id),
                    source_type="delivery_completed",
                    source_id=str(delivery_id),
                    status=PaymentStatus.PROCESADO,
                )
                logger.info(f"[INFO] Bono CONGELADO de ${bonus_amount} registrado para entrega {delivery_id}")
                print(f"[INFO] Bono CONGELADO de ${bonus_amount} registrado para entrega {delivery_id}", flush=True)
            except Exception as e:
                logger.error(f"[ERROR] Fallo al registrar transacción financiera: {str(e)}")
                print(f"[ERROR] Fallo al registrar transacción financiera: {str(e)}", flush=True)
                # No lanzamos excepción para no revertir el cambio de estado
        
        # Actualizar estado del pedido asociado
        order = await order_crud.get(db, delivery.order_id)
        if order:
            await order_crud.update(
                db,
                db_obj=order,
                obj_in={
                    "status": OrderStatus.ENTREGADO,
                    "delivered_at": now,
                }
            )
        
        return delivery
    
    async def fail_delivery(
        self, 
        db: AsyncSession, 
        delivery_id: uuid.UUID,
        failure_cause_enum_value: str,
        failed_by: int
    ) -> Delivery:
        """Marca entrega como fallida y gestiona bonos si aplica basado en el Enum.
        
        IMPORTANTE: En el momento de fallar, se congela el bono aplicable (si corresponde)
        según la configuración vigente en ESE instante. Este valor NUNCA cambiará.
        """
        delivery = await self.get_delivery(db, delivery_id)
        self._ensure_status_transition(
            delivery,
            allowed_from=(DeliveryStatus.PENDIENTE, DeliveryStatus.INICIADA, DeliveryStatus.EN_ROUTE, DeliveryStatus.EN_DESTINO),
            action="fallar entrega",
        )
        
        # 1. Importar Enum y validar causa
        from app.models.enums import DeliveryFailureCause
        try:
            failure_cause = DeliveryFailureCause(failure_cause_enum_value)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Causa de falla inválida: {failure_cause_enum_value}"
            )
        
        # =========================================================================
        # FASE 1: Determinar si aplica bono y capturar snapshot financiero
        # =========================================================================
        bonus_amount = 0.0
        bonus_type = None
        config_warning = None
        
        if failure_cause.is_bonificable and delivery.rider_id:
            # La causa es bonificable: obtener monto y congelar
            bonus_amount, config_warning = await self._get_bonus_config_and_snapshot(
                db=db,
                bonus_type=LockedBonusType.FAILED_ATTEMPT,
                delivery_id=delivery_id,
                rider_id=delivery.rider_id
            )
            bonus_type = LockedBonusType.FAILED_ATTEMPT
        else:
            # No es bonificable: congelar en 0 explícitamente para auditoría
            bonus_amount = 0.0
            bonus_type = None  # Sin bono aplicado
            config_warning = None
        
        # 2. Preparar datos de actualización (usando el ENUM estandarizado + snapshot)
        update_data = {
            "status": DeliveryStatus.FALLIDA,
            "has_issues": True,
            "failure_cause": failure_cause,  # Campo estandarizado
            "issue_type": failure_cause.value,
            "issue_description": f"Fallo por causa: {failure_cause.value}",
            "issue_analysis_result": f"Causa: {failure_cause.value}. Bonificable: {failure_cause.is_bonificable}",
            # Snapshot financiero inmutable
            "locked_bonus_amount": bonus_amount if bonus_type else None,
            "locked_bonus_type": bonus_type,
            "bonus_snapshot_date": datetime.utcnow() if bonus_type else None,
            "bonus_config_warning_snapshot": config_warning,
        }
        
        # 3. Actualizar la entrega
        delivery = await delivery_crud.update(
            db,
            db_obj=delivery,
            obj_in=update_data
        )
        
        # =========================================================================
        # FASE 2: Gestionar bono AUTOMÁTICO si el ENUM indica que es bonificable
        #          El servicio verifica el valor dinámico en PlatformSetting
        # =========================================================================
        if delivery.rider_id and failure_cause.is_bonificable and bonus_amount > 0:
            try:
                from app.models.financial import TransactionType, PaymentStatus
                financial_svc = FinancialService(db)
                await financial_svc.create_transaction(
                    rider_id=str(delivery.rider_id),
                    amount=bonus_amount,
                    transaction_type=TransactionType.PAGO_INTENTO_FALLIDO,
                    description=f"Bono por entrega fallida ({failure_cause.value}). ID Entrega: {str(delivery_id)[:8]}",
                    reference_id=str(delivery_id),
                    source_type="delivery_failed",
                    source_id=str(delivery_id),
                    status=PaymentStatus.PROCESADO,
                )
                print(f"[INFO] Bono CONGELADO de ${bonus_amount} registrado para entrega fallida {delivery_id}")
            except Exception as e:
                print(f"[ERROR] Fallo al registrar transacción financiera: {str(e)}")
                # No lanzamos excepción para no revertir el cambio de estado
        
        # 4. Actualizar estado del pedido asociado
        order = await order_crud.get(db, delivery.order_id)
        if order:
            await order_crud.update(
                db,
                db_obj=order,
                obj_in={
                    "status": OrderStatus.FALLIDO,
                    "failure_reason": failure_cause.value,
                    "failure_notes": f"Causa: {failure_cause.value}. Bonificable: {failure_cause.is_bonificable}",
                }
            )
        
        return delivery
    
    async def list_deliveries(
        self, 
        db: AsyncSession, 
        skip: int = 0, 
        limit: int = 100,
        status_filter: Optional[DeliveryStatus] = None,
        rider_id: Optional[uuid.UUID] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None
    ) -> List[Delivery]:
        """Lista entregas con filtros"""
        filters = {}
        if status_filter:
            filters["status"] = status_filter
        if rider_id:
            filters["rider_id"] = rider_id
        if date_from:
            filters["created_at_gte"] = date_from
        if date_to:
            filters["created_at_lte"] = date_to
        
        return await delivery_crud.get_multi(db, skip=skip, limit=limit, **filters)
    
    async def get_deliveries_by_rider(
        self, 
        db: AsyncSession, 
        rider_id: uuid.UUID,
        status_filter: Optional[DeliveryStatus] = None
    ) -> List[Delivery]:
        """Obtiene entregas de un repartidor"""
        filters = {"rider_id": rider_id}
        if status_filter:
            filters["status"] = status_filter
        
        return await delivery_crud.get_multi(db, skip=0, limit=1000, **filters)
    
    async def get_delivery_history(
        self, 
        db: AsyncSession, 
        rider_id: uuid.UUID,
        limit: int = 50
    ) -> List[Delivery]:
        """Obtiene histórico de entregas completadas de un repartidor"""
        return await delivery_crud.get_multi(
            db, 
            skip=0, 
            limit=limit,
            rider_id=rider_id,
            status=DeliveryStatus.COMPLETADA
        )


delivery_service = DeliveryService()