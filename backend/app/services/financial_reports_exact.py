"""Read-only decimal management reports. Sources remain distinct; no bank claims."""

from datetime import datetime, timezone
from decimal import Decimal, localcontext
import hashlib
import json
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlalchemy import (
    select,
    union_all,
    literal,
    cast,
    String,
    Integer,
    Numeric,
    null,
    func,
    or_,
    and_,
    true,
)
from app.models.order import Order, OrderStatus
from app.models.financial import Financial
from app.models.payout import Payout, PayoutStatus
from app.services.legacy_ledger import CREDIT_TYPES, DEBIT_TYPES
from app.services.customer_cashbook import civil_window, utc, money, ZONE

MAX_ROWS = 5000
KINDS = ("ORDEN", "MOVIMIENTO", "RETIRO")
CREDITS = tuple(sorted(t.value for t in CREDIT_TYPES))
DEBITS = tuple(sorted(t.value for t in DEBIT_TYPES))
TYPES = CREDITS + DEBITS + ("AJUSTE",)
ORDER_STATES = tuple(s.value for s in OrderStatus)
PAYOUT_STATES = tuple(s.value for s in PayoutStatus)
REASONS = (
    "FECHA_NO_REGISTRADA",
    "MONEDA_NO_VERIFICADA",
    "PRECIO_NO_EXACTO",
    "ESTADO_NO_PROCESADO",
    "TIPO_NO_ADMITIDO",
    "ESTADO_NO_ADMITIDO",
)


def query(start, end):
    stamp = func.timezone("UTC", func.statement_timestamp())

    def source(model, kind, clock, status, typ=None):
        order = kind == "ORDEN"
        number = lambda field: getattr(model, field) if order else null().cast(Numeric)
        return select(
            literal(kind).label("kind"),
            model.id.label("id"),
            clock.label("occurred_at"),
            model.currency_code.label("currency"),
            cast(status, String).label("status"),
            (cast(typ, String) if typ is not None else null().cast(String)).label(
                "transaction_type"
            ),
            (model.pricing_version if order else null().cast(Integer)).label(
                "pricing_version"
            ),
            (model.pricing_revision if order else null().cast(Integer)).label(
                "pricing_revision"
            ),
            number("subtotal_exact").label("subtotal_usd"),
            number("delivery_fee_exact").label("delivery_fee_usd"),
            number("total_exact").label("total_usd"),
            (null().cast(Numeric) if order else model.amount).label("amount_usd"),
        ).where(or_(clock.is_(None), and_(clock >= start, clock < end, clock <= stamp)))

    entries = union_all(
        source(
            Order,
            "ORDEN",
            func.coalesce(Order.created_at, Order.ordered_at),
            Order.status,
        ),
        source(
            Financial,
            "MOVIMIENTO",
            Financial.created_at,
            Financial.status,
            Financial.transaction_type,
        ),
        source(Payout, "RETIRO", Payout.requested_at, Payout.status),
    ).cte("financial_sources")
    bounded = (
        select(entries)
        .order_by(
            entries.c.occurred_at.desc().nulls_last(), entries.c.kind, entries.c.id
        )
        .limit(MAX_ROWS + 1)
        .cte("exact_financial_rows")
    )
    clock = select(stamp.label("generated_at")).cte("financial_report_clock")
    return (
        select(clock.c.generated_at, bounded)
        .select_from(clock.outerjoin(bounded, true()))
        .order_by(
            bounded.c.occurred_at.desc().nulls_last(), bounded.c.kind, bounded.c.id
        )
    )


