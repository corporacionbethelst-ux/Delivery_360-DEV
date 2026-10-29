"""API Fiscal Fase 10 — Facturación electrónica, configuración fiscal y reconciliación.

RBAC:
- SUPERADMIN/GERENTE: emisión, notas crédito, cancelación, configuración, resoluciones.
- OPERADOR/AUDITOR: lectura de monitor/reporte excepciones.
- REPARTIDOR/CLIENTE: sin acceso (403).

Feature flag maestro settings.ENABLE_ELECTRONIC_INVOICING en endpoints de escritura.
Todos los montos expuestos en la API van en CENTAVOS (enteros exactos).
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user, require_role
from app.core.config import settings
from app.core.database import get_db
from app.models.fiscal import (
    BankReconciliationRecord,
    CountryTaxRegime,
    ElectronicInvoice,
    FiscalConfiguration,
    InvoiceResolution,
    InvoiceStatus,
    InvoiceType,
    PaymentDistributionSnapshot,
    ReconciliationStatus,
)
from app.models.user import User, UserRole
from app.services.invoicing_engine import (
    InvoicingEngine,
    InvoiceSubmissionError,
    InvoiceOrderNotFound,
)
from app.services.fiscal_integrity import invoice_evidence, MAX_CENTS
from app.services.split_payment_service import (
    process_order_settlement,
    resolve_share_rule,
)

logger = logging.getLogger("delivery360.api.fiscal")

router = APIRouter(prefix="/fiscal", tags=["Fiscal (Fase 10)"])

_admin = require_role(UserRole.SUPERADMIN, UserRole.GERENTE)
_read = require_role(
    UserRole.SUPERADMIN, UserRole.GERENTE, UserRole.OPERADOR, UserRole.AUDITOR
)


# ──────────────────────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────────────────────
class InvoiceItemIn(BaseModel):
    name: str = Field(..., max_length=200)
    unit_price_cents: int = Field(..., ge=0, le=MAX_CENTS, strict=True)
    quantity: int = Field(1, ge=1, le=1000, strict=True)
    category: str = Field("general", max_length=50)


class IssueInvoiceIn(BaseModel):
    order_id: uuid.UUID
    customer_name: str = Field(..., max_length=255)
    customer_tax_id: str = Field("NN", max_length=20)
    customer_email: Optional[str] = Field(None, max_length=255)
    items: List[InvoiceItemIn] = Field(..., min_length=1, max_length=100)
    payment_method: str = Field("TARJETA", max_length=30)
    preview: bool = False
    country: str = Field(default="", max_length=2)  # vacío → default config


class CreditNoteIn(BaseModel):
    reason: str = Field(..., min_length=3, max_length=300)
    amount_cents: int = Field(..., gt=0, le=MAX_CENTS, strict=True)


class CancelIn(BaseModel):
    reason: str = Field(..., min_length=3, max_length=300)


def _serialize_invoice(inv: ElectronicInvoice) -> dict:
    return {
        "id": str(inv.id),
        "order_id": str(inv.order_id),
        "resolution_id": str(inv.resolution_id) if inv.resolution_id else None,
        **invoice_evidence(inv),
        "invoice_type": inv.invoice_type.value if inv.invoice_type else None,
        "resolution_number": inv.resolution_number,
        "sequence_number": inv.sequence_number,
        "unique_identifier": inv.unique_identifier,
        "issue_date": inv.issue_date.isoformat() if inv.issue_date else None,
        "provider_type": inv.provider_type.value if inv.provider_type else None,
        "currency_code": inv.currency_code,
        "subtotal_cents": inv.subtotal_cents,
        "tax_total_cents": inv.tax_total_cents,
        "retention_total_cents": inv.retention_total_cents,
        "grand_total_cents": inv.grand_total_cents,
        "status": inv.status.value if inv.status else None,
        "error_message": inv.error_message,
        "pdf_url": inv.pdf_url,
        "qr_code_url": inv.qr_code_url,
        "reference_invoice_id": (
            str(inv.reference_invoice_id) if inv.reference_invoice_id else None
        ),
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
    }


# ──────────────────────────────────────────────────────────────
# Emisión / documentos
# ──────────────────────────────────────────────────────────────
@router.post("/invoices", status_code=status.HTTP_201_CREATED)
async def emit_invoice(
    body: IssueInvoiceIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_admin),
):
    if not settings.ENABLE_ELECTRONIC_INVOICING:
        raise HTTPException(
            status.HTTP_423_LOCKED, "Facturación electrónica deshabilitada (flag)"
        )
    try:
        country = CountryTaxRegime(
            body.country.upper() if body.country else settings.FISCAL_DEFAULT_COUNTRY
        )
    except ValueError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "País fiscal inválido"
        ) from None
    engine = InvoicingEngine(db)
    try:
        inv = await engine.create_electronic_invoice(
            order_id=body.order_id,
            customer_info={
                "name": body.customer_name,
                "tax_id": body.customer_tax_id,
                "email": body.customer_email,
            },
            items=[it.model_dump() for it in body.items],
            payment_method=body.payment_method,
            country=country,
            preview=body.preview,
        )
    except InvoiceSubmissionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    except InvoiceOrderNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return _serialize_invoice(inv)


@router.get("/invoices")
async def list_invoices(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    inv_status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_read),
):
    q = select(ElectronicInvoice).order_by(ElectronicInvoice.created_at.desc())
    if inv_status:
        try:
            parsed = InvoiceStatus(inv_status.upper())
        except ValueError:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Estado inválido. Válidos: {[s.value for s in InvoiceStatus]}",
            )
        q = q.where(ElectronicInvoice.status == parsed)
    res = await db.execute(q.offset((page - 1) * size).limit(size))
    return {
        "page": page,
        "size": size,
        "items": [_serialize_invoice(i) for i in res.scalars().all()],
    }


@router.get("/invoices/{invoice_id}")
async def get_invoice(
    invoice_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_read),
):
    inv = await db.get(ElectronicInvoice, invoice_id)
    if inv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Factura no encontrada")
    return _serialize_invoice(inv)


@router.get("/invoices/{invoice_id}/status")
async def invoice_status_check(
    invoice_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_read),
):
    """Evidencia local persistida; no consulta el estado de la autoridad."""
    inv = await db.get(ElectronicInvoice, invoice_id)
    if inv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Factura no encontrada")
    return {
        "id": str(inv.id),
        **invoice_evidence(inv),
        "status": inv.status.value,
        "unique_identifier": inv.unique_identifier,
    }


@router.post("/invoices/{invoice_id}/credit-note", status_code=status.HTTP_201_CREATED)
async def create_credit_note(
    invoice_id: uuid.UUID,
    body: CreditNoteIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_admin),
):
    engine = InvoicingEngine(db)
    try:
        nc = await engine.issue_credit_note(invoice_id, body.reason, body.amount_cents)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    except InvoiceSubmissionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return _serialize_invoice(nc)


@router.post("/invoices/{invoice_id}/cancel")
async def cancel_invoice(
    invoice_id: uuid.UUID,
    body: CancelIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_admin),
):
    engine = InvoicingEngine(db)
    try:
        inv = await engine.cancel_invoice(invoice_id, body.reason)
    except InvoiceSubmissionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return _serialize_invoice(inv)


# ──────────────────────────────────────────────────────────────
# Split payments
# ──────────────────────────────────────────────────────────────
@router.post("/orders/{order_id}/settle", status_code=status.HTTP_201_CREATED)
async def settle_order(
    order_id: uuid.UUID,
    force: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_admin),
):
    snap = await process_order_settlement(db, order_id, force=force)
    if snap is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Orden ya liquidada o sin fee de envío repartible"
        )
    return {
        "id": str(snap.id),
        "order_id": str(snap.order_id),
        "gross_amount_cents": snap.gross_amount_cents,
        "platform_share_cents": snap.platform_share_cents,
        "restaurant_share_cents": snap.restaurant_share_cents,
        "rider_share_cents": snap.rider_share_cents,
        "applied_rule_json": snap.applied_rule_json,
        "settled_at": snap.settled_at.isoformat() if snap.settled_at else None,
    }


@router.get("/split-rules/current")
async def current_split_rule(
    db: AsyncSession = Depends(get_db), user: User = Depends(_read)
):
    rule = await resolve_share_rule(db)
    return rule.to_dict()


# ──────────────────────────────────────────────────────────────
# Configuración fiscal
# ──────────────────────────────────────────────────────────────
@router.get("/config")
async def get_fiscal_config(
    db: AsyncSession = Depends(get_db), user: User = Depends(_read)
):
    res = await db.execute(
        select(FiscalConfiguration).order_by(
            FiscalConfiguration.country_code, FiscalConfiguration.priority
        )
    )
    return [
        {
            "id": str(r.id),
            "country_code": r.country_code.value,
            "zone_id": str(r.zone_id) if r.zone_id else None,
            "tax_code": r.tax_code,
            "tax_name": r.tax_name,
            "rate": float(r.rate),
            "applicability_condition": r.applicability_condition,
            "taxable_base_type": r.taxable_base_type,
            "included_in_price": r.included_in_price,
            "priority": r.priority,
            "is_active": r.is_active,
        }
        for r in res.scalars().all()
    ]


class FiscalConfigPatch(BaseModel):
    rate: Optional[Decimal] = Field(
        None, ge=0, le=1, max_digits=5, decimal_places=4, allow_inf_nan=False
    )
    is_active: Optional[bool] = None
    applicability_condition: Optional[str] = Field(None, max_length=200)


@router.patch("/config/{config_id}")
async def patch_fiscal_config(
    config_id: uuid.UUID,
    body: FiscalConfigPatch,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_admin),
):
    row = await db.get(FiscalConfiguration, config_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Regla fiscal no encontrada")
    if body.rate is not None:
        row.rate = body.rate
    if body.is_active is not None:
        row.is_active = body.is_active
    if body.applicability_condition is not None:
        row.applicability_condition = body.applicability_condition
    row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    await db.refresh(row)
    return {"id": str(row.id), "rate": float(row.rate), "is_active": row.is_active}


# ──────────────────────────────────────────────────────────────
# Resoluciones
# ──────────────────────────────────────────────────────────────
@router.get("/resolutions")
async def list_resolutions(
    db: AsyncSession = Depends(get_db), user: User = Depends(_read)
):
    res = await db.execute(
        select(InvoiceResolution).order_by(InvoiceResolution.valid_until.desc())
    )
    return [
        {
            "id": str(r.id),
            "prefix": r.prefix,
            "start_range": r.start_range,
            "end_range": r.end_range,
            "current_counter": r.current_counter,
            "valid_from": r.valid_from.isoformat(),
            "valid_until": r.valid_until.isoformat(),
            "is_active": r.is_active,
            "is_sandbox": r.is_sandbox,
            "country_code": r.country_code.value,
        }
        for r in res.scalars().all()
    ]


# ──────────────────────────────────────────────────────────────
# Reconciliación bancaria
# ──────────────────────────────────────────────────────────────
@router.get("/reconciliation/records")
async def reconciliation_records(
    page: int = Query(1, ge=1),
    size: int = Query(25, ge=1, le=100),
    rec_status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_read),
):
    q = select(BankReconciliationRecord).order_by(
        BankReconciliationRecord.statement_date.desc()
    )
    if rec_status:
        try:
            parsed = ReconciliationStatus(rec_status.upper())
        except ValueError:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Estado inválido. Válidos: {[s.value for s in ReconciliationStatus]}",
            )
        q = q.where(BankReconciliationRecord.status == parsed)
    res = await db.execute(q.offset((page - 1) * size).limit(size))
    return {
        "page": page,
        "size": size,
        "items": [
            {
                "id": str(r.id),
                "statement_date": r.statement_date.isoformat(),
                "bank_reference": r.bank_reference,
                "statement_amount_cents": r.statement_amount_cents,
                "matched_amount_cents": r.matched_amount_cents,
                "variance_cents": r.variance_cents,
                "match_confidence_score": float(r.match_confidence_score or 0),
                "status": r.status.value,
                "resolved_manually": r.resolved_manually,
                "notes": r.notes,
            }
            for r in res.scalars().all()
        ],
    }


class StatementCsvIn(BaseModel):
    csv_text: str = Field(..., min_length=10, max_length=2_000_000)


@router.post("/reconciliation/run")
async def run_reconciliation_endpoint(
    body: StatementCsvIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_admin),
):
    from app.services.bank_reconciliation_service import run_reconciliation

    summary = await run_reconciliation(db, body.csv_text)
    return summary


@router.post("/reconciliation/records/{record_id}/resolve")
async def resolve_record(
    record_id: uuid.UUID,
    note: str = Query("", max_length=300),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_admin),
):
    rec = await db.get(BankReconciliationRecord, record_id)
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Registro no encontrado")
    rec.status = ReconciliationStatus.RESUELTO_MANUAL
    rec.resolved_manually = True
    rec.notes = (rec.notes or "") + f" | Resuelto manual por {user.email}: {note}"[:200]
    await db.commit()
    return {"id": str(rec.id), "status": rec.status.value}
