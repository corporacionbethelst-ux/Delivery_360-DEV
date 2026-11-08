"""Authentication middleware for JWT validation."""

from fastapi import Request, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from app.core.security import decode_token as verify_token

security = HTTPBearer(auto_error=False)


async def get_current_user_from_request(request: Request) -> Optional[dict]:
    """Extract and validate JWT token from request."""
    credentials: Optional[HTTPAuthorizationCredentials] = await security(request)

    if not credentials:
        return None

    return verify_token(credentials.credentials, verify_type="access")


def require_auth():
    """Decorator to require authentication for an endpoint."""

    async def dependency(request: Request):
        credentials: Optional[HTTPAuthorizationCredentials] = await security(request)

        if not credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )

        payload = verify_token(credentials.credentials, verify_type="access")
        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        request.state.current_user = payload
        return payload

    return dependency


def require_role(*allowed_roles: str):
    """Decorator to require specific roles for an endpoint."""

    async def dependency(request: Request):
        # Get user from request state (set by auth middleware)
        user = getattr(request.state, "current_user", None)

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )

        user_role = user.get("role")
        if user_role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role {user_role} not authorized. Required: {allowed_roles}",
            )

        return user

    return dependency
