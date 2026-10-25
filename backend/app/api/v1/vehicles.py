from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
    Path,
    Response,
    Header,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Optional, List, Any, Annotated
from datetime import date, datetime, timezone
import uuid
import logging

# Importación de Enums compartidos
from app.models.enums import VehicleType, VehicleStatus, VehicleOwnershipType
from app.core.database import get_db
from app.models.user import User, UserRole
from app.models.vehicle import Vehicle
from app.core.vehicle_revision import (
    vehicle_revision,
    vehicle_edit_revision,
    ensure_vehicle_edit_revision,
)
from app.services.fleet_assignment import (
    lock_vehicles,
    ensure_vehicle_unassigned,
    available_vehicle_condition,
)
from app.services.fleet_reconciliation import (
    FleetFindingCode,
    FleetReconciliationReport,
    reconcile_fleet,
)
from app.services.vehicle_plates import (
    normalize_vehicle_plate,
    claim_vehicle_plate,
    vehicle_plate_integrity,
)
from app.services.vehicle_inventory_audit import (
    inventory_snapshot,
    record_inventory_change,
)
from app.api.v1.auth import get_current_user, require_role

logger = logging.getLogger(__name__)

# ==============================================================================
# CONFIGURACIÓN DEL ROUTER
# ==============================================================================
router = APIRouter(prefix="/vehicles", tags=["Vehicles"])

# ==============================================================================
# SCHEMAS (Modelos de Datos)
# ==============================================================================


class VehicleCreate(BaseModel):
    """Datos para crear un nuevo vehículo."""

    plate: str = Field(
        ..., min_length=1, max_length=20, description="Placa o patente del vehículo"
    )
    type: VehicleType
    model: str = Field(
        ..., min_length=1, max_length=100, description="Modelo del vehículo"
    )
    color: str = Field(..., min_length=1, max_length=50, description="Color principal")
    year: int = Field(..., ge=1900, le=2100, description="Año de fabricación")
    insurance_expiry: Optional[date] = Field(
        None, description="Fecha de vencimiento del seguro (YYYY-MM-DD)"
    )
    notes: Optional[str] = Field(None, description="Notas adicionales")

    @field_validator("model", "color", mode="before")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("plate", mode="before")
    @classmethod
    def _normalize_plate(cls, value: str) -> str:
        return normalize_vehicle_plate(value)

    model_config = ConfigDict(use_enum_values=True)


class VehicleUpdate(BaseModel):
    """Datos parciales para actualizar un vehículo."""

    plate: Optional[str] = Field(None, min_length=1, max_length=20)
    type: Optional[VehicleType] = None
    model: Optional[str] = Field(None, min_length=1, max_length=100)
    color: Optional[str] = Field(None, min_length=1, max_length=50)
    year: Optional[int] = Field(None, ge=1900, le=2100)
    status: Optional[VehicleStatus] = None
    insurance_expiry: Optional[date] = None
    notes: Optional[str] = None

    @field_validator("model", "color", mode="before")
    @classmethod
    def _strip_optional_text(cls, value: Optional[str]) -> Optional[str]:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("plate", mode="before")
    @classmethod
    def _normalize_plate(cls, value: Optional[str]) -> Optional[str]:
        return normalize_vehicle_plate(value) if value is not None else None

    model_config = ConfigDict(use_enum_values=True)


class VehicleResponse(BaseModel):
    """Esquema de respuesta estándar."""

    id: str
    revision: str
    edit_revision: str
    plate: str
    type: str
    model: str
    color: str
    year: int
    status: str
    insurance_expiry: Optional[str] = None
    rider_id: Optional[str] = None  # ID del usuario (users.id)
    rider_profile_id: Optional[str] = (
        None  # ID del perfil de rider (riders.id) - USAR ESTE PARA LLAMAR A /api/v1/riders/{id}
    )
    rider_name: Optional[str] = None
    notes: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# HELPERS & MODELOS
# ==============================================================================


def _parse_uuid(value: str, field_name: str = "ID") -> uuid.UUID:
    """Convierte string a UUID o lanza error 400."""
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field_name} inválido")


