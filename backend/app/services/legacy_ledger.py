"""Shared recorded-chain policy; no writes, cache assumptions or external settlement."""

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
from uuid import UUID
from app.core.reporting_period import utc_naive
from app.models.financial import PaymentStatus, TransactionType
from app.schemas.cache_reconciliation import (
    IntegrityState,
    IntegrityIssue,
    LedgerIntegrity,
)

# Tipos de crédito: aumentan el balance del rider (Fase 3 Inmutabilidad Financiera)
CREDIT_TYPES = {
    TransactionType.PAGO_ENTREGA,
    TransactionType.PAGO_INTENTO_FALLIDO,
    TransactionType.BONO_RENDIMIENTO,
    TransactionType.INGRESO,
    # Legacy
    TransactionType.BONO,
}

# Tipos de débito: disminuyen el balance del rider (Fase 3 Inmutabilidad Financiera)
DEBIT_TYPES = {
    TransactionType.PENALIZACION,
    TransactionType.RETIRO,
    TransactionType.AJUSTE_MANUAL,
    # Legacy
    TransactionType.DESCUENTO,
}


LEGACY_LEDGER_TYPES = CREDIT_TYPES | DEBIT_TYPES | {TransactionType.AJUSTE}

MAX_LEDGER_ROWS = 10000
MAX_ISSUES = 50
CENT = Decimal("0.01")
MAX_BALANCE = Decimal("99999999.99")
POLICY = "recorded-financials-chain-v1"
PROCESSED = {PaymentStatus.PROCESADO.value, PaymentStatus.PAGADO.value}
UNPROCESSED = {PaymentStatus.PENDIENTE.value, PaymentStatus.RECHAZADO.value}


def exact_money(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
        if (
            not result.is_finite()
            or abs(result) > MAX_BALANCE
            or result != result.quantize(CENT)
        ):
            return None
        return result.quantize(CENT)
    except (InvalidOperation, ValueError, TypeError):
        return None


def money_text(value: Decimal | None) -> str | None:
    return format(value, ".2f") if value is not None else None


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()


@dataclass(frozen=True)
class LedgerEntry:
    id: UUID
    amount: Decimal | None
    before: Decimal | None
    after: Decimal | None
    kind: str
    status: str | None
    created_at: datetime | None

    def evidence(self):
        return [
            str(self.id),
            str(self.amount),
            str(self.before),
            str(self.after),
            self.kind,
            self.status,
            utc_naive(self.created_at).isoformat() if self.created_at else None,
        ]


def analyze_ledger(
    rider_id: UUID,
    entries: list[LedgerEntry],
    *,
    truncated: bool = False,
    now: datetime | None = None,
) -> LedgerIntegrity:
    clock = utc_naive(now or datetime.now(timezone.utc))
    issues: list[IntegrityIssue] = []
    issue_count = 0
    processed = ignored = 0
    running = Decimal("0.00")
    previous_time = None
    latest = None

    def issue(code, entry=None):
        nonlocal issue_count
        issue_count += 1
        if len(issues) < MAX_ISSUES:
            issues.append(
                IntegrityIssue(code=code, transaction_id=entry.id if entry else None)
            )

    if truncated:
        issue("row_limit_exceeded")
    for row in entries:
        if row.status in UNPROCESSED:
            ignored += 1
            continue
        if row.status not in PROCESSED:
            issue("unknown_payment_status", row)
            continue
        processed += 1
        latest = row.id
        stamp = utc_naive(row.created_at) if row.created_at else None
        if stamp is None:
            issue("missing_timestamp", row)
        elif stamp > clock + timedelta(seconds=5):
            issue("future_timestamp", row)
        if stamp is not None and previous_time is not None and stamp <= previous_time:
            issue("ambiguous_or_disordered_timestamp", row)
        if stamp is not None:
            previous_time = stamp
        amount, before, after = (
            exact_money(row.amount),
            exact_money(row.before),
            exact_money(row.after),
        )
        if amount is None or amount == 0:
            issue("invalid_amount", row)
        if before is None or after is None:
            issue("missing_or_invalid_snapshot", row)
        try:
            kind = TransactionType(row.kind)
        except ValueError:
            kind = None
        delta = None
        if amount is not None:
            if kind in CREDIT_TYPES:
                delta = abs(amount)
            elif kind in DEBIT_TYPES:
                delta = -abs(amount)
            elif kind is TransactionType.AJUSTE:
                delta = amount
        if kind not in CREDIT_TYPES | DEBIT_TYPES | {TransactionType.AJUSTE}:
            issue("unsupported_transaction_type", row)
        if before is not None and before != running:
            issue(
                (
                    "unverified_opening_balance"
                    if processed == 1
                    else "chain_discontinuity"
                ),
                row,
            )
        if (
            delta is not None
            and before is not None
            and after is not None
            and after != before + delta
        ):
            issue("arithmetic_mismatch", row)
        if after is not None:
            running = after
    status: IntegrityState = (
        "requires_review" if issue_count else "verified" if processed else "no_evidence"
    )
    return LedgerIntegrity(
        status=status,
        examined_rows=len(entries),
        processed_rows=processed,
        ignored_unprocessed_rows=ignored,
        truncated=truncated,
        issue_count=issue_count,
        issues=issues,
        issues_truncated=issue_count > len(issues),
        verified_balance=money_text(running) if status == "verified" else None,
        latest_transaction_id=latest,
        ledger_fingerprint=digest(
            [
                POLICY,
                str(rider_id),
                truncated,
                [row.evidence() for row in entries],
                status,
                issue_count,
                [[x.code, str(x.transaction_id)] for x in issues],
            ]
        ),
    )
