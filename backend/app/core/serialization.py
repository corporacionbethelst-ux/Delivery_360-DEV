"""Small explicit contracts for nullable enum values and stored UTC clocks."""

from enum import Enum
from datetime import datetime, timezone


def optional_enum_value(value: Enum | str | None) -> str | None:
    if isinstance(value, Enum):
        return str(value.value)
    return value


def utc_isoformat(value: datetime | None) -> str | None:
    """Expose known UTC-naive storage clocks with an explicit UTC offset."""
    if value is None:
        return None
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return aware.astimezone(timezone.utc).isoformat()
