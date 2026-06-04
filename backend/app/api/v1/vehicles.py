from fastapi import APIRouter, Depends, HTTPException, Query, status, Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Any
from datetime import datetime, timezone
import uuid
import logging

# Importación de Enums compartidos
from app.models.enums import VehicleType, VehicleStatus
from app.core.database import get_db
from app.models.user import User, UserRole
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
    plate: str = Field(..., min_length=1, max_length=20, description="Placa o patente del vehículo")
    type: VehicleType
    model: str = Field(..., min_length=1, max_length=100, description="Modelo del vehículo")
    color: str = Field(..., min_length=1, max_length=50, description="Color principal")
    year: int = Field(..., ge=1900, le=2100, description="Año de fabricación")
    insurance_expiry: Optional[str] = Field(None, description="Fecha de vencimiento del seguro (YYYY-MM-DD)")
    notes: Optional[str] = Field(None, description="Notas adicionales")

    model_config = ConfigDict(use_enum_values=True)

class VehicleUpdate(BaseModel):
    """Datos parciales para actualizar un vehículo."""
    plate: Optional[str] = Field(None, min_length=1, max_length=20)
    type: Optional[VehicleType] = None
    model: Optional[str] = Field(None, min_length=1, max_length=100)
    color: Optional[str] = Field(None, min_length=1, max_length=50)
    year: Optional[int] = Field(None, ge=1900, le=2100)
    status: Optional[VehicleStatus] = None
    insurance_expiry: Optional[str] = None
    notes: Optional[str] = None

    model_config = ConfigDict(use_enum_values=True)

class VehicleResponse(BaseModel):
    """Esquema de respuesta estándar."""
    id: str
    plate: str
    type: str
    model: str
    color: str
    year: int
    status: str
    insurance_expiry: Optional[str] = None
    rider_id: Optional[str] = None
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
    if isinstance(date_val, datetime):
        return date_val.isoformat()
    return str(date_val)

def _get_enum_value(enum_obj: Any) -> str:
    """Extrae el valor string de un Enum de SQLAlchemy o Pydantic de forma segura."""
    if enum_obj is None:
        return ""
    if hasattr(enum_obj, 'value'):
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

# Importación segura del modelo de base de datos
try:
    from app.models.vehicle import Vehicle
except ImportError:
    logger.error("❌ CRÍTICO: Modelo 'Vehicle' no encontrado en app/models/vehicle.py")
    class Vehicle: 
        id = None
        plate = None
        type = None
        model = None
        color = None
        year = None
        status = None
        insurance_expiry = None
        rider_id = None
        notes = None
        created_at = None
        updated_at = None

# ==============================================================================
# ENDPOINTS
# ==============================================================================

@router.get("", response_model=List[VehicleResponse])
async def list_vehicles(
    # FORZAMOS QUE SEAN STRINGS PARA EVITAR VALIDACIÓN AUTOMÁTICA DE FASTAPI
    type: Optional[str] = Query(None, description="Filtrar por tipo (MOTO, AUTO, etc.)"),
    status: Optional[str] = Query(None, description="Filtrar por estado (ACTIVO, MANTENIMIENTO, etc.)"),
    search: Optional[str] = Query(None),
    available_only: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    page: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE, UserRole.OPERADOR))
):
    """
    Lista vehículos con filtros opcionales.
    Accesible para: SUPERADMIN, GERENTE, OPERADOR.
    """
    from sqlalchemy.orm import selectinload
    
    # Usar selectinload para cargar eager la relación rider (User)
    stmt = select(Vehicle).options(selectinload(Vehicle.rider))
    
    # Convertir strings a Enums de forma segura MANUALMENTE
    type_enum = _safe_parse_enum(VehicleType, type)
    status_enum = _safe_parse_enum(VehicleStatus, status)

    # Aplicar filtros solo si la conversión fue exitosa
    if type_enum:
        stmt = stmt.where(Vehicle.type == type_enum)
    elif type: 
        logger.warning(f"Tipo de vehículo '{type}' no reconocido. Se omite el filtro.")

    if status_enum:
        stmt = stmt.where(Vehicle.status == status_enum)
    elif status:
        logger.warning(f"Estado '{status}' no reconocido. Se omite el filtro.")

    if search:
        search_lower = f"%{search.lower()}%"
        stmt = stmt.where(
            (func.lower(Vehicle.plate).like(search_lower)) | 
            (func.lower(Vehicle.model).like(search_lower))
        )
    
    if available_only:
        stmt = stmt.where(
            (Vehicle.rider_id.is_(None)) & 
            (Vehicle.status == VehicleStatus.ACTIVO)
        )

    # Paginación y Ordenamiento
    offset = (page - 1) * limit
    stmt = stmt.offset(offset).limit(limit).order_by(Vehicle.created_at.desc())

    result = await db.execute(stmt)
    vehicles = result.scalars().unique().all()

    # Construcción manual de la respuesta
    response_list = []
    for v in vehicles:
        rider_name = None
        if v.rider:
             rider_name = f"{v.rider.first_name or ''} {v.rider.last_name or ''}".strip()
             if not rider_name and v.rider.email:
                 rider_name = v.rider.email

        response_list.append({
            "id": str(v.id),
            "plate": v.plate,
            "type": _get_enum_value(v.type),
            "model": v.model,
            "color": v.color,
            "year": v.year,
            "status": _get_enum_value(v.status),
            "insurance_expiry": _format_date(v.insurance_expiry),
            "rider_id": str(v.rider_id) if v.rider_id else None,
            "rider_name": rider_name,
            "notes": v.notes,
            "created_at": _format_date(v.created_at),
            "updated_at": _format_date(v.updated_at),
        })

    return response_list


