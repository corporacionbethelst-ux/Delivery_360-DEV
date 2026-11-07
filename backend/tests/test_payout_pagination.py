"""HTTP contract and persisted keyset navigation under changing data."""

from datetime import datetime
from uuid import UUID

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import delete, insert, select, update

from app.api.v1 import payouts as api
from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.payout import Payout, PayoutStatus
from app.models.rider import Rider, RiderStatus
from app.models.user import User, UserRole

UUID_BASE = 0xA << 124


def uid(number):
    return UUID(int=UUID_BASE + number)


async def add_row(session, rider_id, number, at, status=PayoutStatus.PENDIENTE):
    # Explicit SQL NULL bypasses the model's creation-time Python default.
    await session.execute(
        insert(Payout).values(
            id=uid(number),
            rider_id=rider_id,
            amount=10,
            method="EFECTIVO",
            status=status,
            requested_at=at,
        )
    )
    await session.commit()


@pytest.fixture
async def page_context(test_engine, db_session, test_user):
    async with test_engine.begin() as connection:
        await connection.run_sync(lambda conn: Payout.__table__.create(conn))
    raw = await (await db_session.connection()).get_raw_connection()
    await raw.driver_connection.create_function("AsEWKB", 1, lambda value: None)
    test_user.role = UserRole.GERENTE
    rider = Rider(user_id=test_user.id, status=RiderStatus.ACTIVO)
    db_session.add(rider)
    await db_session.commit()
    for number, at in [
        (9, datetime(2026, 11, 3)),
        (8, datetime(2026, 11, 2)),
        (7, datetime(2026, 11, 2)),
        (6, datetime(2026, 11, 1)),
        (5, None),
        (4, None),
    ]:
        await add_row(db_session, rider.id, number, at)
    app = FastAPI()
    app.include_router(api.router)

    async def db():
        yield db_session

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_current_user] = lambda: test_user
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, db_session, rider.id, test_user, app


def ids(page):
    return [UUID(row["id"]).int - UUID_BASE for row in page["items"]]


async def read(client, **params):
    response = await client.get("/payouts/page", params={"limit": 2, **params})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_equal_dates_and_null_dates_are_traversed_once_with_uuid_tiebreaker(
    page_context,
):
    client, *_ = page_context
    seen = []
    cursor = None
    for _ in range(3):
        page = await read(client, **({"cursor": cursor} if cursor else {}))
        seen.extend(ids(page))
        cursor = page["next_cursor"]
        assert set(page) == {"items", "next_cursor"}
    assert seen == [9, 8, 7, 6, 5, 4]
    assert cursor is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation", ["insert_newer", "delete_seen", "delete_boundary", "change_seen_status"]
)
async def test_changes_before_the_cursor_do_not_shift_unseen_rows(
    page_context, mutation
):
    client, session, rider_id, *_ = page_context
    first = await read(client, status="PENDIENTE")
    if mutation == "insert_newer":
        await add_row(session, rider_id, 10, datetime(2026, 11, 4))
    elif mutation in ("delete_seen", "delete_boundary"):
        await session.execute(
            delete(Payout).where(
                Payout.id == uid(9 if mutation == "delete_seen" else 8)
            )
        )
        await session.commit()
    else:
        await session.execute(
            update(Payout)
            .where(Payout.id == uid(9))
            .values(status=PayoutStatus.RECHAZADO)
        )
        await session.commit()
    second = await read(client, status="PENDIENTE", cursor=first["next_cursor"])
    assert ids(second) == [7, 6]
    third = await read(client, status="PENDIENTE", cursor=second["next_cursor"])
    assert ids(third) == [5, 4]


@pytest.mark.asyncio
async def test_a_deleted_unseen_row_is_absent_without_skipping_its_neighbor(
    page_context,
):
    client, session, *_ = page_context
    first = await read(client)
    await session.execute(delete(Payout).where(Payout.id == uid(7)))
    await session.commit()
    assert ids(await read(client, cursor=first["next_cursor"])) == [6, 5]


