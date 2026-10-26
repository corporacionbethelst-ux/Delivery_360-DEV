"""Shared authenticated TLS SMTP transport; no simulated delivery."""

import asyncio
import logging
from email.message import EmailMessage
from email.utils import formataddr
from html import escape
from urllib.parse import urlencode, urlsplit

import aiosmtplib
from email_validator import EmailNotValidError, validate_email

from app.core.config import settings

logger = logging.getLogger(__name__)


def _mailbox(value: str) -> str:
    # A single address, without display names or SMTPUTF8 requirements.
    return validate_email(
        value.strip(), check_deliverability=False, allow_smtputf8=False
    ).normalized


def smtp_email_is_configured(from_address: str | None = None) -> bool:
    if not settings.EMAILS_ENABLED:
        return False
    if not (
        settings.SMTP_HOST.strip()
        and not any(c.isspace() for c in settings.SMTP_HOST)
        and settings.SMTP_USER
        and settings.SMTP_PASSWORD
        and 1 <= settings.SMTP_PORT <= 65535
        and settings.SMTP_TLS != settings.SMTP_SSL
        and 0 < settings.SMTP_TIMEOUT_SECONDS <= 60
    ):
        return False
    try:
        _mailbox(settings.EMAIL_FROM if from_address is None else from_address)
    except EmailNotValidError:
        return False
    return True


def reset_email_is_configured() -> bool:
    return smtp_email_is_configured()


def password_reset_link(token: str) -> str:
    """Use only the configured frontend origin/path, never request headers."""
    base = settings.FRONTEND_URL.rstrip("/")
    parsed = urlsplit(base)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (parsed.port is not None and not 1 <= parsed.port <= 65535)
        or any(c.isspace() for c in base)
        or (settings.ENVIRONMENT.lower() == "production" and parsed.scheme != "https")
    ):
        raise ValueError("Invalid password recovery frontend URL")
    return f"{base}/reset-password?{urlencode({'token': token})}"


async def send_smtp_email(
    email: str, subject: str, html: str, plain: str, *, from_address: str | None = None
) -> bool:
    """True means SMTP accepted the message, not confirmed inbox delivery."""
    if not smtp_email_is_configured(from_address):
        logger.warning("SMTP email unavailable: configuration")
        return False
    client = None
    try:
        recipient = _mailbox(email)
        sender = _mailbox(settings.EMAIL_FROM if from_address is None else from_address)
        message = EmailMessage()
        message["From"] = formataddr((settings.APP_NAME, sender))
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(plain)
        message.add_alternative(html, subtype="html")
        client = aiosmtplib.SMTP(
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            start_tls=settings.SMTP_TLS,
            use_tls=settings.SMTP_SSL,
            validate_certs=True,
            timeout=settings.SMTP_TIMEOUT_SECONDS,
            local_hostname="delivery360",
        )

        async def deliver():
            await client.connect()
            result = await client.send_message(
                message, sender=sender, recipients=[recipient]
            )
            await client.quit()
            return result

        refused, _ = await asyncio.wait_for(
            deliver(), timeout=settings.SMTP_TIMEOUT_SECONDS
        )
        if refused:
            logger.warning("SMTP email rejected")
            return False
    except Exception:
        # SMTP exceptions may include recipient, server transcript or credentials.
        logger.warning("SMTP email failed")
        return False
    finally:
        # connect() in the pinned client can fail after opening the transport
        # (STARTTLS/auth). Close explicitly even before context entry succeeds.
        if client is not None:
            client.close()
    logger.info("SMTP email accepted")
    return True


async def send_reset_email(email: str, reset_link: str) -> bool:
    plain = (
        "Has solicitado restablecer tu contraseña en Delivery360.\n\n"
        f"Abre este enlace para continuar:\n{reset_link}\n\n"
        "El enlace expira en 1 hora. Si no lo solicitaste, ignora este correo."
    )
    link = escape(reset_link, quote=True)
    html = (
        "<html><body><h2>Recuperación de contraseña</h2>"
        "<p>Has solicitado restablecer tu contraseña en Delivery360.</p>"
        f'<p><a href="{link}">Restablecer contraseña</a></p>'
        f"<p>O copia y pega este enlace en tu navegador: {link}</p>"
        "<p>El enlace expira en 1 hora. Si no lo solicitaste, ignora este correo.</p>"
        "</body></html>"
    )
    return await send_smtp_email(
        email, "Recuperación de contraseña - Delivery360", html, plain
    )
