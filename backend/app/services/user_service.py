"""Trusted user adapter: physical names, email claims and credential revocation.

Account deactivation is reversible; no physical deletion/tombstone is invented.
Public endpoints retain their own role and optimistic-revision policy.
"""

from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import NotFoundError, ValidationError
from app.core.security import get_password_hash
from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserUpdate
from app.services.user_emails import claim_email, find_email_account, flush_email_change
from app.services.user_revision import lock_user
from app.services.token_revocation import revoke_user_tokens


class UserService:
    async def get_user(self, db: AsyncSession, user_id: UUID) -> User:
        user = await db.scalar(select(User).where(User.id == user_id))
        if user is None:
            raise NotFoundError("Usuario no encontrado")
        return user

    async def get_user_by_email(self, db: AsyncSession, email: str) -> User | None:
        return await find_email_account(db, email)

    async def create_user(
        self, db: AsyncSession, user_data: UserCreate, created_by: int
    ) -> User:
        try:
            email = await claim_email(db, user_data.email)
            user = User(
                email=email,
                first_name=user_data.first_name,
                last_name=user_data.last_name,
                phone=user_data.phone,
                hashed_password=get_password_hash(user_data.password),
                role=UserRole(user_data.role.value),
                is_active=user_data.is_active,
            )
            db.add(user)
            await flush_email_change(db)
            await db.commit()
            return user
        except BaseException:
            await db.rollback()
            raise

    async def update_user(
        self, db: AsyncSession, user_id: UUID, user_data: UserUpdate, updated_by: int
    ) -> User:
        values = user_data.model_dump(exclude_unset=True)
        if any(
            values.get(k) is None
            for k in values.keys()
            & {"email", "first_name", "last_name", "role", "is_active", "password"}
        ):
            raise ValidationError("Un campo obligatorio no puede ser nulo")
        try:
            # Canonical email claim precedes the User lock, matching public edits.
            if "email" in values:
                values["email"] = await claim_email(
                    db, values["email"], excluding=user_id
                )
            user = await lock_user(db, user_id)
            security_changed = False
            if "password" in values:
                user.hashed_password = get_password_hash(values.pop("password"))
                user.reset_token = user.reset_token_expires = None
                security_changed = True
            if "role" in values:
                role = UserRole(values.pop("role"))
                security_changed |= role != user.role
                user.role = role
            if "is_active" in values:
                active = values.pop("is_active")
                security_changed |= active != user.is_active
                user.is_active = active
            for name, value in values.items():
                setattr(user, name, value)
            await flush_email_change(db)
            if security_changed:
                await revoke_user_tokens(db, user.id)
            await db.commit()
            await db.refresh(user)
            return user
        except BaseException:
            await db.rollback()
            raise

    async def delete_user(
        self, db: AsyncSession, user_id: UUID, deleted_by: int
    ) -> None:
        await self.deactivate_user(db, user_id, deleted_by)

    async def list_users(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        role: UserRole | None = None,
        is_active: bool | None = None,
    ) -> list[User]:
        if (
            type(skip) is not int
            or skip < 0
            or type(limit) is not int
            or not 1 <= limit <= 200
        ):
            raise ValidationError("Paginación de usuarios inválida")
        query = select(User)
        if role is not None:
            query = query.where(User.role == role)
        if is_active is not None:
            query = query.where(User.is_active.is_(is_active))
        return list(
            (await db.scalars(query.order_by(User.id).offset(skip).limit(limit))).all()
        )

    async def _set_active(self, db: AsyncSession, user_id: UUID, active: bool) -> User:
        try:
            user = await lock_user(db, user_id)
            if user.is_active != active:
                user.is_active = active
                await db.flush()
                await revoke_user_tokens(db, user.id)
            await db.commit()
            await db.refresh(user)
            return user
        except BaseException:
            await db.rollback()
            raise

    async def deactivate_user(
        self, db: AsyncSession, user_id: UUID, deactivated_by: int
    ) -> User:
        return await self._set_active(db, user_id, False)

    async def activate_user(
        self, db: AsyncSession, user_id: UUID, activated_by: int
    ) -> User:
        return await self._set_active(db, user_id, True)


user_service = UserService()
