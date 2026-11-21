from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from app.schemas.zone import ZoneTariffInput
from app.services.zone_tariffs import tariff_view


@pytest.mark.parametrize(
    "field,value",
    [
        ("base_usd", v)
        for v in (
            0,
            0.1,
            True,
            None,
            "-1",
            "1e2",
            "NaN",
            "Infinity",
            "0.001",
            "100000000.00",
            "01.00",
            "",
        )
    ]
    + [
        ("per_km_usd", "0.001"),
        ("currency", "VES"),
        ("expected_revision", True),
        ("expected_revision", -1),
        ("unexpected", "0"),
    ],
)
def test_new_tariffs_reject_ambiguous_inputs(field, value):
    body = dict(expected_revision=0, currency="USD", base_usd="0.31", per_km_usd="0.1")
    body[field] = value
    with pytest.raises(ValidationError):
        ZoneTariffInput(**body)


@pytest.mark.parametrize(
    "value,expected", [("0", "0.00"), ("0.31", "0.31"), ("99999999.99", "99999999.99")]
)
def test_new_tariffs_preserve_exact_money(value, expected):
    assert (
        ZoneTariffInput(
            expected_revision=0, currency="USD", base_usd=value, per_km_usd=value
        ).base_usd
        == expected
    )


def test_unconfigured_does_not_relabel_historical_float():
    zone = SimpleNamespace(
        id=uuid4(),
        tariff_revision=0,
        tariff_base_usd=None,
        tariff_per_km_usd=None,
        tariff_updated_at=None,
        tariff_updated_by=None,
        delivery_fee_base=4000.123456789,
    )
    value = tariff_view(zone)
    assert (
        value["currency"] is None
        and value["base_usd"] is None
        and value["revision"] == 0
    )
    zone.tariff_base_usd = Decimal("0.00")
    with pytest.raises(HTTPException) as e:
        tariff_view(zone)
    assert e.value.status_code == 409
