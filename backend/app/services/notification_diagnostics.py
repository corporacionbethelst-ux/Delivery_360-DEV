"""Local configuration inspection, without provider initialization or network I/O."""

from importlib.util import find_spec
import math
import os
from pathlib import Path
import re
import stat

from email_validator import validate_email, EmailNotValidError

from app.core.config import settings
from app.core.serialization import utc_isoformat
from app.models.notification import utc_now_naive
from app.schemas.notification_diagnostics import (
    CheckCode,
    CheckState,
    ProviderState,
    ProviderConfigurationCheck,
    ProviderDiagnostic,
    NotificationProviderDiagnostics,
)


def check(code: CheckCode, state: CheckState) -> ProviderConfigurationCheck:
    return ProviderConfigurationCheck(code=code, state=state)


def sdk_state(package: str) -> CheckState:
    try:
        return "ok" if find_spec(package) is not None else "missing"
    except Exception:
        # Finder/SDK errors may include private paths. No exception text is
        # returned or logged, and optional packages are never imported here.
        return "invalid"


def text_state(value: str | None) -> CheckState:
    return "ok" if value else "missing"


def timeout_state(value: float, minimum: float = 0) -> CheckState:
    return (
        "ok"
        if not isinstance(value, bool)
        and math.isfinite(value)
        and 0 < value <= 60
        and value >= minimum
        else "invalid"
    )


def sender_state(value: str | None) -> CheckState:
    if not value:
        return "missing"
    try:
        validate_email(value.strip(), check_deliverability=False, allow_smtputf8=False)
        return "ok"
    except EmailNotValidError:
        return "invalid"


def credential_file_state(path: str | None) -> CheckState:
    if not path:
        return "missing"
    try:
        info = Path(path).stat()
        return (
            "ok"
            if stat.S_ISREG(info.st_mode)
            and info.st_size > 0
            and os.access(path, os.R_OK)
            else "invalid"
        )
    except (OSError, ValueError):
        return "invalid"


def diagnostics() -> NotificationProviderDiagnostics:
    enabled = settings.NOTIFICATIONS_ENABLED
    email_checks = [
        check("mail_enabled", "ok" if settings.EMAILS_ENABLED else "disabled"),
        check(
            "host",
            (
                "missing"
                if not settings.SMTP_HOST.strip()
                else "invalid" if any(c.isspace() for c in settings.SMTP_HOST) else "ok"
            ),
        ),
        check(
            "port",
            (
                "ok"
                if type(settings.SMTP_PORT) is int and 1 <= settings.SMTP_PORT <= 65535
                else "invalid"
            ),
        ),
        check(
            "authentication",
            "ok" if settings.SMTP_USER and settings.SMTP_PASSWORD else "missing",
        ),
        check("sender", sender_state(settings.notification_email_from_computed)),
        check("tls", "ok" if settings.SMTP_TLS != settings.SMTP_SSL else "invalid"),
        check("timeout", timeout_state(settings.SMTP_TIMEOUT_SECONDS)),
    ]
    account = settings.TWILIO_ACCOUNT_SID
    phone = settings.TWILIO_FROM_NUMBER
    sms_checks = [
        check(
            "account_sid",
            (
                "missing"
                if not account
                else "ok" if re.fullmatch(r"AC[0-9a-fA-F]{32}", account) else "invalid"
            ),
        ),
        check("auth_token", text_state(settings.TWILIO_AUTH_TOKEN)),
        check(
            "sender",
            (
                "missing"
                if not phone
                else "ok" if re.fullmatch(r"\+[1-9][0-9]{6,14}", phone) else "invalid"
            ),
        ),
        check("sdk", sdk_state("twilio")),
        check(
            "timeout", timeout_state(settings.NOTIFICATION_PROVIDER_TIMEOUT_SECONDS, 1)
        ),
    ]
    push_checks = [
        check("credentials_reference", text_state(settings.FCM_CREDENTIALS_JSON_PATH)),
        check(
            "credentials_file",
            credential_file_state(settings.FCM_CREDENTIALS_JSON_PATH),
        ),
        check("sdk", sdk_state("firebase_admin")),
        check(
            "timeout", timeout_state(settings.NOTIFICATION_PROVIDER_TIMEOUT_SECONDS, 1)
        ),
    ]

    def state(checks: list[ProviderConfigurationCheck], paused: bool) -> ProviderState:
        return (
            "paused"
            if paused
            else (
                "locally_configured"
                if all(c.state == "ok" for c in checks)
                else "incomplete"
            )
        )

    providers = [
        ProviderDiagnostic(
            channel="EMAIL",
            provider="SMTP",
            state=state(email_checks, not enabled or not settings.EMAILS_ENABLED),
            checks=email_checks,
        ),
        ProviderDiagnostic(
            channel="SMS",
            provider="TWILIO",
            state=state(sms_checks, not enabled),
            checks=sms_checks,
        ),
        ProviderDiagnostic(
            channel="PUSH",
            provider="FCM",
            state=state(push_checks, not enabled),
            checks=push_checks,
        ),
    ]
    return NotificationProviderDiagnostics(
        checked_at=utc_isoformat(utc_now_naive()) or "",
        notifications_enabled=enabled,
        providers=providers,
    )
