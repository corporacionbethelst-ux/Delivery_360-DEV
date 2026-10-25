"""Internal shift contracts matching persisted UUIDs, states and attendance.

The operator HTTP API keeps its existing UI aliases in api/v1/shifts.py.
Unsupported metadata, photos and pause transitions are rejected explicitly.
"""

from datetime import datetime, time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.shift import ShiftStatus


class ShiftBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rider_id: UUID
    scheduled_start: datetime
    scheduled_end: datetime | None = None
    notes: str | None = Field(None, max_length=500)


class ShiftCreate(ShiftBase):
    status: Literal[ShiftStatus.PROGRAMADO] = ShiftStatus.PROGRAMADO


class ShiftUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    notes: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def reject_null_schedule(self) -> "ShiftUpdate":
        for name in ("scheduled_start", "scheduled_end"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError("El horario no puede ser nulo")
        return self


class CheckInOutBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    latitude: float | None = Field(
        None, ge=-90, le=90, allow_inf_nan=False, strict=True
    )
    longitude: float | None = Field(
        None, ge=-180, le=180, allow_inf_nan=False, strict=True
    )
    notes: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def coordinate_pair(self) -> "CheckInOutBase":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Latitud y longitud deben enviarse juntas")
        return self


class CheckInRequest(CheckInOutBase):
    shift_id: UUID


class CheckOutRequest(CheckInOutBase):
    shift_id: UUID


class CheckInOutRequest(CheckInOutBase):
    shift_id: UUID
    is_check_in: bool = True


class CheckInOutResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    rider_id: UUID
    shift_id: UUID | None
    check_type: str
    timestamp: datetime
    latitude: float | None
    longitude: float | None
    device_id: str | None
    ip_address: str | None
    notes: str | None
    created_at: datetime | None


class ShiftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    rider_id: UUID
    shift_date: datetime
    start_time: time
    end_time: time
    status: ShiftStatus | None
    check_in_at: datetime | None
    check_out_at: datetime | None
    total_deliveries: int | None
    completed_deliveries: int | None
    total_earnings: float | None
    notes: str | None
    created_at: datetime | None
    updated_at: datetime | None


class ShiftStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: ShiftStatus
    reason: str | None = Field(None, max_length=255)


class ShiftListResponse(BaseModel):
    total: int
    shifts: list[ShiftResponse]
