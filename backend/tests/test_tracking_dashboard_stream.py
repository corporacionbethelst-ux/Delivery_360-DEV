"""Mounted GPS producer -> both WS topics; writer returns its canonical recorded time."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from tests.test_tracking_permissions import sockets, clean  # noqa: F401
from app.main import app
from app.api.v1 import tracking
from app.core.security import create_access_token


@pytest.mark.asyncio
async def test_dashboard_and_rider_frames_use_the_same_recorded_timestamp(
    sockets, monkeypatch
):
    client, _, ids, manager = sockets
    recorded = datetime(2026, 10, 29, 1, 0, 0, 123456)
    record = AsyncMock(return_value=SimpleNamespace(recorded_at=recorded))

    async def service():
        return SimpleNamespace(record_location_update=record)

    monkeypatch.setitem(
        app.dependency_overrides, tracking._get_tracking_service, service
    )
    manager_token, owner_token = create_access_token(
        ids["manager"]
    ), create_access_token(ids["owner"])
    with client.websocket_connect(
        "/api/v1/tracking/ws/dashboard?token=" + manager_token
    ) as dashboard:
        assert dashboard.receive_json()["type"] == "CONNECTED"
        monkeypatch.setattr(client, "portal", dashboard.portal)
        with client.websocket_connect(
            f"/api/v1/tracking/ws/rider:{ids['rider']}?token={owner_token}"
        ) as rider:
            assert rider.receive_json()["type"] == "CONNECTED"
            response = client.post(
                "/api/v1/tracking/update-location",
                params={"rider_id": str(ids["rider"])},
                json={"lat": 0, "lng": 0},
                headers={"Authorization": "Bearer " + owner_token},
            )
            assert response.status_code == 200, response.text
            frames = [dashboard.receive_json(), rider.receive_json()]
            for frame in frames:
                assert frame["type"] == "POSITION_UPDATE"
                assert (
                    frame["payload"]["timestamp"]
                    == response.json()["recorded_at"]
                    == recorded.isoformat()
                )
                assert frame["payload"]["riderId"] == str(ids["rider"])
                assert frame["payload"]["lat"] == frame["payload"]["lng"] == 0
            record.assert_awaited_once()
    clean(manager)
