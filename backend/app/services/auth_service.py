"""Compatibility authentication facade using canonical JWT epochs and live policy."""

from datetime import timedelta
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException
from passlib.context import CryptContext
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.core.token_version import token_version_matches
from app.models.user import User
from app.schemas.auth import TokenData, LoginRequest
from app.services.user_emails import find_email_account
from app.services.session_policy import ensure_session_allowed


class AuthService:
    def __init__(self):
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        try:
            return self.pwd_context.verify(plain_password, hashed_password)
        except (ValueError, TypeError):
            return False

    def get_password_hash(self, password: str) -> str:
        return self.pwd_context.hash(password)

    def create_access_token(
        self, data: dict, expires_delta: timedelta | None = None
    ) -> str:
        return create_access_token(
            data["sub"], expires_delta, token_version=data.get("ver", 0)
        )

    def create_refresh_token(self, data: dict) -> str:
        return create_refresh_token(data["sub"], token_version=data.get("ver", 0))

    def decode_token(self, token: str) -> TokenData | None:
        payload = decode_token(token)
        if not payload:
            return None
        return TokenData(user_id=payload.get("sub"), role=payload.get("role"))

    async def authenticate_user(
        self, db: AsyncSession, email: str, password: str
    ) -> User | None:
        user = await find_email_account(db, email)
        if user is None or not self.verify_password(password, user.hashed_password):
            return None
        return user

    async def login(
        self, db: AsyncSession, login_data: LoginRequest
    ) -> tuple[str, str, User]:
        user = await self.authenticate_user(db, login_data.email, login_data.password)
        if user is None:
            raise HTTPException(
                status_code=401,
                detail="Email o contraseña incorrectos",
                headers={"WWW-Authenticate": "Bearer"},
            )
        await ensure_session_allowed(db, user)
        return (
            create_access_token(user.id, token_version=user.token_version),
            create_refresh_token(user.id, token_version=user.token_version),
            user,
        )

    async def refresh_tokens(
        self, db: AsyncSession, refresh_token: str
    ) -> tuple[str, str]:
        payload = decode_token(refresh_token, verify_type="refresh")
        if payload is None:
            raise HTTPException(status_code=401, detail="Refresh token inválido")
        try:
            uid = UUID(payload["sub"])
        except (ValueError, TypeError, KeyError, AttributeError):
            raise HTTPException(status_code=401, detail="Refresh token inválido")
        user = await db.scalar(
            select(User).where(User.id == uid).execution_options(populate_existing=True)
        )
        if user is None or not token_version_matches(payload, user.token_version):
            raise HTTPException(status_code=401, detail="Credenciales no vigentes")
        await ensure_session_allowed(db, user)
        return create_access_token(
            user.id, token_version=user.token_version
        ), create_refresh_token(user.id, token_version=user.token_version)


auth_service = AuthService()
