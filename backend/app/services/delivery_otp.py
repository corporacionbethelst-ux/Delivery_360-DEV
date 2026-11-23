"""Explicit recipient email delivery, with durable codes and resend throttling."""

from datetime import datetime, timedelta, timezone
from html import escape
from uuid import UUID

from email_validator import EmailNotValidError, validate_email
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.delivery_rules import initialize_delivery_otp
from app.core.email_service import send_smtp_email, smtp_email_is_configured
from app.models.audit_log import ActionType, AuditLog
from app.models.delivery import Delivery, ProofType
from app.models.order import Order, OrderStatus
from app.models.user import User, UserRole

ATTEMPT_RESOURCE = "DELIVERY_OTP_EMAIL"


async def email_delivery_otp(db: AsyncSession, order_id: UUID, actor: User) -> dict:
    """Persist before SMTP; retries reuse the code, never claim inbox delivery."""
    if actor.role not in (UserRole.GERENTE, UserRole.SUPERADMIN):
        raise HTTPException(403, "El envío del OTP requiere gerencia")
    expected_version = actor.token_version
    order = await db.scalar(
        select(Order)
        .where(Order.id == order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if order is None:
        raise HTTPException(404, "Pedido no encontrado")
    if order.status != OrderStatus.EN_RUTA:
        raise HTTPException(409, "El OTP solo se puede enviar con la orden en ruta")
    records = list(
        (
            await db.scalars(
                select(Delivery)
                .where(Delivery.order_id == order_id)
                .order_by(Delivery.id)
                .limit(2)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    if len(records) != 1:
        raise HTTPException(409, "La orden requiere revisar su registro de entrega")
    delivery = records[0]
    if order.assigned_rider_id is None or delivery.rider_id != order.assigned_rider_id:
        raise HTTPException(409, "La asignación de la entrega requiere revisión")
    if delivery.proof_type != ProofType.OTP:
        raise HTTPException(409, "La entrega no está configurada con prueba OTP")
    # Do not let an old authenticated object authorize a revoked staff session.
    current_actor = await db.scalar(
        select(User)
        .where(User.id == actor.id)
        .execution_options(populate_existing=True)
    )
    if (
        current_actor is None
        or not current_actor.is_active
        or current_actor.token_version != expected_version
    ):
        raise HTTPException(401, "La sesión ya no está vigente")
    if current_actor.role not in (UserRole.GERENTE, UserRole.SUPERADMIN):
        raise HTTPException(403, "El envío del OTP requiere gerencia")
    try:
        recipient = validate_email(
            order.customer_email or "", check_deliverability=False, allow_smtputf8=False
        ).normalized
    except EmailNotValidError:
        raise HTTPException(
            409, "Registra un correo válido del destinatario antes de enviar el OTP"
        ) from None
    if not smtp_email_is_configured():
        raise HTTPException(
            503, "El correo de entrega no está configurado; contacta a administración"
        )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    recent = await db.scalar(
        select(AuditLog.id)
        .where(
            AuditLog.resource_type == ATTEMPT_RESOURCE,
            AuditLog.resource_id == str(order_id),
            AuditLog.created_at >= now - timedelta(seconds=60),
        )
        .limit(1)
    )
    if recent is not None:
        raise HTTPException(
            429,
            "Espera un minuto antes de volver a enviar el OTP",
            headers={"Retry-After": "60"},
        )
    generated = initialize_delivery_otp(delivery)
    code = delivery.proof_otp
    reference = str(order.external_id or order.id)
    actor_id, actor_email, actor_role = actor.id, actor.email, current_actor.role.value
    # This durable attempt is deliberately distinct from provider acceptance.
    db.add(
        AuditLog(
            user_id=actor_id,
            user_email=actor_email,
            user_role=actor_role,
            action_type=ActionType.UPDATE,
            resource_type=ATTEMPT_RESOURCE,
            resource_id=str(order_id),
            created_at=now,
            description="Solicitud de correo OTP de entrega",
            new_values={
                "generated": generated,
                "channel": "EMAIL",
                "outcome": "requested",
            },
        )
    )
    await db.commit()
    # No transaction/row lock is held during the provider request. A timeout or
    # process crash leaves a reusable code and an auditable unknown outcome.
    accepted = await send_smtp_email(
        recipient,
        "Código de entrega Delivery360",
        f"<p>Tu código para recibir la orden {escape(reference)} es:</p>"
        f"<p><strong>{escape(str(code))}</strong></p>"
        "<p>Compártelo con el repartidor únicamente al recibir tu pedido.</p>",
        f"Tu código para recibir la orden {reference} es: {code}. "
        "Compártelo con el repartidor únicamente al recibir tu pedido.",
    )
    db.add(
        AuditLog(
            user_id=actor_id,
            user_email=actor_email,
            user_role=actor_role,
            action_type=ActionType.UPDATE,
            resource_type="DELIVERY_OTP_EMAIL_RESULT",
            resource_id=str(order_id),
            success=accepted,
            description="Resultado del transporte de correo OTP",
            new_values={
                "channel": "EMAIL",
                "outcome": "accepted" if accepted else "failed",
            },
        )
    )
    await db.commit()
    if not accepted:
        raise HTTPException(
            503,
            "No se pudo confirmar el envío del correo. El código se conserva; puedes reintentar en un minuto",
        )
    return {
        "status": "accepted",
        "channel": "EMAIL",
        "message": "El servidor de correo aceptó el mensaje. Pide al destinatario revisar su bandeja y correo no deseado.",
    }
