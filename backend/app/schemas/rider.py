"""Rider schemas for Pydantic validation."""

from datetime import datetime
from typing import Optional, List, Any
import uuid
from pydantic import BaseModel, ConfigDict, Field, field_validator
from enum import Enum

class RiderStatusEnum(str, Enum):
    PENDIENTE = "PENDIENTE"
    ACTIVO = "ACTIVO"
    INACTIVO = "INACTIVO"
    OCUPADO = "OCUPADO"
    SUSPENDIDO = "SUSPENDIDO"

class RiderTierEnum(str, Enum):
    BRONCE = "BRONCE"
    PLATA = "PLATA"
    ORO = "ORO"
    PLATINO = "PLATINO"

class VehicleTypeEnum(str, Enum):
    MOTO = "MOTO"
    BICICLETA = "BICICLETA"
    PATINETA = "PATINETA"
    AUTO = "AUTO"
    FURGONETA = "FURGONETA"

class VehicleOwnershipTypeEnum(str, Enum):
    PROPIO = "PROPIO"
    EMPRESA = "EMPRESA"

class RiderBase(BaseModel):
    vehicle_type: Optional[VehicleTypeEnum] = None
    vehicle_plate: Optional[str] = None
    vehicle_model: Optional[str] = None
    operating_zone: Optional[str] = None
    cpf: Optional[str] = None
    cnh: Optional[str] = None
    status: Optional[RiderStatusEnum] = RiderStatusEnum.PENDIENTE
    tier: Optional[RiderTierEnum] = RiderTierEnum.BRONCE
    is_online: Optional[bool] = False
    notes: Optional[str] = None
    badges: Optional[List[Any]] = []
    level: Optional[int] = 1
    total_points: Optional[int] = 0
    
    # Tipo de propiedad del vehículo (Propio o Empresa)
    vehicle_ownership_type: Optional[VehicleOwnershipTypeEnum] = VehicleOwnershipTypeEnum.PROPIO
    
    # ID del vehículo de empresa asignado (solo si vehicle_ownership_type es EMPRESA)
    assigned_vehicle_id: Optional[uuid.UUID] = None

class RiderCreate(RiderBase):
    user_id: uuid.UUID
    
    @field_validator('assigned_vehicle_id')
    @classmethod
    def validate_assigned_vehicle(cls, v, info):
        """Valida que si el tipo es EMPRESA, assigned_vehicle_id sea requerido."""
        # Nota: Esta validación se hace en el endpoint porque necesitamos acceso a ambos campos
        return v

class RiderUpdate(BaseModel):
    vehicle_type: Optional[VehicleTypeEnum] = None
    vehicle_plate: Optional[str] = None
    vehicle_model: Optional[str] = None
    operating_zone: Optional[str] = None
    status: Optional[RiderStatusEnum] = None
    tier: Optional[RiderTierEnum] = None
    is_online: Optional[bool] = None
    vehicle_ownership_type: Optional[VehicleOwnershipTypeEnum] = None
    assigned_vehicle_id: Optional[uuid.UUID] = None

class RiderResponse(RiderBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: uuid.UUID
    user_id: uuid.UUID
    
    # Ubicación
    last_lat: Optional[float] = None
    last_lng: Optional[float] = None
    last_location_at: Optional[datetime] = None
    
    # CAMPO CLAVE PARA EL MAPA
    current_order_id: Optional[uuid.UUID] = None
    
    # Auditoría
    created_at: datetime
    updated_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    
    # Datos desnormalizados del usuario para conveniencia del frontend
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None

class RiderStatusUpdate(BaseModel):
    status: RiderStatusEnum
    reason: Optional[str] = None

class RiderApprovalRequest(BaseModel):
    """Schema para aprobación/rechazo de repartidores."""
    approved: bool = True
    notes: Optional[str] = None
    rejection_reason: Optional[str] = None