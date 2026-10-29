"""Transactional account-wide revocation; callers own commit/rollback."""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.token_version import MAX_TOKEN_VERSION, valid_token_version
from app.models.user import User


async def revoke_user_tokens(
    db: AsyncSession, user_id: UUID, *, expected_version: int | None = None
) -> int | None:
    """Atomically advance the epoch without overwriting a concurrent increment.

    A captured logout may only retire its own epoch. Password/admin changes use
    the current database value, in the same transaction as their security write.
    No token, digest, session id or provider request is persisted here.
    """
    statement = update(User).where(
        User.id == user_id, User.token_version < MAX_TOKEN_VERSION
    )
    if expected_version is not None:
        if not valid_token_version(expected_version):
            raise ValueError("Invalid credential version")
        statement = statement.where(User.token_version == expected_version)
    result = await db.execute(
        statement.values(token_version=User.token_version + 1)
        .returning(User.token_version)
        .execution_options(synchronize_session=False)
    )
    # Keep RETURNING limited to the explicit scalar. ORM fetch synchronization
    # can inject primary-key columns into the returned result; callers do not
    # depend on cached User attributes and authentication reloads them.
    version = result.scalar_one_or_none()
    if version is not None and not valid_token_version(version):
        raise RuntimeError("Invalid credential version returned by persistence")
    if version is None and expected_version is None:
        raise HTTPException(
            status_code=409, detail="No se pudo invalidar la sesión de la cuenta"
        )
    return version
