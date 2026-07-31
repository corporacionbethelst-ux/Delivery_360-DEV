"""
Servicio de Gestión de Entregas
"""
from datetime import datetime
import uuid
import re
from typing import Optional, List, Tuple
from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.models.delivery import Delivery, DeliveryStatus
from app.models.order import OrderStatus
from app.schemas.delivery import ProofOfDeliveryCreate
from app.crud.delivery import delivery as delivery_crud
from app.crud.order import order as order_crud
from app.models.platform_setting import PlatformSetting
from app.services.financial_service import FinancialService 
from app.models.rider import Rider

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
        """Completa entrega con prueba de entrega"""
        delivery = await self.get_delivery(db, delivery_id)
        self._ensure_status_transition(
            delivery,
            allowed_from=(DeliveryStatus.INICIADA, DeliveryStatus.EN_ROUTE, DeliveryStatus.EN_DESTINO),
            action="completar entrega",
        )
        now = datetime.utcnow()
        
        delivery = await delivery_crud.update(
            db,
            db_obj=delivery,
            obj_in={
                "status": DeliveryStatus.COMPLETADA,
                "completed_at": now,
                "proof_photo_url": proof_data.photo_url,
                "proof_signature": proof_data.signature_base64,
                "proof_otp": proof_data.otp_code,
                "proof_notes": proof_data.notes,
                "customer_name_received": proof_data.customer_name,
                "current_latitude": proof_data.delivery_latitude,
                "current_longitude": proof_data.delivery_longitude,
            }
        )
        
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
        """Marca entrega como fallida y gestiona bonos si aplica basado en el Enum"""
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
        
        # 2. Preparar datos de actualización (usando el ENUM estandarizado)
        update_data = {
            "status": DeliveryStatus.FALLIDA,
            "has_issues": True,
            "failure_cause": failure_cause,  # Campo estandarizado
            "issue_type": failure_cause.value,
            "issue_description": f"Fallo por causa: {failure_cause.value}",
            "issue_analysis_result": f"Causa: {failure_cause.value}. Bonificable: {failure_cause.is_bonificable}"
        }
        
        # 3. Actualizar la entrega
        delivery = await delivery_crud.update(
            db,
            db_obj=delivery,
            obj_in=update_data
        )
        
        # 4. Gestionar bono AUTOMÁTICO si el ENUM indica que es bonificable
        #    El servicio verifica el valor dinámico en PlatformSetting
        if delivery.rider_id and failure_cause.is_bonificable:
            await self._grant_failed_attempt_bonus(
                db=db,
                rider_id=delivery.rider_id,
                delivery_id=delivery_id,
                failure_cause_enum_value=failure_cause.value
            )
        
        # 5. Actualizar estado del pedido asociado
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