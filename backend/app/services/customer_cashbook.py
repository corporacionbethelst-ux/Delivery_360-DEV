"""Exact reports from one PostgreSQL statement; no payment, reconciliation or writes."""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo
from uuid import UUID
import hashlib
import json
from fastapi import HTTPException
from sqlalchemy import select, literal, func, union_all, true, null, String, cast
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.customer_collection import CustomerCollection, CustomerCollectionReview
from app.models.customer_refund import CustomerRefund, CustomerRefundEvent
from app.models.order_currency_quote import OrderCurrencyQuote
from app.models.currency import BcvRate
from app.services.bcv_currency import converted_amount

ZONE = "America/Caracas"
MAX_ROWS = 5000
MAX_DAYS = 31
METHODS = ("EFECTIVO", "TRANSFERENCIA", "PAGO_MOVIL")


def civil_window(start: date | None, end: date | None, now: datetime | None = None):
    clock = now or datetime.now(timezone.utc)
    today = clock.astimezone(ZoneInfo(ZONE)).date()
    last = end or today
    first = start or last - timedelta(days=6)
    if last > today or first > last or (last - first).days >= MAX_DAYS:
        raise HTTPException(
            422,
            "El rango debe ser válido, terminar como máximo hoy en Caracas y abarcar hasta 31 días",
        )

    def midnight(d):
        return (
            datetime.combine(d, time(), ZoneInfo(ZONE))
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
        )

    return first, last, midnight(first), midnight(last + timedelta(days=1))


def utc(value: datetime):
    if value.tzinfo:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat(timespec="microseconds") + "Z"


def money(value):
    return format(Decimal(value), ".2f")


def query(start, end, method=None, currency=None, source_key=None):
    c, v, q, r = (
        CustomerCollection,
        CustomerCollectionReview,
        OrderCurrencyQuote,
        BcvRate,
    )
    stamp = func.timezone("UTC", func.statement_timestamp())
    # Both source branches apply the same verification-time bounds and clock.
    common = [
        c.id.label("collection_id"),
        c.order_id.label("order_id"),
        c.amount_usd.label("collection_amount_usd"),
        c.paid_amount.label("collection_amount_original"),
        c.paid_currency.label("original_currency"),
        v.decision.label("collection_decision"),
        q.id.label("quote_id"),
        r.id.label("rate_id"),
        r.ves_per_usd.label("bcv_rate"),
        r.valid_on.label("bcv_valid_on"),
    ]
    credits = (
        select(
            literal("COBRO").label("kind"),
            v.id.label("verification_id"),
            null().cast(String).label("refund_id"),
            v.reviewed_at.label("verified_at"),
            v.reviewed_by.label("verified_by"),
            c.created_at.label("declared_at"),
            c.declared_by.label("declared_by"),
            c.received_on.label("operation_date"),
            c.method.label("method"),
            c.source_key.label("source_key"),
            c.reference_key.label("reference_key"),
            c.amount_usd.label("amount_usd"),
            c.paid_amount.label("amount_original"),
            c.paid_amount.label("execution_amount"),
            c.paid_currency.label("execution_currency"),
            literal(None).cast(c.amount_usd.type).label("prior_refunded_usd"),
            literal(None).cast(c.paid_amount.type).label("prior_refunded_original"),
            *common,
        )
        .select_from(c)
        .join(v, v.collection_id == c.id)
        .outerjoin(q, q.id == c.quote_id)
        .outerjoin(r, r.id == q.rate_id)
        .where(
            v.decision == "VERIFICADO",
            v.reviewed_at >= start,
            v.reviewed_at < end,
            v.reviewed_at <= stamp,
        )
    )
    f, e = CustomerRefund, aliased(CustomerRefundEvent)
    execution = (
        select(CustomerRefundEvent)
        .where(
            CustomerRefundEvent.refund_id == f.id,
            CustomerRefundEvent.kind == "DECLARAR_EJECUCION",
            CustomerRefundEvent.revision < e.revision,
        )
        .order_by(CustomerRefundEvent.revision.desc())
        .limit(1)
        .correlate(f, e)
        .lateral("execution")
    )
    refunds = (
        select(
            literal("DEVOLUCION").label("kind"),
            e.id.label("verification_id"),
            cast(f.id, String).label("refund_id"),
            e.created_at.label("verified_at"),
            e.actor_id.label("verified_by"),
            execution.c.created_at.label("declared_at"),
            execution.c.actor_id.label("declared_by"),
            execution.c.executed_on.label("operation_date"),
            execution.c.method.label("method"),
            execution.c.source_key.label("source_key"),
            execution.c.reference_key.label("reference_key"),
            f.amount_usd.label("amount_usd"),
            f.return_amount.label("amount_original"),
            execution.c.paid_amount.label("execution_amount"),
            execution.c.paid_currency.label("execution_currency"),
            f.prior_refunded_usd.label("prior_refunded_usd"),
            f.prior_refunded_paid.label("prior_refunded_original"),
            *common,
        )
        .select_from(f)
        .join(e, e.refund_id == f.id)
        .join(c, c.id == f.collection_id)
        .outerjoin(v, v.collection_id == c.id)
        .outerjoin(q, q.id == c.quote_id)
        .outerjoin(r, r.id == q.rate_id)
        .outerjoin(execution, true())
        .where(
            e.kind == "VERIFICAR_DEVOLUCION",
            e.created_at >= start,
            e.created_at < end,
            e.created_at <= stamp,
        )
    )
    entries = union_all(credits, refunds).cte("entries")
    filters = []
    if method:
        filters.append(entries.c.method == method)
    if currency:
        filters.append(entries.c.original_currency == currency)
    if source_key:
        filters.append(entries.c.source_key == source_key)
    limited = (
        select(entries)
        .where(*filters)
        .order_by(
            entries.c.verified_at.desc(),
            entries.c.kind.desc(),
            entries.c.verification_id.desc(),
        )
        .limit(MAX_ROWS + 1)
        .cte("bounded_entries")
    )
    clock = select(stamp.label("generated_at")).cte("report_clock")
    return (
        select(clock.c.generated_at, limited)
        .select_from(clock.outerjoin(limited, true()))
        .order_by(
            limited.c.verified_at.desc(),
            limited.c.kind.desc(),
            limited.c.verification_id.desc(),
        )
    )


