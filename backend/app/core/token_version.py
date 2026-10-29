"""Strict credential epochs; legacy JWTs belong only to epoch zero."""

from collections.abc import Mapping

MAX_TOKEN_VERSION = (1 << 63) - 1


def valid_token_version(value: object) -> bool:
    # bool is an int subclass, but must never authenticate as epoch 0/1.
    return type(value) is int and 0 <= value <= MAX_TOKEN_VERSION


def token_version_matches(payload: Mapping[str, object], stored: object) -> bool:
    version = payload.get("ver", 0)
    return (
        valid_token_version(stored)
        and valid_token_version(version)
        and version == stored
    )
