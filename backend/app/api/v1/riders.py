from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import joinedload
from pydantic import BaseModel
from typing import Optional, Any, List
from datetime import datetime, timezone, timedelta
import uuid
import logging
import os
import inspect
 
from app.core.database import get_db
from app.core.config import settings
from app.models.rider import Rider, RiderStatus, VehicleType, utc_now_naive
from app.models.user import User, UserRole
from app.models.rider_document import RiderDocument, DocumentType, DocumentStatus
from app.api.v1.auth import get_current_user, require_role

logger = logging.getLogger(__name__)

# El prefijo debe ser exactamente este para que coincida con lo que espera el frontend
router = APIRouter(prefix="/riders")

# ==============================================================================
# SCHEMAS (Modelos de datos para validación)
# ==============================================================================

class RiderCreate(BaseModel):
    """Datos requeridos para crear un nuevo repartidor (incluye usuario)."""
    email: str
    password: str
    first_name: str
    last_name: str
    phone: str
    vehicle_type: str
    vehicle_plate: Optional[str] = None
    vehicle_model: Optional[str] = None
    operating_zone: Optional[str] = None
    cpf: Optional[str] = None
    cnh: Optional[str] = None

    class Config:
        extra = "ignore" 


class RiderUpdate(BaseModel):
    """Datos actualizables del perfil del repartidor."""
    vehicle_type: Optional[str] = None
    vehicle_plate: Optional[str] = None
    vehicle_model: Optional[str] = None
    operating_zone: Optional[str] = None
    cpf: Optional[str] = None
    cnh: Optional[str] = None

    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None

class LocationUpdate(BaseModel):
    """Actualización básica de coordenadas GPS."""
    lat: float
    lng: float
    

class HeartbeatRequest(LocationUpdate):
    """Extiende LocationUpdate para incluir datos de telemetría del dispositivo."""
    accuracy: Optional[float] = None
    speed: Optional[float] = None
    battery_level: Optional[int] = None


class RejectRider(BaseModel):
    """Motivo para rechazar un repartidor."""
    reason: str


class ApproveRider(BaseModel):
    """Observaciones opcionales al aprobar un repartidor."""
    observations: Optional[str] = None


class DocumentStatusUpdate(BaseModel):
    """Actualización del estado de un documento."""
    status: str
    rejection_reason: Optional[str] = None


class NearbyRidersQuery(BaseModel):
    """Parámetros para buscar repartidores cercanos."""
    lat: float
    lng: float
    radius_km: Optional[float] = 5.0
    limit: Optional[int] = 10


# ==============================================================================
# HELPERS (Funciones auxiliares internas)
# ==============================================================================

def _parse_uuid(value: str, field_name: str) -> uuid.UUID:
    """Convierte un string a UUID válido o lanza error 400."""
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field_name} inválido")


def _parse_vehicle_type(value: str) -> VehicleType:
    """Valida que el tipo de vehículo sea uno de los permitidos por el Enum."""
    try:
        return VehicleType(value)
    except ValueError:
        allowed = ", ".join(v.value for v in VehicleType)
        raise HTTPException(
            status_code=400,
            detail=f"vehicle_type inválido. Valores permitidos: {allowed}",
        )

