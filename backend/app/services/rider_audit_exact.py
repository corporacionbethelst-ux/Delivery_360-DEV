"""One-statement operational audit with distinct decimal ledger and pending requests."""

from decimal import Decimal, localcontext
from datetime import datetime
import hashlib, json
from fastapi import HTTPException
from sqlalchemy import select, func, case, cast, String, literal, true, and_, or_
from app.models.rider import Rider
from app.models.user import User
from app.models.order import Order
from app.models.delivery import Delivery
from app.models.financial import Financial
from app.models.payout import Payout
from app.services.financial_reports_exact import CREDITS, DEBITS, TYPES
from app.services.customer_cashbook import utc

LEDGER_REASONS = (
    "FECHA_NO_REGISTRADA",
    "MONEDA_NO_VERIFICADA",
    "FECHA_FUTURA",
    "ESTADO_NO_PROCESADO",
    "TIPO_NO_ADMITIDO",
)
PAYOUT_REASONS = (
    "FECHA_NO_REGISTRADA",
    "MONEDA_NO_VERIFICADA",
    "FECHA_FUTURA",
    "ESTADO_NO_PENDIENTE",
)
ZERO = Decimal("0.00")


def query(status, online, limit, offset, rider_id=None):
    stamp = func.timezone("UTC", func.statement_timestamp())
    owners = select(
        Rider.id.label("rider_id"),
        User.id.label("user_id"),
        User.first_name,
        User.last_name,
        User.email,
        User.phone,
        cast(Rider.status, String).label("status"),
        Rider.is_online,
        cast(Rider.vehicle_type, String).label("vehicle_type"),
        Rider.vehicle_plate,
        Rider.operating_zone,
        Rider.zone_id,
        Rider.current_order_id,
        Rider.last_lat,
        Rider.last_lng,
        Rider.last_location_at,
    ).join(User, User.id == Rider.user_id)
    if status is not None:
        owners = owners.where(cast(Rider.status, String) == status)
    if online is not None:
        owners = owners.where(Rider.is_online.is_(online))
    if rider_id is not None:
        owners = owners.where(Rider.id == rider_id)
    owners = (
        owners.order_by(
            Rider.is_online.desc().nulls_last(),
            User.first_name.asc().nulls_last(),
            User.last_name.asc().nulls_last(),
            Rider.id,
        )
        .limit(limit)
        .offset(offset)
        .cte("audit_exact_owners")
    )

    def count(model, *conditions):
        return (
            select(func.count(model.id))
            .where(
                getattr(model, "assigned_rider_id" if model is Order else "rider_id")
                == owners.c.rider_id,
                *conditions,
            )
            .correlate(owners)
            .scalar_subquery()
        )

    metrics = select(
        owners,
        count(Order).label("orders_assigned"),
        count(Order, cast(Order.status, String) == "ENTREGADO").label(
            "orders_delivered"
        ),
        count(
            Order,
            cast(Order.status, String).in_(
                ("ASIGNADO", "EN_RECOLECCION", "RECOLECTADO", "EN_RUTA")
            ),
        ).label("orders_active"),
        count(Delivery).label("deliveries_total"),
        count(Delivery, cast(Delivery.status, String) == "COMPLETADA").label(
            "deliveries_completed"
        ),
        count(Delivery, cast(Delivery.status, String) == "FALLIDA").label(
            "deliveries_failed"
        ),
        count(
            Delivery,
            cast(Delivery.status, String).in_(
                ("INICIADA", "EN_PICKUP", "EN_ROUTE", "EN_DESTINO")
            ),
        ).label("deliveries_in_progress"),
        count(Delivery, Delivery.sla_compliant.is_(True)).label("sla_compliant"),
    ).cte("audit_exact_metrics")

    def group(model, ledger):
        clock = model.created_at if ledger else model.requested_at
        state = cast(model.status, String)
        typ = (
            cast(Financial.transaction_type, String)
            if ledger
            else literal(None, String)
        )
        reason = case(
            (clock.is_(None), "FECHA_NO_REGISTRADA"),
            (
                or_(model.currency_code.is_(None), model.currency_code != "USD"),
                "MONEDA_NO_VERIFICADA",
            ),
            (clock > stamp, "FECHA_FUTURA"),
            (
                (
                    or_(state.is_(None), state.not_in(("PROCESADO", "PAGADO")))
                    if ledger
                    else or_(state.is_(None), state != "PENDIENTE")
                ),
                "ESTADO_NO_PROCESADO" if ledger else "ESTADO_NO_PENDIENTE",
            ),
            *(
                ([(or_(typ.is_(None), typ.not_in(TYPES)), "TIPO_NO_ADMITIDO")])
                if ledger
                else []
            ),
            else_=None,
        )
        rows = (
            select(
                model.rider_id, model.amount, typ.label("kind"), reason.label("reason")
            )
            .join(owners, model.rider_id == owners.c.rider_id)
            .cte("audit_exact_ledger_rows" if ledger else "audit_exact_payout_rows")
        )
        included = rows.c.reason.is_(None)
        good = and_(
            rows.c.amount.is_not(None),
            rows.c.amount.between(
                Decimal("-99999999.99") if ledger else Decimal("0.01"),
                Decimal("99999999.99"),
            ),
            rows.c.amount != 0,
        )

        def number(condition):
            return func.sum(case((condition, 1), else_=0))

        def amount(condition, value):
            return func.coalesce(
                func.sum(case((and_(included, good, condition), value), else_=ZERO)),
                ZERO,
            )

        cols = [
            rows.c.rider_id,
            func.count().label(("ledger" if ledger else "payout") + "_rows"),
            number(included).label(("ledger" if ledger else "payout") + "_included"),
            number(and_(included, ~good)).label(
                ("ledger" if ledger else "payout") + "_invalid"
            ),
        ]
        reasons = LEDGER_REASONS if ledger else PAYOUT_REASONS
        cols += [
            number(rows.c.reason == r).label(
                ("ledger_" if ledger else "payout_") + r.lower()
            )
            for r in reasons
        ]
        if ledger:
            cols += [
                amount(rows.c.kind.in_(CREDITS), func.abs(rows.c.amount)).label(
                    "credit_usd"
                ),
                amount(rows.c.kind.in_(DEBITS), func.abs(rows.c.amount)).label(
                    "debit_usd"
                ),
                amount(rows.c.kind == "AJUSTE", rows.c.amount).label("adjustment_usd"),
            ]
        else:
            cols += [amount(true(), rows.c.amount).label("pending_usd")]
        return (
            select(*cols)
            .group_by(rows.c.rider_id)
            .cte("audit_exact_ledger" if ledger else "audit_exact_payouts")
        )

    ledger = group(Financial, True)
    payouts = group(Payout, False)
    summary = (
        select(
            metrics,
            *[c for c in ledger.c if c.key != "rider_id"],
            *[c for c in payouts.c if c.key != "rider_id"],
        )
        .select_from(
            metrics.outerjoin(
                ledger, metrics.c.rider_id == ledger.c.rider_id
            ).outerjoin(payouts, metrics.c.rider_id == payouts.c.rider_id)
        )
        .cte("audit_exact_summary")
    )
    clock = select(stamp.label("generated_at")).cte("audit_exact_clock")
    return (
        select(clock, summary)
        .select_from(clock.outerjoin(summary, true()))
        .order_by(
            summary.c.is_online.desc().nulls_last(),
            summary.c.first_name.asc().nulls_last(),
            summary.c.last_name.asc().nulls_last(),
            summary.c.rider_id,
        )
    )


