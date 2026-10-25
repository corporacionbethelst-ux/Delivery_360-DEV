"""Read-only, single-statement fleet diagnostics. No ORM entities or repairs."""

from datetime import date, datetime, timezone
from enum import Enum
import re
from uuid import UUID
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import String, cast, func, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.rider import Rider
from app.models.vehicle import Vehicle
from app.services.vehicle_plates import canonical_plate_expression


class FleetFindingCode(str, Enum):
    DUPLICATE_PLATE = "DUPLICATE_PLATE"
    INSURANCE_EXPIRED = "INSURANCE_EXPIRED"
    INSURANCE_EXPIRY_MISSING = "INSURANCE_EXPIRY_MISSING"
    COMPANY_WITHOUT_VEHICLE = "COMPANY_WITHOUT_VEHICLE"
    NONCOMPANY_WITH_VEHICLE = "NONCOMPANY_WITH_VEHICLE"
    MISSING_VEHICLE = "MISSING_VEHICLE"
    OWNER_MISMATCH = "OWNER_MISMATCH"
    MULTIPLE_RIDERS = "MULTIPLE_RIDERS"
    METADATA_MISMATCH = "METADATA_MISMATCH"
    INACTIVE_VEHICLE = "INACTIVE_VEHICLE"
    OWNER_WITHOUT_PROFILE = "OWNER_WITHOUT_PROFILE"
    OWNER_PROFILE_MISMATCH = "OWNER_PROFILE_MISMATCH"
    INVALID_OWNERSHIP = "INVALID_OWNERSHIP"


DESCRIPTIONS = {
    FleetFindingCode.INSURANCE_EXPIRED: "La fecha registrada de vencimiento del seguro es anterior al día de referencia UTC",
    FleetFindingCode.INSURANCE_EXPIRY_MISSING: "No hay fecha registrada de vencimiento del seguro; vigencia desconocida",
    FleetFindingCode.DUPLICATE_PLATE: "Varios vehículos comparten placa al normalizar mayúsculas y espacios ASCII exteriores",
    FleetFindingCode.COMPANY_WITHOUT_VEHICLE: "Perfil EMPRESA sin vehículo asignado",
    FleetFindingCode.NONCOMPANY_WITH_VEHICLE: "Perfil no EMPRESA con vehículo de flota asignado",
    FleetFindingCode.MISSING_VEHICLE: "El vehículo referenciado no existe",
    FleetFindingCode.OWNER_MISMATCH: "El propietario del vehículo no coincide con el usuario del perfil",
    FleetFindingCode.MULTIPLE_RIDERS: "Más de un perfil referencia el mismo vehículo",
    FleetFindingCode.METADATA_MISMATCH: "Tipo, placa o modelo del perfil EMPRESA difieren de la flota",
    FleetFindingCode.INACTIVE_VEHICLE: "El perfil referencia un vehículo que no está ACTIVO",
    FleetFindingCode.OWNER_WITHOUT_PROFILE: "El usuario vinculado al vehículo no tiene perfil de repartidor",
    FleetFindingCode.OWNER_PROFILE_MISMATCH: "El perfil del usuario propietario no referencia este vehículo",
    FleetFindingCode.INVALID_OWNERSHIP: "Propiedad del vehículo del perfil ausente o inválida",
}


class FleetFinding(BaseModel):
    code: FleetFindingCode
    entity_type: Literal["rider", "vehicle"]
    entity_id: UUID
    related_id: UUID | None
    description: str


class FleetReconciliationReport(BaseModel):
    read_only: Literal[True] = True
    generated_at: datetime
    insurance_reference_date: date
    snapshot_scope: Literal["single_statement_per_page"] = "single_statement_per_page"
    findings: list[FleetFinding]
    page_count: int
    has_more: bool
    next_cursor: str | None
    checks: list[FleetFindingCode]


