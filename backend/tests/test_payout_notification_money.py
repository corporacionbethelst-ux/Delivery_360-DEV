from decimal import Decimal
from types import SimpleNamespace
import pytest
from app.services.notification_hooks import payout_context


def payout(amount, currency="USD"):
    return SimpleNamespace(
        id="test",
        amount=amount,
        currency_code=currency,
        status="PENDIENTE",
        bank_account_last4="1234",
    )


@pytest.mark.parametrize(
    "amount,cents",
    [("0.29", 29), ("1.15", 115), (Decimal("99999999.99"), 9999999999), (150.0, 15000)],
)
def test_notification_money_preserves_exact_cents(amount, cents):
    result = payout_context(payout(amount))
    assert result["amount_cents"] == cents
    assert result["amount_usd"] == f"{Decimal(str(amount)):.2f}"
    assert not result["monetary_review"]
    assert result["amount_label"] == result["amount_usd"] + " USD"


@pytest.mark.parametrize(
    "amount", [None, True, "bad", "NaN", "Infinity", "-1", "0", "1.001", "100000000"]
)
def test_invalid_notification_money_never_fabricates_zero(amount):
    with pytest.raises(ValueError, match="Invalid payout"):
        payout_context(payout(amount))


def test_legacy_currency_is_not_relabelled_and_extra_cannot_replace_money():
    result = payout_context(
        payout("1.15", None), {"amount_cents": 0, "currency_code": "USD", "extra": "ok"}
    )
    assert result["amount_cents"] == 115 and result["currency_code"] is None
    assert (
        result["amount_usd"] is None
        and result["monetary_review"]
        and result["extra"] == "ok"
    )
