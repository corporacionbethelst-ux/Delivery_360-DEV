from decimal import Decimal
from uuid import uuid4
import pytest
from pydantic import ValidationError
from app.schemas.zone import ZoneBonusFactorInput
from app.services.zone_bonus_factors import (
    factor_text,
    calculated_with_factor,
    validate_factor_snapshot,
)


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        1,
        1.2,
        "0",
        "-1",
        "5.1",
        "NaN",
        "Infinity",
        "1e0",
        "0.1234567890123456789",
        "01.2",
        "",
    ],
)
def test_factor_input_is_decimal_text_with_explicit_range_and_precision(value):
    with pytest.raises(ValidationError):
        ZoneBonusFactorInput(expected_revision=0, factor=value)


@pytest.mark.parametrize(
    "value,expected",
    [("0.1", "0.1"), ("5.000", "5"), ("1.234567890123456789", "1.234567890123456789")],
)
def test_factor_input_preserves_all_declared_digits(value, expected):
    assert ZoneBonusFactorInput(expected_revision=0, factor=value).factor == expected


def sample():
    return dict(
        version=1,
        unit="dimensionless",
        zone_id=str(uuid4()),
        zone_revision=1,
        zone_factor="1.234567890123456789",
        tier_factor="1.15",
        basis="declared_exact",
    )


@pytest.mark.parametrize(
    "change",
    [
        {"zone_factor": "NaN"},
        {"zone_factor": 1.2},
        {"zone_revision": True},
        {"zone_id": None},
        {"basis": "USD"},
        {"tier_factor": "1.16"},
        {"extra": 1},
    ],
)
def test_frozen_factor_rejects_contradictory_provenance(change):
    with pytest.raises(ValueError):
        validate_factor_snapshot({**sample(), **change})


def test_full_precision_factor_is_used_before_final_cent_rounding():
    assert calculated_with_factor(
        Decimal("99999999.99"), Decimal("0.100000000059999999"), Decimal("1")
    ) == Decimal("10000000.00")
    assert calculated_with_factor(
        Decimal("2.50"), Decimal("1.234567890123456789"), Decimal("1.15")
    ) == Decimal("3.55")