@router.get("/{vehicle_id}", response_model=VehicleResponse)
async def get_vehicle(
    vehicle_id: str = Path(..., description="ID del vehículo (UUID)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtiene detalles de un vehículo específico por ID."""
    from sqlalchemy.orm import selectinload
    
    vid = _parse_uuid(vehicle_id)
    
    stmt = select(Vehicle).options(selectinload(Vehicle.rider)).where(Vehicle.id == vid)
    result = await db.execute(stmt)
    vehicle = result.scalar_one_or_none()

    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")

    rider_name = None
    if vehicle.rider:
        rider_name = f"{vehicle.rider.first_name or ''} {vehicle.rider.last_name or ''}".strip()
        if not rider_name and vehicle.rider.email:
            rider_name = vehicle.rider.email

    return {
        "id": str(vehicle.id),
        "plate": vehicle.plate,
        "type": _get_enum_value(vehicle.type),
        "model": vehicle.model,
        "color": vehicle.color,
        "year": vehicle.year,
        "status": _get_enum_value(vehicle.status),
        "insurance_expiry": _format_date(vehicle.insurance_expiry),
        "rider_id": str(vehicle.rider_id) if vehicle.rider_id else None,
        "rider_name": rider_name,
        "notes": vehicle.notes,
        "created_at": _format_date(vehicle.created_at),
        "updated_at": _format_date(vehicle.updated_at),
    }


@router.post("", status_code=201, response_model=VehicleResponse)
async def create_vehicle(
    body: VehicleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE))
):
    """Registra un nuevo vehículo en la flota."""
    
    plate_upper = body.plate.strip().upper()

    stmt = select(Vehicle).where(func.upper(Vehicle.plate) == plate_upper)
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"La placa '{plate_upper}' ya está registrada")

    new_vehicle = Vehicle(
        id=uuid.uuid4(),
        plate=plate_upper,
        type=body.type,
        model=body.model,
        color=body.color,
        year=body.year,
        status=VehicleStatus.ACTIVO,
        insurance_expiry=body.insurance_expiry,
        notes=body.notes,
        created_at=utc_now_naive()
    )
    
    db.add(new_vehicle)
    await db.commit()
    await db.refresh(new_vehicle)

    return {
        "id": str(new_vehicle.id),
        "plate": new_vehicle.plate,
        "type": _get_enum_value(new_vehicle.type),
        "model": new_vehicle.model,
        "color": new_vehicle.color,
        "year": new_vehicle.year,
        "status": _get_enum_value(new_vehicle.status),
        "insurance_expiry": _format_date(new_vehicle.insurance_expiry),
        "rider_id": None,
        "rider_name": None,
        "notes": new_vehicle.notes,
        "created_at": _format_date(new_vehicle.created_at),
        "updated_at": None,
    }


@router.patch("/{vehicle_id}", response_model=VehicleResponse)
async def update_vehicle(
    vehicle_id: str = Path(..., description="ID del vehículo (UUID)"),
    body: VehicleUpdate = ...,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE))
):
    """Actualiza datos parciales de un vehículo existente."""
    vid = _parse_uuid(vehicle_id)
    
    stmt = select(Vehicle).where(Vehicle.id == vid)
    result = await db.execute(stmt)
    vehicle = result.scalar_one_or_none()

    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")

    update_data = body.model_dump(exclude_unset=True)
    
    if "plate" in update_data:
        new_plate = update_data["plate"].strip().upper()
        if new_plate != vehicle.plate:
            check_stmt = select(Vehicle).where(
                (func.upper(Vehicle.plate) == new_plate) & 
                (Vehicle.id != vid)
            )
            check_res = await db.execute(check_stmt)
            if check_res.scalar_one_or_none():
                raise HTTPException(status_code=400, detail=f"La placa '{new_plate}' ya está en uso")
        vehicle.plate = new_plate

    for field, value in update_data.items():
        if field == "plate": 
            continue
        if hasattr(vehicle, field):
            setattr(vehicle, field, value)

    vehicle.updated_at = utc_now_naive()
    
    await db.commit()
    await db.refresh(vehicle)

    rider_name = None
    if vehicle.rider:
        rider_name = f"{vehicle.rider.first_name or ''} {vehicle.rider.last_name or ''}".strip()
        if not rider_name and vehicle.rider.email:
            rider_name = vehicle.rider.email

    return {
        "id": str(vehicle.id),
        "plate": vehicle.plate,
        "type": _get_enum_value(vehicle.type),
        "model": vehicle.model,
        "color": vehicle.color,
        "year": vehicle.year,
        "status": _get_enum_value(vehicle.status),
        "insurance_expiry": _format_date(vehicle.insurance_expiry),
        "rider_id": str(vehicle.rider_id) if vehicle.rider_id else None,
        "rider_name": rider_name,
        "notes": vehicle.notes,
        "created_at": _format_date(vehicle.created_at),
        "updated_at": _format_date(vehicle.updated_at),
    }


@router.delete("/{vehicle_id}")
async def delete_vehicle(
    vehicle_id: str = Path(..., description="ID del vehículo (UUID)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.SUPERADMIN, UserRole.GERENTE))
):
    """Elimina permanentemente un vehículo."""
    vid = _parse_uuid(vehicle_id)
    
    stmt = select(Vehicle).where(Vehicle.id == vid)
    result = await db.execute(stmt)
    vehicle = result.scalar_one_or_none()

    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")
    
    if vehicle.rider_id:
        raise HTTPException(
            status_code=400, 
            detail="No se puede eliminar un vehículo asignado a un repartidor."
        )

    await db.delete(vehicle)
    await db.commit()
    
    return {"message": "Vehículo eliminado exitosamente", "id": str(vid)}