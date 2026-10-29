"""Physical route geometry and evidence-based metrics; no external providers."""

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
import pytest
from pydantic import ValidationError
from app.api.v1.routes import GPSPoint, RouteCreate, DeviationResolution
from app.models.route import RoutePoint
from app.services.route_geometry import (
    coordinate,
    distance_m,
    segment_distance_m,
    planned_coordinates,
    route_distance_m,
    utc_naive,
)
from app.services.route_service import RouteService
from tests.orm_contract import detailed_mapping_contract


def test_mapping_preserves_existing_postgresql_schema():
    before = json.loads(
        (Path(__file__).parent / "fixtures/orm_routes_baseline.json").read_text()
    )
    assert (
        detailed_mapping_contract(("routes", "route_points", "route_deviations"))
        == before
    )


@pytest.mark.parametrize(
    "a,b,expected",
    [
        ((0, 0), (0, 0), 0),
        ((0, 0), (0, 1), 111194.9266),
        ((0, 179.9), (0, -179.9), 22238.9853),
        ((90, 0), (-90, 0), math.pi * 6371000),
    ],
)
def test_metres_geodesic_and_antimeridian(a, b, expected):
    assert distance_m(a, b) == pytest.approx(expected, abs=0.01)
    assert distance_m(a, b) == pytest.approx(distance_m(b, a))


@pytest.mark.parametrize(
    "lat,lng",
    [
        (True, 0),
        (0, False),
        ("0", 0),
        (10**1000, 0),
        (float("nan"), 0),
        (0, float("inf")),
        (91, 0),
        (0, -181),
    ],
)
def test_invalid_coordinates_are_refused(lat, lng):
    with pytest.raises(ValueError):
        coordinate(lat, lng)


@pytest.mark.parametrize(
    "point,start,end,expected",
    [
        ((0, 0.5), (0, 0), (0, 1), 0),
        ((0.001, 0.5), (0, 0), (0, 1), 111.1949),
        ((0, -0.1), (0, 0), (0, 1), 11119.4927),
        ((0, 1.1), (0, 0), (0, 1), 11119.4927),
        ((0, 180), (0, 179), (0, -179), 0),
        ((0.01, 180), (0, 179), (0, -179), 1111.9493),
        ((1, 1), (0, 0), (0, 0), 157249.3813),
    ],
)
def test_distance_is_to_segment_not_vertices_or_infinite_line(
    point, start, end, expected
):
    assert segment_distance_m(point, start, end) == pytest.approx(expected, abs=0.01)


def test_polygon_interior_can_be_far_from_route_segments():
    path = [(0, 0), (0, 1), (1, 1), (1, 0)]
    assert route_distance_m((0.5, 0.5), path) > 55000


@pytest.mark.parametrize(
    "plan",
    [
        [],
        [{}],
        [{"latitude": 0, "longitude": 0}] * 2001,
        [{"lat": 0, "lng": 0}, {"lat": 1, "lng": 1}],
        [{"latitude": 0, "longitude": 0}, {"latitude": 0, "longitude": 180}],
    ],
)
def test_missing_invalid_or_antipodal_plans_are_not_analyzed(plan):
    with pytest.raises(ValueError):
        planned_coordinates(plan)


@pytest.mark.parametrize(
    "body",
    [
        {"lat": True, "lng": 0},
        {"lat": "0", "lng": 0},
        {"lat": 91, "lng": 0},
        {"lat": 0, "lng": 181},
        {"lat": 0, "lng": 0, "speed_kmh": -1},
        {"lat": 0, "lng": 0, "heading": 361},
        {"lat": 0, "lng": 0, "timestamp": "2026-01-01T00:00:00Z"},
        {"lat": 0, "lng": 0, "speed_kmh": True},
    ],
)
def test_gps_payload_cannot_smuggle_coordinates_speed_or_client_time(body):
    with pytest.raises(ValidationError):
        GPSPoint(**body)


def make_points(coords, step=60, speeds=None):
    start = datetime(2026, 10, 29)
    return [
        RoutePoint(
            id=uuid4(),
            latitude=lat,
            longitude=lng,
            timestamp=start + timedelta(seconds=i * step),
            speed=speeds[i] if speeds else None,
        )
        for i, (lat, lng) in enumerate(coords)
    ]


@pytest.mark.parametrize("count", [0, 1])
def test_empty_or_single_point_metrics_have_the_complete_contract(count):
    metrics = RouteService.metrics(make_points([(0, 0)] * count))
    assert metrics == {
        "total_distance_km": 0,
        "avg_speed_kmh": 0,
        "max_speed_kmh": 0,
        "total_time_minutes": 0,
        "points_count": count,
        "stops_count": 0,
    }


def test_metrics_use_elapsed_time_and_correct_metres_to_kilometres():
    metrics = RouteService.metrics(
        make_points([(0, 0), (0, 0.01)], step=120, speeds=[0, 40])
    )
    assert metrics["total_distance_km"] == pytest.approx(1.112)
    assert metrics["avg_speed_kmh"] == pytest.approx(33.36)
    assert metrics["max_speed_kmh"] == 40
    assert metrics["points_count"] == 2 and metrics["total_time_minutes"] == 2


def test_movement_over_time_is_not_a_stop():
    assert (
        RouteService.metrics(make_points([(0, i * 0.001) for i in range(20)]))[
            "stops_count"
        ]
        == 0
    )


@pytest.mark.parametrize(
    "step,count,stops", [(60, 6, 1), (60, 5, 0), (60, 20, 1), (121, 10, 0), (600, 2, 0)]
)
def test_stop_requires_stationary_evidence_without_sampling_gaps(step, count, stops):
    assert (
        RouteService.metrics(make_points([(0, 0)] * count, step))["stops_count"]
        == stops
    )


def test_two_separate_stops_are_counted_once_each():
    points = make_points([(0, 0)] * 7 + [(0, 0.01)] * 7)
    assert RouteService.metrics(points)["stops_count"] == 2


def test_clock_normalization_and_disordered_history():
    aware = datetime(2026, 10, 29, 8, tzinfo=timezone(timedelta(hours=-4)))
    assert utc_naive(aware) == datetime(2026, 10, 29, 12)
    points = make_points([(0, 0), (0, 0.01)])
    with pytest.raises(ValueError, match="orden"):
        RouteService.metrics(points[::-1])


@pytest.mark.parametrize("notes", ["", "   ", "x" * 2001])
def test_resolution_requires_bounded_human_notes(notes):
    with pytest.raises(ValidationError):
        DeviationResolution(notes=notes)


def test_real_mounted_routes_and_legacy_alias_use_one_router():
    from app.main import app
    from app.api.v1 import routes, routers_combined

    assert routes.router is routers_combined.routes_router
    paths = {r.path for r in app.routes}
    assert "/api/v1/routes/{rider_id}/track" in paths
    assert "/api/v1/routes/routes/{rider_id}/track" in paths
    assert "/api/v1/routes/{route_id}/metrics" in paths
