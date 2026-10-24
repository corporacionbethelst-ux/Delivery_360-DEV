"""Reconciliación Bancaria Automática — Fase 10 (Hito 5, parte banco).

Pipeline diario:
1. Parsear extracto bancario CSV (columnas esperadas: date,reference,amount)
   con normalización flexible (acepta 'fecha','concepto','monto', etc.).
2. Matching algorítmico contra FinancialTransaction no reconciliadas:
   - monto exacto en centavos (peso alto)
   - fecha dentro de ±1 día (peso medio)
   - referencia/bank_reference contiene reference_id interno (peso bajo)
3. score >= 0.8 → RELACIONADO; monto con diferencia > RECONCILIATION_VARIANCE_ALERT_CENTS
   y candidato fuerte → VARIANCIA; sin candidato → SIN_RELACIONAR.
4. Reporte de excepciones para contabilidad.

Sin credenciales/API bank → el parser CSV local es la fuente (modo dev/stub);
la integración real queda como hook `fetch_bank_statement()` reemplazable.
Nunca lanza al scheduler: errores quedan loggeados.
"""

from __future__ import annotations

import csv
import io
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.financial import FinancialTransaction
from app.models.fiscal import BankReconciliationRecord, ReconciliationStatus

logger = logging.getLogger("delivery360.reconciliation")


@dataclass
class StatementLine:
    statement_date: date
    bank_reference: Optional[str]
    amount_cents: int
    raw: dict = field(default_factory=dict)


_COL_ALIASES = {
    "date": ["date", "fecha", "transdate", "transaction_date"],
    "reference": [
        "reference",
        "referencia",
        "concept",
        "concepto",
        "description",
        "detail",
    ],
    "amount": ["amount", "monto", "value", "valor", "debit/credit", "importe"],
}


def _norm(s: str) -> str:
    return (s or "").strip().lower().replace(" ", "_")


def parse_statement_csv(csv_text: str) -> List[StatementLine]:
    """Parseo tolerante: mapea cabeceras por alias, salta líneas inválidas."""
    lines: List[StatementLine] = []
    try:
        reader = csv.DictReader(io.StringIO(csv_text))
        if not reader.fieldnames:
            return lines
        colmap: Dict[str, str] = {}
        for fname in reader.fieldnames:
            n = _norm(fname)
            for canon, aliases in _COL_ALIASES.items():
                if n in [_norm(a) for a in aliases]:
                    colmap[canon] = fname
        if "amount" not in colmap or "date" not in colmap:
            logger.warning(
                "CSV sin columnas date/amount reconocibles: %s", reader.fieldnames
            )
            return lines

        amount_idx = reader.fieldnames.index(colmap["amount"])
        n_cols = len(reader.fieldnames)
        last_idx = n_cols - 1
        for row in reader:
            try:
                # CSV latino sin comillas: "01/10/2026,1234,56" → csv.DictReader
                # parte el decimal en celdas ('monto'='1234', restkey=None=['56']).
                # Si la columna monto es la última y el overflow son SOLO dígitos
                # (1-2 decimales), se reconstruye: 1234 + ,56 → '1234.56'
                overflow = [str(o or "").strip() for o in (row.get(None) or [])]
                amt_val = str(row.get(colmap["amount"]) or "").strip()
                if (
                    overflow
                    and amount_idx == last_idx
                    and all(t.isdigit() for t in overflow)
                    and len(overflow[0]) <= 2
                ):
                    row[colmap["amount"]] = f"{amt_val}.{overflow[0]}"
                    row.pop(None, None)
                raw_date = (row.get(colmap["date"]) or "").strip()
                d: Optional[date] = None
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y%m%d"):
                    try:
                        d = datetime.strptime(raw_date[:10], fmt).date()
                        break
                    except ValueError:
                        continue
                if d is None:
                    continue
                amt_raw = (row.get(colmap["amount"]) or "0").strip().replace("$", "")
                # formato latino 1.234,56 → 1234.56
                if "," in amt_raw and "." in amt_raw:
                    amt_raw = amt_raw.replace(".", "").replace(",", ".")
                elif "," in amt_raw:
                    amt_raw = amt_raw.replace(",", ".")
                cents = int((Decimal(amt_raw) * 100).quantize(Decimal("1")))
                ref = (row.get(colmap.get("reference", ""), "") or "").strip() or None
                lines.append(
                    StatementLine(
                        statement_date=d,
                        bank_reference=ref,
                        amount_cents=cents,
                        raw=dict(row),
                    )
                )
            except (InvalidOperation, ValueError, KeyError):
                continue  # línea basura: se reporta como no parseada
    except Exception as exc:
        logger.exception("Parseo CSV falló: %s", exc)
    return lines