def reason(row):
    if row["occurred_at"] is None:
        return "FECHA_NO_REGISTRADA"
    if row["currency"] != "USD":
        return "MONEDA_NO_VERIFICADA"
    if row["kind"] == "ORDEN":
        if row["pricing_version"] != 1:
            return "PRECIO_NO_EXACTO"
        if row["status"] not in ORDER_STATES:
            return "ESTADO_NO_ADMITIDO"
    elif row["kind"] == "MOVIMIENTO":
        if row["status"] not in ("PROCESADO", "PAGADO"):
            return "ESTADO_NO_PROCESADO"
        if row["transaction_type"] not in TYPES:
            return "TIPO_NO_ADMITIDO"
    elif row["status"] not in PAYOUT_STATES:
        return "ESTADO_NO_ADMITIDO"
    return None


def row_view(row):
    excluded = reason(row)
    result = dict(
        key=row["kind"] + ":" + str(row["id"]),
        kind=row["kind"],
        id=str(row["id"]),
        occurred_at=utc(row["occurred_at"]) if row["occurred_at"] else None,
        currency=row["currency"],
        status=row["status"],
        transaction_type=row["transaction_type"],
        pricing_version=row["pricing_version"],
        pricing_revision=row["pricing_revision"],
        included=excluded is None,
        exclusion_reason=excluded,
        subtotal_usd=None,
        delivery_fee_usd=None,
        total_usd=None,
        amount_usd=None,
        delta_usd=None,
    )
    if excluded:
        return result
    error = HTTPException(
        409,
        "Un importe de las fuentes requiere revisión antes de emitir el reporte exacto",
    )

    def exact(value, zero=False, signed=False):
        if (
            not isinstance(value, Decimal)
            or not value.is_finite()
            or value.quantize(Decimal(".01")) != value
            or abs(value) > Decimal("99999999.99")
            or (not signed and value < 0)
            or (not zero and value == 0)
        ):
            raise error
        return value

    if row["kind"] == "ORDEN":
        values = [
            exact(row[k], zero=True)
            for k in ("subtotal_usd", "delivery_fee_usd", "total_usd")
        ]
        if (
            values[0] + values[1] != values[2]
            or not isinstance(row["pricing_revision"], int)
            or row["pricing_revision"] < 1
        ):
            raise error
        result.update(
            zip(("subtotal_usd", "delivery_fee_usd", "total_usd"), map(money, values))
        )
    else:
        amount = exact(row["amount_usd"], signed=row["kind"] == "MOVIMIENTO")
        result["amount_usd"] = money(amount)
        if row["kind"] == "MOVIMIENTO":
            kind = row["transaction_type"]
            result["delta_usd"] = money(
                abs(amount)
                if kind in CREDITS
                else -abs(amount) if kind in DEBITS else amount
            )
    return result


def blank_orders():
    return dict(
        count=0,
        subtotal_usd=Decimal(0),
        delivery_fee_usd=Decimal(0),
        total_usd=Decimal(0),
    )


def blank_ledger():
    return dict(
        count=0,
        credit_usd=Decimal(0),
        debit_usd=Decimal(0),
        adjustment_usd=Decimal(0),
        net_change_usd=Decimal(0),
    )


def blank_payouts():
    return dict(count=0, amount_usd=Decimal(0))


def add_orders(total, row):
    total["count"] += 1
    for k in ("subtotal_usd", "delivery_fee_usd", "total_usd"):
        total[k] += Decimal(row[k])


def add_ledger(total, row):
    total["count"] += 1
    key = (
        "credit_usd"
        if row["transaction_type"] in CREDITS
        else "debit_usd" if row["transaction_type"] in DEBITS else "adjustment_usd"
    )
    total[key] += (
        abs(Decimal(row["amount_usd"]))
        if key != "adjustment_usd"
        else Decimal(row["amount_usd"])
    )
    total["net_change_usd"] += Decimal(row["delta_usd"])


def add_payouts(total, row):
    total["count"] += 1
    total["amount_usd"] += Decimal(row["amount_usd"])


def view(total):
    return {k: money(v) if isinstance(v, Decimal) else v for k, v in total.items()}


