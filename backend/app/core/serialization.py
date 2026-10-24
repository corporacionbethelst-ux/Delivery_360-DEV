"""Small explicit contracts for nullable enum values in API representations."""

from enum import Enum


def optional_enum_value(value: Enum | str | None) -> str | None:
    if isinstance(value, Enum):
        return str(value.value)
    return value