def utc_now_naive():
    """Obtiene la hora actual en UTC sin zona horaria (naive) para compatibilidad con DB."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _get_rider_for_user(db: AsyncSession, user_id) -> Optional[Rider]:
    """Busca el perfil de Rider asociado a un ID de usuario."""
    result = await db.execute(select(Rider).where(Rider.user_id == user_id))
    return result.scalar_one_or_none()


async def _ensure_rider_self_scope(db: AsyncSession, current_user: User, rider: Rider) -> None:
    """
    Middleware de seguridad: Si el usuario es REPARTIDOR, verifica que solo pueda 
    acceder/modificar su propio perfil. Si es ADMIN/GERENTE, permite todo.
    """
    if current_user.role != UserRole.REPARTIDOR:
        return
    current_rider = await _get_rider_for_user(db, current_user.id)
    if not current_rider or current_rider.id != rider.id:
        raise HTTPException(status_code=403, detail="No tienes permiso para acceder a este repartidor")


def _rider_to_dict(r: Rider, include_user: bool = False) -> dict:
    full_name = "Desconocido"
    email = ""
    phone = ""
    
    # CRUCIAL: Verificar si la relación 'user' fue cargada
    if hasattr(r, 'user') and r.user:
        full_name = f"{r.user.first_name} {r.user.last_name}"
        email = r.user.email
        phone = r.user.phone or ""
    else:
        pass

    d: dict[str, Any] = {
        "id": str(r.id),
        "user_id": str(r.user_id),
        "status": r.status.value if hasattr(r.status, 'value') else r.status,
        "vehicle_type": r.vehicle_type.value if hasattr(r.vehicle_type, 'value') else r.vehicle_type,
        "vehicle_plate": r.vehicle_plate or "",
        "vehicle_model": r.vehicle_model,
        "operating_zone": r.operating_zone,
        "is_online": r.is_online,
        "last_lat": r.last_lat,
        "last_lng": r.last_lng,
        "last_location_at": r.last_location_at.isoformat() if r.last_location_at else None,
        "level": r.level,
        "total_points": r.total_points,
        "badges": r.badges or [],
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "approved_at": r.approved_at.isoformat() if r.approved_at else None,
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "first_name": r.user.first_name if r.user else "",
        "last_name": r.user.last_name if r.user else "",
    }
    return d

# ==============================================================================
# ⚠️ IMPORTANTE: ORDEN DE RUTAS
# Las rutas específicas ("/me/...") DEBEN ir ANTES que las genéricas ("/{id}/...")
# FastAPI evalúa en orden; si "{rider_id}" va primero, capturará "me" como un ID.
# ==============================================================================

# ------------------------------------------------------------------------------
# ENDPOINTS DE DOCUMENTOS DEL REPARTIDOR (ACCESO PROPIO - "/me")
# ------------------------------------------------------------------------------

# [REPARTIDOR] Obtener lista de documentos propios
@router.get("/me/documents")
async def get_my_documents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Obtiene la lista de documentos del repartidor autenticado.
    Solo accesible para rol REPARTIDOR.
    """
    if current_user.role != UserRole.REPARTIDOR:
        raise HTTPException(status_code=403, detail="Solo repartidores pueden acceder a sus documentos")
    
    result = await db.execute(select(Rider).where(Rider.user_id == current_user.id))
    rider = result.scalar_one_or_none()
    
    if not rider:
        return []
    
    docs_result = await db.execute(
        select(RiderDocument)
        .where(RiderDocument.rider_id == rider.id)
        .order_by(RiderDocument.created_at.desc())
    )
    documents = docs_result.scalars().all()
    
    return [
        {
            "id": str(d.id),
            "type": d.type.value,
            "status": d.status.value,
            "file_url": d.file_url,
            "rejection_reason": d.rejection_reason,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "updated_at": d.updated_at.isoformat() if d.updated_at else None,
        }
        for d in documents
    ]

