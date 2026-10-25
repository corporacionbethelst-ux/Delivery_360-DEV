"""Profile state preconditions. Lock order: vehicles (if any), Rider, User."""

import hashlib
import hmac
import json
import re
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload
from app.models.rider import Rider
from app.models.user import User
from app.services.document_review import lock_rider

PROFILE_FIELDS = frozenset(
    {"first_name", "last_name", "phone", "operating_zone", "cpf", "cnh", "tier"}
)
RIDER_PROFILE_FIELDS = ["operating_zone", "cpf", "cnh", "tier"]


def profile_revision(rider: Rider) -> str:
    user = rider.user
    values = [
        str(rider.id),
        str(rider.user_id),
        user.first_name,
        user.last_name,
        user.phone,
        rider.operating_zone,
        rider.cpf,
        rider.cnh,
        getattr(rider.tier, "value", rider.tier),
    ]
    return hashlib.sha256(
        json.dumps(values, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


async def ensure_profile_revision(
    db: AsyncSession, rider: Rider, expected: str | None
) -> None:
    await lock_rider(db, rider.id)
    await db.refresh(rider, attribute_names=RIDER_PROFILE_FIELDS)
    user = await db.scalar(
        select(User)
        .options(raiseload("*"))
        .where(User.id == rider.user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None:
        raise HTTPException(
            status_code=409, detail="El usuario del perfil requiere revisión"
        )
    rider.user = user
    if expected is None:
        raise HTTPException(
            status_code=409,
            detail="Recargue y revise el perfil antes de guardar sus datos personales o nivel",
        )
    if not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise HTTPException(status_code=422, detail="Revisión de perfil inválida")
    if not hmac.compare_digest(profile_revision(rider), expected):
        raise HTTPException(
            status_code=409,
            detail="Los datos del perfil cambiaron. Recargue y revise el perfil antes de guardar",
        )
