"""Validation shared by delivery completion paths, before any side effects."""

import secrets

from fastapi import HTTPException

from app.models.delivery import Delivery, DeliveryStatus, ProofType


def validate_delivery_otp(delivery: Delivery, supplied_otp: str | None) -> None:
    expected = delivery.proof_otp
    required = delivery.proof_type == ProofType.OTP or bool(expected)
    if not required:
        return
    if (
        not expected
        or not supplied_otp
        or not secrets.compare_digest(
            str(expected).encode("utf-8"), str(supplied_otp).encode("utf-8")
        )
    ):
        raise HTTPException(status_code=400, detail="Código OTP requerido o incorrecto")


def ensure_delivery_not_terminal(delivery: Delivery) -> None:
    if delivery.status in (
        DeliveryStatus.COMPLETADA,
        DeliveryStatus.FALLIDA,
        DeliveryStatus.CANCELADA,
    ):
        raise HTTPException(status_code=400, detail="La entrega ya está finalizada")
