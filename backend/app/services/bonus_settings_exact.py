"""Exact prospective parameters and USD-only scenarios; no historical relabelling."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import hashlib
import json
import re

from fastapi import HTTPException
from sqlalchemy import String, Text, cast, func, select

from app.models.delivery import Delivery
from app.models.platform_setting import PlatformSetting

MONEY_KEYS = (
    "delivery_fee_base",
    "min_order_amount",
    "rider_delivery_bonus",
    "rider_failed_attempt_bonus",
)
NUMERIC_KEYS = (*MONEY_KEYS, "commission_percentage")
MAX_AMOUNT = Decimal("99999999.99")


def exact_parameter(value, *, percentage=False, incoming=False):
    """New inputs are decimal text; stored JSON numbers are decoded as Decimal."""
    if incoming and not isinstance(value, str):
        raise ValueError("Introduce el importe como texto decimal, sin exponentes")
    if isinstance(value, bool) or not isinstance(value, (str, Decimal, int)):
        raise ValueError("Parámetro decimal no válido")
    text = str(value)
    scale = 18 if percentage else 2
    if incoming and not re.fullmatch(
        rf"(?:0|[1-9][0-9]{{0,7}})(?:\.[0-9]{{1,{scale}}})?", text
    ):
        raise ValueError("Usa hasta dos decimales en importes, sin exponentes")
    try:
        number = Decimal(text)
        if (
            not number.is_finite()
            or number < 0
            or number > (100 if percentage else MAX_AMOUNT)
            or number.as_tuple().exponent < -scale
        ):
            raise ValueError("Parámetro fuera de rango o precisión")
        if number == 0:
            number = abs(number)
        if percentage:
            return (
                format(number, "f").rstrip("0").rstrip(".")
                if "." in format(number, "f")
                else format(number, "f")
            )
        return format(number, ".2f")
    except InvalidOperation as exc:
        raise ValueError("Parámetro decimal no válido") from exc


async def load_rows(db, keys, *, for_update=False):
    query = (
        select(PlatformSetting, cast(PlatformSetting.value, Text).label("raw_value"))
        .where(PlatformSetting.key.in_(keys))
        .order_by(PlatformSetting.key)
        .execution_options(populate_existing=True)
    )
    if for_update:
        query = query.with_for_update()
    rows = (await db.execute(query)).all()
    return (
        {row.key: row for row, raw in rows},
        {row.key: raw for row, raw in rows},
    )


def exact_revision(rows, raw):
    snapshot = [
        [
            key,
            raw[key],
            row.updated_at.isoformat() if row.updated_at else None,
            str(row.updated_by_user_id) if row.updated_by_user_id else None,
        ]
        for key, row in sorted(rows.items())
    ]
    return (
        "s2-"
        + hashlib.sha256(
            json.dumps(
                snapshot,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
        ).hexdigest()
    )


def settings_view(rows, raw, revision, legacy_revision=None):
    values = {}
    issues = []
    for key in NUMERIC_KEYS:
        try:
            value = json.loads(
                raw.get(key, "null"), parse_float=Decimal, parse_int=Decimal
            )
            values[key] = (
                None
                if value is None
                else exact_parameter(value, percentage=key == "commission_percentage")
            )
        except (ValueError, ArithmeticError, TypeError):
            values[key] = None
            issues.append({"field": key, "reason": "PARAMETRO_NO_VALIDO"})

    def stored(key, default):
        return (
            rows[key].value if key in rows and rows[key].value is not None else default
        )

    zones = stored("active_zones", [])
    email = stored("support_email", None)
    maintenance = stored("maintenance_mode", False)
    if (
        not isinstance(zones, list)
        or any(not isinstance(z, str) or not z.strip() for z in zones)
        or (email is not None and not isinstance(email, str))
        or type(maintenance) is not bool
    ):
        raise HTTPException(409, "La configuración operativa requiere revisión")
    latest = max(
        (row.updated_at for row in rows.values() if row.updated_at), default=None
    )
    changed_by = next(
        (
            str(row.updated_by_user_id) if row.updated_by_user_id else None
            for row in rows.values()
            if row.updated_at == latest
        ),
        None,
    )
    return dict(
        version=2,
        currency="USD",
        units_basis="prospective_usd_parameters",
        revision=revision,
        legacy_revision=legacy_revision,
        **values,
        active_zones=[z.strip() for z in zones],
        support_email=email,
        maintenance_mode=maintenance,
        updated_at=latest.isoformat() if latest else None,
        updated_by_user_id=changed_by,
        field_issues=issues,
    )


def finish(value):
    value["content_sha256"] = hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()
    return value


async def scenario(db, proposed, days, actor, expected_revision, keys):
    """One SQL statement captures configuration, window and every candidate bonus."""
    from datetime import timedelta

    settings_cte = (
        select(
            PlatformSetting.key,
            cast(PlatformSetting.value, Text).label("raw"),
            PlatformSetting.value,
            PlatformSetting.updated_at,
            PlatformSetting.updated_by_user_id,
        )
        .where(PlatformSetting.key.in_(keys))
        .cte("scenario_settings")
    )
    clock = select(func.timezone("UTC", func.statement_timestamp()).label("at")).cte(
        "scenario_clock"
    )
    stamp = func.coalesce(Delivery.completed_at, Delivery.bonus_snapshot_date)
    deliveries = (
        select(
            Delivery.id,
            cast(Delivery.status, String).label("status"),
            cast(Delivery.locked_bonus_type, String).label("kind"),
            Delivery.locked_bonus_amount.label("amount"),
            Delivery.locked_bonus_currency.label("currency"),
            stamp.label("stamp"),
        )
        .where(
            Delivery.status.in_(["COMPLETADA", "FALLIDA"]),
            (stamp.is_(None))
            | (
                (stamp >= select(clock.c.at).scalar_subquery() - timedelta(days=days))
                & (stamp < select(clock.c.at).scalar_subquery())
            ),
        )
        .limit(10001)
        .cte("scenario_deliveries")
    )
    # JSON aggregation is bounded at one aggregate row; no join multiplication.
    raw_settings = select(
        func.jsonb_agg(
            func.jsonb_build_object(
                "key",
                settings_cte.c.key,
                "raw",
                settings_cte.c.raw,
                "value",
                settings_cte.c.value,
                "updated_at",
                settings_cte.c.updated_at,
                "updated_by_user_id",
                settings_cte.c.updated_by_user_id,
            )
        )
    ).scalar_subquery()
    raw_deliveries = select(
        func.jsonb_agg(
            func.jsonb_build_object(
                "id",
                deliveries.c.id,
                "status",
                deliveries.c.status,
                "kind",
                deliveries.c.kind,
                "amount",
                cast(deliveries.c.amount, Text),
                "currency",
                deliveries.c.currency,
                "stamp",
                deliveries.c.stamp,
            )
        )
    ).scalar_subquery()
    # Limit materialization rather than letting a browser calculate or total rows.
    count = select(func.count()).select_from(deliveries).scalar_subquery()
    result = (
        await db.execute(
            select(
                clock.c.at,
                raw_settings.label("settings"),
                raw_deliveries.label("deliveries"),
                count.label("count"),
            )
        )
    ).one()
    if result._mapping["count"] > 10000:
        raise HTTPException(
            409,
            "La muestra y sus registros sin fecha exceden 10000 entregas; revisa el alcance",
        )
    from types import SimpleNamespace
    from datetime import datetime

    rows = {
        r["key"]: SimpleNamespace(
            value=r["value"],
            updated_at=(
                datetime.fromisoformat(r["updated_at"]) if r["updated_at"] else None
            ),
            updated_by_user_id=r["updated_by_user_id"],
        )
        for r in result.settings or []
    }
    raw_values = {r["key"]: r["raw"] for r in result.settings or []}
    revision = exact_revision(rows, raw_values)
    if revision != expected_revision:
        raise HTTPException(412, "La configuración cambió. Recarga antes de simular")
    config = settings_view(
        rows, {r["key"]: r["raw"] for r in result.settings or []}, revision
    )
    current = config["rider_delivery_bonus"]
    if current is None:
        raise HTTPException(409, "Configura un bono decimal válido antes de simular")
    proposal = proposed if proposed is not None else current
    completed = failed = 0
    success_amount = failed_amount = Decimal("0.00")
    exclusions = {
        key: 0
        for key in (
            "undated",
            "unknown_currency",
            "other_currency",
            "no_bonus",
            "invalid_snapshot",
        )
    }
    for row in result.deliveries or []:
        if row["stamp"] is None:
            exclusions["undated"] += 1
        elif (
            row["status"] == "FALLIDA" and row["amount"] is None and row["kind"] is None
        ):
            exclusions["no_bonus"] += 1
        elif row["currency"] is None:
            exclusions["unknown_currency"] += 1
        elif row["currency"] != "USD":
            exclusions["other_currency"] += 1
        else:
            try:
                amount = Decimal(exact_parameter(row["amount"]))
                if row["status"] == "COMPLETADA" and row["kind"] == "SUCCESS":
                    completed += 1
                    success_amount += amount
                elif row["status"] == "FALLIDA" and row["kind"] == "FAILED_ATTEMPT":
                    failed += 1
                    failed_amount += amount
                else:
                    raise ValueError("outcome")
            except (ValueError, ArithmeticError, TypeError):
                exclusions["invalid_snapshot"] += 1
    with localcontext() as context:
        context.prec = 48
        historical = success_amount + failed_amount
        calculated = Decimal(proposal) * completed + failed_amount
        difference = calculated - historical
        percentage_value = (
            (difference * 100 / historical).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if historical
            else None
        )
        percentage = (
            format(
                abs(percentage_value) if percentage_value == 0 else percentage_value,
                ".2f",
            )
            if percentage_value is not None
            else None
        )
    end = result.at
    return finish(
        dict(
            version=2,
            scope="uniform_bonus_usd_scenario",
            currency="USD",
            actor={"user_id": str(actor.id), "role": actor.role.value},
            settings_revision=revision,
            snapshot_basis="single_statement_visibility",
            history_days=days,
            period_start=(end - timedelta(days=days)).isoformat(timespec="microseconds")
            + "Z",
            period_end=end.isoformat(timespec="microseconds") + "Z",
            generated_at=end.isoformat(timespec="microseconds") + "Z",
            comparison_basis="flat_bonus_same_usd_deliveries",
            current_base_bonus=current,
            applied_bonus=proposal,
            completed_deliveries=completed,
            failed_bonus_deliveries=failed,
            recorded_completed_bonus=format(success_amount, ".2f"),
            recorded_failed_bonus=format(failed_amount, ".2f"),
            historical_cost=format(historical, ".2f"),
            scenario_cost=format(calculated, ".2f"),
            difference=format(difference, ".2f"),
            candidate_deliveries=result._mapping["count"],
            exclusions=exclusions,
            bank_verified=False,
            percentage_change=percentage,
        )
    )
