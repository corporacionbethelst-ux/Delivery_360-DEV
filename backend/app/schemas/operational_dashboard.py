"""Operational snapshots: missing evidence remains null, totals are not list lengths."""

from datetime import date, datetime
from uuid import UUID
from pydantic import BaseModel, Field


class DashboardSummary(BaseModel):
    orders_created: int = Field(ge=0)
    completed_deliveries: int = Field(ge=0)
    cancelled_orders: int = Field(ge=0)
    pending_orders: int = Field(ge=0)
    in_progress_orders: int = Field(ge=0)
    active_deliveries: int = Field(ge=0)
    riders_online: int = Field(ge=0)
    available_riders: int = Field(ge=0)
    active_shifts: int = Field(ge=0)
    open_alerts: int = Field(ge=0)
    active_users: int = Field(ge=0)
    avg_delivery_minutes: float | None = Field(ge=0)
    valid_duration_count: int = Field(ge=0)
    sla_percent: float | None = Field(ge=0, le=100)
    sla_known_count: int = Field(ge=0)
    sla_unknown_count: int = Field(ge=0)


class DailyActivity(BaseModel):
    date: date
    orders_created: int = Field(ge=0)
    completed_deliveries: int = Field(ge=0)


class PendingOrderPreview(BaseModel):
    id: UUID
    number: str | None
    status: str | None
    address: str
    priority: str | None


class RiderPositionPreview(BaseModel):
    id: UUID
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    recorded_at: datetime


class DashboardSnapshot(BaseModel):
    summary: DashboardSummary
    series: list[DailyActivity]
    period_start: datetime
    period_end: datetime
    timezone: str
    generated_at: datetime
    pending_orders: list[PendingOrderPreview] = []
    riders_online: list[RiderPositionPreview] = []
    queue_truncated: bool = False
    positions_truncated: bool = False
    source: str = "database_snapshot"
    financials_available: bool = False
    # Compatibility names for the former one-day manager response. New clients
    # use summary/period; "today" aliases are not populated for multi-day windows.
    orders_today: int | None = None
    delivered_today: int | None = None
    sla_compliance_pct: float | None = None
    sla_breached: int | None = None
    active_riders: int | None = None
    avg_delivery_time_min: float | None = None
