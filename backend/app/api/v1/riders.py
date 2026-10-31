from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
    UploadFile,
    File,
    Form,
    Header,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from sqlalchemy.orm import joinedload, load_only
from pydantic import BaseModel, Field
from typing import Optional, Any, List
from datetime import datetime, timezone, timedelta
import uuid
import logging
import os
import inspect

from fastapi.responses import FileResponse
from app.core.document_files import (
    document_download_url,
    resolve_document_file,
    document_revision,
    ensure_document_revision,
)
from app.services.document_uploads import validate_document, replace_document
from app.services.document_review import (
    document_readiness_error,
    lock_rider,
    restrict_rider_documents,
    ensure_rider_can_report_online,
    review_document,
    delete_reviewed_document,
)
from app.core.serialization import optional_enum_value
from app.core.database import get_db
from app.core.operation_permissions import ensure_operation_role
from app.core.config import settings
from app.models.rider import Rider, RiderStatus, VehicleType
from app.models.user import User, UserRole
from app.models.rider_document import RiderDocument, DocumentType, DocumentStatus
from app.models.order import Order, OrderStatus
from app.models.delivery import Delivery, DeliveryStatus
from app.models.financial import Financial, TransactionType, PaymentStatus
from app.models.payout import Payout, PayoutStatus
from app.models.enums import VehicleOwnershipType
from app.api.v1.auth import get_current_user, require_role
from app.services.financial_service import CREDIT_TYPES
from app.services.user_emails import claim_email, flush_email_change
from app.services.rider_profile_revision import (
    PROFILE_FIELDS,
    profile_revision,
    ensure_profile_revision,
)
from app.core.fleet_revision import assignment_revision
from app.core.vehicle_revision import vehicle_revision, ensure_vehicle_revision
from app.services.fleet_audit import record_fleet_change
from app.services.fleet_assignment import (
    VEHICLE_FIELDS,
    lock_vehicles,
    ensure_vehicle_available,
    prepare_vehicle_update,
    invalidate_vehicle_documents,
)

logger = logging.getLogger(__name__)

# El prefijo debe ser exactamente este para que coincida con lo que espera el frontend
router = APIRouter(prefix="/riders")


async def _ensure_rider_can_go_online(
    db: AsyncSession, rider: Rider, *, allow_busy: bool = False
) -> None:
    await ensure_rider_can_report_online(db, rider, allow_busy=allow_busy)


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

    # Campos para vehículo de empresa (opcionales, solo si vehicle_ownership_type es EMPRESA)
    vehicle_ownership_type: Optional[str] = "PROPIO"
    assigned_vehicle_id: Optional[uuid.UUID] = None
    expected_vehicle_revision: Optional[str] = Field(None, pattern=r"^[a-f0-9]{64}$")

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

    # Campos para vehículo de empresa (opcionales)
    vehicle_ownership_type: Optional[str] = None
    assigned_vehicle_id: Optional[uuid.UUID] = None
    expected_vehicle_revision: Optional[str] = Field(None, pattern=r"^[a-f0-9]{64}$")

    expected_assignment_revision: Optional[str] = Field(None, pattern=r"^[a-f0-9]{64}$")
    expected_profile_revision: Optional[str] = Field(None, pattern=r"^[a-f0-9]{64}$")

    # Campo para nivel/gamificación (Fase 4)
    tier: Optional[str] = None


def _ensure_rider_update_fields(current_user: User, body: RiderUpdate) -> None:
    """Administrative compensation and fleet assignment cannot be self-edited."""
    ensure_operation_role(current_user, write=True)
    protected = {"tier", "vehicle_ownership_type", "assigned_vehicle_id"}
    if protected.intersection(body.model_fields_set) and current_user.role not in (
        UserRole.SUPERADMIN,
        UserRole.GERENTE,
    ):
        raise HTTPException(
            status_code=403,
            detail="Solo gerencia puede cambiar el nivel o la asignación de flota",
        )


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
    rejection_reason: Optional[str] = Field(None, max_length=2000)
    expected_revision: Optional[str] = Field(None, pattern=r"^[a-f0-9]{64}$")


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


async def _ensure_rider_self_scope(
    db: AsyncSession, current_user: User, rider: Rider
) -> None:
    """
    Middleware de seguridad: Si el usuario es REPARTIDOR, verifica que solo pueda
    acceder/modificar su propio perfil. Si es ADMIN/GERENTE, permite todo.
    """
    if current_user.role != UserRole.REPARTIDOR:
        return
    current_rider = await _get_rider_for_user(db, current_user.id)
    if not current_rider or current_rider.id != rider.id:
        raise HTTPException(
            status_code=403, detail="No tienes permiso para acceder a este repartidor"
        )


