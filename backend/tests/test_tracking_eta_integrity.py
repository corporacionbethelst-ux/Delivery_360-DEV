"""ETA must use a real destination, preserve zero coordinates and free the event loop."""

import asyncio
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
import pytest
from app.core.config import settings
from app.services.tracking_service import TrackingService, haversine_km
from tests.orm_contract import detailed_mapping_contract


def test_tracking_mappings_keep_native_ddl_defaults_and_indexes():
    before = json.loads(
        (Path(__file__).parent / "fixtures/orm_tracking_baseline.json").read_text()
    )
    assert (
        detailed_mapping_contract(("rider_live_locations", "delivery_route_snapshots"))
        == before
    )


def service_for(latitude, longitude):
    delivery = SimpleNamespace(
        order=SimpleNamespace(delivery_latitude=latitude, delivery_longitude=longitude),
        current_latitude=40,
        current_longitude=40,
    )
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(scalar_one_or_none=lambda: delivery)
        )
    )
    return TrackingService(db)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "destination,origin",
    [((0, 0), (0, 0.01)), ((0, 10), (0.01, 10)), ((10, 0), (10, 0.01))],
)
async def test_zero_destination_coordinates_are_not_replaced_by_current_position(
    monkeypatch, destination, origin
):
    monkeypatch.setattr(settings, "GOOGLE_MAPS_API_KEY", None)
    monkeypatch.setattr(settings, "AVG_RIDER_SPEED_KMH", 18)
    eta = await service_for(*destination).calculate_eta(uuid4(), *origin)
    assert eta == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "destination", [(None, 0), (0, None), (float("nan"), 0), (91, 0)]
)
async def test_invalid_destination_never_becomes_an_eta_to_the_current_rider(
    monkeypatch, destination
):
    monkeypatch.setattr(settings, "GOOGLE_MAPS_API_KEY", None)
    with pytest.raises(ValueError):
        await service_for(*destination).calculate_eta(uuid4(), 0, 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("speed", [0, -1, float("nan"), float("inf"), 301])
async def test_invalid_configured_speed_cannot_produce_a_false_eta(monkeypatch, speed):
    monkeypatch.setattr(settings, "AVG_RIDER_SPEED_KMH", speed)
    with pytest.raises(ValueError):
        await service_for(0, 0.01).calculate_eta(uuid4(), 0, 0)


@pytest.mark.asyncio
async def test_optional_provider_error_preserves_local_eta_and_redacts_error(
    monkeypatch, caplog
):
    monkeypatch.setattr(settings, "GOOGLE_MAPS_API_KEY", "test-key-never-sent")
    service = service_for(0, 0.01)
    service._google_distance_matrix_eta = AsyncMock(
        side_effect=RuntimeError("sensitive-provider-url")
    )
    assert await service.calculate_eta(uuid4(), 0, 0) == 4
    assert "sensitive-provider-url" not in caplog.text


@pytest.mark.asyncio
async def test_google_sdk_runs_off_event_loop_with_transport_timeouts(monkeypatch):
    loop_thread = threading.get_ident()
    observed = []

    def request(**kwargs):
        observed.append(threading.get_ident())
        return {
            "rows": [
                {"elements": [{"status": "OK", "duration_in_traffic": {"value": 121}}]}
            ]
        }

    factory = MagicMock(return_value=SimpleNamespace(distance_matrix=request))
    monkeypatch.setitem(sys.modules, "googlemaps", SimpleNamespace(Client=factory))
    value = await TrackingService(None)._google_distance_matrix_eta(
        "test-key", 0, 0, 0, 0.01
    )
    assert value == 3 and observed[0] != loop_thread
    assert factory.call_args.kwargs == {
        "key": "test-key",
        "timeout": 5,
        "retry_timeout": 5,
        "retry_over_query_limit": False,
    }


@pytest.mark.parametrize(
    "response",
    [
        None,
        {},
        {"rows": []},
        {"rows": [None]},
        {"rows": [{"elements": []}]},
        {"rows": [{"elements": [{"status": "ZERO_RESULTS"}]}]},
        {"rows": [{"elements": [{"status": "OK", "duration": {"value": -1}}]}]},
        {"rows": [{"elements": [{"status": "OK", "duration": {"value": True}}]}]},
        {"rows": [{"elements": [{"status": "OK", "duration": {"value": "120"}}]}]},
    ],
)
def test_invalid_provider_response_has_no_fabricated_duration(monkeypatch, response):
    factory = MagicMock(
        return_value=SimpleNamespace(distance_matrix=lambda **kwargs: response)
    )
    monkeypatch.setitem(sys.modules, "googlemaps", SimpleNamespace(Client=factory))
    assert TrackingService._distance_matrix_eta_sync("test-key", 0, 0, 0, 0.01) is None


def test_haversine_antipodes_remain_finite():
    assert haversine_km(90, 0, -90, 0) == pytest.approx(20015.0868)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "destination", [(0, None), (None, 0), (91, 0), (0, float("nan"))]
)
async def test_live_snapshot_leaves_legacy_invalid_destination_distance_unknown(
    monkeypatch, destination
):
    from app.api.v1 import tracking

    delivery = SimpleNamespace(
        id=uuid4(),
        order=SimpleNamespace(
            delivery_latitude=destination[0], delivery_longitude=destination[1]
        ),
        rider=SimpleNamespace(
            id=uuid4(), last_lat=0, last_lng=0, last_location_at=None, user=None
        ),
    )
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(scalar_one_or_none=lambda: delivery)
        )
    )
    monkeypatch.setattr(tracking, "resolve_tracking_channel", AsyncMock())
    service = SimpleNamespace(
        calculate_eta=AsyncMock(side_effect=ValueError("missing destination"))
    )
    result = await tracking.get_live_tracking(uuid4(), service, db, SimpleNamespace())
    assert result["distance_km"] is None and result["eta_minutes"] is None
    assert result["destination"] == {"lat": None, "lng": None}
    json.dumps(result, default=str, allow_nan=False)
