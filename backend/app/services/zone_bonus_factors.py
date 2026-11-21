"""Dimensionless decimal configuration and the factor actually used by a terminal bonus."""

from decimal import Decimal, InvalidOperation, localcontext
import re
from uuid import UUID
from fastapi import HTTPException
from app.core.exceptions import ValidationError
from sqlalchemy import select
from app.models.zone import Zone
from app.services.delivery_ledger import bonus_component, calculated_bonus


def factor_text(value, *, incoming=False):
    if incoming and (
        not isinstance(value, str)
        or not re.fullmatch(r"(?:0|[1-5])(?:\.[0-9]{1,18})?", value)
    ):
        raise ValueError(
            "Introduce un factor decimal entre 0.1 y 5, con hasta 18 decimales"
        )
    if isinstance(value, bool):
        raise ValueError("Factor no válido")
    try:
        n = Decimal(str(value))
        if (
            not n.is_finite()
            or n < Decimal("0.1")
            or n > 5
            or n.as_tuple().exponent < -18
        ):
            raise ValueError("Factor fuera de rango o precisión")
        text = format(n, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text
    except (InvalidOperation, TypeError):
        raise ValueError("Factor decimal no válido") from None


def factor_view(zone):
    revision = zone.bonus_factor_revision
    empty = (
        revision == 0
        and zone.bonus_factor_exact is None
        and zone.bonus_factor_updated_at is None
        and zone.bonus_factor_updated_by is None
    )
    if not empty:
        try:
            value = factor_text(zone.bonus_factor_exact)
            if (
                type(revision) is not int
                or not 1 <= revision <= 2147483647
                or zone.bonus_factor_updated_at is None
                or zone.bonus_factor_updated_by is None
            ):
                raise ValueError()
        except ValueError:
            raise HTTPException(409, "El factor de zona requiere revisión") from None
    try:
        legacy = bonus_component(zone.bonus_multiplier)
        legacy_text = format(legacy, "f")
    except ValidationError:
        legacy_text = None
    return dict(
        version=1,
        scope="zone_bonus_factor",
        legacy_factor=legacy_text,
        zone_id=str(zone.id),
        revision=revision,
        factor=None if empty else value,
        unit="dimensionless",
        updated_at=None if empty else zone.bonus_factor_updated_at.isoformat(),
        updated_by=None if empty else str(zone.bonus_factor_updated_by),
        application="prospective_delivery_bonus",
    )


async def resolve_factor(db, zone_id, tier):
    # Callers lock the rider first, matching zone deletion's rider-before-zone order.
    zone = (
        await db.scalar(
            select(Zone)
            .where(Zone.id == zone_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if zone_id
        else None
    )
    revision = None
    if zone is None:
        value = Decimal("1")
        basis = "no_zone_default"
        zone_id = None
    elif zone.bonus_factor_revision:
        view = factor_view(zone)
        value = Decimal(view["factor"])
        revision = view["revision"]
        basis = "declared_exact"
    else:
        value = bonus_component(
            zone.bonus_multiplier if zone.bonus_multiplier is not None else 1
        )
        basis = "legacy_decimal_representation"
    text = format(value, "f")
    text = text.rstrip("0").rstrip(".") if "." in text else text
    tier_text = format(tier, "f")
    tier_text = tier_text.rstrip("0").rstrip(".") if "." in tier_text else tier_text
    return value, dict(
        version=1,
        unit="dimensionless",
        zone_id=str(zone_id) if zone_id else None,
        zone_revision=revision,
        zone_factor=text,
        tier_factor=tier_text,
        basis=basis,
    )


def calculated_with_factor(base, zone, tier, *, precise=True):
    if not precise:
        return calculated_bonus(base * zone * tier)
    with localcontext() as context:
        context.prec = 80
        return calculated_bonus(base * zone * tier)


def validate_factor_snapshot(raw):
    if (
        not isinstance(raw, dict)
        or set(raw)
        != {
            "version",
            "unit",
            "zone_id",
            "zone_revision",
            "zone_factor",
            "tier_factor",
            "basis",
        }
        or type(raw["version"]) is not int
        or raw["version"] != 1
        or raw["unit"] != "dimensionless"
    ):
        raise ValueError("Snapshot de factores inválido")
    for key in ("zone_factor", "tier_factor"):
        if not isinstance(raw[key], str) or not re.fullmatch(
            r"(?:0|[1-9][0-9]{0,7})(?:\.[0-9]{1,324})?", raw[key]
        ):
            raise ValueError("Factor conservado inválido")
        try:
            bonus_component(raw[key])
        except ValidationError:
            raise ValueError("Factor conservado fuera de rango") from None
    if raw["tier_factor"] not in ("1", "1.05", "1.1", "1.15"):
        raise ValueError("Nivel conservado inválido")
    if raw["basis"] == "no_zone_default":
        if (
            raw["zone_id"] is not None
            or raw["zone_revision"] is not None
            or raw["zone_factor"] != "1"
        ):
            raise ValueError("Factor por defecto contradictorio")
    else:
        if (
            not isinstance(raw["zone_id"], str)
            or str(UUID(raw["zone_id"])) != raw["zone_id"]
        ):
            raise ValueError("Zona conservada inválida")
        if raw["basis"] == "declared_exact":
            if (
                type(raw["zone_revision"]) is not int
                or not 1 <= raw["zone_revision"] <= 2147483647
                or factor_text(raw["zone_factor"], incoming=True) != raw["zone_factor"]
            ):
                raise ValueError("Revisión conservada inválida")
        elif (
            raw["basis"] != "legacy_decimal_representation"
            or raw["zone_revision"] is not None
        ):
            raise ValueError("Procedencia conservada inválida")
    return raw


async def configured_rider_bonus(db, rider_id, base):
    """Opt in base-only compatibility entrypoints only after explicit factor confirmation."""
    from app.models.rider import Rider, RiderTier

    rider = await db.scalar(
        select(Rider)
        .where(Rider.id == rider_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if rider is None or rider.zone_id is None:
        return None
    zone = await db.scalar(
        select(Zone)
        .where(Zone.id == rider.zone_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if zone is None or not zone.bonus_factor_revision:
        return None
    tiers = {
        RiderTier.BRONCE: Decimal("1"),
        RiderTier.PLATA: Decimal("1.05"),
        RiderTier.ORO: Decimal("1.10"),
        RiderTier.PLATINO: Decimal("1.15"),
    }
    tier = tiers.get(rider.tier, Decimal("1"))
    factor, snapshot = await resolve_factor(db, zone.id, tier)
    return calculated_with_factor(base, factor, tier), snapshot
