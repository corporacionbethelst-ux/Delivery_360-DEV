from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
from pydantic import BaseModel, EmailStr
from typing import Optional
import logging, secrets, uuid
from app.core.config import settings

from app.services.document_uploads import validate_document, DocumentUploadBatch
from app.services.user_emails import claim_email, flush_email_change, find_email_account
from app.services.session_policy import ensure_session_allowed
from app.services.password_reset import issue_password_reset, consume_password_reset
from app.core.database import get_db
from app.core.security import (
    verify_password,
    hash_password,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.models.user import User, UserRole
from app.models.rider import Rider, RiderStatus

# Asegúrate de importar el modelo de documentos y sus enums
from app.models.rider_document import RiderDocument, DocumentType, DocumentStatus
from app.schemas.auth import ForgotPasswordRequest, ResetPasswordRequest

router = APIRouter(prefix="/auth")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

logger = logging.getLogger(__name__)


# ── Schemas ───────────────────────────────────────────────────────────────────
class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: str
    role: str
    full_name: str
    email: Optional[str] = None


class RefreshRequest(BaseModel):
    refresh_token: str


# ── Dependency: obtener usuario actual ────────────────────────────────────────
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciales inválidas",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_token(token)
    except Exception:
        raise credentials_exception

    if not payload or payload.get("type") != "access":
        raise credentials_exception
    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise credentials_exception
    try:
        user_uuid = uuid.UUID(subject)
    except ValueError:
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if not user or not user.is_active or user.role is None:
        raise credentials_exception

    await ensure_session_allowed(db, user)
    return user


def require_role(*roles: UserRole):
    async def checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Acceso denegado. Roles permitidos: {[r.value for r in roles]}",
            )
        return current_user

    return checker


