"""Values representable by persisted JSON columns."""

from typing import TypeAlias, Union

JsonValue: TypeAlias = Union[
    None, bool, int, float, str, list["JsonValue"], dict[str, "JsonValue"]
]


def json_value(value: object) -> JsonValue:
    """Validate/copy untrusted JSON without treating arbitrary objects as JSON."""
    import math

    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON contiene un número no finito")
        return value
    if isinstance(value, list):
        return [json_value(item) for item in value]
    if isinstance(value, dict):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("Las claves JSON deben ser texto")
            result[key] = json_value(item)
        return result
    raise ValueError("Tipo de dato no permitido en JSON")
