"""Bounded legacy-cache reconciliation, with explicit units and state evidence."""

from datetime import datetime, date
from typing import Literal
from uuid import UUID
import unicodedata
from pydantic import BaseModel, ConfigDict, Field, field_validator

IntegrityState = Literal["verified", "requires_review", "no_evidence"]
CacheState = Literal[
    "ok", "within_tolerance", "discrepancy", "requires_review", "no_ledger_evidence"
]


class IntegrityIssue(BaseModel):
    code: str
    transaction_id: UUID | None = None


class LedgerIntegrity(BaseModel):
    status: IntegrityState
    source: Literal["financials"] = "financials"
    scope: Literal["processed_financials_chain"] = "processed_financials_chain"
    external_settlement_verified: Literal[False] = False
    examined_rows: int = Field(ge=0)
    processed_rows: int = Field(ge=0)
    ignored_unprocessed_rows: int = Field(ge=0)
    truncated: bool
    issue_count: int = Field(ge=0)
    issues: list[IntegrityIssue]
    issues_truncated: bool
    verified_balance: str | None
    latest_transaction_id: UUID | None
    ledger_fingerprint: str


class CachePreview(BaseModel):
    status: CacheState
    rider_id: UUID
    cache_store: Literal["riders.wallet_balance"] = "riders.wallet_balance"
    source: Literal["financials"] = "financials"
    currency: None = None
    currency_verified: Literal[False] = False
    dry_run: Literal[True] = True
    ledger_balance: str | None
    stored_balance: str | None
    difference: str | None
    adjustment_amount: str | None
    version: int | None
    fingerprint: str
    cache_issues: list[str]
    can_apply: bool
    generated_at: datetime
    integrity: LedgerIntegrity


class CacheSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0, le=2147483647, strict=True)
    expected_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=8, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def clean_reason(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if any(unicodedata.category(c) in ("Cc", "Cf", "Cs") for c in value):
                raise ValueError("El motivo no admite caracteres de control")
        return value


class CacheSyncResult(BaseModel):
    status: Literal["reconciled", "already_applied", "no_change"]
    rider_id: UUID
    dry_run: Literal[False] = False
    before_balance: str | None
    after_balance: str
    previous_version: int
    version: int
    audit_id: UUID | None
    ledger_changed: Literal[False] = False
    modern_wallet_changed: Literal[False] = False
    currency: None = None
    source: Literal["verified_financials_chain"] = "verified_financials_chain"


class CachePreviewPage(BaseModel):
    date: date
    scope: Literal["current_page"] = "current_page"
    dry_run: Literal[True] = True
    fixed_count: Literal[0] = 0
    total_adjusted_amount: Literal["0.00"] = "0.00"
    total_discrepancy_amount: None = None
    currency: None = None
    page_count: int = Field(ge=0)
    ok_count: int = Field(ge=0)
    discrepancy_count: int = Field(ge=0)
    requires_review_count: int = Field(ge=0)
    no_evidence_count: int = Field(ge=0)
    has_more: bool
    next_after_id: UUID | None
    details: list[CachePreview]


class LedgerAuditItem(BaseModel):
    rider_id: UUID
    integrity: LedgerIntegrity


class LedgerAuditPage(BaseModel):
    scope: Literal["current_page"] = "current_page"
    status: Literal["verified_page", "review_required", "no_evidence"]
    page_count: int
    verified_count: int
    requires_review_count: int
    no_evidence_count: int
    has_more: bool
    next_after_id: UUID | None
    details: list[LedgerAuditItem]
