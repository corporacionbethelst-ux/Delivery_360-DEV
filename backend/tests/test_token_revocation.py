"""Real HTTP contracts and strict JWT credential epochs."""

import secrets
from datetime import timedelta
from uuid import uuid4
import pytest
from fastapi import HTTPException, FastAPI
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy import select
from tests.test_auth_contracts import auth_http  # noqa: F401
from app.api.v1 import auth, users
from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_active_user,
    hash_password,
    verify_password,
)
from app.core.token_version import MAX_TOKEN_VERSION, token_version_matches
from app.crud.user import user as user_crud
from app.models.user import User, UserRole, utc_now_naive
from app.services.password_reset import reset_token_digest
from app.services.token_revocation import revoke_user_tokens
from app.services.user_revision import user_revision

BAD = [True, False, -1, 1.5, "0", None, [], {}, MAX_TOKEN_VERSION + 1]


def sign(payload):
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def legacy(token):
    p = decode_token(token)
    p.pop("ver")
    return sign(p)


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize("value", BAD)
@pytest.mark.parametrize("factory", [create_access_token, create_refresh_token])
def test_issuers_reject_invalid_versions(value, factory):
    with pytest.raises(ValueError):
        factory("account", token_version=value)


@pytest.mark.parametrize("value", BAD)
def test_signed_invalid_versions_fail_closed(value):
    p = decode_token(create_access_token("account"))
    p["ver"] = value
    assert decode_token(sign(p)) is None
    assert not token_version_matches(p, 0)


@pytest.mark.parametrize("version", [0, 1, 151, MAX_TOKEN_VERSION])
def test_both_issuers_preserve_epoch_and_unique_ids(version):
    a = decode_token(create_access_token("account", token_version=version))
    r = decode_token(create_refresh_token("account", token_version=version))
    assert a["ver"] == r["ver"] == version
    assert a["type"] == "access" and r["type"] == "refresh"
    assert a["jti"] != r["jti"]
    assert token_version_matches(a, version)
    assert not token_version_matches(a, version + 1)


async def retired(client, access, refresh):
    r = await client.get("/api/v1/auth/me", headers=bearer(access))
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r.status_code == 401, r.text


@pytest.mark.asyncio
async def test_logout_retires_all_pairs_but_old_request_cannot_retire_new_login(
    auth_http, db_session, test_user
):
    pairs = [
        (create_access_token(test_user.id), create_refresh_token(test_user.id))
        for _ in range(2)
    ]
    r = await auth_http.post("/api/v1/auth/logout", headers=bearer(pairs[0][0]))
    assert r.status_code == 200 and r.json()["scope"] == "all_sessions"
    for a, refresh in pairs:
        await retired(auth_http, a, refresh)
    r = await auth_http.post(
        "/api/v1/auth/login",
        data={"username": test_user.email, "password": "testpassword123"},
    )
    assert r.status_code == 200, r.text
    new = r.json()
    assert (
        decode_token(new["access_token"])["ver"]
        == decode_token(new["refresh_token"])["ver"]
        == 1
    )
    assert (
        await auth_http.post("/api/v1/auth/logout", headers=bearer(pairs[0][0]))
    ).status_code == 401
    assert (
        await auth_http.get("/api/v1/auth/me", headers=bearer(new["access_token"]))
    ).status_code == 200
    assert test_user.token_version == 1


@pytest.mark.asyncio
async def test_legacy_tokens_are_epoch_zero_only(auth_http, test_user):
    a, r = legacy(create_access_token(test_user.id)), legacy(
        create_refresh_token(test_user.id)
    )
    assert (
        await auth_http.get("/api/v1/auth/me", headers=bearer(a))
    ).status_code == 200
    fresh = await auth_http.post("/api/v1/auth/refresh", json={"refresh_token": r})
    assert fresh.status_code == 200
    assert decode_token(fresh.json()["access_token"])["ver"] == 0
    assert (
        await auth_http.post("/api/v1/auth/logout", headers=bearer(a))
    ).status_code == 200
    await retired(auth_http, a, r)
    await retired(
        auth_http, fresh.json()["access_token"], fresh.json()["refresh_token"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", ["missing", "invalid", "refresh", "expired", "bad_subject", "unknown"]
)
async def test_logout_requires_existing_account_access_token(
    auth_http, test_user, kind
):
    token = {
        "invalid": "bad",
        "refresh": create_refresh_token(test_user.id),
        "expired": create_access_token(test_user.id, timedelta(seconds=-1)),
        "bad_subject": create_access_token("bad"),
        "unknown": create_access_token(uuid4()),
    }.get(kind, create_access_token(test_user.id))
    r = await auth_http.post(
        "/api/v1/auth/logout", headers={} if kind == "missing" else bearer(token)
    )
    assert r.status_code == 401 and test_user.token_version == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["inactive", "roleless", "missing_rider"])
async def test_disabled_accounts_can_retire_their_own_tokens(
    auth_http, db_session, test_user, kind
):
    token = create_access_token(test_user.id)
    if kind == "inactive":
        test_user.is_active = False
    elif kind == "roleless":
        test_user.role = None
    else:
        test_user.role = UserRole.REPARTIDOR
    await db_session.commit()
    assert (
        await auth_http.get("/api/v1/auth/me", headers=bearer(token))
    ).status_code in (401, 403)
    r = await auth_http.post("/api/v1/auth/logout", headers=bearer(token))
    assert r.status_code == 200
    assert (
        await db_session.scalar(
            select(User.token_version).where(User.id == test_user.id)
        )
        == 1
    )