# ── Endpoints ─────────────────────────────────────────────────────────────────
@router.post("/login", response_model=TokenResponse)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    user = await find_email_account(db, form_data.username)

    # Verificar credenciales básicas
    if (
        not user
        or not user.is_active
        or user.role is None
        or not verify_password(form_data.password, user.hashed_password)
    ):
        # Mensaje genérico por seguridad para no revelar si el email existe
        raise HTTPException(status_code=400, detail="Email o contraseña incorrectos")

    await ensure_session_allowed(db, user)

    # 3. Actualizar último login
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    user.last_login = now_naive
    await db.commit()

    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        refresh_token=create_refresh_token(str(user.id)),
        user_id=str(user.id),
        role=user.role.value,
        full_name=f"{user.first_name} {user.last_name}",
        email=user.email,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    payload = decode_token(body.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Token de refresco inválido")

    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise HTTPException(status_code=401, detail="Token de refresco inválido")
    try:
        user_id = uuid.UUID(subject)
    except ValueError:
        raise HTTPException(status_code=401, detail="Token de refresco inválido")
    result = await db.execute(
        select(User).where(User.id == user_id, User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()
    if not user or user.role is None:
        raise HTTPException(status_code=401, detail="Usuario no encontrado")

    await ensure_session_allowed(db, user)
    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        refresh_token=create_refresh_token(str(user.id)),
        user_id=str(user.id),
        role=user.role.value,
        full_name=f"{user.first_name} {user.last_name}",
        email=user.email,
    )


@router.post("/register-rider", status_code=201)
async def register_rider(
    # Datos de texto extraídos del FormData
    email: str = Form(...),
    password: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    phone: str = Form(None),
    vehicle_type: str = Form("MOTO"),
    vehicle_plate: Optional[str] = Form(None),
    # Archivos
    license_file: UploadFile = File(...),
    id_card_file: UploadFile = File(...),
    vehicle_registration_file: UploadFile = File(...),
    insurance_file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Registro público para repartidores con subida de documentos."""

    canonical_email = await claim_email(db, email)

    uploads = [
        (DocumentType.LICENCIA, license_file),
        (DocumentType.DOCUMENTO_IDENTIDAD, id_card_file),
        (DocumentType.REGISTRO_VEHICULO, vehicle_registration_file),
        (DocumentType.SEGURO, insurance_file),
    ]
    validated = [(kind, await validate_document(file)) for kind, file in uploads]
    async with DocumentUploadBatch(db) as batch:
        user = User(
            email=canonical_email,
            hashed_password=hash_password(password),
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            role=UserRole.REPARTIDOR,
            is_active=True,
        )
        db.add(user)
        await flush_email_change(db)
        rider = Rider(
            user_id=user.id,
            vehicle_type=vehicle_type,
            status=RiderStatus.PENDIENTE,
            is_online=False,
        )
        if vehicle_plate:
            rider.vehicle_plate = vehicle_plate
        db.add(rider)
        await db.flush()
        for kind, document in validated:
            reference = await batch.store(document, rider.id, kind)
            db.add(
                RiderDocument(
                    rider_id=rider.id,
                    type=kind,
                    status=DocumentStatus.PENDIENTE,
                    file_url=reference,
                )
            )
        response = {
            "message": "Registro exitoso. Tus documentos están siendo revisados por un gerente.",
            "user_id": str(user.id),
        }
        await batch.commit()
    return response


@router.post("/logout")
async def logout():
    return {"message": "Logout exitoso"}


@router.get("/me")
async def get_current_user_info(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    if current_user.role is None:
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "first_name": current_user.first_name,  # Debe venir de la DB
        "last_name": current_user.last_name,  # Debe venir de la DB
        "role": current_user.role.value,
        "is_active": current_user.is_active,
    }


# ==============================================================================
# RECUPERACIÓN DE CONTRASEÑA (Lote 12.1.3)
# ==============================================================================


@router.post("/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)
):
    """
    Solicita un restablecimiento de contraseña.
    Envía un correo con un token temporal (válido por 1 hora).
    Por seguridad, no revela si el email existe o no.
    """
    user = await find_email_account(db, body.email)

    response = {
        "message": "Si el correo está registrado y activo, recibirás un enlace de recuperación."
    }
    if not user or not user.is_active or not settings.EMAILS_ENABLED:
        return response

    # No token mutation when transport/link configuration cannot be used.
    try:
        from app.core.email_service import (
            password_reset_link,
            reset_email_is_configured,
            send_reset_email,
        )

        if not reset_email_is_configured():
            logger.warning("Password recovery unavailable: SMTP configuration")
            return response
        reset_token = secrets.token_urlsafe(32)
        reset_link = password_reset_link(reset_token)
    except Exception:
        logger.warning("Password recovery unavailable: email/link configuration")
        return response

    if not await issue_password_reset(db, user, reset_token):
        return response

    # Persist first so a delivered link is already usable. Do not hold DB locks
    # while talking to SMTP. Public output stays identical on provider failure.
    try:
        sent = await send_reset_email(user.email, reset_link)
    except Exception:
        sent = False
    if not sent:
        logger.warning("Password recovery request completed without SMTP acceptance")
    return response


@router.post("/reset-password")
async def reset_password(
    body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)
):
    """
    Restablece la contraseña usando un token válido.
    Valida que el token exista, no haya expirado y pertenezca a un usuario activo.
    """
    # 1. Validar longitud de contraseña (política de seguridad básica)
    if len(body.new_password) < 6:
        raise HTTPException(
            status_code=400, detail="La contraseña debe tener al menos 6 caracteres."
        )

    try:
        password_bytes = body.new_password.encode("utf-8")
    except UnicodeEncodeError:
        raise HTTPException(status_code=400, detail="La contraseña no es UTF-8 válido.")
    if b"\x00" in password_bytes:
        raise HTTPException(
            status_code=400, detail="La contraseña contiene caracteres no permitidos."
        )
    if len(password_bytes) > 72:
        raise HTTPException(
            status_code=400, detail="La contraseña no debe superar 72 bytes UTF-8."
        )
    await consume_password_reset(db, body.token, body.new_password)
    logger.info("Password reset completed")
    return {
        "message": "Contraseña actualizada exitosamente. Ahora puedes iniciar sesión."
    }
