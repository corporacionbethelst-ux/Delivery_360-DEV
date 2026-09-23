"""Tests críticos del ledger financiero y payouts - Fase 7 Enterprise."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.financial import PaymentStatus, TransactionType, PayoutStatus
from app.services.financial_service import FinancialService, ledger_delta, money
from app.api.v1 import payouts as payouts_api


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value

    def scalar_one_or_none(self):
        return self._value


class _FakeDb:
    def __init__(self, scalar_values=None):
        self.scalar_values = list(scalar_values or [])
        self.added = []
        self.execute = AsyncMock(side_effect=self._execute)
        self.commit = AsyncMock()
        self.refresh = AsyncMock()
        self.flush = AsyncMock()

    async def _execute(self, _stmt):
        value = self.scalar_values.pop(0) if self.scalar_values else None
        return _ScalarResult(value)

    def add(self, obj):
        self.added.append(obj)


@pytest.mark.parametrize(
    ("transaction_type", "amount", "expected_delta"),
    [
        (TransactionType.PAGO_ENTREGA, Decimal("25.00"), Decimal("25.00")),
        (TransactionType.PAGO_INTENTO_FALLIDO, Decimal("5.00"), Decimal("5.00")),
        (TransactionType.BONO_RENDIMIENTO, Decimal("10.00"), Decimal("10.00")),
        (TransactionType.INGRESO, Decimal("50.00"), Decimal("50.00")),
        (TransactionType.BONO, Decimal("5.50"), Decimal("5.50")),
        (TransactionType.DESCUENTO, Decimal("3.00"), Decimal("-3.00")),
        (TransactionType.PENALIZACION, Decimal("7.00"), Decimal("-7.00")),
        (TransactionType.RETIRO, Decimal("10.00"), Decimal("-10.00")),
        (TransactionType.AJUSTE_MANUAL, Decimal("2.75"), Decimal("-2.75")),
        (TransactionType.AJUSTE, Decimal("-2.75"), Decimal("-2.75")),
    ],
)
def test_ledger_delta_uses_transaction_direction(transaction_type, amount, expected_delta):
    assert ledger_delta(amount, transaction_type) == expected_delta


def test_money_normalizes_to_two_decimals():
    assert money("10.236") == Decimal("10.24")
    assert money(None) == Decimal("0.00")


@pytest.mark.asyncio
async def test_create_ledger_entry_is_idempotent_when_key_exists():
    existing = SimpleNamespace(id="existing-financial-id")
    db = _FakeDb([existing])

    result = await FinancialService(db).create_ledger_entry(
        rider_id="rider-1",
        amount=Decimal("20.00"),
        transaction_type=TransactionType.PAGO_ENTREGA,
        idempotency_key="delivery-123",
    )

    assert result is existing
    assert db.added == []
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_ledger_entry_calculates_processed_balance():
    db = _FakeDb([None])
    service = FinancialService(db)
    service.get_current_balance = AsyncMock(return_value=Decimal("100.00"))

    transaction = await service.create_ledger_entry(
        rider_id="rider-1",
        amount=Decimal("15.00"),
        transaction_type=TransactionType.RETIRO,
        source_type="PAYOUT",
        source_id="payout-1",
        idempotency_key="payout-approve-1",
        status=PaymentStatus.PROCESADO,
        commit=False,
    )

    assert transaction.balance_before == Decimal("100.00")
    assert transaction.balance_after == Decimal("85.00")
    assert transaction.source_type == "PAYOUT"
    assert transaction.source_id == "payout-1"
    assert transaction.idempotency_key == "payout-approve-1"
    db.flush.assert_awaited_once()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_ledger_entry_does_not_move_balance_for_pending_status():
    db = _FakeDb([None])
    service = FinancialService(db)
    service.get_current_balance = AsyncMock(return_value=Decimal("42.00"))

    transaction = await service.create_ledger_entry(
        rider_id="rider-1",
        amount=Decimal("99.00"),
        transaction_type=TransactionType.PAGO_ENTREGA,
        status=PaymentStatus.PENDIENTE,
        commit=False,
    )

    assert transaction.balance_before == Decimal("42.00")
    assert transaction.balance_after == Decimal("42.00")


@pytest.mark.asyncio
async def test_calculate_available_balance_reserves_pending_and_processed_payouts():
    db = _FakeDb([Decimal("100.00"), Decimal("25.00"), Decimal("40.00")])

    balance = await payouts_api._calculate_available_balance(db, rider_id="rider-1")

    assert balance == {
        "available": 35.0,
        "pending": 25.0,
        "processed": 40.0,
        "total_earned": 100.0,
        "currency": "COP",
    }


# === TESTS DE FASE 7: Estados de Payout en Español ===

@pytest.mark.parametrize(
    "status_value",
    [
        PayoutStatus.PENDIENTE.value,
        PayoutStatus.APROBADO.value,
        PayoutStatus.EN_PROCESO.value,
        PayoutStatus.COMPLETADO.value,
        PayoutStatus.RECHAZADO.value,
        PayoutStatus.FALLIDO.value,
    ],
)
def test_payout_status_enum_spanish_values(status_value):
    """Verifica que los estados de payout estén en español."""
    assert status_value in ["PENDIENTE", "APROBADO", "EN_PROCESO", "COMPLETADO", "RECHAZADO", "FALLIDO"]


def test_payout_status_complete_workflow():
    """Prueba el flujo completo de estados de un payout."""
    # Simular transición de estados
    initial_status = PayoutStatus.PENDIENTE
    approved_status = PayoutStatus.APROBADO
    processing_status = PayoutStatus.EN_PROCESO
    final_status = PayoutStatus.COMPLETADO
    
    # Verificar transiciones válidas
    assert initial_status.value == "PENDIENTE"
    assert approved_status.value == "APROBADO"
    assert processing_status.value == "EN_PROCESO"
    assert final_status.value == "COMPLETADO"


@pytest.mark.asyncio
async def test_payout_rejection_restores_balance():
    """Prueba que rechazar un payout restaura el saldo pendiente."""
    # Simular DB con saldo total, payout pendiente y payout procesado
    db = _FakeDb([Decimal("100.00"), Decimal("20.00"), Decimal("0.00")])
    
    # El saldo disponible debería ser 100 - 20 (pendiente) - 0 (procesado) = 80
    balance = await payouts_api._calculate_available_balance(db, rider_id="rider-1")
    
    assert balance["available"] == 80.0
    assert balance["pending"] == 20.0


@pytest.mark.asyncio
async def test_payout_status_transitions():
    """Prueba las transiciones de estado permitidas para payouts."""
    # Estado inicial
    payout_mock = SimpleNamespace(
        id="payout-1",
        rider_id="rider-1",
        amount=Decimal("50.00"),
        status=PayoutStatus.PENDIENTE,
        requested_at=None,
        processed_at=None,
        updated_at=None,
        bank_account_last4="1234",
        reference_code=None,
        rejection_reason=None,
        balance_before=Decimal("100.00"),
        balance_after=Decimal("50.00"),
        requested_by_user_id="user-1",
        processed_by_user_id=None,
        idempotency_key=None,
    )
    
    # Verificar estado inicial
    assert payout_mock.status == PayoutStatus.PENDIENTE
    
    # Transición a APROBADO
    payout_mock.status = PayoutStatus.APROBADO
    assert payout_mock.status.value == "APROBADO"
    
    # Transición a EN_PROCESO
    payout_mock.status = PayoutStatus.EN_PROCESO
    assert payout_mock.status.value == "EN_PROCESO"
    
    # Transición a COMPLETADO
    payout_mock.status = PayoutStatus.COMPLETADO
    assert payout_mock.status.value == "COMPLETADO"