@pytest.mark.asyncio
async def test_refresh_rotates_ids_without_revoking_same_account_epoch(
    auth_http, db_session, test_user
):
    await revoke_user_tokens(db_session, test_user.id)
    await db_session.commit()
    token = create_refresh_token(test_user.id, token_version=1)
    responses = [
        (
            await auth_http.post("/api/v1/auth/refresh", json={"refresh_token": token})
        ).json()
        for _ in range(2)
    ]
    claims = [decode_token(r["access_token"]) for r in responses]
    assert all(p["ver"] == 1 for p in claims)
    assert claims[0]["jti"] != claims[1]["jti"] and test_user.token_version == 1
    # Single-use refresh replay prevention requires a separate session ledger.


@pytest.mark.asyncio
async def test_reset_revokes_access_refresh_and_replay_cannot_advance_again(
    auth_http, db_session, test_user
):
    t = secrets.token_urlsafe(32)
    a, r = create_access_token(test_user.id), create_refresh_token(test_user.id)
    test_user.reset_token = reset_token_digest(t)
    test_user.reset_token_expires = utc_now_naive() + timedelta(hours=1)
    await db_session.commit()
    body = {"token": t, "new_password": "NewPassword123!"}
    response = await auth_http.post("/api/v1/auth/reset-password", json=body)
    assert response.status_code == 200, response.text
    await db_session.refresh(test_user)
    assert test_user.token_version == 1 and test_user.reset_token is None
    await retired(auth_http, a, r)
    assert (
        await auth_http.post("/api/v1/auth/reset-password", json=body)
    ).status_code == 400
    await db_session.refresh(test_user)
    assert test_user.token_version == 1 and verify_password(
        body["new_password"], test_user.hashed_password
    )


@pytest.mark.asyncio
async def test_core_dependency_rejects_revoked_token(db_session, test_user):
    token = create_access_token(test_user.id)
    assert (
        await get_current_active_user(token=token, db=db_session)
    ).id == test_user.id
    await revoke_user_tokens(db_session, test_user.id)
    await db_session.commit()
    with pytest.raises(HTTPException) as e:
        await get_current_active_user(token=token, db=db_session)
    assert e.value.status_code == 401


@pytest.fixture
async def admin_http(db_session, test_user):
    test_user.role = UserRole.GERENTE
    target = User(
        email="target@example.test",
        hashed_password=hash_password("OldPassword123!"),
        first_name="Target",
        last_name="Account",
        role=UserRole.OPERADOR,
    )
    db_session.add(target)
    await db_session.commit()
    app = FastAPI()
    app.include_router(users.router, prefix="/api/v1/users")

    async def database():
        yield db_session

    async def manager():
        return test_user

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[auth.get_current_user] = manager
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, target


@pytest.mark.asyncio
async def test_admin_password_revokes_and_clears_pending_recovery(
    admin_http, db_session
):
    client, u = admin_http
    u.reset_token = reset_token_digest(secrets.token_urlsafe(32))
    u.reset_token_expires = utc_now_naive() + timedelta(hours=1)
    await db_session.commit()
    r = await client.patch(
        f"/api/v1/users/{u.id}/password", json={"password": "AdminChanged123!"}
    )
    assert r.status_code == 200, r.text
    assert u.token_version == 1 and u.reset_token is u.reset_token_expires is None
    assert verify_password("AdminChanged123!", u.hashed_password)
    assert "token_version" not in r.text and "hashed_password" not in r.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["role", "deactivate", "reactivate", "metadata", "same_values", "delete"]
)
async def test_admin_security_changes_revoke_but_metadata_and_noops_do_not(
    admin_http, db_session, change
):
    client, u = admin_http
    if change == "reactivate":
        u.is_active = False
        await db_session.commit()
    old = u.token_version
    if change == "delete":
        r = await client.delete(
            f"/api/v1/users/{u.id}", headers={"If-Match": user_revision(u)}
        )
        assert r.status_code == 204, r.text
    else:
        body = {"expected_user_revision": user_revision(u)}
        body.update(
            {"role": "AUDITOR"}
            if change == "role"
            else (
                {"is_active": False}
                if change == "deactivate"
                else (
                    {"is_active": True}
                    if change == "reactivate"
                    else (
                        {"role": "OPERADOR", "is_active": True}
                        if change == "same_values"
                        else {"phone": "+584120000000"}
                    )
                )
            )
        )
        r = await client.patch(f"/api/v1/users/{u.id}", json=body)
        assert r.status_code == 200, r.text
    assert await db_session.scalar(
        select(User.token_version).where(User.id == u.id)
    ) == old + int(change not in ["metadata", "same_values"])


@pytest.mark.asyncio
async def test_crud_password_update_retires_tokens_and_recovery(db_session, test_user):
    test_user.reset_token = reset_token_digest(secrets.token_urlsafe(32))
    await db_session.commit()
    u = await user_crud.update_password(db_session, test_user, "CrudChanged123!")
    assert u.token_version == 1 and u.reset_token is None
    assert verify_password("CrudChanged123!", u.hashed_password)
