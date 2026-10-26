"""Mounted reset route: digest storage, rejection policy and bcrypt boundaries."""

import secrets
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from tests.test_tracking_permissions import sockets  # noqa: F401
from tests.test_password_recovery_email import smtp  # noqa: F401
from app.core.security import verify_password
from app.models.user import User, utc_now_naive
from app.services.password_reset import reset_token_digest


@pytest.fixture
async def reset_account(sockets):
    client, sessions, ids, _ = sockets
    token = secrets.token_urlsafe(32)
    async with sessions() as db:
        await db.execute(
            update(User)
            .where(User.id == ids["manager"])
            .values(
                reset_token=reset_token_digest(token),
                reset_token_expires=utc_now_naive() + timedelta(hours=1),
            )
        )
        await db.commit()
    return client, sessions, ids, token


def reset(client, token, password="NewPassword123!"):
    return client.post(
        "/api/v1/auth/reset-password", json={"token": token, "new_password": password}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "condition",
    [
        "unknown",
        "expired",
        "inactive",
        "missing_expiry",
        "legacy_plaintext",
        "digest_replay",
        "ambiguous",
    ],
)
async def test_invalid_tokens_leave_all_accounts_unchanged(reset_account, condition):
    client, sessions, ids, token = reset_account
    supplied = token
    async with sessions() as db:
        user = await db.get(User, ids["manager"])
        if condition == "unknown":
            supplied = secrets.token_urlsafe(32)
        elif condition == "expired":
            user.reset_token_expires = utc_now_naive() - timedelta(seconds=1)
        elif condition == "inactive":
            user.is_active = False
        elif condition == "missing_expiry":
            user.reset_token_expires = None
        elif condition == "legacy_plaintext":
            user.reset_token = token
        elif condition == "digest_replay":
            supplied = user.reset_token
        elif condition == "ambiguous":
            await db.execute(
                update(User)
                .where(User.id == ids["operator"])
                .values(
                    reset_token=user.reset_token,
                    reset_token_expires=user.reset_token_expires,
                )
            )
        await db.commit()
        before = list(
            (
                await db.execute(
                    select(
                        User.id,
                        User.hashed_password,
                        User.reset_token,
                        User.reset_token_expires,
                    ).order_by(User.id)
                )
            ).all()
        )
    response = reset(client, supplied)
    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "Token inválido o expirado. Por favor solicita uno nuevo."
    )
    async with sessions() as db:
        after = list(
            (
                await db.execute(
                    select(
                        User.id,
                        User.hashed_password,
                        User.reset_token,
                        User.reset_token_expires,
                    ).order_by(User.id)
                )
            ).all()
        )
    assert after == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token",
    [
        "",
        "a" * 42,
        "a" * 44,
        "a" * 4096,
        "a" * 42 + "\n",
        "a" * 42 + "é",
        "a" * 42 + "$",
        "a" * 42 + " ",
    ],
)
async def test_malformed_secret_cannot_consume_valid_token(reset_account, token):
    client, sessions, ids, original = reset_account
    assert reset(client, token).status_code == 400
    async with sessions() as db:
        assert (await db.get(User, ids["manager"])).reset_token == reset_token_digest(
            original
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "password,accepted",
    [
        ("abcde", False),
        ("abcdef", True),
        ("a" * 72, True),
        ("a" * 73, False),
        ("é" * 36, True),
        ("é" * 37, False),
        ("abc\x00def", False),
        ("abc\ud800def", False),
    ],
)
async def test_password_boundaries_do_not_silently_truncate_or_burn_token(
    reset_account, password, accepted
):
    client, sessions, ids, token = reset_account
    response = reset(client, token, password)
    assert response.status_code == (200 if accepted else 400)
    async with sessions() as db:
        user = await db.get(User, ids["manager"])
        if accepted:
            assert verify_password(password, user.hashed_password)
            assert user.reset_token is None and user.reset_token_expires is None
        else:
            assert user.hashed_password == "unused"
            assert user.reset_token == reset_token_digest(token)


@pytest.mark.asyncio
async def test_new_request_replaces_digest_and_old_link_is_rejected(
    reset_account, smtp
):
    client, sessions, ids, old = reset_account
    from urllib.parse import parse_qs, urlsplit

    response = client.post(
        "/api/v1/auth/forgot-password", json={"email": "manager@example.com"}
    )
    assert response.status_code == 200
    plain = smtp.await_args.args[0].get_body(preferencelist=("plain",)).get_content()
    link = next(line for line in plain.splitlines() if line.startswith("https://"))
    new = parse_qs(urlsplit(link).query)["token"][0]
    assert new != old
    async with sessions() as db:
        assert (await db.get(User, ids["manager"])).reset_token == reset_token_digest(
            new
        )
    assert reset(client, old).status_code == 400
    assert reset(client, new).status_code == 200
    assert reset(client, new).status_code == 400


@pytest.mark.asyncio
async def test_success_logs_no_email_secret_or_password(reset_account, caplog):
    client, _, _, token = reset_account
    password = "PrivatePassword123!"
    assert reset(client, token, password).status_code == 200
    assert "Password reset completed" in caplog.text
    for secret in [token, reset_token_digest(token), password, "manager@example.com"]:
        assert secret not in caplog.text
