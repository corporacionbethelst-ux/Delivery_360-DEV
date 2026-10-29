"""Local fiscal evidence and exact minor-unit arithmetic; no external submission."""

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from app.models.fiscal import ElectronicInvoice
from app.core.config import settings

MAX_CENTS = (1 << 63) - 1
PREVIEW_NOTE = "SANDBOX_PREVIEW: sin emisión ni aceptación fiscal"
NON_PRODUCTION = {
    "development",
    "dev",
    "test",
    "testing",
    "local",
    "sandbox",
    "staging",
    "stage",
}


def sandbox_allowed() -> bool:
    return settings.FISCAL_SANDBOX_ENABLED and all(
        value.strip().lower() in NON_PRODUCTION
        for value in (settings.APP_ENV, settings.ENVIRONMENT)
    )


def checked_cents(value: object) -> int:
    if type(value) is not int or not 0 <= value <= MAX_CENTS:
        raise ValueError("Importe en centavos inválido")
    return value


def money_to_cents(value: object) -> int:
    try:
        amount = Decimal(str(value if value is not None else 0))
        if not amount.is_finite() or amount < 0:
            raise ValueError("Importe monetario inválido")
        cents = int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, OverflowError):
        raise ValueError("Importe monetario inválido") from None
    return checked_cents(cents)


def decimal_amount(cents: int) -> str:
    if type(cents) is not int or abs(cents) > MAX_CENTS:
        raise ValueError("Importe en centavos inválido")
    return format(Decimal(cents) / 100, ".2f")


def invoice_evidence(invoice: ElectronicInvoice) -> dict:
    mode = invoice.execution_mode
    if mode not in {"sandbox", "real", "legacy_unverified"}:
        mode = "legacy_unverified"
    if (invoice.pdf_url or "").startswith("stub://"):
        mode = "sandbox"
    accepted = (
        mode == "real"
        and getattr(invoice.status, "value", invoice.status) == "ACEPTADA"
    )
    return {
        "execution_mode": mode,
        "is_simulation": mode == "sandbox",
        "is_officially_accepted": accepted,
        "status_source": "local_snapshot",
    }


def decimal_unit_amount(cents: int, quantity: int) -> str:
    if type(quantity) is not int or not 1 <= quantity <= 1000:
        raise ValueError("Cantidad de línea inválida")
    checked_cents(cents)
    return format(
        (Decimal(cents) / quantity / 100).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP
        ),
        ".6f",
    )