def utc_now_naive() -> datetime:
    """Obtiene la hora actual UTC naive (sin zona horaria)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _format_date(date_val: Any) -> Optional[str]:
    """Normaliza fechas a string ISO o retorna None."""
    if not date_val:
        return None
    if isinstance(date_val, (date, datetime)):
        return date_val.isoformat()
    return str(date_val)


def _get_enum_value(enum_obj: Any) -> str:
    """Extrae el valor string de un Enum de SQLAlchemy o Pydantic de forma segura."""
    if enum_obj is None:
        return ""
    if hasattr(enum_obj, "value"):
        return enum_obj.value
    return str(enum_obj)


def _safe_parse_enum(enum_class, value: Optional[str]) -> Optional[Any]:
    """
    Intenta convertir un string a un Enum específico de forma segura.
    Retorna None si el valor es None, vacío o no es válido.
    Esto previene errores 422 al permitir filtrado flexible.
    """
    if not value or value.strip() == "":
        return None

    # Normalizar entrada
    val_upper = str(value).strip().upper()

    if val_upper in {"ALL", "TODOS", "TODAS"}:
        return None

    # Intentar coincidir por valor (ej: "MOTO" == VehicleType.MOTO.value)
    for item in enum_class:
        if item.value == val_upper:
            return item

    # Intentar coincidir por nombre (ej: "MOTO" == VehicleType.MOTO.name)
    try:
        return enum_class[val_upper]
    except KeyError:
        pass

    return None


def _build_vehicle_response(vehicle: Vehicle) -> dict:
    """Construye una respuesta serializable y estable para el frontend."""
    rider_name = None
    rider_user_id = None
    rider_profile_id = None  # El ID real del rider (de la tabla riders)

    rider = vehicle.__dict__.get("rider")
    if rider:
        rider_name = f"{rider.first_name or ''} {rider.last_name or ''}".strip()
        if not rider_name and rider.email:
            rider_name = rider.email
        rider_user_id = str(rider.id)

        # Si el user tiene un perfil rider, obtener ese ID (este es el ID que necesita el frontend para llamar a /api/v1/riders/{id})
        if hasattr(rider, "rider_profile") and rider.rider_profile:
            rider_profile_id = str(rider.rider_profile.id)

    return {
        "id": str(vehicle.id),
        "revision": vehicle_revision(vehicle),
        "edit_revision": vehicle_edit_revision(vehicle),
        "plate": vehicle.plate,
        "type": _get_enum_value(vehicle.type),
        "model": vehicle.model,
        "color": vehicle.color,
        "year": vehicle.year,
        "status": _get_enum_value(vehicle.status),
        "insurance_expiry": _format_date(vehicle.insurance_expiry),
        "rider_id": rider_user_id,  # ID del usuario (users.id)
        "rider_profile_id": rider_profile_id,  # ID del perfil de rider (riders.id) - USAR ESTE PARA LLAMAR A /api/v1/riders/{id}
        "rider_name": rider_name,
        "notes": vehicle.notes,
        "created_at": _format_date(vehicle.created_at),
        "updated_at": _format_date(vehicle.updated_at),
    }


# ==============================================================================
# ENDPOINTS
# ==============================================================================


@router.get("/available", response_model=List[VehicleResponse])
async def get_available_vehicles(
    ownership_type: Optional[str] = Query(
        None,
        description="Filtrar por tipo de propiedad (EMPRESA para vehículos de flota)",
    ),
    type: Optional[str] = Query(
        None, description="Filtrar por tipo de vehículo (MOTO, AUTO, etc.)"
    ),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.SUPERADMIN, UserRole.GERENTE, UserRole.OPERADOR)
    ),
):
    """
    Obtiene vehículos disponibles (no asignados) para asignar a repartidores.
    Si ownership_type=EMPRESA, retorna solo vehículos de la flota de la empresa.
    Accesible para: SUPERADMIN, GERENTE, OPERADOR.
    """
    from sqlalchemy.orm import selectinload

    stmt = select(Vehicle).options(
        selectinload(Vehicle.rider).selectinload(User.rider_profile)
    )

    # Disponibilidad coherente con ambos vínculos y el estado operativo.
    stmt = stmt.where(available_vehicle_condition())

    # Filtro opcional por tipo de vehículo
    type_enum = _safe_parse_enum(VehicleType, type)
    if type_enum:
        stmt = stmt.where(Vehicle.type == type_enum.value)

    # Limitar resultados
    stmt = stmt.limit(limit).order_by(Vehicle.created_at.desc(), Vehicle.id)

    result = await db.execute(stmt)
    vehicles = result.scalars().unique().all()

    return [_build_vehicle_response(vehicle) for vehicle in vehicles]


@router.get("", response_model=List[VehicleResponse])
async def list_vehicles(
    # FORZAMOS QUE SEAN STRINGS PARA EVITAR VALIDACIÓN AUTOMÁTICA DE FASTAPI
    type: Optional[str] = Query(
        None, description="Filtrar por tipo (MOTO, AUTO, etc.)"
    ),
    status: Optional[str] = Query(
        None, description="Filtrar por estado (ACTIVO, MANTENIMIENTO, etc.)"
    ),
    search: Optional[str] = Query(None),
    available_only: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    page: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.SUPERADMIN, UserRole.GERENTE, UserRole.OPERADOR)
    ),
):
    """
    Lista vehículos con filtros opcionales.
    Accesible para: SUPERADMIN, GERENTE, OPERADOR.
    """
    from sqlalchemy.orm import selectinload

    # Usar selectinload para cargar eager la relación rider (User) y su perfil rider anidado
    stmt = select(Vehicle).options(
        selectinload(Vehicle.rider).selectinload(User.rider_profile)
    )

    # Convertir strings a Enums de forma segura MANUALMENTE
    type_enum = _safe_parse_enum(VehicleType, type)
    status_enum = _safe_parse_enum(VehicleStatus, status)

    # Aplicar filtros solo si la conversión fue exitosa
    if type_enum:
        stmt = stmt.where(Vehicle.type == type_enum.value)
    elif type:
        logger.warning(f"Tipo de vehículo '{type}' no reconocido. Se omite el filtro.")

    if status_enum:
        stmt = stmt.where(Vehicle.status == status_enum.value)
    elif status:
        logger.warning(f"Estado '{status}' no reconocido. Se omite el filtro.")

    if search:
        search_lower = f"%{search.lower()}%"
        stmt = stmt.where(
            (func.lower(Vehicle.plate).like(search_lower))
            | (func.lower(Vehicle.model).like(search_lower))
        )

    if available_only:
        stmt = stmt.where(available_vehicle_condition())

    # Paginación y Ordenamiento
    offset = (page - 1) * limit
    stmt = (
        stmt.offset(offset).limit(limit).order_by(Vehicle.created_at.desc(), Vehicle.id)
    )

    result = await db.execute(stmt)
    vehicles = result.scalars().unique().all()

    return [_build_vehicle_response(vehicle) for vehicle in vehicles]


@router.get("/reconciliation", response_model=FleetReconciliationReport)
async def fleet_reconciliation_report(
    response: Response,
    limit: int = Query(100, ge=1, le=500),
    cursor: Optional[str] = Query(None, max_length=120),
    code: Optional[FleetFindingCode] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE)),
):
    """Diagnóstico paginado de vínculos actuales. No repara ni certifica históricos."""
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization"
    return await reconcile_fleet(db, limit=limit, cursor=cursor, code=code)


@router.get("/{vehicle_id}", response_model=VehicleResponse)
async def get_vehicle(
    response: Response,
    vehicle_id: str = Path(..., description="ID del vehículo (UUID)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Obtiene detalles de un vehículo específico por ID."""
    from sqlalchemy.orm import selectinload

    vid = _parse_uuid(vehicle_id)

    # Cargar el rider (User) y su perfil de rider (Rider) anidado
    stmt = (
        select(Vehicle)
        .options(selectinload(Vehicle.rider).selectinload(User.rider_profile))
        .where(Vehicle.id == vid)
        .execution_options(populate_existing=True)
    )
    result = await db.execute(stmt)
    vehicle = result.scalar_one_or_none()

    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")

    response.headers["ETag"] = f'"{vehicle_edit_revision(vehicle)}"'
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization"
    return _build_vehicle_response(vehicle)


