"""
Servicio de Gestión de Entregas
"""
from datetime import datetime
import uuid
import re
from typing import Optional, List, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.models.delivery import Delivery, DeliveryStatus
from app.models.order import OrderStatus
from app.schemas.delivery import ProofOfDeliveryCreate
from app.crud.delivery import delivery as delivery_crud
from app.crud.order import order as order_crud
# Importaciones necesarias para la lógica de bonos y settings
from app.crud.settings import settings as settings_crud
from app.services.finance_service import finance_service 
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
        reason: str
    ) -> None:
        """Registra el bono por entrega fallida si la configuración lo permite"""
        try:
            # Obtener el valor del setting
            bonus_setting = await settings_crud.get_by_key(db, "rider_failed_attempt_bonus")
            
            if not bonus_setting or not bonus_setting.value:
                print(f"[WARNING] Setting 'rider_failed_attempt_bonus' no encontrado o vacío.")
                return

            bonus_amount = float(bonus_setting.value)
            
            if bonus_amount <= 0:
                return

            # Obtener datos del rider para el ledger
            rider = db.get(Rider, rider_id) # O usar un CRUD async si es necesario
            
            # Registrar en el ledger financiero
            await finance_service.add_transaction(
                db=db,
                user_id=rider_id,
                amount=bonus_amount,
                transaction_type="BONO_FALLIDA",
                description=f"Bono por entrega fallida ({reason}). ID Entrega: {str(delivery_id)[:8]}",
                reference_id=str(delivery_id)
            )
            
            print(f"[INFO] Bono de ${bonus_amount} asignado al rider {rider_id} por entrega fallida externa.")
            
        except Exception as e:
            print(f"[ERROR] Fallo al asignar bono por entrega fallida: {str(e)}")
            # No lanzamos excepción para no fallar el proceso de marcado como fallida, solo logueamos.

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
        failure_reason: str,
        failed_by: int
    ) -> Delivery:
        """Marca entrega como fallida y gestiona bonos si aplica"""
        delivery = await self.get_delivery(db, delivery_id)
        self._ensure_status_transition(
            delivery,
            allowed_from=(DeliveryStatus.PENDIENTE, DeliveryStatus.INICIADA, DeliveryStatus.EN_ROUTE, DeliveryStatus.EN_DESTINO),
            action="fallar entrega",
        )
        
        # 1. Analizar la causa del fallo
        is_external_cause, reason_detail = self._analyze_failure_cause(failure_reason)
        
        # 2. Preparar datos de actualización
        update_data = {
            "status": DeliveryStatus.FALLIDA,
            "has_issues": True,
            "issue_type": "delivery_failed",
            "issue_description": failure_reason,
            "issue_analysis_result": reason_detail # Guardamos el resultado del análisis en DB si tienes la columna
        }
        
        # 3. Actualizar la entrega
        delivery = await delivery_crud.update(
            db,
            db_obj=delivery,
            obj_in=update_data
        )
        
        # 4. Gestionar bono si es causa externa
        if is_external_cause and delivery.rider_id:
            await self._grant_failed_attempt_bonus(
                db=db,
                rider_id=delivery.rider_id,
                delivery_id=delivery_id,
                reason=reason_detail
            )
        
        # 5. Actualizar estado del pedido asociado
        order = await order_crud.get(db, delivery.order_id)
        if order:
            await order_crud.update(
                db,
                db_obj=order,
                obj_in={
                    "status": OrderStatus.FALLIDO,
                    "failure_reason": failure_reason,
                    "failure_cause_external": is_external_cause, # Si tienes este campo en Order
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