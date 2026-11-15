"""An owner's recorded earnings only; no inference from orders or wallet caches."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo
import hashlib, json
from fastapi import HTTPException
from sqlalchemy import select, cast, String, func, true
from app.models.rider import Rider
from app.models.financial import Financial
from app.services import financial_reports_exact as management
from app.services.customer_cashbook import utc, ZONE

MAX_ROWS = 10000
REASONS = (
    "MONEDA_NO_VERIFICADA",
    "FECHA_NO_REGISTRADA",
    "ESTADO_NO_PROCESADO",
    "TIPO_NO_ADMITIDO",
    "FECHA_FUTURA",
)


def query(user_id):
    owner = (
        select(
            Rider.id.label("owner_id"),
            func.timezone("UTC", func.statement_timestamp()).label("generated_at"),
        )
        .where(Rider.user_id == user_id)
        .cte("earnings_owner")
    )
    entries = (
        select(
            Financial.id,
            Financial.rider_id,
            Financial.currency_code.label("currency"),
            cast(Financial.status, String).label("status"),
            cast(Financial.transaction_type, String).label("transaction_type"),
            Financial.created_at.label("occurred_at"),
            Financial.amount.label("amount_usd"),
            Financial.description,
        )
        .join(owner, Financial.rider_id == owner.c.owner_id)
        .order_by(Financial.created_at.desc().nulls_last(), Financial.id.desc())
        .limit(MAX_ROWS + 1)
        .cte("owner_earnings_rows")
    )
    return (
        select(owner, entries)
        .select_from(owner.outerjoin(entries, true()))
        .order_by(entries.c.occurred_at.desc().nulls_last(), entries.c.id.desc())
    )


def row_view(raw, generated):
    row = dict(raw)
    row.update(
        kind="MOVIMIENTO",
        pricing_version=None,
        pricing_revision=None,
        subtotal_usd=None,
        delivery_fee_usd=None,
        total_usd=None,
    )
    view = management.row_view(row)
    if raw["occurred_at"] is not None and raw["occurred_at"] > generated:
        view.update(
            included=False,
            exclusion_reason="FECHA_FUTURA",
            amount_usd=None,
            delta_usd=None,
        )
    return {
        k: view[k]
        for k in (
            "key",
            "id",
            "occurred_at",
            "currency",
            "status",
            "transaction_type",
            "included",
            "exclusion_reason",
            "amount_usd",
            "delta_usd",
        )
    } | {"rider_id": str(raw["rider_id"]), "description": raw["description"]}


def total(rows):
    value = management.blank_ledger()
    for row in rows:
        management.add_ledger(value, row)
    return dict(
        **management.view(value),
        completed_delivery_count=sum(
            r["transaction_type"] == "PAGO_ENTREGA" for r in rows
        ),
    )


async def report(db, user_id):
    records = (await db.execute(query(user_id))).mappings().all()
    if not records:
        raise HTTPException(404, "Perfil de repartidor no encontrado")
    owners = {r["owner_id"] for r in records}
    if len(owners) != 1:
        raise HTTPException(
            409, "La cuenta tiene más de un perfil de repartidor; requiere revisión"
        )
    rider_id = next(iter(owners))
    generated = records[0]["generated_at"]
    records = [r for r in records if r["id"] is not None]
    if len(records) > MAX_ROWS:
        raise HTTPException(
            409,
            "El historial supera 10000 movimientos; requiere una exportación histórica revisada. No se muestran totales ni archivos parciales",
        )
    with localcontext() as context:
        context.prec = 60
        rows = [row_view(row, generated) for row in records]
        valid = [r for r in rows if r["included"]]
        today = generated.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(ZONE)).date()
        first = today - timedelta(days=6)
        days = {(first + timedelta(days=i)).isoformat(): [] for i in range(7)}
        for row in valid:
            day = (
                datetime.fromisoformat(row["occurred_at"].replace("Z", "+00:00"))
                .astimezone(ZoneInfo(ZONE))
                .date()
                .isoformat()
            )
            if day in days:
                days[day].append(row)
        result = dict(
            version=1,
            scope="own_recorded_usd_earnings",
            user_id=str(user_id),
            rider_id=str(rider_id),
            currency="USD",
            timezone=ZONE,
            generated_at=utc(generated),
            today=today.isoformat(),
            week_from=first.isoformat(),
            snapshot_basis="single_statement_visibility",
            earnings_basis="processed_ledger_credits",
            available_balance_included=False,
            order_values_included=False,
            wallet_cents_included=False,
            bank_verified=False,
            maximum_rows=MAX_ROWS,
            export_complete=True,
            row_count=len(rows),
            excluded_count=len(rows) - len(valid),
            lifetime=total(valid),
            day=total(days[today.isoformat()]),
            week=total([r for rs in days.values() for r in rs]),
            daily=[dict(date=d, **total(rs)) for d, rs in days.items()],
            exclusions=[
                dict(reason=r, count=sum(x["exclusion_reason"] == r for x in rows))
                for r in REASONS
            ],
            rows=rows,
        )
    result["content_sha256"] = hashlib.sha256(
        json.dumps(
            result, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    return result