@router.post("", status_code=201, response_model=VehicleResponse)
async def create_vehicle(
    body: VehicleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE)),
):
    """Registra un nuevo vehículo en la flota."""

    plate_upper = normalize_vehicle_plate(body.plate)
    await claim_vehicle_plate(db, plate_upper)

    new_vehicle = Vehicle(
        id=uuid.uuid4(),
        plate=plate_upper,
        type=body.type,
        model=body.model,
        color=body.color,
        year=body.year,
        status=VehicleStatus.ACTIVO.value,
        insurance_expiry=body.insurance_expiry,
        notes=body.notes,
        created_at=utc_now_naive(),
    )

    async with vehicle_plate_integrity(db):
        db.add(new_vehicle)
        await db.flush()
        await record_inventory_change(
            db,
            current_user,
            vehicle_id=new_vehicle.id,
            before=None,
            after=inventory_snapshot(new_vehicle),
        )
        await db.commit()
    await db.refresh(new_vehicle)

    return _build_vehicle_response(new_vehicle)


@router.patch("/{vehicle_id}", response_model=VehicleResponse)
async def update_vehicle(
    vehicle_id: str = Path(..., description="ID del vehículo (UUID)"),
    body: VehicleUpdate = ...,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE)),
    if_match: Annotated[Optional[str], Header(alias="If-Match")] = None,
):
    """Actualiza datos parciales de un vehículo existente."""
    vid = _parse_uuid(vehicle_id)

    vehicle = (await lock_vehicles(db, {vid}))[vid]
    ensure_vehicle_edit_revision(vehicle, if_match)

    before = inventory_snapshot(vehicle)
    update_data = body.model_dump(exclude_unset=True)
    required = {"plate", "type", "model", "color", "year", "status"}
    if any(update_data.get(key) is None for key in required.intersection(update_data)):
        raise HTTPException(
            status_code=422,
            detail="Los datos obligatorios del vehículo no pueden ser nulos",
        )
    if "plate" in update_data:
        update_data["plate"] = update_data["plate"].strip().upper()
    critical = {"plate", "type", "model", "year", "status", "insurance_expiry"}
    if any(
        getattr(vehicle, key) != value
        for key, value in update_data.items()
        if key in critical
    ):
        await ensure_vehicle_unassigned(db, vehicle)

    if "plate" in update_data:
        new_plate = normalize_vehicle_plate(update_data["plate"])
        await claim_vehicle_plate(db, new_plate, excluding=vid)
        vehicle.plate = new_plate

    for field, value in update_data.items():
        if field == "plate":
            continue
        if hasattr(vehicle, field):
            setattr(vehicle, field, value)

    vehicle.updated_at = utc_now_naive()

    async with vehicle_plate_integrity(db):
        await db.flush()
        await record_inventory_change(
            db,
            current_user,
            vehicle_id=vehicle.id,
            before=before,
            after=inventory_snapshot(vehicle),
        )
        await db.commit()
    from sqlalchemy.orm import selectinload

    refreshed_vehicle = await db.scalar(
        select(Vehicle)
        .options(selectinload(Vehicle.rider).selectinload(User.rider_profile))
        .where(Vehicle.id == vid)
        .execution_options(populate_existing=True)
    )
    if refreshed_vehicle is None:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")

    vehicle = refreshed_vehicle

    return _build_vehicle_response(vehicle)


@router.delete("/{vehicle_id}")
async def delete_vehicle(
    vehicle_id: str = Path(..., description="ID del vehículo (UUID)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE)),
    if_match: Annotated[Optional[str], Header(alias="If-Match")] = None,
):
    """Elimina permanentemente un vehículo."""
    vid = _parse_uuid(vehicle_id)

    vehicle = (await lock_vehicles(db, {vid}))[vid]
    ensure_vehicle_edit_revision(vehicle, if_match)
    await ensure_vehicle_unassigned(db, vehicle)

    before = inventory_snapshot(vehicle)
    await db.delete(vehicle)
    await record_inventory_change(
        db, current_user, vehicle_id=vid, before=before, after=None
    )
    await db.commit()

    return {"message": "Vehículo eliminado exitosamente", "id": str(vid)}
