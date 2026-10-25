"""Canonical plate claims and precise uniqueness conflicts, without data repair.

PostgreSQL transaction advisory locks serialize claims for one ASCII canonical
plate. Vehicle edits acquire their existing row lock before this plate lock.
"""

import hashlib
import re
import sqlite3
from contextlib import asynccontextmanager
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import Integer, func, literal, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.vehicle import Vehicle

ASCII_WHITESPACE = " \t\n\r\v\f"
PLATE_LOCK_NAMESPACE = 0x44563350
PLATE_UNIQUE_NAMES = frozenset({"ix_vehicles_plate", "vehicles_plate_key"})


def normalize_vehicle_plate(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("La placa debe ser texto")
    clean = value.strip(ASCII_WHITESPACE)
    if not re.fullmatch(r"[A-Za-z0-9-]{1,20}", clean):
        raise ValueError(
            "La placa debe tener entre 1 y 20 letras ASCII, números o guiones"
        )
    return clean.upper()


def plate_conflict() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "VEHICLE_PLATE_CONFLICT",
            "message": "La placa ya está registrada. Use otra placa",
        },
    )


async def claim_vehicle_plate(
    db: AsyncSession, plate: str, *, excluding: UUID | None = None
) -> None:
    canonical = normalize_vehicle_plate(plate)
    postgres = db.get_bind().dialect.name == "postgresql"
    if postgres:
        key = int.from_bytes(
            hashlib.sha256(canonical.encode("ascii")).digest()[:4], "big", signed=True
        )
        await db.execute(
            select(
                func.pg_advisory_xact_lock(
                    literal(PLATE_LOCK_NAMESPACE, type_=Integer),
                    literal(key, type_=Integer),
                )
            )
        )
    trimmed = (
        func.btrim(Vehicle.plate, ASCII_WHITESPACE)
        if postgres
        else func.trim(Vehicle.plate, ASCII_WHITESPACE)
    )
    stmt = select(Vehicle.id).where(func.upper(trimmed) == canonical).limit(1)
    if excluding is not None:
        stmt = stmt.where(Vehicle.id != excluding)
    with db.no_autoflush:
        if await db.scalar(stmt) is not None:
            raise plate_conflict()


def is_vehicle_plate_unique_error(error: IntegrityError) -> bool:
    original = error.orig
    if isinstance(original, sqlite3.IntegrityError):
        return (
            getattr(original, "sqlite_errorcode", None)
            == sqlite3.SQLITE_CONSTRAINT_UNIQUE
            and str(original) == "UNIQUE constraint failed: vehicles.plate"
        )
    current = original
    states: set[str] = set()
    constraints: set[str] = set()
    for _ in range(8):
        if current is None:
            break
        states.update(
            str(code)
            for code in (
                getattr(current, "sqlstate", None),
                getattr(current, "pgcode", None),
            )
            if code
        )
        name = getattr(current, "constraint_name", None) or getattr(
            getattr(current, "diag", None), "constraint_name", None
        )
        if name:
            constraints.add(name)
        current = getattr(current, "__cause__", None)
    return "23505" in states and bool(constraints & PLATE_UNIQUE_NAMES)


@asynccontextmanager
async def vehicle_plate_integrity(db: AsyncSession):
    """Translate only recognized plate uniqueness failures; rollback all effects."""
    try:
        yield
    except IntegrityError as error:
        if not is_vehicle_plate_unique_error(error):
            raise
        await db.rollback()
        raise plate_conflict() from None