# [REPARTIDOR] Subir nuevo documento o reemplazar rechazado
@router.post("/me/documents/upload")
async def upload_my_document(
    type: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Sube un nuevo documento o reemplaza uno rechazado del repartidor autenticado.
    Valida reglas de negocio: no subir si está APROBADO o PENDIENTE.
    """
    if current_user.role != UserRole.REPARTIDOR:
        raise HTTPException(status_code=403, detail="Solo repartidores pueden subir documentos")
    
    try:
        doc_type = DocumentType(type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Tipo inválido. Opciones: {[t.value for t in DocumentType]}")
    
    result = await db.execute(select(Rider).where(Rider.user_id == current_user.id))
    rider = result.scalar_one_or_none()
    
    if not rider:
        raise HTTPException(status_code=404, detail="Perfil de repartidor no encontrado")
    
    existing = await db.execute(
        select(RiderDocument).where(
            RiderDocument.rider_id == rider.id,
            RiderDocument.type == doc_type
        )
    )
    existing_doc = existing.scalar_one_or_none()
    
    if existing_doc and existing_doc.status == DocumentStatus.APROBADO:
        raise HTTPException(status_code=400, detail="Documento ya aprobado. Contacta al administrador.")
    
    if existing_doc and existing_doc.status == DocumentStatus.PENDIENTE:
        raise HTTPException(status_code=400, detail="Documento en revisión. Espera la validación.")
    
    file_extension = file.filename.split(".")[-1] if "." in file.filename else "pdf"
    safe_filename = f"{uuid.uuid4()}.{file_extension}"
    file_url = f"/uploads/documents/{rider.id}/{safe_filename}"
    
    if existing_doc:
        existing_doc.file_url = file_url
        existing_doc.status = DocumentStatus.PENDIENTE
        existing_doc.rejection_reason = None
        existing_doc.updated_at = utc_now_naive()
        doc_to_return = existing_doc
    else:
        new_doc = RiderDocument(
            id=uuid.uuid4(),
            rider_id=rider.id,
            type=doc_type,
            status=DocumentStatus.PENDIENTE,
            file_url=file_url,
            rejection_reason=None
        )
        db.add(new_doc)
        doc_to_return = new_doc
    
    await db.commit()
    await db.refresh(doc_to_return)
    
    return {
        "id": str(doc_to_return.id),
        "type": doc_to_return.type.value,
        "status": doc_to_return.status.value,
        "file_url": doc_to_return.file_url,
        "message": "Documento subido exitosamente."
    }

# [ADMIN/GERENTE] Aprobar o rechazar documento específico
@router.patch("/documents/{doc_id}/status")
async def update_document_status(
    doc_id: str,
    status_update: DocumentStatusUpdate,
    current_user: User = Depends(require_role(UserRole.GERENTE, UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db)
):
    """
    [ADMIN/GERENTE] Aprueba o rechaza un documento específico.
    Si se aprueba y todos los documentos del rider están listos, activa al rider automáticamente.
    """
    new_status = status_update.status
    rejection_reason = status_update.rejection_reason

    if new_status not in ["APROBADO", "RECHAZADO"]:
        raise HTTPException(status_code=400, detail="Estado inválido")

    if new_status == "RECHAZADO" and not rejection_reason:
        raise HTTPException(status_code=400, detail="Se requiere un motivo para el rechazo")

    result = await db.execute(select(RiderDocument).where(RiderDocument.id == _parse_uuid(doc_id, "doc_id")))
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    try:
        doc.status = DocumentStatus(new_status)
    except ValueError:
        raise HTTPException(status_code=400, detail="Estado de documento inválido")
        
    doc.rejection_reason = rejection_reason if new_status == "RECHAZADO" else None
    
    if new_status == "APROBADO":
        rider_result = await db.execute(select(Rider).where(Rider.id == doc.rider_id))
        rider = rider_result.scalar_one_or_none()
        if rider:
            all_docs_result = await db.execute(
                select(RiderDocument).where(RiderDocument.rider_id == rider.id)
            )
            all_docs = all_docs_result.scalars().all()
            if all(d.status == DocumentStatus.APROBADO for d in all_docs):
                rider.status = RiderStatus.ACTIVO
                rider.approved_at = utc_now_naive()

    await db.commit()

    return {"message": f"Documento {new_status.lower()} correctamente", "doc_id": str(doc.id)}

# ==============================================================================
# NUEVOS ENDPOINTS PARA GESTIÓN DE DOCUMENTOS POR ADMINISTRADORES
# ==============================================================================

# [ADMIN/GERENTE] Subir documento en nombre de un repartidor
@router.post("/{rider_id}/documents/upload")
async def upload_document_for_rider(
    rider_id: str,
    type: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.GERENTE, UserRole.SUPERADMIN)),
):
    """
    [ADMIN/GERENTE] Sube un documento en nombre de un repartidor específico.
    Útil cuando el repartidor tiene problemas técnicos o se necesita corrección manual.
    """
    # Validar ID del rider
    rid = _parse_uuid(rider_id, "rider_id")
    
    # Verificar que el rider existe
    rider_result = await db.execute(select(Rider).where(Rider.id == rid))
    rider = rider_result.scalar_one_or_none()
    if not rider:
        raise HTTPException(status_code=404, detail="Repartidor no encontrado")

    # Validar tipo de documento
    try:
        doc_type = DocumentType(type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Tipo inválido. Opciones: {[t.value for t in DocumentType]}")
    
    # Buscar documento existente del mismo tipo
    existing = await db.execute(
        select(RiderDocument).where(
            RiderDocument.rider_id == rider.id,
            RiderDocument.type == doc_type
        )
    )
    existing_doc = existing.scalar_one_or_none()
    
    # Regla: No sobrescribir si está APROBADO (a menos que sea una nueva versión, pero aquí prevenimos accidentes)
    if existing_doc and existing_doc.status == DocumentStatus.APROBADO:
        raise HTTPException(status_code=400, detail="Ya existe un documento aprobado de este tipo. Si necesita actualizarlo, rechace el anterior primero o contacte a superadmin.")
    
    # Generar ruta segura
    file_extension = file.filename.split(".")[-1] if "." in file.filename else "pdf"
    safe_filename = f"{uuid.uuid4()}.{file_extension}"
    file_url = f"/uploads/documents/{rider.id}/{safe_filename}"
    
    if existing_doc:
        # Actualizar existente (ej. estaba rechazado o incompleto)
        existing_doc.file_url = file_url
        existing_doc.status = DocumentStatus.PENDIENTE
        existing_doc.rejection_reason = None
        existing_doc.updated_at = utc_now_naive()
        doc_to_return = existing_doc
    else:
        # Crear nuevo
        new_doc = RiderDocument(
            id=uuid.uuid4(),
            rider_id=rider.id,
            type=doc_type,
            status=DocumentStatus.PENDIENTE,
            file_url=file_url,
            rejection_reason=None
        )
        db.add(new_doc)
        doc_to_return = new_doc
    
    await db.commit()
    await db.refresh(doc_to_return)
    
    return {
        "id": str(doc_to_return.id),
        "type": doc_to_return.type.value,
        "status": doc_to_return.status.value,
        "file_url": doc_to_return.file_url,
        "message": "Documento subido exitosamente por administrador."
    }

# [ADMIN/GERENTE] Eliminar permanentemente un documento
@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.GERENTE, UserRole.SUPERADMIN)),
):
    """
    [ADMIN/GERENTE] Elimina permanentemente un documento de la base de datos.
    Útil para limpiar documentos corruptos, duplicados o subidos por error.
    """
    did = _parse_uuid(doc_id, "doc_id")
    
    result = await db.execute(select(RiderDocument).where(RiderDocument.id == did))
    doc = result.scalar_one_or_none()
    
    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    
    # Opcional: Guardar registro de auditoría antes de borrar (si tu sistema lo requiere)
    # logger.info(f"Admin {current_user.email} eliminó documento {doc_id} del rider {doc.rider_id}")
    
    await db.delete(doc)
    await db.commit()
    
    return {"message": "Documento eliminado exitosamente", "doc_id": str(doc_id)}

# ------------------------------------------------------------------------------
# ENDPOINTS GENERALES DE RIDERS (Creación, Listado, Gestión Admin)
# ------------------------------------------------------------------------------

# [ADMIN/GERENTE] Crear nuevo repartidor (Usuario + Perfil Rider)
@router.post("", status_code=201)
async def create_rider(
    body: RiderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE)),
):
    """
    [ADMIN/GERENTE] Crea un nuevo usuario con rol REPARTIDOR y su perfil asociado.
    Transaccional: si falla uno, no se guarda nada.
    """
    from app.core.security import hash_password
    
    existing_user = await db.execute(select(User).where(User.email == body.email))
    if existing_user.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="El email ya está registrado")

    first_name = body.first_name
    last_name = body.last_name

    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        first_name=first_name,
        last_name=last_name,
        phone=body.phone,
        role=UserRole.REPARTIDOR,
        is_active=True
    )
    db.add(user)
    await db.flush()
    
    rider = Rider(
        user_id=user.id,
        vehicle_type=_parse_vehicle_type(body.vehicle_type),
        vehicle_plate=body.vehicle_plate,
        vehicle_model=body.vehicle_model,
        operating_zone=body.operating_zone,
        cpf=body.cpf,
        cnh=body.cnh,
        status=RiderStatus.PENDIENTE
    )
    db.add(rider)
    await db.commit()
    await db.refresh(rider)
    await db.refresh(rider, attribute_names=['user'])
    
    return _rider_to_dict(rider, include_user=True)

# [ADMIN/GERENTE/OPERADOR] Listar todos los repartidores con filtros
@router.get("")
async def list_riders(
    status_filter: Optional[str] = Query(None, description="Filtro por estado"),
    is_online: Optional[bool] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE, UserRole.OPERADOR)),
):
    """
    [ADMIN/GERENTE/OPERADOR] Lista todos los repartidores con filtros opcionales.
    Incluye datos del usuario relacionado.
    """
    q = select(Rider).options(joinedload(Rider.user))
    
    if status_filter:
        try:
            q = q.where(Rider.status == RiderStatus(status_filter))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Estado inválido: {status_filter}")
    
    if is_online is not None:
        q = q.where(Rider.is_online.is_(is_online))
    
    q = q.order_by(Rider.created_at.desc())
    
    result = await db.execute(q)
    riders = result.scalars().all()
    
    return [_rider_to_dict(r) for r in riders]

# [REPARTIDOR] Obtener mi propio perfil
@router.get("/me")
async def get_my_rider_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    [REPARTIDOR] Obtiene el perfil completo del usuario autenticado.
    """
    stmt = select(Rider).options(joinedload(Rider.user)).where(Rider.user_id == current_user.id)
    result = await db.execute(select(Rider).where(Rider.user_id == current_user.id))
    rider = result.scalar_one_or_none()
    if not rider:
        raise HTTPException(status_code=404, detail="Perfil de repartidor no encontrado")
    return _rider_to_dict(rider)


# [REPARTIDOR] Actualizar mi propio perfil (Nombre, Vehículo, etc)
@router.put("/me")
async def update_my_rider_profile(
    body: RiderUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    [REPARTIDOR] Actualiza los datos de su propio perfil (User + Rider).
    MEJORA LOTE 12.1.2: Si cambia el vehículo, invalida documentos, bloquea la cuenta 
    y notifica a administración mediante Audit Log y Alertas en consola.
    """
    result = await db.execute(select(Rider).where(Rider.user_id == current_user.id))
    rider = result.scalar_one_or_none()
    
    if not rider:
        raise HTTPException(status_code=404, detail="Perfil de repartidor no encontrado")

    payload = body.model_dump(exclude_none=True)
    
    vehicle_changed = False
    old_vehicle_info = f"{rider.vehicle_type.value} - {rider.vehicle_plate}"
    new_vehicle_info = ""

    if "vehicle_type" in payload and str(payload["vehicle_type"]) != rider.vehicle_type.value:
        vehicle_changed = True
        new_vehicle_info = f"{payload['vehicle_type']} - {rider.vehicle_plate}"
        
    if "vehicle_plate" in payload and payload["vehicle_plate"] != rider.vehicle_plate:
        vehicle_changed = True
        if not new_vehicle_info:
            new_vehicle_info = f"{rider.vehicle_type.value} - {payload['vehicle_plate']}"
        else:
            new_vehicle_info = f"{new_vehicle_info.split(' - ')[0]} - {payload['vehicle_plate']}"

    if vehicle_changed:
        print(f"⚠️ ALERTA DE SEGURIDAD: El repartidor {current_user.email} ha solicitado cambio de vehículo.")
        print(f"   🔄 De: {old_vehicle_info}  -->  A: {new_vehicle_info}")
        
        docs_result = await db.execute(
            select(RiderDocument).where(RiderDocument.rider_id == rider.id)
        )
        documents = docs_result.scalars().all()
        
        for doc in documents:
            doc.status = DocumentStatus.RECHAZADO
            doc.rejection_reason = "Cambio de vehículo detectado. Por favor, suba la documentación nueva."
            doc.updated_at = utc_now_naive()
            
        print(f"   🗑️ {len(documents)} documentos marcados como RECHAZADOS automáticamente.")

        if rider.status == RiderStatus.ACTIVO:
            rider.status = RiderStatus.PENDIENTE
            print(f"   🚫 Estado del repartidor cambiado a PENDIENTE. Acceso a pedidos bloqueado.")

        try:
            from app.models.audit_log import ActionType, AuditLog
            audit_entry = AuditLog(
                id=uuid.uuid4(),
                user_id=current_user.id,
                user_email=current_user.email,
                user_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
                action_type=ActionType.UPDATE,
                resource_type="Rider",
                resource_id=str(rider.id),
                description="Solicitud de cambio de vehículo desde perfil",
                old_values={"vehicle": old_vehicle_info},
                new_values={
                    "vehicle": new_vehicle_info,
                    "documents_invalidated": len(documents),
                    "status_changed_to": "PENDIENTE",
                },
                changes_summary="Cambio de vehículo; documentos invalidados y rider pendiente",
                success=True,
                created_at=utc_now_naive(),
            )
            db.add(audit_entry)
            print(f"   📝 Registro de auditoría creado exitosamente.")
        except Exception as e:
            print(f"   ❌ Error al crear registro de auditoría: {str(e)}")

    if "vehicle_type" in payload:
        try:
            if isinstance(payload["vehicle_type"], str):
                payload["vehicle_type"] = VehicleType(payload["vehicle_type"])
        except ValueError:
            raise HTTPException(status_code=400, detail="Tipo de vehículo inválido.")

    for field, value in payload.items():
        if hasattr(rider, field) and field not in ["first_name", "last_name", "phone", "email"]:
            setattr(rider, field, value)

    user_updated = False
    if "first_name" in payload:
        current_user.first_name = payload["first_name"]
        user_updated = True
    if "last_name" in payload:
        current_user.last_name = payload["last_name"]
        user_updated = True
    if "phone" in payload:
        current_user.phone = payload["phone"]
        user_updated = True

    await db.commit()
    
    await db.refresh(rider)
    await db.refresh(current_user)
    
    response_data = _rider_to_dict(rider)
    
    if vehicle_changed:
        response_data["warning"] = "Su vehículo ha sido actualizado. Sus documentos han sido reiniciados y su cuenta está pendiente de aprobación nuevamente."
        response_data["status"] = "PENDIENTE"
    
    return response_data

# [ADMIN/GERENTE] Listar repartidores pendientes de aprobación
@router.get("/documents/pending")
async def get_pending_documents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE)),
):
    """
    [ADMIN/GERENTE] Lista repartidores cuyo estado general es PENDIENTE (esperando aprobación).
    Útil para bandejas de entrada de gestión.
    """
    result = await db.execute(
        select(Rider).where(
            Rider.status == RiderStatus.PENDIENTE
        ).order_by(Rider.created_at.desc())
    )
    riders = result.scalars().all()
    return [_rider_to_dict(r) for r in riders]

# ------------------------------------------------------------------------------
# ENDPOINTS GENÉRICOS POR ID ({rider_id})
# Deben ir al final para no interceptar rutas específicas como /me
# ------------------------------------------------------------------------------

@router.get("/{rider_id}")
async def get_rider(
    rider_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Obtiene el detalle de un repartidor específico por su ID.
    Valida permisos: el repartidor solo puede verse a sí mismo.
    ADMIN/GERENTE pueden ver todos los repartidores.
    """
    # Validar UUID
    rid = _parse_uuid(rider_id, "rider_id")
    
    # Cargar rider con relación user
    stmt = select(Rider).options(joinedload(Rider.user)).where(Rider.id == rid)
    result = await db.execute(stmt)
    rider = result.scalar_one_or_none()
    
    if not rider:
        raise HTTPException(status_code=404, detail="Repartidor no encontrado")
    
    # Validar permisos: REPARTIDOR solo puede verse a sí mismo
    # ADMIN/GERENTE/SUPERADMIN pueden ver cualquier rider
    if current_user.role == UserRole.REPARTIDOR:
        if rider.user_id != current_user.id:
            raise HTTPException(
                status_code=403, 
                detail="No tienes permiso para acceder a este repartidor. Solo puedes ver tu propio perfil."
            )
    
    return _rider_to_dict(rider)

# [ADMIN/REPARTIDOR] Actualizar datos de un repartidor específico
@router.patch("/{rider_id}")
async def update_rider(
    rider_id: str,
    body: RiderUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Actualiza datos de un repartidor específico.
    Usado por admins para corregir datos o por el propio rider (vía scope check).
    """
    result = await db.execute(select(Rider).where(Rider.id == _parse_uuid(rider_id, "rider_id")))
    rider = result.scalar_one_or_none()
    if not rider:
        raise HTTPException(status_code=404, detail="Repartidor no encontrado")
    await _ensure_rider_self_scope(db, current_user, rider)

    payload = body.model_dump(exclude_none=True)
    if "vehicle_type" in payload:
        payload["vehicle_type"] = _parse_vehicle_type(payload["vehicle_type"])

    for field, value in payload.items():
        setattr(rider, field, value)
    await db.commit()
    return _rider_to_dict(rider)

# [ADMIN/GERENTE] Aprobar manualmente a un repartidor
@router.patch("/{rider_id}/approve")
async def approve_rider(
    rider_id: str,
    body: Optional[ApproveRider] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE)),
):
    """
    [ADMIN/GERENTE] Aprueba manualmente a un repartidor (cambia estado a ACTIVO).
    """
    result = await db.execute(select(Rider).where(Rider.id == _parse_uuid(rider_id, "rider_id")))
    rider = result.scalar_one_or_none()
    if not rider:
        raise HTTPException(status_code=404, detail="Repartidor no encontrado")

    rider.status = RiderStatus.ACTIVO
    rider.approved_at = utc_now_naive()
    if body and body.observations:
        rider.notes = body.observations if hasattr(rider, 'notes') else rider.notes
    await db.commit()
    return {"message": "Repartidor aprobado exitosamente", "rider_id": rider_id}

# [ADMIN/GERENTE] Rechazar/Suspender a un repartidor
@router.post("/{rider_id}/reject")
async def reject_rider(
    rider_id: str,
    body: RejectRider,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE)),
):
    """
    [ADMIN/GERENTE] Rechaza/Suspende a un repartidor con un motivo obligatorio.
    """
    result = await db.execute(select(Rider).where(Rider.id == _parse_uuid(rider_id, "rider_id")))
    rider = result.scalar_one_or_none()
    if not rider:
        raise HTTPException(status_code=404, detail="Repartidor no encontrado")

    rider.status = RiderStatus.SUSPENDIDO
    await db.commit()
    return {"message": "Repartidor rechazado", "rider_id": rider_id}

# [ADMIN/GERENTE] Eliminar permanentemente un repartidor
@router.delete("/{rider_id}")
async def delete_rider(
    rider_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE)),
):
    """
    [ADMIN/GERENTE] Elimina permanentemente el perfil de un repartidor.
    """
    result = await db.execute(select(Rider).where(Rider.id == _parse_uuid(rider_id, "rider_id")))
    rider = result.scalar_one_or_none()
    if not rider:
        raise HTTPException(status_code=404, detail="Repartidor no encontrado")

    await db.delete(rider)
    await db.commit()
    return {"message": "Repartidor eliminado exitosamente", "rider_id": rider_id}

# [REPARTIDOR] Enviar heartbeat (ubicación + telemetría)
@router.patch("/{rider_id}/heartbeat")
async def update_heartbeat(
    rider_id: str,
    body: HeartbeatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    [REPARTIDOR] Endpoint crítico para telemetría en tiempo real.
    Actualiza ubicación GPS, marca al rider como ONLINE y guarda metadatos del dispositivo.
    Usa PostGIS para guardar la geometría espacial.
    """
    result = await db.execute(select(Rider).where(Rider.id == _parse_uuid(rider_id, "rider_id")))
    rider = result.scalar_one_or_none()
    
    if not rider:
        raise HTTPException(status_code=404, detail="Repartidor no encontrado")
    
    await _ensure_rider_self_scope(db, current_user, rider)

    rider.last_lat = body.lat
    rider.last_lng = body.lng
    rider.last_location = func.ST_SetSRID(func.ST_MakePoint(body.lng, body.lat), 4326)
    rider.last_location_at = utc_now_naive()
    rider.is_online = True

    await db.commit()
    
    return {
        "status": "ok", 
        "message": "Ubicación actualizada",
        "timestamp": rider.last_location_at
    }

# [REPARTIDOR] Actualizar ubicación simple (Legacy)
@router.patch("/{rider_id}/location")
async def update_location(
    rider_id: str,
    body: LocationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    [REPARTIDOR] Versión simplificada de actualización de ubicación (legacy).
    También actualiza la columna geoespacial.
    """
    result = await db.execute(select(Rider).where(Rider.id == _parse_uuid(rider_id, "rider_id")))
    rider = result.scalar_one_or_none()
    if not rider:
        raise HTTPException(status_code=404, detail="Repartidor no encontrado")
    await _ensure_rider_self_scope(db, current_user, rider)

    rider.last_lat = body.lat
    rider.last_lng = body.lng
    rider.last_location = func.ST_SetSRID(func.ST_MakePoint(body.lng, body.lat), 4326)
    rider.last_location_at = utc_now_naive()
    
    await db.commit()
    return {"ok": True}

# [REPARTIDOR] Cambiar estado Online/Offline manualmente
@router.patch("/{rider_id}/online")
async def toggle_online(
    rider_id: str,
    online: bool,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    [REPARTIDOR] Cambia manualmente el estado de conexión (Online/Offline).
    """
    result = await db.execute(select(Rider).where(Rider.id == _parse_uuid(rider_id, "rider_id")))
    rider = result.scalar_one_or_none()
    if not rider:
        raise HTTPException(status_code=404, detail="Repartidor no encontrado")
    await _ensure_rider_self_scope(db, current_user, rider)
    rider.is_online = online
    await db.commit()
    return {"is_online": rider.is_online}

# [ADMIN/GERENTE] Cambiar estado administrativo (Activo/Suspendido)
@router.patch("/{rider_id}/status")
async def update_rider_status(
    rider_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE)),
):
    """
    [ADMIN/GERENTE] Cambia el estado administrativo del repartidor (ACTIVO, SUSPENDIDO, INACTIVO).
    """
    result = await db.execute(select(Rider).where(Rider.id == _parse_uuid(rider_id, "rider_id")))
    rider = result.scalar_one_or_none()
    
    if not rider:
        raise HTTPException(status_code=404, detail="Repartidor no encontrado")

    new_status_str = body.get("status")
    if not new_status_str or new_status_str not in ["ACTIVO", "SUSPENDIDO", "INACTIVO"]:
        raise HTTPException(status_code=400, detail="Estado inválido. Use ACTIVO, SUSPENDIDO o INACTIVO.")

    try:
        rider.status = RiderStatus(new_status_str)
    except ValueError:
        rider.status = new_status_str

    await db.commit()
    await db.refresh(rider)

    return {
        "message": f"Estado actualizado a {new_status_str}",
        "rider_id": str(rider.id),
        "status": new_status_str
    }

# [ADMIN/OPERADOR] Buscar repartidores cercanos geográficamente
@router.post("/nearby")
async def get_nearby_riders(
    query: NearbyRidersQuery,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE, UserRole.OPERADOR)),
):
    """
    [ADMIN/OPERADOR] Busca repartidores activos y online en un radio geográfico específico.
    Usa cálculos esféricos (ST_DistanceSphere) para precisión en metros.
    """
    ref_point = func.ST_SetSRID(func.ST_MakePoint(query.lng, query.lat), 4326)
    radius_meters = query.radius_km * 1000

    stmt = (
        select(
            Rider,
            func.ST_DistanceSphere(Rider.last_location, ref_point).label('distance_meters')
        )
        .options(joinedload(Rider.user))
        .where(
            Rider.status == RiderStatus.ACTIVO,
            Rider.is_online == True,
            Rider.last_location.isnot(None),
            func.ST_DistanceSphere(Rider.last_location, ref_point) <= radius_meters
        )
        .order_by('distance_meters')
        .limit(query.limit)
    )
    
    result = await db.execute(stmt)
    rows = result.all()
    
    response = []
    for rider, distance in rows:
        data = _rider_to_dict(rider)
        data['distance_meters'] = round(distance, 2)
        data['distance_km'] = round(distance / 1000, 2)
        response.append(data)
        
    return {
        "center": {"lat": query.lat, "lng": query.lng},
        "radius_km": query.radius_km,
        "count": len(response),
        "riders": response
    }