@pytest.mark.asyncio
async def test_read_is_live_and_restart_includes_newer_rows(page_context):
    client, session, rider_id, *_ = page_context
    first = await read(client, status="PENDIENTE")
    await add_row(session, rider_id, 10, datetime(2026, 11, 4))
    await session.execute(
        update(Payout).where(Payout.id == uid(7)).values(status=PayoutStatus.COMPLETADO)
    )
    await session.commit()
    assert ids(await read(client, cursor=first["next_cursor"], status="PENDIENTE")) == [
        6,
        5,
    ]
    assert ids(await read(client, status="PENDIENTE")) == [10, 9]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["status", "limit", "rider_id", "actor", "role", "tamper"]
)
async def test_continuation_cannot_be_reused_for_a_different_scope(
    page_context, change
):
    client, _, rider_id, user, _ = page_context
    first = await read(client)
    params = {"limit": 2, "cursor": first["next_cursor"]}
    if change == "status":
        params["status"] = "COMPLETADO"
    elif change == "limit":
        params["limit"] = 3
    elif change == "rider_id":
        params["rider_id"] = str(rider_id)
    elif change == "actor":
        user.id = uid(1000)
    elif change == "role":
        user.role = UserRole.SUPERADMIN
    else:
        token = params["cursor"]
        params["cursor"] = token[:-1] + ("0" if token[-1] != "0" else "1")
    response = await client.get("/payouts/page", params=params)
    assert response.status_code == 400
    assert "Vuelve al inicio" in response.json()["detail"]


@pytest.mark.asyncio
async def test_rider_cannot_widen_scope_with_another_rider_query(page_context):
    client, session, rider_id, user, _ = page_context
    other_user = User(
        email="other@example.test",
        hashed_password="unused",
        first_name="Other",
        last_name="Test",
        role=UserRole.REPARTIDOR,
    )
    session.add(other_user)
    await session.flush()
    session.add(Rider(id=uid(1001), user_id=other_user.id, status=RiderStatus.ACTIVO))
    await session.commit()
    await add_row(session, uid(1001), 10, datetime(2026, 11, 4))
    user.role = UserRole.REPARTIDOR
    await session.commit()
    first = await read(client, rider_id=str(uid(1001)))
    assert ids(first) == [9, 8]
    second = await read(client, cursor=first["next_cursor"])
    assert ids(second) == [7, 6]
    assert all(row["rider_id"] == str(rider_id) for row in second["items"])


@pytest.mark.asyncio
async def test_downgraded_role_is_denied_even_with_a_valid_cursor(page_context):
    client, _, _, user, _ = page_context
    first = await read(client)
    user.role = UserRole.OPERADOR
    response = await client.get(
        "/payouts/page", params={"limit": 2, "cursor": first["next_cursor"]}
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_cursor_does_not_replace_authentication(page_context):
    client, _, _, _, app = page_context
    first = await read(client)
    del app.dependency_overrides[get_current_user]
    response = await client.get(
        "/payouts/page", params={"cursor": first["next_cursor"]}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 201},
        {"cursor": ""},
        {"cursor": "x" * 2049},
        {"status": "CANCELADO"},
    ],
)
async def test_invalid_query_is_rejected_at_http_boundary(page_context, params):
    client, *_ = page_context
    assert (await client.get("/payouts/page", params=params)).status_code == 422


@pytest.mark.asyncio
async def test_legacy_array_contract_remains_bounded_and_deterministic(page_context):
    client, session, *_ = page_context
    response = await client.get("/payouts", params={"limit": 2, "offset": 2})
    assert response.status_code == 200
    assert [UUID(row["id"]).int - UUID_BASE for row in response.json()] == [7, 6]
    assert len((await session.execute(select(Payout))).scalars().all()) == 6


@pytest.mark.asyncio
async def test_empty_or_exact_page_has_no_fictitious_continuation(page_context):
    client, *_ = page_context
    assert (await read(client, limit=6))["next_cursor"] is None
    assert await read(client, status="FALLIDO") == {"items": [], "next_cursor": None}


@pytest.mark.asyncio
@pytest.mark.parametrize("cursor", ["invalid", "YQ." + "0" * 64])
async def test_malformed_or_unsigned_cursor_returns_recoverable_400(
    page_context, cursor
):
    client, *_ = page_context
    response = await client.get("/payouts/page", params={"cursor": cursor})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_rotating_signing_key_invalidates_old_continuation(
    page_context, monkeypatch
):
    from app.core.config import settings

    client, *_ = page_context
    first = await read(client)
    monkeypatch.setattr(settings, "SECRET_KEY", "another-local-test-key")
    response = await client.get(
        "/payouts/page", params={"limit": 2, "cursor": first["next_cursor"]}
    )
    assert response.status_code == 400