def entry_view(row):
    error = HTTPException(
        409,
        "El libro contiene un movimiento incoherente; requiere revisión antes de emitir el reporte",
    )
    required = (
        "verification_id",
        "verified_at",
        "verified_by",
        "declared_at",
        "declared_by",
        "operation_date",
        "method",
        "source_key",
        "reference_key",
        "amount_usd",
        "amount_original",
        "collection_id",
        "order_id",
        "original_currency",
        "collection_amount_usd",
        "collection_amount_original",
    )
    if (
        any(row[key] is None for key in required)
        or row["collection_decision"] != "VERIFICADO"
    ):
        raise error
    if (
        row["method"] not in METHODS
        or row["original_currency"] not in ("USD", "VES")
        or (row["method"] == "PAGO_MOVIL" and row["original_currency"] != "VES")
    ):
        raise error
    if (
        row["verified_by"] == row["declared_by"]
        or row["declared_at"] > row["verified_at"]
    ):
        raise error
    if (
        row["operation_date"]
        != row["declared_at"]
        .replace(tzinfo=timezone.utc)
        .astimezone(ZoneInfo(ZONE))
        .date()
    ):
        raise error
    usd, paid, original_usd, original_paid = (
        Decimal(row[k])
        for k in (
            "amount_usd",
            "amount_original",
            "collection_amount_usd",
            "collection_amount_original",
        )
    )
    if any(
        not v.is_finite() or v <= 0 or v.quantize(Decimal("0.01")) != v
        for v in (usd, paid, original_usd, original_paid)
    ):
        raise error
    rate = Decimal("1") if row["original_currency"] == "USD" else row["bcv_rate"]
    if rate is None or (
        row["original_currency"] == "VES"
        and (
            row["quote_id"] is None
            or row["rate_id"] is None
            or row["bcv_valid_on"] is None
        )
    ):
        raise error
    if (
        row["execution_amount"] != paid
        or row["execution_currency"] != row["original_currency"]
    ):
        raise error
    if converted_amount(original_usd, rate) != original_paid:
        raise error
    prior_usd, prior_paid = row["prior_refunded_usd"], row["prior_refunded_original"]
    if row["kind"] == "COBRO":
        if row["refund_id"] is not None or usd != original_usd or paid != original_paid:
            raise error
    else:
        if (
            row["refund_id"] is None
            or prior_usd is None
            or prior_paid is None
            or prior_usd < 0
            or prior_paid < 0
            or prior_usd + usd > original_usd
        ):
            raise error
        if (
            converted_amount(prior_usd, rate) != prior_paid
            or converted_amount(prior_usd + usd, rate) - prior_paid != paid
        ):
            raise error
    return dict(
        key=row["kind"] + ":" + str(row["verification_id"]),
        kind=row["kind"],
        verification_id=str(row["verification_id"]),
        collection_id=str(row["collection_id"]),
        refund_id=str(row["refund_id"]) if row["refund_id"] else None,
        order_id=str(row["order_id"]),
        verified_at=utc(row["verified_at"]),
        verified_by=str(row["verified_by"]),
        declared_at=utc(row["declared_at"]),
        declared_by=str(row["declared_by"]),
        operation_date=row["operation_date"].isoformat(),
        method=row["method"],
        source_key=row["source_key"],
        reference_key=row["reference_key"],
        amount_usd=money(usd),
        amount_original=money(paid),
        original_currency=row["original_currency"],
        collection_amount_usd=money(original_usd),
        collection_amount_original=money(original_paid),
        prior_refunded_usd=money(prior_usd) if prior_usd is not None else None,
        prior_refunded_original=money(prior_paid) if prior_paid is not None else None,
        bcv_rate=format(rate, ".8f") if row["original_currency"] == "VES" else None,
        bcv_rate_id=str(row["rate_id"]) if row["original_currency"] == "VES" else None,
        bcv_valid_on=(
            row["bcv_valid_on"].isoformat()
            if row["original_currency"] == "VES"
            else None
        ),
    )