def _findings_query(*, insurance_reference_date: date, postgres: bool = False):
    r, v = Rider.__table__, Vehicle.__table__
    plate_key = canonical_plate_expression(v.c.plate, postgres=postgres)
    repeated_plates = select(plate_key).group_by(plate_key).having(func.count() > 1)
    repeated = (
        select(r.c.assigned_vehicle_id)
        .where(r.c.assigned_vehicle_id.is_not(None))
        .group_by(r.c.assigned_vehicle_id)
        .having(func.count() > 1)
    )

    def rider_rows(code, condition, source=r):
        return (
            select(
                literal(code.value).label("code"),
                literal("rider").label("entity_type"),
                r.c.id.label("entity_id"),
                r.c.assigned_vehicle_id.label("related_id"),
            )
            .select_from(source)
            .where(condition)
        )

    def vehicle_rows(code, condition, source):
        return (
            select(
                literal(code.value).label("code"),
                literal("vehicle").label("entity_type"),
                v.c.id.label("entity_id"),
                v.c.rider_id.label("related_id"),
            )
            .select_from(source)
            .where(condition)
        )

    joined = r.join(v, r.c.assigned_vehicle_id == v.c.id)
    owner_profiles = v.outerjoin(r, v.c.rider_id == r.c.user_id)

    def inventory_rows(code, condition):
        return select(
            literal(code.value).label("code"),
            literal("vehicle").label("entity_type"),
            v.c.id.label("entity_id"),
            literal(None, type_=v.c.id.type).label("related_id"),
        ).where(condition)

    return union_all(
        inventory_rows(
            FleetFindingCode.DUPLICATE_PLATE, plate_key.in_(repeated_plates)
        ),
        inventory_rows(
            FleetFindingCode.INSURANCE_EXPIRED,
            v.c.insurance_expiry < insurance_reference_date,
        ),
        inventory_rows(
            FleetFindingCode.INSURANCE_EXPIRY_MISSING, v.c.insurance_expiry.is_(None)
        ),
        rider_rows(
            FleetFindingCode.COMPANY_WITHOUT_VEHICLE,
            (r.c.vehicle_ownership_type == "EMPRESA")
            & r.c.assigned_vehicle_id.is_(None),
        ),
        rider_rows(
            FleetFindingCode.NONCOMPANY_WITH_VEHICLE,
            r.c.vehicle_ownership_type.is_distinct_from("EMPRESA")
            & r.c.assigned_vehicle_id.is_not(None),
        ),
        rider_rows(
            FleetFindingCode.MISSING_VEHICLE,
            r.c.assigned_vehicle_id.is_not(None) & v.c.id.is_(None),
            r.outerjoin(v, r.c.assigned_vehicle_id == v.c.id),
        ),
        rider_rows(
            FleetFindingCode.OWNER_MISMATCH,
            v.c.rider_id.is_distinct_from(r.c.user_id),
            joined,
        ),
        rider_rows(
            FleetFindingCode.MULTIPLE_RIDERS, r.c.assigned_vehicle_id.in_(repeated)
        ),
        rider_rows(
            FleetFindingCode.METADATA_MISMATCH,
            (r.c.vehicle_ownership_type == "EMPRESA")
            & or_(
                cast(r.c.vehicle_type, String).is_distinct_from(cast(v.c.type, String)),
                r.c.vehicle_plate.is_distinct_from(v.c.plate),
                r.c.vehicle_model.is_distinct_from(v.c.model),
            ),
            joined,
        ),
        rider_rows(
            FleetFindingCode.INACTIVE_VEHICLE,
            v.c.status.is_distinct_from("ACTIVO"),
            joined,
        ),
        vehicle_rows(
            FleetFindingCode.OWNER_WITHOUT_PROFILE,
            v.c.rider_id.is_not(None) & r.c.id.is_(None),
            owner_profiles,
        ),
        vehicle_rows(
            FleetFindingCode.OWNER_PROFILE_MISMATCH,
            v.c.rider_id.is_not(None)
            & r.c.id.is_not(None)
            & r.c.assigned_vehicle_id.is_distinct_from(v.c.id),
            owner_profiles,
        ),
        rider_rows(
            FleetFindingCode.INVALID_OWNERSHIP,
            r.c.vehicle_ownership_type.is_distinct_from("PROPIO")
            & r.c.vehicle_ownership_type.is_distinct_from("EMPRESA"),
        ),
    ).cte("fleet_findings")


async def reconcile_fleet(
    db: AsyncSession,
    *,
    limit: int = 100,
    cursor: str | None = None,
    code: FleetFindingCode | None = None,
) -> FleetReconciliationReport:
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="Límite inválido")
    if cursor is not None:
        match = re.fullmatch(
            r"([A-Z_]+):([a-f0-9-]{32,36}):([a-f0-9-]{32,36})?", cursor
        )
        if not match or match[1] not in {item.value for item in FleetFindingCode}:
            raise HTTPException(
                status_code=422, detail="Cursor de conciliación inválido"
            )
        try:
            UUID(match[2])
            if match[3]:
                UUID(match[3])
        except ValueError:
            raise HTTPException(
                status_code=422, detail="Cursor de conciliación inválido"
            )
    generated_at = datetime.now(timezone.utc)
    insurance_reference_date = generated_at.date()
    findings = _findings_query(
        insurance_reference_date=insurance_reference_date,
        postgres=db.get_bind().dialect.name == "postgresql",
    )
    key = (
        findings.c.code
        + literal(":")
        + cast(findings.c.entity_id, String)
        + literal(":")
        + func.coalesce(cast(findings.c.related_id, String), "")
    )
    stmt = select(findings, key.label("cursor_key")).order_by(key).limit(limit + 1)
    if cursor is not None:
        stmt = stmt.where(key > cursor)
    if code is not None:
        stmt = stmt.where(findings.c.code == code.value)
    with db.no_autoflush:
        rows = (await db.execute(stmt)).mappings().all()
    page = rows[:limit]
    more = len(rows) > limit
    return FleetReconciliationReport(
        generated_at=generated_at,
        insurance_reference_date=insurance_reference_date,
        findings=[
            FleetFinding(
                code=row["code"],
                entity_type=row["entity_type"],
                entity_id=row["entity_id"],
                related_id=row["related_id"],
                description=DESCRIPTIONS[FleetFindingCode(row["code"])],
            )
            for row in page
        ],
        page_count=len(page),
        has_more=more,
        next_cursor=page[-1]["cursor_key"] if more else None,
        checks=list(FleetFindingCode),
    )
