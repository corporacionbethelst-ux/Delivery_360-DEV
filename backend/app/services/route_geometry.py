"""Finite GPS coordinates and distances to great-circle route segments, in metres."""

import math
from collections.abc import Sequence
from datetime import datetime, timezone

EARTH_RADIUS_M = 6_371_000.0
Coordinate = tuple[float, float]


def finite_number(value: object, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} debe ser numérico")
    # Compare before float conversion: a valid JSON integer can exceed float range.
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} fuera de rango")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f"{name} fuera de rango")
    return result


def coordinate(latitude: object, longitude: object) -> Coordinate:
    return (
        finite_number(latitude, "latitude", -90, 90),
        finite_number(longitude, "longitude", -180, 180),
    )


def utc_naive(value: datetime) -> datetime:
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def distance_m(a: Coordinate, b: Coordinate) -> float:
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlat, dlon = lat2 - lat1, math.radians(b[1] - a[1])
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1.0, max(0.0, h))))


def _bearing(a: Coordinate, b: Coordinate) -> float:
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dl = math.radians(b[1] - a[1])
    return math.atan2(
        math.sin(dl) * math.cos(lat2),
        math.cos(lat1) * math.sin(lat2)
        - math.sin(lat1) * math.cos(lat2) * math.cos(dl),
    )


def segment_distance_m(point: Coordinate, start: Coordinate, end: Coordinate) -> float:
    """Distance to the shorter great-circle arc, clamped at its endpoints.

    Antipodal endpoints have no unique shorter arc and are refused.
    """
    length = distance_m(start, end) / EARTH_RADIUS_M
    if length < 1e-12:
        return distance_m(point, start)
    if math.pi - length < 1e-8:
        raise ValueError("Segmento antipodal ambiguo")
    delta = distance_m(start, point) / EARTH_RADIUS_M
    angle = _bearing(start, point) - _bearing(start, end)
    along = math.atan2(math.sin(delta) * math.cos(angle), math.cos(delta))
    if along < 0 or along > length:
        return min(distance_m(point, start), distance_m(point, end))
    cross = math.asin(min(1.0, max(-1.0, math.sin(delta) * math.sin(angle))))
    return abs(cross) * EARTH_RADIUS_M


def planned_coordinates(value: object) -> list[Coordinate]:
    """Canonical plan: two to 2000 {latitude, longitude} waypoints."""
    if not isinstance(value, list) or not 2 <= len(value) <= 2000:
        raise ValueError("La ruta requiere entre 2 y 2000 puntos")
    result = []
    for point in value:
        if not isinstance(point, dict):
            raise ValueError("Punto de ruta inválido")
        result.append(coordinate(point.get("latitude"), point.get("longitude")))
    for start, end in zip(result, result[1:]):
        segment_distance_m(start, start, end)
    return result


def route_distance_m(point: Coordinate, path: Sequence[Coordinate]) -> float:
    if len(path) < 2:
        raise ValueError("La ruta necesita segmentos")
    return min(segment_distance_m(point, a, b) for a, b in zip(path, path[1:]))