def _rider_to_dict(r: Rider, include_user: bool = False) -> dict:
    full_name = "Desconocido"
    email = ""
    phone = ""

    # CRUCIAL: Verificar si la relación 'user' fue cargada
    if hasattr(r, "user") and r.user:
        full_name = f"{r.user.first_name} {r.user.last_name}"
        email = r.user.email
        phone = r.user.phone or ""
    else:
        pass

    d: dict[str, Any] = {
        "id": str(r.id),
        "user_id": str(r.user_id),
        "status": optional_enum_value(r.status),
        "tier": (
            r.tier.value if hasattr(r.tier, "value") else r.tier
        ),  # ✅ AGREGADO: Campo tier para gamificación
        "vehicle_type": optional_enum_value(r.vehicle_type),
        "assignment_revision": assignment_revision(r),
        "profile_revision": profile_revision(r),
        "vehicle_plate": r.vehicle_plate or "",
        "vehicle_model": r.vehicle_model,
        "operating_zone": r.operating_zone,
        "is_online": r.is_online,
        "last_lat": r.last_lat,
        "last_lng": r.last_lng,
        "last_location_at": (
            r.last_location_at.isoformat() if r.last_location_at else None
        ),
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
        # Campos de vehículo de empresa
        "vehicle_ownership_type": (
            r.vehicle_ownership_type
            if hasattr(r, "vehicle_ownership_type") and r.vehicle_ownership_type
            else "PROPIO"
        ),
        "assigned_vehicle_id": (
            str(r.assigned_vehicle_id) if r.assigned_vehicle_id else None
        ),
    }

    # Incluir datos del vehículo asignado si existe
    if hasattr(r, "assigned_vehicle") and r.assigned_vehicle:
        d["assigned_vehicle"] = {
            "id": str(r.assigned_vehicle.id),
            "revision": vehicle_revision(r.assigned_vehicle),
            "plate": r.assigned_vehicle.plate,
            "model": r.assigned_vehicle.model,
            "type": r.assigned_vehicle.type,
            "color": r.assigned_vehicle.color,
            "year": r.assigned_vehicle.year,
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
        raise HTTPException(
            status_code=403, detail="Solo repartidores pueden acceder a sus documentos"
        )

    rider_id = await db.scalar(select(Rider.id).where(Rider.user_id == current_user.id))
    if rider_id is None:
        return []

    docs_result = await db.execute(
        select(RiderDocument)
        .where(RiderDocument.rider_id == rider_id)
        .order_by(RiderDocument.created_at.desc())
        .execution_options(populate_existing=True)
    )
    documents = docs_result.scalars().all()

    return [
        {
            "id": str(d.id),
            "type": d.type.value,
            "status": d.status.value,
            "file_url": document_download_url(d.id, d.file_url),
            "revision": document_revision(d),
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
        raise HTTPException(
            status_code=403, detail="Solo repartidores pueden subir documentos"
        )

    try:
        doc_type = DocumentType(type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo inválido. Opciones: {[t.value for t in DocumentType]}",
        )

    rider_id = await db.scalar(select(Rider.id).where(Rider.user_id == current_user.id))
    if rider_id is None:
        raise HTTPException(
            status_code=404, detail="Perfil de repartidor no encontrado"
        )
    document = await validate_document(file)
    return await replace_document(db, rider_id, doc_type, document, allow_pending=False)


@router.get("/documents/{doc_id}/download")
async def download_document(
    doc_id: uuid.UUID,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    allowed_staff = (UserRole.SUPERADMIN, UserRole.GERENTE, UserRole.OPERADOR)
    if current_user.role not in (*allowed_staff, UserRole.REPARTIDOR):
        raise HTTPException(
            status_code=403, detail="No autorizado para consultar documentos"
        )
    doc = await db.scalar(
        select(RiderDocument)
        .where(RiderDocument.id == doc_id)
        .execution_options(populate_existing=True)
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    if current_user.role == UserRole.REPARTIDOR:
        owner = await db.scalar(select(Rider.user_id).where(Rider.id == doc.rider_id))
        if owner != current_user.id:
            raise HTTPException(status_code=404, detail="Documento no encontrado")
    if if_match is not None:
        ensure_document_revision(doc, if_match)
    path = resolve_document_file(doc.rider_id, doc.file_url)
    extension = (
        path.suffix.lower()
        if path.suffix.lower() in (".pdf", ".png", ".jpg", ".jpeg")
        else ".bin"
    )
    return FileResponse(
        path,
        media_type={
            ".pdf": "application/pdf",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
        }.get(extension, "application/octet-stream"),
        filename=f"documento-{doc.id}{extension}",
        headers={
            "Cache-Control": "private, no-store",
            "Pragma": "no-cache",
            "Vary": "Authorization",
            "ETag": f'"{document_revision(doc)}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


# [ADMIN/GERENTE] Aprobar o rechazar documento específico
@router.patch("/documents/{doc_id}/status")
async def update_document_status(
    doc_id: str,
    status_update: DocumentStatusUpdate,
    current_user: User = Depends(require_role(UserRole.GERENTE, UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    [ADMIN/GERENTE] Aprueba o rechaza un documento específico.
    Si se aprueba y todos los documentos del rider están listos, activa al rider automáticamente.
    """
    try:
        target = DocumentStatus(status_update.status)
    except ValueError:
        raise HTTPException(status_code=400, detail="Estado de documento inválido")
    response = await review_document(
        db,
        _parse_uuid(doc_id, "doc_id"),
        target,
        status_update.expected_revision,
        status_update.rejection_reason,
    )
    await db.commit()
    return response


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
    rid = _parse_uuid(rider_id, "rider_id")
    try:
        doc_type = DocumentType(type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Tipo de documento inválido")
    document = await validate_document(file)
    response = await replace_document(db, rid, doc_type, document, allow_pending=True)
    response["message"] = "Documento subido exitosamente por administrador."
    return response


# [ADMIN/GERENTE] Eliminar permanentemente un documento
@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: str,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.GERENTE, UserRole.SUPERADMIN)),
):
    """
    [ADMIN/GERENTE] Elimina permanentemente un documento de la base de datos.
    Útil para limpiar documentos corruptos, duplicados o subidos por error.
    """
    response = await delete_reviewed_document(
        db, _parse_uuid(doc_id, "doc_id"), if_match
    )
    await db.commit()
    return response


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

    Soporta dos modalidades:
    - Vehículo Propio: body.vehicle_ownership_type="PROPIO" (default), se usan vehicle_plate/model
    - Vehículo Empresa: body.vehicle_ownership_type="EMPRESA", se usa assigned_vehicle_id
    """
    from app.core.security import hash_password
    from sqlalchemy import select

    canonical_email = await claim_email(db, body.email)

    # Validación: Si es EMPRESA, debe proporcionar assigned_vehicle_id
    if body.vehicle_ownership_type == "EMPRESA" and not body.assigned_vehicle_id:
        raise HTTPException(
            status_code=400,
            detail="Cuando vehicle_ownership_type es EMPRESA, debe proporcionar assigned_vehicle_id",
        )

    # Validación: Si es PROPIO, debería tener al menos placa o modelo (opcional, pero recomendado)
    if (
        body.vehicle_ownership_type == "PROPIO"
        and not body.vehicle_plate
        and not body.vehicle_model
    ):
        # No es error crítico, solo advertencia en logs
        logger.warning(
            f"Rider {body.email} creado como PROPIO sin placa ni modelo de vehículo"
        )

    first_name = body.first_name
    last_name = body.last_name

    user = User(
        email=canonical_email,
        hashed_password=hash_password(body.password),
        first_name=first_name,
        last_name=last_name,
        phone=body.phone,
        role=UserRole.REPARTIDOR,
        is_active=True,
    )
    db.add(user)
    await flush_email_change(db)

    if body.vehicle_ownership_type not in (None, "PROPIO", "EMPRESA"):
        raise HTTPException(status_code=422, detail="Propiedad de vehículo inválida")
    vehicle = None
    if body.vehicle_ownership_type == "EMPRESA" and body.assigned_vehicle_id:
        vehicles = await lock_vehicles(db, {body.assigned_vehicle_id})
        vehicle = vehicles[body.assigned_vehicle_id]
        ensure_vehicle_revision(vehicle, body.expected_vehicle_revision)
        await ensure_vehicle_available(db, vehicle, user.id)

    rider = Rider(
        user_id=user.id,
        vehicle_type=_parse_vehicle_type(
            vehicle.type if vehicle else body.vehicle_type
        ),
        vehicle_plate=vehicle.plate if vehicle else body.vehicle_plate,
        vehicle_model=vehicle.model if vehicle else body.vehicle_model,
        operating_zone=body.operating_zone,
        cpf=body.cpf,
        cnh=body.cnh,
        vehicle_ownership_type=body.vehicle_ownership_type or "PROPIO",
        assigned_vehicle_id=(
            body.assigned_vehicle_id
            if body.vehicle_ownership_type == "EMPRESA"
            else None
        ),
        status=RiderStatus.PENDIENTE,
    )
    db.add(rider)

    if vehicle is not None:
        vehicle.rider_id = user.id

    await db.flush()
    await record_fleet_change(
        db,
        rider,
        current_user,
        before=None,
        source="admin_create",
        selected_vehicle_revision=(
            body.expected_vehicle_revision
            if rider.vehicle_ownership_type == "EMPRESA"
            else None
        ),
    )

    await db.commit()
    await db.refresh(rider)
    await db.refresh(rider, attribute_names=["user"])

    # Cargar el vehículo asignado si existe
    if rider.assigned_vehicle_id:
        await db.refresh(rider, attribute_names=["assigned_vehicle"])

    return _rider_to_dict(rider, include_user=True)


# [ADMIN/GERENTE/OPERADOR] Listar todos los repartidores con filtros
@router.get("")
async def list_riders(
    status_filter: Optional[str] = Query(None, description="Filtro por estado"),
    is_online: Optional[bool] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.SUPERADMIN, UserRole.GERENTE, UserRole.OPERADOR)
    ),
):
    """
    [ADMIN/GERENTE/OPERADOR] Lista todos los repartidores con filtros opcionales.
    Incluye datos del usuario relacionado y vehículo asignado si corresponde.
    """
    q = select(Rider).options(
        joinedload(Rider.user), joinedload(Rider.assigned_vehicle)
    )

    if status_filter:
        try:
            q = q.where(Rider.status == RiderStatus(status_filter))
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"Estado inválido: {status_filter}"
            )

    if is_online is not None:
        q = q.where(Rider.is_online.is_(is_online))

    q = q.order_by(Rider.created_at.desc())

    result = await db.execute(q)
    riders = result.unique().scalars().all()

    return [_rider_to_dict(r) for r in riders]


# [REPARTIDOR] Obtener mi propio perfil
@router.get("/me")
async def get_my_rider_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    [REPARTIDOR] Obtiene el perfil completo del usuario autenticado.
    Carga de forma asíncrona las relaciones user y assigned_vehicle.
    """
    # Usamos selectinload para carga asíncrona correcta de relaciones
    stmt = (
        select(Rider)
        .options(joinedload(Rider.user), joinedload(Rider.assigned_vehicle))
        .where(Rider.user_id == current_user.id)
        .execution_options(populate_existing=True)
    )
    result = await db.execute(stmt)
    rider = result.unique().scalar_one_or_none()
    if not rider:
        raise HTTPException(
            status_code=404, detail="Perfil de repartidor no encontrado"
        )
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
    Los cambios de vehículo invalidan documentos y registran la auditoría
    en la misma transacción que el perfil y sus vínculos de flota.
    """
    _ensure_rider_update_fields(current_user, body)
    result = await db.execute(
        select(Rider)
        .options(joinedload(Rider.user))
        .where(Rider.user_id == current_user.id)
    )
    rider = result.unique().scalar_one_or_none()

    if not rider:
        raise HTTPException(
            status_code=404, detail="Perfil de repartidor no encontrado"
        )

    payload = body.model_dump(
        exclude_none=True,
        exclude={
            "expected_assignment_revision",
            "expected_vehicle_revision",
            "expected_profile_revision",
        },
    )
    before_state: dict = {}
    vehicle_changed = False
    if VEHICLE_FIELDS.intersection(payload):
        vehicle_changed = await prepare_vehicle_update(
            db,
            rider,
            payload,
            body.expected_assignment_revision,
            before_state=before_state,
            expected_vehicle_revision=body.expected_vehicle_revision,
        )
    if PROFILE_FIELDS.intersection(payload):
        await ensure_profile_revision(db, rider, body.expected_profile_revision)
    if "vehicle_type" in payload:
        try:
            if isinstance(payload["vehicle_type"], str):
                payload["vehicle_type"] = VehicleType(payload["vehicle_type"])
        except ValueError:
            raise HTTPException(status_code=400, detail="Tipo de vehículo inválido.")

    # Manejar el campo tier (nivel) si está presente
    if "tier" in payload:
        try:
            from app.models.rider import RiderTier

            if isinstance(payload["tier"], str):
                payload["tier"] = RiderTier(payload["tier"])
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Nivel inválido. Valores permitidos: BRONCE, PLATA, ORO, PLATINO",
            )

    for field, value in payload.items():
        if hasattr(rider, field) and field not in [
            "first_name",
            "last_name",
            "phone",
            "email",
        ]:
            setattr(rider, field, value)

    if "first_name" in payload:
        rider.user.first_name = payload["first_name"]
    if "last_name" in payload:
        rider.user.last_name = payload["last_name"]
    if "phone" in payload:
        rider.user.phone = payload["phone"]

    if vehicle_changed:
        count = await invalidate_vehicle_documents(db, rider.id)
        await db.refresh(rider, attribute_names=["status", "is_online"])
        await record_fleet_change(
            db,
            rider,
            current_user,
            before=before_state,
            source="self_profile",
            documents_invalidated=count,
            selected_vehicle_revision=(
                body.expected_vehicle_revision
                if rider.vehicle_ownership_type == "EMPRESA"
                else None
            ),
        )

    await db.commit()

    refreshed = await db.execute(
        select(Rider)
        .options(joinedload(Rider.user), joinedload(Rider.assigned_vehicle))
        .where(Rider.id == rider.id)
    )
    rider = refreshed.unique().scalar_one()

    response_data = _rider_to_dict(rider)

    if vehicle_changed:
        response_data["warning"] = (
            "Su vehículo ha sido actualizado. Sus documentos requieren revisión y su disponibilidad ha sido deshabilitada."
        )
        response_data["status"] = optional_enum_value(rider.status)

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
        select(Rider)
        .where(Rider.status == RiderStatus.PENDIENTE)
        .order_by(Rider.created_at.desc())
    )
    riders = result.scalars().all()
    return [_rider_to_dict(r) for r in riders]


@router.get("/audit/summary")
async def get_riders_audit_summary(
    status_filter: Optional[str] = Query(
        None, description="Filtro opcional por estado del rider"
    ),
    is_online: Optional[bool] = Query(
        None, description="Filtro opcional por disponibilidad online"
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE)),
):
    """
    Vista agregada para managers: órdenes, entregas, SLA, ganancias y retiros
    agrupados por repartidor sin multiplicar totales por JOINs cruzados.
    """
    if status_filter:
        try:
            rider_status = RiderStatus(status_filter)
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"Estado inválido: {status_filter}"
            )
    else:
        rider_status = None

    orders_assigned = (
        select(func.count(Order.id))
        .where(Order.assigned_rider_id == Rider.id)
        .correlate(Rider)
        .scalar_subquery()
    )
    orders_delivered = (
        select(func.count(Order.id))
        .where(
            Order.assigned_rider_id == Rider.id, Order.status == OrderStatus.ENTREGADO
        )
        .correlate(Rider)
        .scalar_subquery()
    )
    orders_active = (
        select(func.count(Order.id))
        .where(
            Order.assigned_rider_id == Rider.id,
            Order.status.in_(
                [
                    OrderStatus.ASIGNADO,
                    OrderStatus.EN_RECOLECCION,
                    OrderStatus.RECOLECTADO,
                    OrderStatus.EN_RUTA,
                ]
            ),
        )
        .correlate(Rider)
        .scalar_subquery()
    )
    deliveries_total = (
        select(func.count(Delivery.id))
        .where(Delivery.rider_id == Rider.id)
        .correlate(Rider)
        .scalar_subquery()
    )
    deliveries_completed = (
        select(func.count(Delivery.id))
        .where(
            Delivery.rider_id == Rider.id, Delivery.status == DeliveryStatus.COMPLETADA
        )
        .correlate(Rider)
        .scalar_subquery()
    )
    deliveries_failed = (
        select(func.count(Delivery.id))
        .where(Delivery.rider_id == Rider.id, Delivery.status == DeliveryStatus.FALLIDA)
        .correlate(Rider)
        .scalar_subquery()
    )
    deliveries_in_progress = (
        select(func.count(Delivery.id))
        .where(
            Delivery.rider_id == Rider.id,
            Delivery.status.in_(
                [
                    DeliveryStatus.INICIADA,
                    DeliveryStatus.EN_PICKUP,
                    DeliveryStatus.EN_ROUTE,
                    DeliveryStatus.EN_DESTINO,
                ]
            ),
        )
        .correlate(Rider)
        .scalar_subquery()
    )
    sla_compliant = (
        select(func.count(Delivery.id))
        .where(Delivery.rider_id == Rider.id, Delivery.sla_compliant.is_(True))
        .correlate(Rider)
        .scalar_subquery()
    )
    total_earned = (
        select(func.coalesce(func.sum(Financial.amount), 0))
        .where(
            Financial.rider_id == Rider.id,
            Financial.transaction_type.in_(list(CREDIT_TYPES)),
            Financial.status == PaymentStatus.PROCESADO,
        )
        .correlate(Rider)
        .scalar_subquery()
    )
    pending_payouts = (
        select(func.coalesce(func.sum(Payout.amount), 0))
        .where(Payout.rider_id == Rider.id, Payout.status == PayoutStatus.PENDIENTE)
        .correlate(Rider)
        .scalar_subquery()
    )

    stmt = (
        select(
            Rider,
            User,
            orders_assigned.label("orders_assigned"),
            orders_delivered.label("orders_delivered"),
            orders_active.label("orders_active"),
            deliveries_total.label("deliveries_total"),
            deliveries_completed.label("deliveries_completed"),
            deliveries_failed.label("deliveries_failed"),
            deliveries_in_progress.label("deliveries_in_progress"),
            sla_compliant.label("sla_compliant"),
            total_earned.label("total_earned"),
            pending_payouts.label("pending_payouts"),
        )
        .join(User, Rider.user_id == User.id)
        .order_by(Rider.is_online.desc(), User.first_name.asc(), User.last_name.asc())
        .limit(limit)
        .offset(offset)
    )

    if rider_status:
        stmt = stmt.where(Rider.status == rider_status)
    if is_online is not None:
        stmt = stmt.where(Rider.is_online.is_(is_online))

    result = await db.execute(stmt)
    rows = result.all()

    items = []
    for (
        rider,
        user,
        assigned,
        delivered,
        active,
        total_deliveries,
        completed,
        failed,
        in_progress,
        sla_ok,
        earned,
        pending,
    ) in rows:
        total_deliveries_int = int(total_deliveries or 0)
        sla_ok_int = int(sla_ok or 0)
        sla_rate = (
            round((sla_ok_int / total_deliveries_int) * 100, 2)
            if total_deliveries_int
            else 0.0
        )
        first_name = user.first_name or ""
        last_name = user.last_name or ""

        items.append(
            {
                "rider_id": str(rider.id),
                "user_id": str(user.id),
                "email": user.email,
                "first_name": first_name,
                "last_name": last_name,
                "full_name": f"{first_name} {last_name}".strip() or user.email,
                "phone": user.phone,
                "status": optional_enum_value(rider.status),
                "is_online": bool(rider.is_online),
                "vehicle_type": optional_enum_value(rider.vehicle_type),
                "vehicle_plate": rider.vehicle_plate,
                "operating_zone": rider.operating_zone,
                "zone_id": str(rider.zone_id) if rider.zone_id else None,
                "current_order_id": (
                    str(rider.current_order_id) if rider.current_order_id else None
                ),
                "last_lat": rider.last_lat,
                "last_lng": rider.last_lng,
                "last_location_at": (
                    rider.last_location_at.isoformat()
                    if rider.last_location_at
                    else None
                ),
                "orders_assigned": int(assigned or 0),
                "orders_delivered": int(delivered or 0),
                "orders_active": int(active or 0),
                "deliveries_total": total_deliveries_int,
                "deliveries_completed": int(completed or 0),
                "deliveries_failed": int(failed or 0),
                "deliveries_in_progress": int(in_progress or 0),
                "sla_compliant": sla_ok_int,
                "sla_compliance_rate": sla_rate,
                "total_earned": float(earned or 0),
                "pending_payouts": float(pending or 0),
                "available_to_payout": max(
                    float(earned or 0) - float(pending or 0), 0.0
                ),
            }
        )

    return {"items": items, "total": len(items), "limit": limit, "offset": offset}


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
    stmt = (
        select(Rider)
        .options(joinedload(Rider.user))
        .where(Rider.id == rid)
        .execution_options(populate_existing=True)
    )
    result = await db.execute(stmt)
    rider = result.unique().scalar_one_or_none()

    if not rider:
        raise HTTPException(status_code=404, detail="Repartidor no encontrado")

    # Validar permisos: REPARTIDOR solo puede verse a sí mismo
    # ADMIN/GERENTE/SUPERADMIN pueden ver cualquier rider
    if current_user.role == UserRole.REPARTIDOR:
        if rider.user_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso para acceder a este repartidor. Solo puedes ver tu propio perfil.",
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

    Soporta actualización de vehículo de empresa:
    - Si vehicle_ownership_type es EMPRESA, debe proporcionar assigned_vehicle_id
    - Si vehicle_ownership_type es PROPIO, limpia assigned_vehicle_id
    """
    _ensure_rider_update_fields(current_user, body)
    result = await db.execute(
        select(Rider)
        .options(joinedload(Rider.user))
        .where(Rider.id == _parse_uuid(rider_id, "rider_id"))
    )
    rider = result.unique().scalar_one_or_none()
    if not rider:
        raise HTTPException(status_code=404, detail="Repartidor no encontrado")
    await _ensure_rider_self_scope(db, current_user, rider)

    payload = body.model_dump(
        exclude_none=True,
        exclude={
            "expected_assignment_revision",
            "expected_vehicle_revision",
            "expected_profile_revision",
        },
    )

    before_state: dict = {}
    vehicle_changed = False
    if VEHICLE_FIELDS.intersection(payload):
        vehicle_changed = await prepare_vehicle_update(
            db,
            rider,
            payload,
            body.expected_assignment_revision,
            before_state=before_state,
            expected_vehicle_revision=body.expected_vehicle_revision,
        )

    if PROFILE_FIELDS.intersection(payload):
        await ensure_profile_revision(db, rider, body.expected_profile_revision)

    if "vehicle_type" in payload:
        payload["vehicle_type"] = _parse_vehicle_type(payload["vehicle_type"])

    # Manejar el campo tier (nivel) si está presente
    if "tier" in payload:
        try:
            from app.models.rider import RiderTier

            if isinstance(payload["tier"], str):
                payload["tier"] = RiderTier(payload["tier"])
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Nivel inválido. Valores permitidos: BRONCE, PLATA, ORO, PLATINO",
            )

    for field, value in payload.items():
        if field in {"first_name", "last_name", "phone"}:
            setattr(rider.user, field, value)
        else:
            setattr(rider, field, value)

    if vehicle_changed:
        await db.flush()
        count = await invalidate_vehicle_documents(db, rider.id)
        await db.refresh(rider, attribute_names=["status", "is_online"])
        await record_fleet_change(
            db,
            rider,
            current_user,
            before=before_state,
            source="rider_patch",
            documents_invalidated=count,
            selected_vehicle_revision=(
                body.expected_vehicle_revision
                if rider.vehicle_ownership_type == "EMPRESA"
                else None
            ),
        )

    await db.commit()

    # Recargar el vehículo asignado si existe
    if rider.assigned_vehicle_id:
        await db.refresh(rider, attribute_names=["assigned_vehicle"])

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
    rid = _parse_uuid(rider_id, "rider_id")
    await lock_rider(db, rid)
    error = await document_readiness_error(db, rid)
    if error:
        await restrict_rider_documents(db, rid)
        await db.commit()
        raise HTTPException(
            status_code=400, detail=f"No se puede aprobar el repartidor. {error}"
        )
    values = {
        "status": RiderStatus.ACTIVO,
        "approved_at": utc_now_naive(),
        "is_online": False,
    }
    if body and body.observations:
        values["notes"] = body.observations
    await db.execute(update(Rider).where(Rider.id == rid).values(**values))
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
    rid = _parse_uuid(rider_id, "rider_id")
    await lock_rider(db, rid)
    await db.execute(
        update(Rider)
        .where(Rider.id == rid)
        .values(status=RiderStatus.SUSPENDIDO, is_online=False)
    )
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
    result = await db.execute(
        select(Rider).where(Rider.id == _parse_uuid(rider_id, "rider_id"))
    )
    rider = result.unique().scalar_one_or_none()
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
    result = await db.execute(
        select(Rider)
        .options(
            load_only(
                Rider.id,
                Rider.user_id,
                Rider.status,
                Rider.is_online,
                Rider.approved_at,
            )
        )
        .where(Rider.id == _parse_uuid(rider_id, "rider_id"))
    )
    rider = result.unique().scalar_one_or_none()

    if not rider:
        raise HTTPException(status_code=404, detail="Repartidor no encontrado")

    await _ensure_rider_self_scope(db, current_user, rider)
    await _ensure_rider_can_go_online(db, rider, allow_busy=True)

    rider.last_lat = body.lat
    rider.last_lng = body.lng
    rider.last_location = func.ST_SetSRID(func.ST_MakePoint(body.lng, body.lat), 4326)
    rider.last_location_at = utc_now_naive()
    rider.is_online = True

    await db.commit()

    return {
        "status": "ok",
        "message": "Ubicación actualizada",
        "timestamp": rider.last_location_at,
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
    result = await db.execute(
        select(Rider).where(Rider.id == _parse_uuid(rider_id, "rider_id"))
    )
    rider = result.unique().scalar_one_or_none()
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
    result = await db.execute(
        select(Rider)
        .options(
            load_only(
                Rider.id,
                Rider.user_id,
                Rider.status,
                Rider.is_online,
                Rider.approved_at,
            )
        )
        .where(Rider.id == _parse_uuid(rider_id, "rider_id"))
    )
    rider = result.unique().scalar_one_or_none()
    if not rider:
        raise HTTPException(status_code=404, detail="Repartidor no encontrado")
    await _ensure_rider_self_scope(db, current_user, rider)
    if online:
        await _ensure_rider_can_go_online(db, rider)
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
    rid = _parse_uuid(rider_id, "rider_id")
    new_status = body.get("status")
    if new_status not in ("ACTIVO", "SUSPENDIDO", "INACTIVO"):
        raise HTTPException(
            status_code=400, detail="Estado inválido. Use ACTIVO, SUSPENDIDO o INACTIVO"
        )
    await lock_rider(db, rid)
    if new_status == "ACTIVO":
        error = await document_readiness_error(db, rid)
        if error:
            await restrict_rider_documents(db, rid)
            await db.commit()
            raise HTTPException(
                status_code=409, detail=f"La documentación requiere revisión. {error}"
            )
    await db.execute(
        update(Rider)
        .where(Rider.id == rid)
        .values(status=RiderStatus(new_status), is_online=False)
    )
    await db.commit()
    return {
        "message": f"Estado actualizado a {new_status}",
        "rider_id": str(rid),
        "status": new_status,
    }


# [ADMIN/OPERADOR] Buscar repartidores cercanos geográficamente
@router.post("/nearby")
async def get_nearby_riders(
    query: NearbyRidersQuery,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.SUPERADMIN, UserRole.GERENTE, UserRole.OPERADOR)
    ),
):
    """
    [ADMIN/OPERADOR] Busca repartidores activos y online en un radio geográfico específico.
    Usa cálculos esféricos (ST_DistanceSphere) para precisión en metros.
    """
    ref_point = func.ST_SetSRID(func.ST_MakePoint(query.lng, query.lat), 4326)
    if query.radius_km is None:
        raise HTTPException(
            status_code=422, detail="Indique un radio de búsqueda válido"
        )
    radius_meters = query.radius_km * 1000

    stmt = (
        select(
            Rider,
            func.ST_DistanceSphere(Rider.last_location, ref_point).label(
                "distance_meters"
            ),
        )
        .options(joinedload(Rider.user))
        .where(
            Rider.status == RiderStatus.ACTIVO,
            Rider.is_online == True,
            Rider.last_location.isnot(None),
            func.ST_DistanceSphere(Rider.last_location, ref_point) <= radius_meters,
        )
        .order_by("distance_meters")
        .limit(query.limit)
    )

    result = await db.execute(stmt)
    rows = result.all()

    response = []
    for rider, distance in rows:
        data = _rider_to_dict(rider)
        data["distance_meters"] = round(distance, 2)
        data["distance_km"] = round(distance / 1000, 2)
        response.append(data)

    return {
        "center": {"lat": query.lat, "lng": query.lng},
        "radius_km": query.radius_km,
        "count": len(response),
        "riders": response,
    }


# [ADMIN/GERENTE/OPERADOR] Ver documentos de un repartidor específico
@router.get("/{rider_id}/documents")
async def get_rider_documents(
    rider_id: str,
    current_user: User = Depends(
        require_role(UserRole.GERENTE, UserRole.SUPERADMIN, UserRole.OPERADOR)
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    [ADMIN/GERENTE/OPERADOR] Obtiene todos los documentos de un repartidor específico.
    NOTA: Esta ruta va al final deliberadamente para no interceptar /me/documents.
    """
    rider_uuid = _parse_uuid(rider_id, "rider_id")
    if await db.scalar(select(Rider.id).where(Rider.id == rider_uuid)) is None:
        raise HTTPException(status_code=404, detail="Repartidor no encontrado")

    result = await db.execute(
        select(RiderDocument)
        .where(RiderDocument.rider_id == rider_uuid)
        .order_by(RiderDocument.created_at.desc())
        .execution_options(populate_existing=True)
    )
    documents = result.scalars().all()

    return [
        {
            "id": str(doc.id),
            "rider_id": str(doc.rider_id),
            "type": doc.type.value if hasattr(doc.type, "value") else doc.type,
            "status": doc.status.value if hasattr(doc.status, "value") else doc.status,
            "file_url": document_download_url(doc.id, doc.file_url),
            "revision": document_revision(doc),
            "rejection_reason": doc.rejection_reason,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
            "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
        }
        for doc in documents
    ]
