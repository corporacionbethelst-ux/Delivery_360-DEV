"""JWT migration: legacy wire compatibility and adversarial claims/algorithms."""

import base64
import hashlib
import hmac
import json
import time
from uuid import uuid4
import jwt
import pytest
from fastapi import FastAPI, Depends
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from app.core.config import Settings, settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    validate_token_strength,
)
from app.middleware.auth_middleware import require_auth, get_current_user_from_request


@pytest.fixture(autouse=True)
def signing_configuration(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", "synthetic-local-jwt-key-" + "x" * 64)
    monkeypatch.setattr(settings, "JWT_ALGORITHM", "HS256")


def claims(**changes):
    now = int(time.time())
    return {
        "sub": str(uuid4()),
        "iat": now - 1,
        "exp": now + 300,
        "jti": uuid4().hex,
        "type": "access",
        **changes,
    }


def independent_signature(payload, *, algorithm="HS256", key=None):
    """The wire format used by the old issuer; no dependency on the new encoder."""

    def encoded(value):
        return base64.urlsafe_b64encode(
            json.dumps(value, separators=(",", ":")).encode()
        ).rstrip(b"=")

    message = encoded({"alg": algorithm, "typ": "JWT"}) + b"." + encoded(payload)
    signature = hmac.new(
        (key or settings.SECRET_KEY).encode(), message, hashlib.sha256
    ).digest()
    return (message + b"." + base64.urlsafe_b64encode(signature).rstrip(b"=")).decode()


def test_legacy_jose_wire_claims_without_epoch_are_still_accepted():
    payload = claims()
    assert decode_token(independent_signature(payload), "access") == payload


@pytest.mark.parametrize("algorithm", ["HS256", "HS384", "HS512"])
@pytest.mark.parametrize(
    "factory,kind", [(create_access_token, "access"), (create_refresh_token, "refresh")]
)
def test_both_issuers_roundtrip_only_the_configured_algorithm(
    monkeypatch, algorithm, factory, kind
):
    monkeypatch.setattr(settings, "JWT_ALGORITHM", algorithm)
    subject = uuid4()
    token = factory(subject, token_version=7)
    payload = decode_token(token, kind)
    assert payload["sub"] == str(subject) and payload["ver"] == 7
    assert jwt.get_unverified_header(token)["alg"] == algorithm
    assert validate_token_strength(token)["valid"]
    assert decode_token(token, "refresh" if kind == "access" else "access") is None


@pytest.mark.parametrize("field", ["sub", "exp", "iat", "jti", "type"])
def test_missing_required_claims_never_authenticate(field):
    payload = claims()
    del payload[field]
    assert decode_token(independent_signature(payload)) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("exp", None),
        ("exp", True),
        ("exp", "4102444800"),
        ("exp", float("inf")),
        ("exp", 10**100),
        ("exp", []),
        ("iat", True),
        ("iat", "0"),
        ("iat", -1),
        ("iat", float("nan")),
        pytest.param("iat", lambda: int(time.time()) + 600, id="future-issued-at"),
        pytest.param("exp", lambda: int(time.time()) - 1, id="expired-at-execution"),
        ("sub", ""),
        ("sub", " "),
        ("sub", 1),
        ("sub", {}),
        ("jti", ""),
        ("jti", " "),
        ("jti", []),
        ("type", "unknown"),
        ("type", []),
        ("type", None),
        ("ver", True),
        ("ver", -1),
        ("ver", "0"),
        ("ver", None),
    ],
)
def test_signed_but_malformed_claims_fail_closed(field, value):
    # Collection can precede this case by more than ten minutes in a full CI run.
    # Resolve relative timestamps when issuing the token, never during collection.
    resolved = value() if callable(value) else value
    payload = claims(**{field: resolved})
    if field == "iat" and callable(value):
        # Keep the lifetime coherent so this specifically exercises future iat.
        payload["exp"] = resolved + 300
    assert decode_token(independent_signature(payload)) is None


