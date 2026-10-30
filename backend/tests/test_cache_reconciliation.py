"""Recorded-chain evidence and real PostgreSQL/HTTP cache-only reconciliation."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4, UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError as SchemaError
from sqlalchemy import select, func, update, delete, text
from app.main import app
from app.core.database import get_db
from app.core.exceptions import AppException, NotFoundError
from app.core.rate_limiter import RateLimiter
from app.core.security import create_access_token
from app.middleware import rate_limit_middleware
from app.models.audit_log import AuditLog
from app.models.financial import (
    Financial,
    RiderWallet,
    FinancialTransaction,
    PaymentStatus,
    TransactionType,
)
from app.models.rider import Rider, RiderStatus
from app.models.user import User, UserRole
from app.schemas.cache_reconciliation import CacheSyncRequest
from app.services.cache_reconciliation import (
    CacheReconciliationService,
    LedgerEntry,
    analyze_ledger,
    exact_money,
)
from app.services.financial_service import FinancialService, CREDIT_TYPES, DEBIT_TYPES
from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from tests.test_reconciliation_postgresql import pg_reconciliation  # noqa: F401

CLOCK = datetime(2026, 10, 24, 12)
RID = UUID("00000000-0000-0000-0000-000000000001")
REASON = "Revisión y reparación explícita de caché"


def entry(**values):
    return LedgerEntry(
        **{
            "id": uuid4(),
            "amount": Decimal("100.00"),
            "before": Decimal("0.00"),
            "after": Decimal("100.00"),
            "kind": "INGRESO",
            "status": "PROCESADO",
            "created_at": CLOCK - timedelta(hours=2),
            **values,
        }
    )


def audit(*rows, **values):
    return analyze_ledger(RID, list(rows), now=CLOCK, **values)


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        "NaN",
        "Infinity",
        "-Infinity",
        Decimal("NaN"),
        Decimal("Infinity"),
        "bad",
        "0.001",
        "0.30000000000000004",
        "100000000.00",
        "-100000000.00",
        object(),
    ],
)
def test_invalid_money_is_unknown_instead_of_zero(value):
    assert exact_money(value) is None


@pytest.mark.parametrize(
    "value,expected",
    [
        ("0", "0.00"),
        ("100", "100.00"),
        ("-1.23", "-1.23"),
        ("99999999.99", "99999999.99"),
        ("-99999999.99", "-99999999.99"),
    ],
)
def test_exact_cents_and_range_boundaries(value, expected):
    assert exact_money(value) == Decimal(expected)


@pytest.mark.parametrize(
    "kind", list(CREDIT_TYPES | DEBIT_TYPES | {TransactionType.AJUSTE})
)
def test_supported_legacy_types_have_explicit_arithmetic(kind):
    amount = Decimal("-5.00")
    delta = abs(amount) if kind in CREDIT_TYPES else -abs(amount)
    rows = [
        entry(),
        entry(
            amount=amount,
            before=Decimal("100.00"),
            after=Decimal("100.00") + delta,
            kind=kind.value,
            created_at=CLOCK - timedelta(hours=1),
        ),
    ]
    result = audit(*rows)
    assert result.status == "verified" and result.verified_balance == format(
        Decimal("100.00") + delta, ".2f"
    )
    assert result.processed_rows == 2 and result.external_settlement_verified is False


@pytest.mark.parametrize(
    "kind",
    [
        x
        for x in TransactionType
        if x not in CREDIT_TYPES | DEBIT_TYPES | {TransactionType.AJUSTE}
    ],
)
def test_other_financial_type_cannot_be_assumed_to_be_a_credit(kind):
    result = audit(entry(kind=kind.value))
    assert result.status == "requires_review" and result.verified_balance is None
    assert "unsupported_transaction_type" in [x.code for x in result.issues]


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"before": None}, "missing_or_invalid_snapshot"),
        ({"after": None}, "missing_or_invalid_snapshot"),
        ({"amount": Decimal("NaN")}, "invalid_amount"),
        ({"amount": Decimal("0")}, "invalid_amount"),
        ({"after": Decimal("101")}, "arithmetic_mismatch"),
        (
            {"before": Decimal("1"), "after": Decimal("101")},
            "unverified_opening_balance",
        ),
        ({"created_at": None}, "missing_timestamp"),
        ({"created_at": CLOCK + timedelta(seconds=6)}, "future_timestamp"),
        ({"status": None}, "unknown_payment_status"),
        ({"status": "UNKNOWN"}, "unknown_payment_status"),
        ({"kind": "UNKNOWN"}, "unsupported_transaction_type"),
        ({"before": Decimal("Infinity")}, "missing_or_invalid_snapshot"),
    ],
)
def test_incomplete_or_inconsistent_records_never_yield_a_verified_balance(
    changes, code
):
    result = audit(entry(**changes))
    assert result.status == "requires_review" and result.verified_balance is None
    assert code in [x.code for x in result.issues]


def test_empty_or_only_unprocessed_ledger_is_not_evidence_of_zero():
    for rows in ([], [entry(status="PENDIENTE"), entry(status="RECHAZADO")]):
        result = audit(*rows)
        assert result.status == "no_evidence" and result.verified_balance is None
        assert result.processed_rows == 0


def test_unprocessed_amounts_are_ignored_explicitly_not_summed():
    result = audit(
        entry(),
        entry(status="PENDIENTE", amount=Decimal("999"), after=None),
        entry(status="RECHAZADO"),
    )
    assert result.status == "verified" and result.verified_balance == "100.00"
    assert result.ignored_unprocessed_rows == 2


def test_continuity_timestamp_ties_and_reversed_history_require_review():
    first = entry()
    second = entry(
        amount=Decimal("5"),
        before=Decimal("100"),
        after=Decimal("105"),
        created_at=CLOCK - timedelta(hours=1),
    )
    assert audit(first, second).status == "verified"
    assert "chain_discontinuity" in [
        x.code for x in audit(first, replace(second, before=Decimal("99"))).issues
    ]
    assert "ambiguous_or_disordered_timestamp" in [
        x.code
        for x in audit(first, replace(second, created_at=first.created_at)).issues
    ]
    assert audit(second, first).status == "requires_review"


def test_limits_and_issue_truncation_do_not_claim_a_complete_audit():
    result = audit(entry(), truncated=True)
    assert (
        result.status == "requires_review"
        and result.truncated
        and result.verified_balance is None
    )
    many = [entry(amount=Decimal("0"), before=None, after=None) for _ in range(100)]
    result = audit(*many)
    assert (
        len(result.issues) == 50 and result.issue_count > 50 and result.issues_truncated
    )


def test_fingerprint_binds_both_records_and_the_assessment():
    row = entry()
    assert audit(row).ledger_fingerprint == audit(row).ledger_fingerprint
    assert (
        audit(row).ledger_fingerprint
        != audit(replace(row, status="PAGADO")).ledger_fingerprint
    )
    future = entry(created_at=CLOCK + timedelta(seconds=10))
    first = analyze_ledger(RID, [future], now=CLOCK)
    later = analyze_ledger(RID, [future], now=CLOCK + timedelta(seconds=6))
    assert first.status == "requires_review" and later.status == "verified"
    assert first.ledger_fingerprint != later.ledger_fingerprint


@pytest.mark.parametrize(
    "values",
    [
        {"expected_version": True},
        {"expected_version": -1},
        {"expected_version": 2147483648},
        {"expected_fingerprint": "x" * 64},
        {"expected_fingerprint": "A" * 64},
        {"expected_fingerprint": "0" * 63},
        {"reason": " "},
        {"reason": "short"},
        {"reason": "x" * 501},
        {"reason": "a\nbbbbbbbb"},
        {"reason": "a\x00bbbbbbbb"},
        {"target_balance": "1000.00"},
    ],
)
def test_apply_request_does_not_accept_unreviewed_targets_or_invalid_identity(values):
    base = {
        "expected_version": 0,
        "expected_fingerprint": "a" * 64,
        "reason": REASON,
        **values,
    }
    with pytest.raises(SchemaError):
        CacheSyncRequest.model_validate(base)


@pytest.fixture
async def cache_db(pg_reconciliation, monkeypatch):
    sessions, rid = pg_reconciliation
    monkeypatch.setattr(rate_limit_middleware, "rate_limiter", RateLimiter())
    ids = {"rider": rid}
    async with sessions() as db:
        conn = await db.connection()
        await conn.run_sync(Rider.__table__.c.status.type.create, checkfirst=True)
        await db.execute(
            text("ALTER TABLE riders ADD COLUMN status riderstatus DEFAULT 'ACTIVO'")
        )
        await conn.run_sync(AuditLog.__table__.create)
        await db.execute(
            update(Financial).values(
                created_at=CLOCK - timedelta(hours=2),
                description="private-customer-detail",
                reference_id="private-bank-reference",
            )
        )
        ids["entry"] = await db.scalar(select(Financial.id))
        ids["owner"] = await db.scalar(select(Rider.user_id).where(Rider.id == rid))
        for name, role in {
            "super": UserRole.SUPERADMIN,
            "manager": UserRole.GERENTE,
            "operator": UserRole.OPERADOR,
            "auditor": UserRole.AUDITOR,
            "customer": UserRole.CLIENTE,
            "inactive": UserRole.SUPERADMIN,
            "roleless": UserRole.SUPERADMIN,
        }.items():
            user = User(
                id=uuid4(),
                email=name + "@cache.test",
                hashed_password="unused",
                first_name=name,
                last_name="Test",
                role=role,
                is_active=name != "inactive",
            )
            db.add(user)
            ids[name] = user.id
        await db.flush()
        await db.execute(
            update(User).where(User.id == ids["roleless"]).values(role=None)
        )
        await db.commit()
    old = app.dependency_overrides.copy()

    async def database():
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = database
    client = TestClient(app)
    try:
        yield client, sessions, ids
    finally:
        client.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(old)


def auth(ids, who="super"):
    return {"Authorization": "Bearer " + create_access_token(ids[who])}


def command(preview, **values):
    raw = preview.model_dump() if hasattr(preview, "model_dump") else preview
    return CacheSyncRequest(
        expected_version=raw["version"],
        expected_fingerprint=raw["fingerprint"],
        reason=REASON,
        **values,
    )


def path(ids):
    return f"/api/v1/reconciliation/wallet/{ids['rider']}"


async def state(sessions, rid):
    async with sessions() as db:
        cache = (
            await db.execute(
                select(Rider.wallet_balance, Rider.version).where(Rider.id == rid)
            )
        ).one()
        entries = (
            await db.execute(
                select(
                    Financial.id,
                    Financial.amount,
                    Financial.balance_before,
                    Financial.balance_after,
                    Financial.status,
                ).order_by(Financial.id)
            )
        ).all()
        modern = (
            await db.execute(
                select(RiderWallet.id, RiderWallet.balance_cents).order_by(
                    RiderWallet.id
                )
            )
        ).all()
        modern_entries = await db.scalar(
            select(func.count()).select_from(FinancialTransaction)
        )
        audits = await db.scalar(select(func.count()).select_from(AuditLog))
        return (
            tuple(cache),
            list(map(tuple, entries)),
            list(map(tuple, modern)),
            modern_entries,
            audits,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "who,read,write,audit_status",
    [
        ("super", 200, 200, 200),
        ("manager", 200, 403, 403),
        ("auditor", 403, 403, 200),
        ("operator", 403, 403, 403),
        ("customer", 403, 403, 403),
        ("owner", 403, 403, 403),
        ("inactive", 401, 401, 401),
        ("roleless", 401, 401, 401),
    ],
)
async def test_real_mounted_role_matrix(cache_db, who, read, write, audit_status):
    client, sessions, ids = cache_db
    before = await state(sessions, ids["rider"])
    for url in (path(ids), "/api/v1/reconciliation/batch/daily"):
        response = client.get(url, headers=auth(ids, who))
        assert response.status_code == read, response.text
        assert (
            "private-bank-reference" not in response.text
            and "private-customer-detail" not in response.text
        )
    assert (
        client.get(
            "/api/v1/reconciliation/audit/ledger-integrity", headers=auth(ids, who)
        ).status_code
        == audit_status
    )
    assert client.post(path(ids) + "/sync", headers=auth(ids, who)).status_code == write
    assert (
        client.post(
            "/api/v1/reconciliation/fix-all-discrepancies", headers=auth(ids, who)
        ).status_code
        == write
    )
    assert await state(sessions, ids["rider"]) == before


@pytest.mark.asyncio
async def test_preview_and_batch_never_move_legacy_or_modern_money(cache_db):
    client, sessions, ids = cache_db
    before = await state(sessions, ids["rider"])
    data = client.get(path(ids), headers=auth(ids, "manager")).json()
    assert (
        data["status"] == "discrepancy"
        and data["can_apply"] is True
        and data["dry_run"] is True
    )
    assert (
        data["stored_balance"] == "3.00"
        and data["ledger_balance"] == "100.00"
        and data["adjustment_amount"] == "97.00"
    )
    assert data["currency"] is None and data["currency_verified"] is False
    assert data["integrity"]["external_settlement_verified"] is False
    batch = client.get("/api/v1/reconciliation/batch/daily", headers=auth(ids)).json()
    assert (
        batch["page_count"] == 2
        and batch["discrepancy_count"] == 1
        and batch["no_evidence_count"] == 1
    )
    assert (
        batch["total_discrepancy_amount"] is None
        and batch["fixed_count"] == 0
        and batch["total_adjusted_amount"] == "0.00"
    )
    assert await state(sessions, ids["rider"]) == before


@pytest.mark.asyncio
async def test_apply_requires_explicit_review_and_never_accepts_a_target_amount(
    cache_db,
):
    client, sessions, ids = cache_db
    before = await state(sessions, ids["rider"])
    assert (
        client.post(path(ids) + "/sync?dry_run=false", headers=auth(ids)).status_code
        == 428
    )
    preview = client.get(path(ids), headers=auth(ids)).json()
    body = command(preview).model_dump()
    assert (
        client.post(
            path(ids) + "/sync?dry_run=false",
            headers=auth(ids),
            json={**body, "target_balance": "9999"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/reconciliation/fix-all-discrepancies?dry_run=false",
            headers=auth(ids),
        ).status_code
        == 409
    )
    assert await state(sessions, ids["rider"]) == before


@pytest.mark.asyncio
async def test_explicit_apply_is_cache_only_audited_and_same_operation_replays(
    cache_db,
):
    client, sessions, ids = cache_db
    before = await state(sessions, ids["rider"])
    preview = client.get(path(ids), headers=auth(ids)).json()
    body = command(preview).model_dump()
    first = client.post(path(ids) + "/sync?dry_run=false", headers=auth(ids), json=body)
    assert first.status_code == 200, first.text
    result = first.json()
    assert (
        result["status"] == "reconciled"
        and result["before_balance"] == "3.00"
        and result["after_balance"] == "100.00"
    )
    assert (
        result["version"] == 1
        and result["ledger_changed"] is result["modern_wallet_changed"] is False
    )
    replay = client.post(
        path(ids) + "/sync?dry_run=false", headers=auth(ids), json=body
    )
    assert (
        replay.status_code == 200
        and replay.json()["status"] == "already_applied"
        and replay.json()["audit_id"] == result["audit_id"]
    )
    after = await state(sessions, ids["rider"])
    assert (
        after[0] == (Decimal("100.00"), 1)
        and after[1:4] == before[1:4]
        and after[4] == 1
    )
    async with sessions() as db:
        audit = await db.get(AuditLog, UUID(result["audit_id"]))
        assert audit.user_id == ids["super"] and audit.changes_summary == REASON
        assert (
            audit.old_values["stored_balance"] == "3.00"
            and audit.new_values["stored_balance"] == "100.00"
        )
    # Same before-state token with another identity/reason cannot rewrite the receipt.
    assert (
        client.post(
            path(ids) + "/sync?dry_run=false",
            headers=auth(ids),
            json={**body, "reason": "Otro motivo administrativo"},
        ).status_code
        == 409
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["cache", "version", "ledger", "delete"])
async def test_intervening_changes_make_the_preview_stale(cache_db, change):
    client, sessions, ids = cache_db
    preview = client.get(path(ids), headers=auth(ids)).json()
    async with sessions() as db:
        if change == "cache":
            await db.execute(
                update(Rider).where(Rider.id == ids["rider"]).values(wallet_balance=4)
            )
        elif change == "version":
            await db.execute(
                update(Rider).where(Rider.id == ids["rider"]).values(version=1)
            )
        elif change == "ledger":
            await db.execute(update(Financial).values(amount=110, balance_after=110))
        else:
            await db.execute(delete(Financial))
        await db.commit()
    before = await state(sessions, ids["rider"])
    result = client.post(
        path(ids) + "/sync?dry_run=false",
        headers=auth(ids),
        json=command(preview).model_dump(),
    )
    assert result.status_code == 409 and await state(sessions, ids["rider"]) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "no_evidence",
        "opening",
        "arithmetic",
        "null_snapshot",
        "nan_amount",
        "unsupported_type",
        "unknown_status",
        "future",
        "nan_cache",
        "version_exhausted",
    ],
)
async def test_unverified_or_invalid_data_cannot_be_applied(cache_db, change):
    client, sessions, ids = cache_db
    async with sessions() as db:
        if change == "no_evidence":
            await db.execute(delete(Financial))
        elif change == "opening":
            await db.execute(
                update(Financial).values(balance_before=1, balance_after=101)
            )
        elif change == "arithmetic":
            await db.execute(update(Financial).values(balance_after=101))
        elif change == "null_snapshot":
            await db.execute(update(Financial).values(balance_before=None))
        elif change == "nan_amount":
            await db.execute(update(Financial).values(amount=Decimal("NaN")))
        elif change == "unsupported_type":
            await db.execute(
                update(Financial).values(transaction_type=TransactionType.STRIPE_PAYOUT)
            )
        elif change == "unknown_status":
            await db.execute(update(Financial).values(status=None))
        elif change == "future":
            await db.execute(
                update(Financial).values(
                    created_at=datetime.now(timezone.utc).replace(tzinfo=None)
                    + timedelta(hours=1)
                )
            )
        elif change == "nan_cache":
            await db.execute(
                update(Rider)
                .where(Rider.id == ids["rider"])
                .values(wallet_balance=Decimal("NaN"))
            )
        else:
            await db.execute(
                update(Rider).where(Rider.id == ids["rider"]).values(version=2147483647)
            )
        await db.commit()
    preview = client.get(path(ids), headers=auth(ids)).json()
    assert (
        preview["status"] in ("requires_review", "no_ledger_evidence")
        and not preview["can_apply"]
    )
    before = await state(sessions, ids["rider"])
    response = client.post(
        path(ids) + "/sync?dry_run=false",
        headers=auth(ids),
        json=command(preview).model_dump(),
    )
    assert response.status_code == 409
    # NaN does not compare equal to itself; compare its textual SQL state.
    after = await state(sessions, ids["rider"])
    assert repr(after) == repr(before)


@pytest.mark.asyncio
@pytest.mark.parametrize("balance", [Decimal("100.00"), Decimal("99.99")])
async def test_zero_and_one_cent_difference_are_noops(cache_db, balance):
    client, sessions, ids = cache_db
    async with sessions() as db:
        await db.execute(
            update(Rider).where(Rider.id == ids["rider"]).values(wallet_balance=balance)
        )
        await db.commit()
    before = await state(sessions, ids["rider"])
    preview = client.get(path(ids), headers=auth(ids)).json()
    assert preview["status"] in ("ok", "within_tolerance") and not preview["can_apply"]
    result = client.post(
        path(ids) + "/sync?dry_run=false",
        headers=auth(ids),
        json=command(preview).model_dump(),
    )
    assert (
        result.status_code == 200
        and result.json()["status"] == "no_change"
        and result.json()["audit_id"] is None
    )
    assert await state(sessions, ids["rider"]) == before


@pytest.mark.asyncio
async def test_null_cache_can_be_rebuilt_only_from_verified_records(cache_db):
    client, sessions, ids = cache_db
    async with sessions() as db:
        await db.execute(
            update(Rider).where(Rider.id == ids["rider"]).values(wallet_balance=None)
        )
        await db.commit()
    preview = client.get(path(ids), headers=auth(ids)).json()
    assert (
        preview["stored_balance"] is preview["difference"] is None
        and preview["can_apply"] is True
    )
    result = client.post(
        path(ids) + "/sync?dry_run=false",
        headers=auth(ids),
        json=command(preview).model_dump(),
    )
    assert (
        result.status_code == 200
        and result.json()["before_balance"] is None
        and result.json()["after_balance"] == "100.00"
    )


@pytest.mark.asyncio
async def test_empty_ledger_does_not_zero_an_existing_cache(cache_db):
    _, sessions, ids = cache_db
    async with sessions() as db:
        other = await db.scalar(select(Rider.id).where(Rider.id != ids["rider"]))
        result = await CacheReconciliationService(db).preview(other)
        assert (
            result.status == "no_ledger_evidence"
            and result.ledger_balance is None
            and result.stored_balance == "3.00"
        )


@pytest.mark.asyncio
async def test_pending_rows_do_not_increase_balance_and_inactive_riders_are_included(
    cache_db,
):
    client, sessions, ids = cache_db
    async with sessions() as db:
        db.add(
            Financial(
                rider_id=ids["rider"],
                amount=999,
                balance_before=None,
                balance_after=None,
                transaction_type=TransactionType.INGRESO,
                status=PaymentStatus.PENDIENTE,
            )
        )
        await db.execute(
            update(Rider)
            .where(Rider.id == ids["rider"])
            .values(status=RiderStatus.INACTIVO)
        )
        await db.commit()
    data = client.get(path(ids), headers=auth(ids)).json()
    assert (
        data["ledger_balance"] == "100.00"
        and data["integrity"]["ignored_unprocessed_rows"] == 1
    )
    page = client.get(
        "/api/v1/reconciliation/batch/daily?rider_status=INACTIVO", headers=auth(ids)
    ).json()
    assert page["page_count"] == 1 and page["details"][0]["rider_id"] == str(
        ids["rider"]
    )


@pytest.mark.asyncio
async def test_oversized_history_blocks_apply_without_returning_a_partial_balance(
    cache_db, monkeypatch
):
    import app.services.cache_reconciliation as module

    client, sessions, ids = cache_db
    monkeypatch.setattr(module, "MAX_LEDGER_ROWS", 1)
    async with sessions() as db:
        db.add(
            Financial(
                rider_id=ids["rider"],
                amount=1,
                balance_before=100,
                balance_after=101,
                transaction_type=TransactionType.INGRESO,
                status=PaymentStatus.PROCESADO,
                created_at=CLOCK - timedelta(hours=1),
            )
        )
        await db.commit()
    data = client.get(path(ids), headers=auth(ids)).json()
    assert (
        data["status"] == "requires_review"
        and data["ledger_balance"] is None
        and data["integrity"]["truncated"]
    )
    assert "row_limit_exceeded" in [x["code"] for x in data["integrity"]["issues"]]
    assert (
        client.post(
            path(ids) + "/sync?dry_run=false",
            headers=auth(ids),
            json=command(data).model_dump(),
        ).status_code
        == 409
    )


@pytest.mark.asyncio
async def test_keyset_pagination_and_audit_page_have_local_counts_only(cache_db):
    client, sessions, ids = cache_db
    first = client.get(
        "/api/v1/reconciliation/batch/daily?limit=1", headers=auth(ids)
    ).json()
    second = client.get(
        "/api/v1/reconciliation/batch/daily?limit=1&after_id=" + first["next_after_id"],
        headers=auth(ids),
    ).json()
    assert (
        first["has_more"] and not second["has_more"] and second["next_after_id"] is None
    )
    assert first["details"][0]["rider_id"] < second["details"][0]["rider_id"]
    result = client.get(
        "/api/v1/reconciliation/audit/ledger-integrity", headers=auth(ids, "auditor")
    ).json()
    assert (
        result["page_count"] == 2
        and result["verified_count"] == 1
        and result["no_evidence_count"] == 1
        and result["status"] == "no_evidence"
    )
    assert all("stored_balance" not in item for item in result["details"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=26",
        "after_id=bad",
        "rider_status=bad",
        "target_date=2020-01-01",
    ],
)
async def test_invalid_or_historical_page_queries_are_rejected(cache_db, query):
    client, _, ids = cache_db
    assert (
        client.get(
            "/api/v1/reconciliation/batch/daily?" + query, headers=auth(ids)
        ).status_code
        == 422
    )


@pytest.mark.asyncio
async def test_auth_uuid_missing_data_and_live_revocation(cache_db):
    client, sessions, ids = cache_db
    assert client.get(path(ids)).status_code == 401
    assert (
        client.get(
            "/api/v1/reconciliation/wallet/not-a-uuid", headers=auth(ids)
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"/api/v1/reconciliation/wallet/{uuid4()}", headers=auth(ids)
        ).status_code
        == 404
    )
    token = auth(ids)
    async with sessions() as db:
        await db.execute(
            update(User).where(User.id == ids["super"]).values(role=UserRole.GERENTE)
        )
        await db.commit()
    assert client.get(path(ids), headers=token).status_code == 200
    assert client.post(path(ids) + "/sync", headers=token).status_code == 403
    async with sessions() as db:
        await db.execute(
            update(User).where(User.id == ids["super"]).values(token_version=1)
        )
        await db.commit()
    assert client.get(path(ids), headers=token).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["flush", "commit"])
async def test_audit_or_commit_failure_rolls_back_cache_and_receipt(
    cache_db, monkeypatch, failure
):
    _, sessions, ids = cache_db
    before = await state(sessions, ids["rider"])
    async with sessions() as db:
        actor = await db.get(User, ids["super"])
        service = CacheReconciliationService(db)
        proof = command(await service.preview(ids["rider"]))

        async def fail(*args, **kwargs):
            raise RuntimeError("injected audit failure")

        monkeypatch.setattr(db, failure, fail)
        with pytest.raises(RuntimeError):
            await service.apply(ids["rider"], proof, actor)
    assert await state(sessions, ids["rider"]) == before


@pytest.mark.asyncio
async def test_concurrent_apply_has_one_change_and_one_receipt(cache_db):
    _, sessions, ids = cache_db
    async with sessions() as db:
        actor = await db.get(User, ids["super"])
        proof = command(await CacheReconciliationService(db).preview(ids["rider"]))

    async def apply():
        async with sessions() as db:
            return await CacheReconciliationService(db).apply(
                ids["rider"], proof, actor
            )

    results = await asyncio.gather(apply(), apply())
    assert sorted(x.status for x in results) == ["already_applied", "reconciled"]
    assert results[0].audit_id == results[1].audit_id
    saved = await state(sessions, ids["rider"])
    assert saved[0] == (Decimal("100.00"), 1) and saved[4] == 1 and len(saved[1]) == 1


@pytest.mark.asyncio
async def test_post_apply_ledger_change_cannot_be_undone_by_an_old_request(cache_db):
    _, sessions, ids = cache_db
    async with sessions() as db:
        actor = await db.get(User, ids["super"])
        service = CacheReconciliationService(db)
        proof = command(await service.preview(ids["rider"]))
        await service.apply(ids["rider"], proof, actor)
        await FinancialService(db).create_ledger_entry(
            rider_id=ids["rider"], amount=10, transaction_type=TransactionType.INGRESO
        )
        with pytest.raises(AppException) as exc:
            await service.apply(ids["rider"], proof, actor)
        assert exc.value.status_code == 409
    saved = await state(sessions, ids["rider"])
    assert saved[0] == (Decimal("100.00"), 1) and len(saved[1]) == 2 and saved[4] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["update", "insert"])
async def test_ledger_changes_are_locked_during_apply(cache_db, monkeypatch, operation):
    _, sessions, ids = cache_db
    async with sessions() as db:
        actor = await db.get(User, ids["super"])
        proof = command(await CacheReconciliationService(db).preview(ids["rider"]))
    acquired, release = asyncio.Event(), asyncio.Event()

    async def apply():
        async with sessions() as db:
            service = CacheReconciliationService(db)
            original = service.preview

            async def paused(identifier):
                acquired.set()
                await release.wait()
                return await original(identifier)

            monkeypatch.setattr(service, "preview", paused)
            return await service.apply(ids["rider"], proof, actor)

    async def write():
        async with sessions() as db:
            if operation == "update":
                await db.execute(
                    update(Financial)
                    .where(Financial.id == ids["entry"])
                    .values(amount=105, balance_after=105)
                )
            else:
                db.add(
                    Financial(
                        rider_id=ids["rider"],
                        amount=5,
                        balance_before=100,
                        balance_after=105,
                        transaction_type=TransactionType.INGRESO,
                        status=PaymentStatus.PROCESADO,
                        created_at=CLOCK - timedelta(hours=1),
                    )
                )
            await db.commit()

    apply_task = asyncio.create_task(apply())
    await asyncio.wait_for(acquired.wait(), 5)
    write_task = asyncio.create_task(write())
    try:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(write_task), 0.15)
    finally:
        release.set()
    result = await asyncio.wait_for(apply_task, 5)
    await asyncio.wait_for(write_task, 5)
    assert result.status == "reconciled"
    async with sessions() as db:
        latest = await CacheReconciliationService(db).preview(ids["rider"])
        assert (
            latest.stored_balance == "100.00"
            and latest.ledger_balance == "105.00"
            and latest.status == "discrepancy"
        )


@pytest.mark.asyncio
async def test_a_proof_is_bound_to_its_rider_and_default_post_remains_read_only(
    cache_db,
):
    client, sessions, ids = cache_db
    preview = client.get(path(ids), headers=auth(ids)).json()
    body = command(preview).model_dump()
    before = await state(sessions, ids["rider"])
    response = client.post(path(ids) + "/sync", headers=auth(ids), json=body)
    assert response.status_code == 200 and response.json()["dry_run"] is True
    async with sessions() as db:
        other = await db.scalar(select(Rider.id).where(Rider.id != ids["rider"]))
    assert (
        client.post(
            f"/api/v1/reconciliation/wallet/{other}/sync?dry_run=false",
            headers=auth(ids),
            json=body,
        ).status_code
        == 409
    )
    assert await state(sessions, ids["rider"]) == before


@pytest.mark.asyncio
async def test_negative_cache_version_requires_manual_review(cache_db):
    client, sessions, ids = cache_db
    async with sessions() as db:
        await db.execute(
            update(Rider).where(Rider.id == ids["rider"]).values(version=-1)
        )
        await db.commit()
    data = client.get(path(ids), headers=auth(ids)).json()
    assert data["status"] == "requires_review" and data["version"] is None
    assert data["cache_issues"] == ["invalid_cache_version"] and not data["can_apply"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change,code", [("role", 403), ("inactive", 401), ("version", 401)]
)
async def test_apply_rechecks_a_previously_loaded_actor_against_live_db(
    cache_db, change, code
):
    _, sessions, ids = cache_db
    async with sessions() as db:
        actor = await db.get(User, ids["super"])
        proof = command(await CacheReconciliationService(db).preview(ids["rider"]))
    async with sessions() as db:
        values = (
            {"role": UserRole.GERENTE}
            if change == "role"
            else {"is_active": False} if change == "inactive" else {"token_version": 1}
        )
        await db.execute(update(User).where(User.id == ids["super"]).values(**values))
        await db.commit()
    before = await state(sessions, ids["rider"])
    async with sessions() as db:
        with pytest.raises(AppException) as error:
            await CacheReconciliationService(db).apply(ids["rider"], proof, actor)
        assert error.value.status_code == code
    assert await state(sessions, ids["rider"]) == before


@pytest.mark.asyncio
async def test_corrupt_replay_receipt_cannot_claim_an_operation_was_applied(cache_db):
    client, sessions, ids = cache_db
    preview = client.get(path(ids), headers=auth(ids)).json()
    body = command(preview).model_dump()
    first = client.post(path(ids) + "/sync?dry_run=false", headers=auth(ids), json=body)
    assert first.status_code == 200
    async with sessions() as db:
        await db.execute(update(AuditLog).values(new_values=None))
        await db.commit()
    assert (
        client.post(
            path(ids) + "/sync?dry_run=false", headers=auth(ids), json=body
        ).status_code
        == 409
    )
    saved = await state(sessions, ids["rider"])
    assert saved[0] == (Decimal("100.00"), 1) and saved[4] == 1