# [ADMIN/GERENTE/OPERADOR] Ver documentos de un repartidor específico
@router.get("/{rider_id}/documents")
async def get_rider_documents(
    rider_id: str,
    current_user: User = Depends(require_role(UserRole.GERENTE, UserRole.SUPERADMIN, UserRole.OPERADOR)),
    db: AsyncSession = Depends(get_db)
):
    """
    [ADMIN/GERENTE/OPERADOR] Obtiene todos los documentos de un repartidor específico.
    NOTA: Esta ruta va al final deliberadamente para no interceptar /me/documents.
    """
    rider_result = await db.execute(select(Rider).where(Rider.id == _parse_uuid(rider_id, "rider_id")))
    rider = rider_result.scalar_one_or_none()
    
    if not rider:
        raise HTTPException(status_code=404, detail="Repartidor no encontrado")

    result = await db.execute(
        select(RiderDocument)
        .where(RiderDocument.rider_id == rider.id)
        .order_by(RiderDocument.created_at.desc())
    )
    documents = result.scalars().all()

    api_base = settings.API_BASE_URL if hasattr(settings, 'API_BASE_URL') else "http://localhost:8000"
    
    return [
        {
            "id": str(doc.id),
            "rider_id": str(doc.rider_id),
            "type": doc.type.value if hasattr(doc.type, 'value') else doc.type,
            "status": doc.status.value if hasattr(doc.status, 'value') else doc.status,
            "file_url": f"{api_base}/{doc.file_url}" if doc.file_url else None,
            "rejection_reason": doc.rejection_reason,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
            "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
        }
        for doc in documents
    ]