def empty_totals():
    return dict(
        collection_count=0,
        refund_count=0,
        collection_usd=Decimal("0.00"),
        refund_usd=Decimal("0.00"),
    )


def add(totals, row, physical=False):
    credit = row["kind"] == "COBRO"
    prefix = "collection" if credit else "refund"
    totals[prefix + "_count"] += 1
    totals[prefix + "_usd"] += Decimal(row["amount_usd"])
    if physical:
        totals[prefix + "_original"] += Decimal(row["amount_original"])


def totals_view(totals, physical=False):
    result = dict(
        collection_count=totals["collection_count"],
        refund_count=totals["refund_count"],
        entry_count=totals["collection_count"] + totals["refund_count"],
        collection_usd=money(totals["collection_usd"]),
        refund_usd=money(totals["refund_usd"]),
        net_usd=money(totals["collection_usd"] - totals["refund_usd"]),
    )
    if physical:
        result.update(
            collection_original=money(totals["collection_original"]),
            refund_original=money(totals["refund_original"]),
            net_original=money(
                totals["collection_original"] - totals["refund_original"]
            ),
        )
    return result


async def report(
    db: AsyncSession,
    date_from=None,
    date_to=None,
    method=None,
    currency=None,
    source_key=None,
):
    first, last, start, end = civil_window(date_from, date_to)
    # Exactly one DB read: totals, details and export share this statement's rows.
    records = (
        (await db.execute(query(start, end, method, currency, source_key)))
        .mappings()
        .all()
    )
    generated = records[0]["generated_at"]
    records = [row for row in records if row["verification_id"] is not None]
    if len(records) > MAX_ROWS:
        raise HTTPException(
            409,
            "El rango supera 5000 movimientos; reduce las fechas o filtra por moneda, medio o caja/cuenta para obtener una exportación completa",
        )
    with localcontext() as context:
        context.prec = 60
        rows = [entry_view(row) for row in records]
        total = empty_totals()
        currencies = {
            key: dict(
                **empty_totals(),
                collection_original=Decimal("0.00"),
                refund_original=Decimal("0.00"),
            )
            for key in ("USD", "VES")
        }
        methods = {
            (c, m): dict(
                **empty_totals(),
                collection_original=Decimal("0.00"),
                refund_original=Decimal("0.00"),
            )
            for c in ("USD", "VES")
            for m in METHODS
            if (c, m) != ("USD", "PAGO_MOVIL")
        }
        days = {
            (first + timedelta(days=i)).isoformat(): empty_totals()
            for i in range((last - first).days + 1)
        }
        for row in rows:
            add(total, row)
            add(currencies[row["original_currency"]], row, True)
            add(methods[(row["original_currency"], row["method"])], row, True)
            day = (
                datetime.fromisoformat(row["verified_at"].replace("Z", "+00:00"))
                .astimezone(ZoneInfo(ZONE))
                .date()
                .isoformat()
            )
            add(days[day], row)
        result = dict(
            version=1,
            scope="verified_customer_cashbook",
            base_currency="USD",
            timezone=ZONE,
            recognition_basis="manual_verification_time",
            snapshot_basis="single_statement_visibility",
            bank_verified=False,
            date_from=first.isoformat(),
            date_to=last.isoformat(),
            period_start=utc(start),
            period_end_exclusive=utc(end),
            generated_at=utc(generated),
            filters=dict(method=method, currency=currency, source_key=source_key),
            summary=totals_view(total),
            currencies=[
                dict(currency=c, **totals_view(t, True)) for c, t in currencies.items()
            ],
            methods=[
                dict(currency=c, method=m, **totals_view(t, True))
                for (c, m), t in methods.items()
            ],
            daily=[dict(date=d, **totals_view(t)) for d, t in days.items()],
            rows=rows,
            export_complete=True,
            maximum_rows=MAX_ROWS,
        )
    result["content_sha256"] = hashlib.sha256(
        json.dumps(
            result, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    return result
