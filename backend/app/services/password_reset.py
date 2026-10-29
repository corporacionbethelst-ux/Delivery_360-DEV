"""Hashed recovery secrets and conditional, atomic password replacement."""

import hashlib
import re
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.security import hash_password
from app.models.user import User, utc_now_naive

_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
_PREFIX = "sha256$"


def reset_token_digest(token: str) -> str:
    return _PREFIX + hashlib.sha256(token.encode("ascii")).hexdigest()


def _invalid_token() -> HTTPException:
    return HTTPException(
        status_code=400,
        detail="Token inválido o expirado. Por favor solicita uno nuevo.",
    )


def _now(db: AsyncSession):
    # PostgreSQL now() is fixed at transaction start. Use the current wall clock
    # when evaluating eligibility, including after password hashing.
    if db.get_bind().dialect.name == "postgresql":
        return func.timezone("UTC", func.clock_timestamp())
    return utc_now_naive()


async def issue_password_reset(db: AsyncSession, user: User, token: str) -> bool:
    """Do not let a stale forgot request overwrite a changed account/password."""
    result = await db.execute(
        update(User)
        .where(
            User.id == user.id,
            User.email == user.email,
            User.hashed_password == user.hashed_password,
            User.is_active.is_(True),
        )
        .values(
            reset_token=reset_token_digest(token),
            reset_token_expires=_now(db) + timedelta(hours=1),
        )
        .returning(User.id)
        .execution_options(synchronize_session=False)
    )
    if result.scalar_one_or_none() is None:
        await db.rollback()
        return False
    await db.commit()
    return True


async def consume_password_reset(
    db: AsyncSession, token: str, new_password: str
) -> None:
    if not _TOKEN.fullmatch(token):
        raise _invalid_token()
    digest = reset_token_digest(token)
    matches = list(
        (
            await db.execute(
                select(User.id, User.email, User.hashed_password)
                .where(
                    User.reset_token == digest,
                    User.reset_token_expires > _now(db),
                    User.is_active.is_(True),
                )
                .limit(2)
            )
        ).all()
    )
    if len(matches) != 1:
        raise _invalid_token()
    uid, email, previous_password = matches[0]
    # bcrypt is CPU-bound; do not block other requests on the ASGI event loop.
    password_hash = await run_in_threadpool(hash_password, new_password)
    result = await db.execute(
        update(User)
        .where(
            User.id == uid,
            User.reset_token == digest,
            User.reset_token_expires > _now(db),
            User.is_active.is_(True),
            User.email == email,
            User.hashed_password == previous_password,
        )
        .values(
            hashed_password=password_hash,
            reset_token=None,
            reset_token_expires=None,
            token_version=User.token_version + 1,
        )
        .returning(User.id)
        .execution_options(synchronize_session=False)
    )
    if result.scalar_one_or_none() is None:
        await db.rollback()
        raise _invalid_token()
    # No password update can commit independently from invalidating its token.
    await db.commit()
