"""OTP issuance invariants independent of the recipient transport."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.delivery_rules import initialize_delivery_otp, validate_delivery_otp
from app.models.delivery import DeliveryStatus, ProofType


def delivery():
    return SimpleNamespace(
        status=DeliveryStatus.INICIADA, proof_type=ProofType.OTP, proof_otp=None
    )


@pytest.mark.parametrize(
    "number,expected", [(0, "000000"), (1234, "001234"), (999999, "999999")]
)
def test_generated_code_preserves_six_digits_and_validates(
    monkeypatch, number, expected
):
    record = delivery()
    monkeypatch.setattr(
        "app.core.delivery_rules.secrets.randbelow",
        lambda bound: (
            number if bound == 1_000_000 else pytest.fail("Wrong entropy range")
        ),
    )
    assert initialize_delivery_otp(record) is True
    assert record.proof_otp == expected
    validate_delivery_otp(record, expected)
    with pytest.raises(HTTPException):
        validate_delivery_otp(record, "wrong")


def test_retry_preserves_existing_code_without_random_generation(monkeypatch):
    record = delivery()
    record.proof_otp = "001234"
    monkeypatch.setattr(
        "app.core.delivery_rules.secrets.randbelow",
        lambda _: pytest.fail("Existing code must not rotate"),
    )
    assert initialize_delivery_otp(record) is False
    assert record.proof_otp == "001234"


@pytest.mark.parametrize(
    "proof_type", [None, ProofType.NINGUNO, ProofType.FOTO, ProofType.FIRMA]
)
def test_other_proof_types_are_not_changed(proof_type):
    record = delivery()
    record.proof_type = proof_type
    with pytest.raises(HTTPException) as error:
        initialize_delivery_otp(record)
    assert error.value.status_code == 409
    assert record.proof_otp is None
    assert record.proof_type == proof_type


@pytest.mark.parametrize(
    "status",
    [DeliveryStatus.COMPLETADA, DeliveryStatus.FALLIDA, DeliveryStatus.CANCELADA],
)
def test_terminal_delivery_cannot_issue_code(status):
    record = delivery()
    record.status = status
    with pytest.raises(HTTPException) as error:
        initialize_delivery_otp(record)
    assert error.value.status_code == 400
    assert record.proof_otp is None
