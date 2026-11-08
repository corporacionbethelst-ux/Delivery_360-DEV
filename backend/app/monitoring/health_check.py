"""Bounded readiness checks; liveness must not restart pods for dependency outages."""

import asyncio
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text
from app.core.config import settings
from app.core.database import engine

router = APIRouter()
HEALTH_TIMEOUT_SECONDS = 2.0


async def _database_ready() -> bool:
    try:
        async with asyncio.timeout(HEALTH_TIMEOUT_SECONDS):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def _redis_ready() -> bool:
    try:
        async with asyncio.timeout(HEALTH_TIMEOUT_SECONDS):
            async with Redis.from_url(
                settings.REDIS_URL,
                socket_connect_timeout=HEALTH_TIMEOUT_SECONDS,
                socket_timeout=HEALTH_TIMEOUT_SECONDS,
            ) as client:
                return bool(await client.ping())
    except Exception:
        return False


@router.get("/check", tags=["Health"])
async def health_check():
    """Basic health check"""
    return {"status": "healthy", "service": "delivery360-api"}


@router.get(
    "/ready",
    tags=["Health"],
    responses={503: {"description": "Database or Redis unavailable"}},
)
async def readiness_check() -> JSONResponse:
    """Readiness check with database connectivity"""
    database, redis = await asyncio.gather(_database_ready(), _redis_ready())
    ready = database and redis
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ready" if ready else "not_ready",
            "checks": {"database": database, "redis": redis},
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/live", tags=["Health"])
async def liveness_check():
    """Liveness probe"""
    return {"status": "alive"}


health_router = router
health_check_router = router