def _confidence(line: StatementLine, txn: FinancialTransaction) -> float:
    """Score 0..1: monto exacto 0.6 + fecha±1d 0.25 + referencia compartida 0.15."""
    score = 0.0
    txn_cents = int(txn.amount_cents or 0)
    if abs(abs(txn_cents) - abs(line.amount_cents)) == 0:
        score += 0.6
    elif (
        abs(abs(txn_cents) - abs(line.amount_cents))
        <= settings.RECONCILIATION_VARIANCE_ALERT_CENTS
    ):
        score += 0.3  # variance candidate
    txn_date = txn.created_at.date() if txn.created_at else None
    if txn_date is not None and abs((txn_date - line.statement_date).days) <= 1:
        score += 0.25
    ref_txt = (line.bank_reference or "").lower()
    internal_ref = (txn.reference_id or "").lower()
    if (
        ref_txt
        and internal_ref
        and (internal_ref[:13] in ref_txt or ref_txt[:13] in internal_ref)
    ):
        score += 0.15
    return round(score, 2)


async def run_reconciliation(
    db: AsyncSession, csv_text: str, statement_day: Optional[date] = None
) -> dict:
    """Ejecuta el matching completo y persiste BankReconciliationRecords.

    Retorna resumen {processed, matched, variance, unmatched}. Nunca lanza por
    datos: solo Propagará errores de DB graves (el job los loguea).
    """
    lines = parse_statement_csv(csv_text)
    if statement_day:
        lines = [l for l in lines if l.statement_date == statement_day]

    # Candidatos internos: transacciones del rango de fechas del extracto
    if lines:
        lo = min(l.statement_date for l in lines) - timedelta(days=2)
        hi = max(l.statement_date for l in lines) + timedelta(days=2)
    else:
        today = datetime.now(timezone.utc).date()
        lo, hi = today - timedelta(days=7), today

    res = await db.execute(
        select(FinancialTransaction).where(
            FinancialTransaction.created_at
            >= datetime.combine(lo, datetime.min.time()),
            FinancialTransaction.created_at
            < datetime.combine(hi + timedelta(days=1), datetime.min.time()),
        )
    )
    txns = list(res.scalars().all())
    already_matched_ids = set()
    prev = await db.execute(
        select(BankReconciliationRecord.internal_transaction_id).where(
            BankReconciliationRecord.status.in_(
                [ReconciliationStatus.RELACIONADO, ReconciliationStatus.RESUELTO_MANUAL]
            )
        )
    )
    already_matched_ids = {r for (r,) in prev.all() if r}

    summary = {"processed": 0, "matched": 0, "variance": 0, "unmatched": 0}
    for line in lines:
        summary["processed"] += 1
        best_txn, best_score = None, 0.0
        for t in txns:
            if t.id in already_matched_ids:
                continue
            s = _confidence(line, t)
            if s > best_score:
                best_txn, best_score = t, s

        record = BankReconciliationRecord(
            id=uuid.uuid4(),
            statement_date=line.statement_date,
            bank_reference=line.bank_reference,
            statement_amount_cents=line.amount_cents,
            match_confidence_score=Decimal(str(best_score)),
        )
        if best_txn is not None and best_score >= 0.8:
            diff = abs(abs(line.amount_cents) - abs(int(best_txn.amount_cents or 0)))
            record.internal_transaction_id = best_txn.id
            record.matched_amount_cents = int(best_txn.amount_cents)
            record.variance_cents = diff
            if diff > settings.RECONCILIATION_VARIANCE_ALERT_CENTS:
                record.status = ReconciliationStatus.VARIANCIA
                record.notes = f"Diferencia {diff}¢ vs tx {best_txn.id}"
                summary["variance"] += 1
            else:
                record.status = ReconciliationStatus.RELACIONADO
                summary["matched"] += 1
                already_matched_ids.add(best_txn.id)
        else:
            record.status = ReconciliationStatus.SIN_RELACIONAR
            record.variance_cents = abs(line.amount_cents)
            summary["unmatched"] += 1
        db.add(record)

    await db.commit()
    logger.info("Reconciliación: %s", summary)
    return summary


async def fetch_and_reconcile_safe() -> None:
    """Job diario (lifespan). En dev sin API bancaria: busca CSV local
    /app/data/bank_statement.csv; si no existe, log info y sale. Hook real:
    reemplazar por descarga SFTP/API del banco."""
    import os

    path = os.environ.get("BANK_STATEMENT_CSV_PATH", "/app/data/bank_statement.csv")
    if not os.path.exists(path):
        logger.info("reconciliación: no hay extracto en %s; skip", path)
        return
    try:
        from app.core.database import AsyncSessionLocal

        with open(path, "r", encoding="utf-8-sig") as fh:
            text_data = fh.read()
        async with AsyncSessionLocal() as db:
            await run_reconciliation(db, text_data)
    except Exception:
        logger.exception("Job reconciliación diaria falló (no bloqueante)")