async def report(db, actor, status, online, limit, offset, rider_id=None):
    records = (
        (await db.execute(query(status, online, limit, offset, rider_id)))
        .mappings()
        .all()
    )
    generated = records[0]["generated_at"]
    if not isinstance(generated, datetime):
        raise HTTPException(503, "No se pudo confirmar el corte de auditoría")
    items = []
    with localcontext() as context:
        context.prec = 60
        for raw in records:
            if raw["rider_id"] is None:
                continue
            row = dict(raw)
            if row["ledger_invalid"] or row["payout_invalid"]:
                raise HTTPException(
                    409,
                    "Un importe USD elegible requiere revisión; no se publica un total inventado",
                )
            counts = {
                k: int(row[k] or 0)
                for k in (
                    "orders_assigned",
                    "orders_delivered",
                    "orders_active",
                    "deliveries_total",
                    "deliveries_completed",
                    "deliveries_failed",
                    "deliveries_in_progress",
                    "sla_compliant",
                )
            }
            money = {}
            for key in ("credit_usd", "debit_usd", "adjustment_usd", "pending_usd"):
                value = row[key] if row[key] is not None else ZERO
                if (
                    not isinstance(value, Decimal)
                    or not value.is_finite()
                    or value != value.quantize(Decimal(".01"))
                ):
                    raise HTTPException(409, "El importe agregado requiere revisión")
                money[key] = format(value, ".2f")
            money["net_change_usd"] = format(
                Decimal(money["credit_usd"])
                - Decimal(money["debit_usd"])
                + Decimal(money["adjustment_usd"]),
                ".2f",
            )
            for prefix, reasons in [
                ("ledger", LEDGER_REASONS),
                ("payout", PAYOUT_REASONS),
            ]:
                money[prefix + "_rows"] = int(row[prefix + "_rows"] or 0)
                money[prefix + "_included"] = int(row[prefix + "_included"] or 0)
                money[prefix + "_exclusions"] = [
                    {"reason": r, "count": int(row[prefix + "_" + r.lower()] or 0)}
                    for r in reasons
                ]
            item = {
                k: row[k]
                for k in (
                    "email",
                    "phone",
                    "status",
                    "is_online",
                    "vehicle_type",
                    "vehicle_plate",
                    "operating_zone",
                    "last_lat",
                    "last_lng",
                )
            }
            item.update(
                {
                    k: str(row[k]) if row[k] is not None else None
                    for k in ("rider_id", "user_id", "zone_id", "current_order_id")
                }
            )
            name = " ".join(p for p in (row["first_name"], row["last_name"]) if p)
            item.update(
                full_name=name or row["email"],
                last_location_at=(
                    utc(row["last_location_at"]) if row["last_location_at"] else None
                ),
                **counts,
                sla_compliance_rate=(
                    round(counts["sla_compliant"] / counts["deliveries_total"] * 100, 2)
                    if counts["deliveries_total"]
                    else 0.0
                ),
                money=money,
            )
            items.append(item)
    result = dict(
        version=1,
        scope="operational_rider_audit_usd",
        currency="USD",
        viewer_user_id=str(actor.id),
        viewer_role=actor.role.value,
        generated_at=utc(generated),
        snapshot_basis="single_statement_visibility",
        ledger_basis="processed_registered_movements",
        payout_basis="current_pending_requests",
        available_balance_included=False,
        bank_verified=False,
        wallet_cents_included=False,
        filters={
            "status": status,
            "online": online,
            "rider_id": str(rider_id) if rider_id else None,
        },
        limit=limit,
        offset=offset,
        total=len(items),
        items=items,
    )
    result["content_sha256"] = hashlib.sha256(
        json.dumps(
            result, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    return result