async def report(db, date_from=None, date_to=None):
    first, last, start, end = civil_window(date_from, date_to)
    records = (await db.execute(query(start, end))).mappings().all()
    generated = records[0]["generated_at"]
    records = [r for r in records if r["id"] is not None]
    if len(records) > MAX_ROWS:
        raise HTTPException(
            409,
            "El rango supera 5000 registros; reduce las fechas. Los registros sin fecha también necesitan revisión; no se genera una exportación parcial",
        )
    with localcontext() as context:
        context.prec = 60
        rows = [row_view(r) for r in records]
        orders = blank_orders()
        ledger = blank_ledger()
        payouts = blank_payouts()
        order_states = {s: blank_orders() for s in ORDER_STATES}
        ledger_types = {
            t: dict(count=0, amount_usd=Decimal(0), delta_usd=Decimal(0)) for t in TYPES
        }
        payout_states = {s: blank_payouts() for s in PAYOUT_STATES}
        from datetime import timedelta

        daily = {
            (first + timedelta(days=i)).isoformat(): dict(
                orders=blank_orders(), ledger=blank_ledger(), payouts=blank_payouts()
            )
            for i in range((last - first).days + 1)
        }
        exclusions = {reason: 0 for reason in REASONS}
        sources = {
            kind: dict(row_count=0, included_count=0, excluded_count=0)
            for kind in KINDS
        }
        for row in rows:
            source = sources[row["kind"]]
            source["row_count"] += 1
            if not row["included"]:
                source["excluded_count"] += 1
                exclusions[row["exclusion_reason"]] += 1
                continue
            source["included_count"] += 1
            d = (
                datetime.fromisoformat(row["occurred_at"].replace("Z", "+00:00"))
                .astimezone(ZoneInfo(ZONE))
                .date()
                .isoformat()
            )
            if row["kind"] == "ORDEN":
                add_orders(orders, row)
                add_orders(order_states[row["status"]], row)
                add_orders(daily[d]["orders"], row)
            elif row["kind"] == "MOVIMIENTO":
                add_ledger(ledger, row)
                add_ledger(daily[d]["ledger"], row)
                t = ledger_types[row["transaction_type"]]
                t["count"] += 1
                t["amount_usd"] += Decimal(row["amount_usd"])
                t["delta_usd"] += Decimal(row["delta_usd"])
            else:
                add_payouts(payouts, row)
                add_payouts(payout_states[row["status"]], row)
                add_payouts(daily[d]["payouts"], row)
        result = dict(
            version=2,
            scope="exact_management_sources",
            currency="USD",
            timezone=ZONE,
            date_from=first.isoformat(),
            date_to=last.isoformat(),
            period_start=utc(start),
            period_end_exclusive=utc(end),
            generated_at=utc(generated),
            snapshot_basis="single_statement_visibility",
            recognition_basis="source_creation_time",
            payout_basis="requests_created_in_period_current_status",
            undated_policy="included_as_excluded",
            bank_verified=False,
            customer_cashbook_included=False,
            wallet_cents_included=False,
            maximum_rows=MAX_ROWS,
            export_complete=True,
            row_count=len(rows),
            excluded_count=sum(exclusions.values()),
            sources=sources,
            orders=dict(
                **view(orders),
                by_status=[dict(status=s, **view(t)) for s, t in order_states.items()],
            ),
            ledger=dict(
                **view(ledger),
                by_type=[
                    dict(transaction_type=s, **view(t)) for s, t in ledger_types.items()
                ],
            ),
            payouts=dict(
                **view(payouts),
                by_status=[dict(status=s, **view(t)) for s, t in payout_states.items()],
            ),
            exclusions=[dict(reason=r, count=n) for r, n in exclusions.items()],
            daily=[
                dict(date=d, **{k: view(v) for k, v in t.items()})
                for d, t in daily.items()
            ],
            rows=rows,
        )
    result["content_sha256"] = hashlib.sha256(
        json.dumps(
            result, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    return result
