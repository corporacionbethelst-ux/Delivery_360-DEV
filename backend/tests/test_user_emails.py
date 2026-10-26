"""Email conflicts are canonical and leave no partial account/profile/files."""

from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select, func
from tests.test_user_preconditions import accounts  # noqa: F401
from tests.test_fleet_assignment import fleet  # noqa: F401
from tests.test_document_uploads import submissions, PDF  # noqa: F401
from tests.test_private_documents import documents  # noqa: F401
from app.api.v1 import auth, users, riders
from app.models.user import User
from app.models.rider import Rider
from app.models.rider_document import RiderDocument
from app.core.security import hash_password
from app.services.user_emails import normalize_email


@pytest.fixture
async def emails(accounts):
    client, db, actor, target, rid = accounts
    client._transport.app.include_router(auth.router, prefix="/api/v1")
    return client, db, actor, target, rid


def body(email):
    return dict(
        email=email,
        password="ValidPassword123!",
        first_name="New",
        last_name="User",
        phone="+111111111",
        role="OPERADOR",
        vehicle_type="MOTO",
    )


async def counts(db):
    return [
        await db.scalar(select(func.count()).select_from(model))
        for model in [User, Rider, RiderDocument]
    ]


async def create(client, path, email):
    if path == "public":
        files = {
            name: (name + ".pdf", PDF, "application/pdf")
            for name in [
                "license_file",
                "id_card_file",
                "vehicle_registration_file",
                "insurance_file",
            ]
        }
        return await client.post(
            "/api/v1/auth/register-rider", data=body(email), files=files
        )
    return await client.post(
        "/api/v1/users" if path == "users" else "/api/v1/riders", json=body(email)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["users", "riders", "public"])
async def test_all_account_creation_routes_share_canonical_conflict(emails, path):
    client, db, actor, _, _ = emails
    email = (await db.get(User, actor)).email
    before = await counts(db)
    response = await create(client, path, " \t" + email.upper() + "\n")
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "USER_EMAIL_CONFLICT"
    assert await counts(db) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["users", "riders", "public"])
async def test_new_accounts_are_stored_with_one_email_policy(emails, path):
    client, db, _, _, _ = emails
    response = await create(client, path, " New.Email@Example.Com ")
    assert response.status_code == 201, response.text
    user = await db.scalar(select(User).where(User.email == "new.email@example.com"))
    assert user is not None
    assert (await create(client, "users", "NEW.EMAIL@EXAMPLE.COM")).status_code == 409


@pytest.mark.asyncio
async def test_duplicate_edit_can_be_corrected_without_replacing_user_revision(emails):
    client, db, actor, target, _ = emails
    url = f"/api/v1/users/{target}"
    original = (await client.get(url)).json()
    duplicate = (await db.get(User, actor)).email.upper()
    response = await client.patch(
        url,
        json={
            "email": duplicate,
            "phone": "+999999999",
            "expected_user_revision": original["user_revision"],
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "USER_EMAIL_CONFLICT"
    current = (await client.get(url)).json()
    assert current["user_revision"] == original["user_revision"]
    response = await client.patch(
        url,
        json={
            "email": " New.Mail@Example.Com ",
            "expected_user_revision": original["user_revision"],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["email"] == "new.mail@example.com"


@pytest.mark.asyncio
async def test_historical_equivalent_accounts_fail_closed_for_login_and_recovery(
    emails, monkeypatch
):
    client, db, actor, target, _ = emails
    (await db.get(User, actor)).email = " \tLEGACY@example.com\n"
    password_hash = hash_password("LegacyPassword123!")
    (await db.get(User, actor)).hashed_password = password_hash
    (await db.get(User, target)).hashed_password = password_hash
    (await db.get(User, target)).email = "legacy@example.com"
    await db.commit()
    response = await create(client, "users", "legacy@example.com")
    assert response.status_code == 409, response.text
    denied = await client.post(
        "/api/v1/auth/login",
        data={"username": "legacy@example.com", "password": "LegacyPassword123!"},
    )
    assert denied.status_code == 400, denied.text
    import sys
    from types import ModuleType

    send = AsyncMock()
    mail = ModuleType("app.core.email_service")
    mail.send_reset_email = send
    monkeypatch.setitem(sys.modules, "app.core.email_service", mail)
    response = await client.post(
        "/api/v1/auth/forgot-password", json={"email": "LEGACY@example.com"}
    )
    assert response.status_code == 200, response.text
    send.assert_not_awaited()
    assert set((await db.scalars(select(User.email))).all()) == {
        " \tLEGACY@example.com\n",
        "legacy@example.com",
    }


@pytest.mark.asyncio
async def test_unique_legacy_case_variant_can_login_with_normalized_input(emails):
    client, db, actor, _, _ = emails
    row = await db.get(User, actor)
    row.email = " \tLOGIN@Example.Com\n"
    row.hashed_password = hash_password("EmailPassword123!")
    await db.commit()
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": " Login@example.com ", "password": "EmailPassword123!"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["user_id"] == str(actor)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["users", "riders", "public"])
async def test_genuine_email_unique_failure_is_409_and_rolls_back(
    emails, path, monkeypatch
):
    client, db, actor, _, _ = emails
    email = (await db.get(User, actor)).email

    async def bypass(db, email, **kwargs):
        return normalize_email(email)

    monkeypatch.setattr(
        {"users": users, "riders": riders, "public": auth}[path], "claim_email", bypass
    )
    before = await counts(db)
    response = await create(client, path, email)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "USER_EMAIL_CONFLICT"
    assert await counts(db) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["riders", "public"])
@pytest.mark.parametrize("email", ["", "   ", "a" * 256])
async def test_blank_or_oversized_email_cannot_create_accounts_or_documents(
    emails, path, email
):
    client, db, _, _, _ = emails
    before = await counts(db)
    response = await create(client, path, email)
    assert response.status_code == 422, response.text
    assert await counts(db) == before
