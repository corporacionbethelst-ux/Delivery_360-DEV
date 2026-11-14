"""Decimal boundaries, provenance inputs and the Caracas day boundary."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from app.api.v1.currency import BcvRateInput, UsdVesQuoteInput
from app.services import bcv_currency as service, fx_service


def rate_input(**changes):
    data = dict(
        request_key=uuid4(),
        previous_rate_id=None,
        valid_on="2026-11-14",
        reference_date="2026-11-14",
        ves_per_usd="40.12345678",
        note="Referencia sintética de prueba",
        confirmed_bcv=True,
    )
    return {**data, **changes}


@pytest.mark.parametrize(
    "value",
    [
        0,
        1.2,
        True,
        "0",
        "-1",
        "NaN",
        "Infinity",
        "1e2",
        "1,23",
        "01.2",
        "1000000000",
        "1.123456789",
    ],
)
def test_rates_require_exact_positive_bounded_decimal_strings(value):
    with pytest.raises(ValidationError):
        BcvRateInput(**rate_input(ves_per_usd=value))


@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_manual_confirmation_is_a_real_boolean(value):
    with pytest.raises(ValidationError):
        BcvRateInput(**rate_input(confirmed_bcv=value))


@pytest.mark.parametrize(
    "value", [1.23, True, "NaN", "-1", "1.001", "1000000000000", "1e2"]
)
def test_quote_amounts_cannot_lose_precision_before_conversion(value):
    with pytest.raises(ValidationError):
        UsdVesQuoteInput(
            request_key=uuid4(), rate_id=uuid4(), amount_usd=value, reference="Prueba"
        )


@pytest.mark.parametrize(
    "amount,rate,expected",
    [
        ("0.01", "1.50000000", "0.02"),
        ("12.34", "40.12345678", "495.12"),
        ("0", "1", "0.00"),
        ("999999999999.99", "999999999.99999999", "999999999999989990000.00"),
    ],
)
def test_exact_half_up_conversion_including_values_beyond_float_precision(
    amount, rate, expected
):
    assert service.converted_amount(Decimal(amount), Decimal(rate)) == Decimal(expected)


@pytest.mark.parametrize(
    "instant,day",
    [("2026-11-14T03:59:59", "2026-11-13"), ("2026-11-14T04:00:00", "2026-11-14")],
)
def test_day_uses_caracas_not_utc_or_browser_clock(monkeypatch, instant, day):
    monkeypatch.setattr(
        service,
        "utc_now",
        lambda: datetime.fromisoformat(instant).replace(tzinfo=timezone.utc),
    )
    assert service.current_day().isoformat() == day


@pytest.mark.parametrize("operation", ["convert", "rate"])
@pytest.mark.parametrize("pair", [("USD", "VES"), ("VES", "USD"), ("VES", "VES")])
async def test_ves_never_uses_demo_fallback_or_one_to_one(monkeypatch, operation, pair):
    async def forbidden(*args, **kwargs):
        raise AssertionError("VES must not consult a demo or generic FX provider")

    monkeypatch.setattr(fx_service, "get_rates", forbidden)
    with pytest.raises(ValueError, match="BCV"):
        if operation == "convert":
            await fx_service.convert(100, *pair)
        else:
            await fx_service.get_exchange_rate(*pair)


async def test_unknown_currency_is_not_silently_treated_as_usd(monkeypatch):
    async def rates(*args, **kwargs):
        return {"USD": 1, "COP": 3900}

    monkeypatch.setattr(fx_service, "get_rates", rates)
    with pytest.raises(ValueError):
        await fx_service.convert(100, "UNKNOWN", "USD")
    with pytest.raises(ValueError):
        await fx_service.get_exchange_rate("USD", "UNKNOWN")


async def test_legacy_converter_uses_half_up_for_integer_cents(monkeypatch):
    async def rates(*args, **kwargs):
        return {"USD": 1, "COP": 2.5}

    monkeypatch.setattr(fx_service, "get_rates", rates)
    assert await fx_service.convert(1, "USD", "COP") == 3
