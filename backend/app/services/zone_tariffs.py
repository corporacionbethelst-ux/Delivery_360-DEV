"""Explicit USD configuration, separate from historical unverified Float rates."""

from decimal import Decimal
from fastapi import HTTPException


def tariff_view(zone):
    revision = zone.tariff_revision
    base, per_km = zone.tariff_base_usd, zone.tariff_per_km_usd
    empty = (
        revision == 0
        and base is None
        and per_km is None
        and zone.tariff_updated_at is None
        and zone.tariff_updated_by is None
    )
    if not empty:
        if (
            not isinstance(revision, int)
            or revision < 1
            or revision > 2147483647
            or any(
                not isinstance(n, Decimal)
                or not n.is_finite()
                or n < 0
                or n > Decimal("99999999.99")
                or n.as_tuple().exponent < -2
                for n in (base, per_km)
            )
            or zone.tariff_updated_at is None
            or zone.tariff_updated_by is None
        ):
            raise HTTPException(
                409, "Las tarifas exactas de la zona requieren revisión"
            )
    return {
        "version": 1,
        "scope": "zone_usd_tariff",
        "zone_id": str(zone.id),
        "revision": revision,
        "currency": None if empty else "USD",
        "base_usd": None if empty else format(base, ".2f"),
        "per_km_usd": None if empty else format(per_km, ".2f"),
        "updated_at": None if empty else zone.tariff_updated_at.isoformat(),
        "updated_by": None if empty else str(zone.tariff_updated_by),
        "application": "zone_configuration_only",
    }