@pytest.mark.parametrize(
    "token", [None, b"bytes", "", "x" * 8193, "a.b.c", "é.é.é", "not-a-token"]
)
def test_non_tokens_and_oversize_tokens_return_none(token):
    assert decode_token(token) is None


def test_wrong_signature_and_header_algorithm_cannot_choose_a_decoder():
    assert decode_token(independent_signature(claims(), key="other-test-key")) is None
    for algorithm in ("none", "RS256", "HS512"):
        assert (
            decode_token(independent_signature(claims(), algorithm=algorithm)) is None
        )


@pytest.mark.parametrize(
    "token_factory", [lambda: "malformed", lambda: create_refresh_token(uuid4())]
)
async def test_compatibility_middleware_rejects_bad_and_refresh_bearers(token_factory):
    app = FastAPI()

    @app.get("/protected", dependencies=[Depends(require_auth())])
    async def protected():
        return {"ok": True}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/protected", headers={"authorization": "Bearer " + token_factory()}
        )
    assert (
        response.status_code == 401 and response.headers["www-authenticate"] == "Bearer"
    )


async def test_compatibility_middleware_accepts_valid_access_and_optional_auth_is_closed():
    app = FastAPI()

    @app.get("/required", dependencies=[Depends(require_auth())])
    async def required():
        return {"ok": True}

    @app.get("/optional")
    async def optional(payload=Depends(get_current_user_from_request)):
        return {"authenticated": payload is not None}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/required")).status_code == 401
        assert (
            await client.get(
                "/required",
                headers={"authorization": "Bearer " + create_access_token(uuid4())},
            )
        ).status_code == 200
        for token in ("bad", create_refresh_token(uuid4())):
            assert (
                await client.get(
                    "/optional", headers={"authorization": "Bearer " + token}
                )
            ).json() == {"authenticated": False}


@pytest.mark.parametrize("algorithm", ["none", "RS256", "ES256", "hs256", ""])
def test_settings_reject_unsupported_jwt_algorithms_without_echoing_inputs(algorithm):
    secret = "sensitive-test-only-value-" + "s" * 64
    with pytest.raises(ValidationError) as error:
        Settings(SECRET_KEY=secret, JWT_ALGORITHM=algorithm, _env_file=None)
    assert secret not in str(error.value)


@pytest.mark.parametrize(
    "secret",
    [
        "short",
        " " * 40,
        "x" * 32 + " ",
        "CHANGE-THIS-SECRET-KEY-IN-PRODUCTION-MIN-32-CHARS-RANDOM!",
    ],
)
def test_production_settings_reject_weak_or_default_secrets_without_leaking_them(
    secret,
):
    with pytest.raises(ValidationError) as error:
        Settings(SECRET_KEY=secret, ENVIRONMENT="production", _env_file=None)
    assert "input_value" not in str(error.value)


@pytest.mark.parametrize(
    "key,value", [("ACCESS_TOKEN_EXPIRE_MINUTES", 0), ("REFRESH_TOKEN_EXPIRE_DAYS", -1)]
)
def test_non_positive_lifetimes_fail_at_configuration(key, value):
    with pytest.raises(ValidationError):
        Settings(SECRET_KEY="local-test-only", _env_file=None, **{key: value})


@pytest.mark.parametrize(
    "algorithm,length", [("HS256", 32), ("HS384", 48), ("HS512", 64)]
)
def test_production_hmac_configuration_accepts_the_correct_minimum(algorithm, length):
    value = Settings(
        SECRET_KEY="x" * length,
        JWT_ALGORITHM=algorithm,
        ENVIRONMENT="production",
        _env_file=None,
    )
    assert value.JWT_ALGORITHM == algorithm
    if length > 32:
        with pytest.raises(ValidationError):
            Settings(
                SECRET_KEY="x" * (length - 1),
                JWT_ALGORITHM=algorithm,
                ENVIRONMENT="production",
                _env_file=None,
            )
