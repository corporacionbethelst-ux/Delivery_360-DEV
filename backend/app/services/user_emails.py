"""Canonical email claims. Lock order: email, vehicles, Rider, User.

No automatic repair of historical identities. Ambiguous lookups fail closed.
"""

import hashlib
import sqlite3
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import Integer, func, literal, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User

WHITESPACE = " \t\n\r\v\f"
EMAIL_LOCK_NAMESPACE = 0x44563345


def normalize_email(value: str) -> str:
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail="El correo debe ser texto")
    canonical = value.strip(WHITESPACE).lower()
    if not canonical or len(canonical) > 255:
        raise HTTPException(
            status_code=422, detail="El correo debe tener entre 1 y 255 caracteres"
        )
    return canonical


def email_expression(column, *, postgres: bool):
    return func.lower(
        func.btrim(column, WHITESPACE) if postgres else func.trim(column, WHITESPACE)
    )


def email_conflict() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "USER_EMAIL_CONFLICT",
            "message": "El correo ya está registrado. Use otro correo",
        },
    )


async def claim_email(
    db: AsyncSession, email: str, *, excluding: UUID | None = None
) -> str:
    canonical = normalize_email(email)
    postgres = db.get_bind().dialect.name == "postgresql"
    if postgres:
        key = int.from_bytes(
            hashlib.sha256(canonical.encode("utf-8")).digest()[:4], "big", signed=True
        )
        await db.execute(
            select(
                func.pg_advisory_xact_lock(
                    literal(EMAIL_LOCK_NAMESPACE, type_=Integer),
                    literal(key, type_=Integer),
                )
            )
        )
    stmt = (
        select(User.id)
        .where(email_expression(User.email, postgres=postgres) == canonical)
        .limit(1)
    )
    if excluding is not None:
        stmt = stmt.where(User.id != excluding)
    with db.no_autoflush:
        if await db.scalar(stmt) is not None:
            raise email_conflict()
    return canonical


def is_email_unique_error(error: IntegrityError) -> bool:
    original = error.orig
    if isinstance(original, sqlite3.IntegrityError):
        return (
            getattr(original, "sqlite_errorcode", None)
            == sqlite3.SQLITE_CONSTRAINT_UNIQUE
            and str(original) == "UNIQUE constraint failed: users.email"
        )
    current = original
    states: set[str] = set()
    names: set[str] = set()
    for _ in range(8):
        if current is None:
            break
        for attribute in ["sqlstate", "pgcode"]:
            if value := getattr(current, attribute, None):
                states.add(str(value))
        name = getattr(current, "constraint_name", None) or getattr(
            getattr(current, "diag", None), "constraint_name", None
        )
        if name:
            names.add(name)
        current = getattr(current, "__cause__", None)
    return "23505" in states and bool(names & {"ix_users_email", "users_email_key"})


async def flush_email_change(db: AsyncSession) -> None:
    try:
        await db.flush()
    except IntegrityError as error:
        if not is_email_unique_error(error):
            raise
        await db.rollback()
        raise email_conflict() from None


async def find_email_account(db: AsyncSession, email: str) -> User | None:
    try:
        canonical = normalize_email(email)
    except HTTPException:
        return None
    stmt = (
        select(User)
        .where(
            email_expression(
                User.email, postgres=db.get_bind().dialect.name == "postgresql"
            )
            == canonical
        )
        .limit(2)
    )
    matches = list((await db.scalars(stmt)).all())
    return matches[0] if len(matches) == 1 else None
