"""Verify the recorded legacy ledger before rebuilding its derived Rider cache.

No ledger entries, modern wallets, reserves or transfers are created/modified.
"""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID
from sqlalchemy import select, cast, String, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import AppException, NotFoundError, ValidationError
from app.models.financial import Financial
from app.models.rider import Rider, RiderStatus
from app.models.user import User, UserRole
from app.models.audit_log import AuditLog, ActionType
from app.schemas.cache_reconciliation import (
    CacheState,
    CachePreview,
    CacheSyncRequest,
    CacheSyncResult,
    CachePreviewPage,
    LedgerAuditItem,
    LedgerAuditPage,
)

from app.services.legacy_ledger import (
    MAX_LEDGER_ROWS,
    MAX_ISSUES,
    CENT,
    MAX_BALANCE,
    POLICY,
    PROCESSED,
    UNPROCESSED,
    LedgerEntry,
    analyze_ledger,
    exact_money,
    money_text,
    digest,
)

MAX_PAGE_SIZE = 25
AUDIT_RESOURCE = "rider_cache_reconciliation"


def state_fingerprint(
    rider_id: UUID, stored: object, version: object, ledger_fingerprint: str
) -> str:
    return digest([POLICY, str(rider_id), str(stored), version, ledger_fingerprint])


class CacheReconciliationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def preview(self, rider_id: UUID) -> CachePreview:
        if not isinstance(rider_id, UUID):
            raise ValidationError("El identificador de repartidor debe ser UUID")
        # One statement gives the cache and its bounded ledger one DB snapshot.
        rows = (
            await self.db.execute(
                select(
                    Rider.wallet_balance,
                    Rider.version,
                    Financial.id.label("transaction_id"),
                    Financial.amount,
                    Financial.balance_before,
                    Financial.balance_after,
                    cast(Financial.transaction_type, String).label("kind"),
                    cast(Financial.status, String).label("payment_status"),
                    Financial.created_at,
                )
                .select_from(Rider)
                .outerjoin(Financial, Financial.rider_id == Rider.id)
                .where(Rider.id == rider_id)
                .order_by(Financial.created_at.asc().nullsfirst(), Financial.id)
                .limit(MAX_LEDGER_ROWS + 1)
            )
        ).all()
        if not rows:
            raise NotFoundError("Repartidor no encontrado")
        entries = [
            LedgerEntry(
                r.transaction_id,
                r.amount,
                r.balance_before,
                r.balance_after,
                r.kind,
                r.payment_status,
                r.created_at,
            )
            for r in rows
            if r.transaction_id is not None
        ]
        truncated = len(entries) > MAX_LEDGER_ROWS
        integrity = analyze_ledger(
            rider_id, entries[:MAX_LEDGER_ROWS], truncated=truncated
        )
        raw_stored, raw_version = rows[0].wallet_balance, rows[0].version
        stored = exact_money(raw_stored)
        version = (
            raw_version
            if type(raw_version) is int and 0 <= raw_version <= 2147483647
            else None
        )
        cache_issues = []
        if version is None:
            cache_issues.append("invalid_cache_version")
        if raw_stored is not None and stored is None:
            cache_issues.append("invalid_cache_balance")
        target = exact_money(integrity.verified_balance)
        adjustment = (
            target - stored if target is not None and stored is not None else None
        )
        difference = abs(adjustment) if adjustment is not None else None
        status: CacheState
        if (
            integrity.status == "requires_review"
            or version is None
            or raw_stored is not None
            and stored is None
        ):
            status = "requires_review"
        elif integrity.status == "no_evidence":
            status = "no_ledger_evidence"
        elif difference == 0:
            status = "ok"
        elif difference is not None and difference <= CENT:
            status = "within_tolerance"
        else:
            status = "discrepancy"
        if status == "discrepancy" and version == 2147483647:
            status = "requires_review"
            cache_issues.append("cache_version_exhausted")
        return CachePreview(
            status=status,
            rider_id=rider_id,
            ledger_balance=integrity.verified_balance,
            stored_balance=money_text(stored),
            difference=money_text(difference),
            adjustment_amount=money_text(adjustment),
            version=version,
            fingerprint=state_fingerprint(
                rider_id, raw_stored, raw_version, integrity.ledger_fingerprint
            ),
            can_apply=status == "discrepancy",
            cache_issues=cache_issues,
            generated_at=datetime.now(timezone.utc),
            integrity=integrity,
        )

    async def apply(
        self, rider_id: UUID, request: CacheSyncRequest, actor: User
    ) -> CacheSyncResult:
        try:
            # Serialize authorization with administrative revocation. Read the
            # current DB values, not the ORM identity captured before lock waits.
            authorization = (
                await self.db.execute(
                    select(User.is_active, User.role, User.token_version)
                    .where(User.id == actor.id)
                    .with_for_update(read=True)
                )
            ).one_or_none()
            if (
                authorization is None
                or not authorization.is_active
                or authorization.token_version != actor.token_version
            ):
                raise AppException(
                    "La cuenta o sus credenciales ya no están vigentes", 401
                )
            if authorization.role != UserRole.SUPERADMIN:
                raise AppException(
                    "La sincronización requiere superadministración vigente", 403
                )
            parent = await self.db.scalar(
                select(Rider.id).where(Rider.id == rider_id).with_for_update()
            )
            if parent is None:
                raise NotFoundError("Repartidor no encontrado")
            # Parent lock serializes canonical writers/FK inserts. Existing rows
            # are also locked so direct updates/deletes cannot change the evidence.
            await self.db.execute(
                select(Financial.id)
                .where(Financial.rider_id == rider_id)
                .order_by(Financial.id)
                .limit(MAX_LEDGER_ROWS + 1)
                .with_for_update()
            )
            current = await self.preview(rider_id)
            if (
                current.version != request.expected_version
                or current.fingerprint != request.expected_fingerprint
            ):
                audit = await self.db.scalar(
                    select(AuditLog)
                    .where(
                        AuditLog.resource_type == AUDIT_RESOURCE,
                        AuditLog.resource_id == str(rider_id),
                        AuditLog.action_type == ActionType.CONFIG_CHANGE,
                        AuditLog.user_id == actor.id,
                        AuditLog.success.is_(True),
                        AuditLog.changes_summary == request.reason,
                        AuditLog.old_values["fingerprint"].as_string()
                        == request.expected_fingerprint,
                    )
                    .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                    .limit(1)
                )
                if (
                    audit is not None
                    and isinstance(audit.old_values, dict)
                    and isinstance(audit.new_values, dict)
                    and audit.old_values.get("version") == request.expected_version
                    and audit.new_values.get("fingerprint") == current.fingerprint
                    and audit.new_values.get("version") == current.version
                    and audit.new_values.get("stored_balance") == current.stored_balance
                    and audit.new_values.get("ledger_fingerprint")
                    == current.integrity.ledger_fingerprint
                    and (
                        audit.old_values.get("stored_balance") is None
                        or isinstance(audit.old_values.get("stored_balance"), str)
                        and exact_money(audit.old_values["stored_balance"]) is not None
                    )
                    and current.status == "ok"
                    and current.version is not None
                    and current.stored_balance is not None
                ):
                    await self.db.commit()
                    return CacheSyncResult(
                        status="already_applied",
                        rider_id=rider_id,
                        before_balance=audit.old_values.get("stored_balance"),
                        after_balance=current.stored_balance,
                        previous_version=request.expected_version,
                        version=current.version,
                        audit_id=UUID(str(audit.id)),
                    )
                raise AppException(
                    "El estado cambió; obtenga una nueva previsualización", 409
                )
            if (
                current.status in ("ok", "within_tolerance")
                and current.version is not None
                and current.stored_balance is not None
            ):
                await self.db.commit()
                return CacheSyncResult(
                    status="no_change",
                    rider_id=rider_id,
                    before_balance=current.stored_balance,
                    after_balance=current.stored_balance,
                    previous_version=current.version,
                    version=current.version,
                    audit_id=None,
                )
            if (
                not current.can_apply
                or current.version is None
                or current.ledger_balance is None
            ):
                raise AppException(
                    "La evidencia contable requiere revisión; no se modificó la caché",
                    409,
                )
            target = Decimal(current.ledger_balance)
            changed = await self.db.scalar(
                update(Rider)
                .where(Rider.id == rider_id, Rider.version == current.version)
                .values(wallet_balance=target, version=current.version + 1)
                .returning(Rider.id)
            )
            if changed is None:
                raise AppException(
                    "Conflicto de versión; obtenga una nueva previsualización", 409
                )
            after_fingerprint = state_fingerprint(
                rider_id,
                target,
                current.version + 1,
                current.integrity.ledger_fingerprint,
            )
            audit = AuditLog(
                user_id=actor.id,
                user_role=actor.role.value if actor.role else None,
                action_type=ActionType.CONFIG_CHANGE,
                resource_type=AUDIT_RESOURCE,
                resource_id=str(rider_id),
                description="Sincronización explícita de caché legacy con cadena financiera verificada",
                changes_summary=request.reason,
                success=True,
                old_values={
                    "fingerprint": current.fingerprint,
                    "version": current.version,
                    "stored_balance": current.stored_balance,
                },
                new_values={
                    "fingerprint": after_fingerprint,
                    "version": current.version + 1,
                    "stored_balance": current.ledger_balance,
                    "ledger_fingerprint": current.integrity.ledger_fingerprint,
                },
            )
            self.db.add(audit)
            await self.db.flush()
            result = CacheSyncResult(
                status="reconciled",
                rider_id=rider_id,
                before_balance=current.stored_balance,
                after_balance=current.ledger_balance,
                previous_version=current.version,
                version=current.version + 1,
                audit_id=UUID(str(audit.id)),
            )
            await self.db.commit()
            return result
        except BaseException:
            await self.db.rollback()
            raise

    async def page_ids(
        self, limit: int, after_id: UUID | None, rider_status: RiderStatus | None
    ) -> tuple[list[UUID], bool]:
        if type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE:
            raise ValidationError("La página admite entre uno y 25 repartidores")
        query = select(Rider.id)
        if after_id is not None:
            query = query.where(Rider.id > after_id)
        if rider_status is not None:
            query = query.where(cast(Rider.status, String) == rider_status.value)
        rows = list(
            (await self.db.scalars(query.order_by(Rider.id).limit(limit + 1))).all()
        )
        return rows[:limit], len(rows) > limit

    async def preview_page(
        self,
        limit: int = 25,
        after_id: UUID | None = None,
        rider_status: RiderStatus | None = None,
    ) -> CachePreviewPage:
        ids, more = await self.page_ids(limit, after_id, rider_status)
        details = [await self.preview(identifier) for identifier in ids]
        return CachePreviewPage(
            date=datetime.now(timezone.utc).date(),
            page_count=len(details),
            ok_count=sum(x.status in ("ok", "within_tolerance") for x in details),
            discrepancy_count=sum(x.status == "discrepancy" for x in details),
            requires_review_count=sum(x.status == "requires_review" for x in details),
            no_evidence_count=sum(x.status == "no_ledger_evidence" for x in details),
            has_more=more,
            next_after_id=ids[-1] if more else None,
            details=details,
        )

    async def audit_page(
        self,
        limit: int = 25,
        after_id: UUID | None = None,
        rider_status: RiderStatus | None = None,
    ) -> LedgerAuditPage:
        ids, more = await self.page_ids(limit, after_id, rider_status)
        items = [
            LedgerAuditItem(
                rider_id=identifier,
                integrity=(await self.preview(identifier)).integrity,
            )
            for identifier in ids
        ]
        verified = sum(x.integrity.status == "verified" for x in items)
        review = sum(x.integrity.status == "requires_review" for x in items)
        no_evidence = len(items) - verified - review
        return LedgerAuditPage(
            scope="current_page",
            status=(
                "review_required"
                if review
                else "no_evidence" if no_evidence or not items else "verified_page"
            ),
            page_count=len(items),
            verified_count=verified,
            requires_review_count=review,
            no_evidence_count=no_evidence,
            has_more=more,
            next_after_id=ids[-1] if more else None,
            details=items,
        )
