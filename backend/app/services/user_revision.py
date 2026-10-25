"""User metadata preconditions; this lock never requests a Rider lock."""

import hashlib
import hmac
import json
import re
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload
from app.models.user import User


def user_revision(user: User) -> str:
    values = [
        str(user.id),
        user.email,
        user.first_name,
        user.last_name,
        user.phone,
        user.avatar_url,
        getattr(user.role, "value", user.role),
        user.is_active,
        user.is_superuser,
    ]
    return hashlib.sha256(
        json.dumps(values, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


async def lock_user(db: AsyncSession, user_id: UUID) -> User:
    user = await db.scalar(
        select(User)
        .options(raiseload("*"))
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return user


def ensure_user_revision(user: User, expected: str | None) -> None:
    if expected is None:
        raise HTTPException(
            status_code=409,
            detail="Recargue y revise el usuario antes de guardar o desactivarlo",
        )
    if len(expected) == 66 and expected.startswith('"') and expected.endswith('"'):
        expected = expected[1:-1]
    if not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise HTTPException(status_code=422, detail="Revisión de usuario inválida")
    if not hmac.compare_digest(user_revision(user), expected):
        raise HTTPException(
            status_code=409,
            detail="El usuario cambió. Recargue y revise sus datos antes de continuar",
        )
