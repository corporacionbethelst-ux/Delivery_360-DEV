"""Executable contracts for repaired adapters and informational utilities."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from unittest.mock import AsyncMock
import json
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session
from pydantic import BaseModel
from app.core.exceptions import AppException
from app.core.security import decode_token
from app.crud.base import CRUDBase
from app.schemas.rider import RiderCreate, RiderUpdate
from app.services.rider_service import RiderService
from app.services.auth_service import AuthService
from app.utils.cost_calculator import (
    CostCalculator,
    calculate_delivery_cost,
    calculate_profit_margin,
)
from app.utils.data_exporter import export_to_json, create_data_package
from app.utils.sla_checker import calculate_sla_compliance_rate
from app.utils.validators import validate_future_date
from app.api.v1.deliveries import _serialize_delivery, _serialize_order_as_delivery
from app.models.order import Order, OrderStatus
from app.models.delivery import Delivery, DeliveryStatus
from app.models.rider import Rider, RiderStatus
from tests.orm_contract import detailed_mapping_contract


def test_runtime_model_annotations_preserve_base_physical_contract():
    expected = json.loads(
        (Path(__file__).parent / "fixtures/runtime_models_contract.json").read_text()
    )
    assert (
        detailed_mapping_contract(["riders", "zones", "platform_settings"]) == expected
    )


def test_nullable_rider_owner_is_serialized_without_dereferencing_none():
    rider = Rider(id=uuid4(), user_id=uuid4(), status=RiderStatus.ACTIVO)
    order = Order(
        id=uuid4(),
        status=OrderStatus.ASIGNADO,
        customer_name="Cliente",
        customer_phone="123",
        pickup_address="A",
        delivery_address="B",
    )
    delivery = Delivery(
        id=uuid4(), order_id=order.id, rider_id=rider.id, status=DeliveryStatus.INICIADA
    )
    for value in (
        _serialize_delivery(delivery, rider, None, order),
        _serialize_order_as_delivery(order, rider, None),
    ):
        assert value["rider"]["first_name"] == "Sin Nombre"
        assert value["rider"]["last_name"] == ""


def test_generic_crud_uses_real_primary_key_and_truthfully_returns_missing_rows():
    class Base(DeclarativeBase):
        pass

    class Record(Base):
        __tablename__ = "records"
        key: Mapped[str] = mapped_column(String, primary_key=True)
        value: Mapped[str] = mapped_column(String)

    class Input(BaseModel):
        key: str
        value: str

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            crud = CRUDBase[Record, Input, Input](Record)
            saved = crud.create(db, obj_in=Input(key="a", value="stored"))
            assert crud.get(db, "a").value == saved.value == "stored"
            assert crud.get_count(db) == 1
            assert crud.remove(db, id="missing") is None
    finally:
        engine.dispose()


def test_cost_adapter_supports_total_or_breakdown_and_preserves_profit_calculation():
    calculator = CostCalculator()
    assert calculator.calculate_profit_margin(100, 25)["profit"] == 75
    assert calculator.calculate_profit_margin(100, {"rider": 20, "fixed": 5})[
        "cost_breakdown"
    ] == {"rider": 20, "fixed": 5}


def test_cost_scenarios_use_configured_rates_and_accept_explicit_overrides_once():
    calculator = CostCalculator(
        base_rate=10, per_km_rate=2, per_minute_rate=0.5, platform_fee_percentage=0.1
    )
    expected = calculate_delivery_cost(
        5,
        base_rate=10,
        per_km_rate=2,
        time_minutes=20,
        per_minute_rate=0.5,
        platform_fee_percentage=0.1,
    )
    assert (
        calculator.simulate_pricing_scenarios(
            {"distance_km": 5, "time_minutes": 20}, [{"name": "same"}]
        )[0]["total_cost"]
        == expected["total"]
    )
    assert calculator.calculate_delivery_cost(5, 20, base_rate=12)["base_rate"] == 12
    with pytest.raises(ValueError):
        calculator.simulate_pricing_scenarios({}, [])


def test_operational_summary_requires_explicit_financial_inputs():
    calculator = CostCalculator()
    with pytest.raises(ValueError):
        calculator.get_operational_summary([])
    result = calculator.get_operational_summary(
        [{"distance_km": 5}], [2.5], {"fixed": 10}
    )
    assert result["grand_total"] == 17.5


@pytest.mark.parametrize(
    "value", [True, None, "12", float("nan"), float("inf"), -float("inf")]
)
def test_cost_previews_reject_non_numeric_or_nonfinite_values(value):
    with pytest.raises(ValueError):
        calculate_delivery_cost(value)
    with pytest.raises(ValueError):
        calculate_profit_margin(100, {"bad": value})


def test_export_shapes_and_counts_are_real_for_both_json_modes():
    data = [{"amount": 12.5}, {"amount": 0}]
    assert json.loads(export_to_json(data, include_metadata=False)) == data
    assert json.loads(export_to_json(data))["metadata"]["record_count"] == 2
    package = create_data_package(7, ["orders", "missing"], {"orders": data})
    assert package["data"] == {"orders": data}
    assert package["summary"] == {"total_records": 2, "by_type": {"orders": 2}}


@pytest.mark.parametrize(
    "delivery",
    [
        {},
        {"estimated_delivery": None},
        {"estimated_delivery": "unknown"},
        {"estimated_delivery": datetime.now(), "actual_delivery": "unknown"},
    ],
)
def test_sla_utility_cannot_invent_compliance_for_unknown_dates(delivery):
    with pytest.raises(ValueError):
        calculate_sla_compliance_rate([delivery])


def test_sla_utility_compares_known_instants_across_timezones():
    utc = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
    caracas = timezone(timedelta(hours=-4))
    assert (
        calculate_sla_compliance_rate(
            [
                {"estimated_delivery": utc, "actual_delivery": utc.astimezone(caracas)},
                {
                    "estimated_delivery": utc.replace(tzinfo=None),
                    "actual_delivery": utc + timedelta(minutes=1),
                },
            ]
        )
        == 50
    )


@pytest.mark.parametrize("date", ["bad", "2026-02-31", "", None])
def test_bad_future_dates_return_false(date):
    assert validate_future_date(date) is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fields",
    [
        {"status": "ACTIVO"},
        {"tier": "ORO"},
        {"is_online": True},
        {"vehicle_ownership_type": "EMPRESA", "assigned_vehicle_id": uuid4()},
        {"badges": ["fake"]},
        {"total_points": 20},
    ],
)
async def test_legacy_registration_cannot_self_approve_or_assign_rewards(fields):
    db = AsyncMock()
    uid = uuid4()
    with pytest.raises(AppException):
        await RiderService(db).create_rider(RiderCreate(user_id=uid, **fields), uid)
    assert db.mock_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fields",
    [
        {"status": "ACTIVO"},
        {"tier": "PLATINO"},
        {"is_online": True},
        {"vehicle_plate": "ABC123"},
    ],
)
async def test_generic_rider_edit_cannot_bypass_canonical_workflows(fields):
    db = AsyncMock()
    with pytest.raises(AppException) as error:
        await RiderService(db).update_rider(uuid4(), RiderUpdate(**fields))
    assert error.value.status_code == 409
    assert db.mock_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,args", [("increment_delivery_count", (True,)), ("update_rating", (5.0,))]
)
async def test_unsupported_metrics_fail_explicitly_without_shadow_attributes(
    method, args
):
    db = AsyncMock()
    with pytest.raises(AppException) as error:
        await getattr(RiderService(db), method)(uuid4(), *args)
    assert error.value.status_code == 501
    assert db.mock_calls == []


@pytest.mark.asyncio
async def test_auth_facade_cannot_exchange_access_token_for_refresh_tokens():
    db = AsyncMock()
    facade = AuthService()
    token = facade.create_access_token({"sub": str(uuid4()), "ver": 3})
    assert decode_token(token)["type"] == "access"
    with pytest.raises(HTTPException) as error:
        await facade.refresh_tokens(db, token)
    assert error.value.status_code == 401
    assert db.mock_calls == []
