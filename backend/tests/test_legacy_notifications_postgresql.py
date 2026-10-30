"""Actual legacy inbox persistence and HTTP ownership, without external dispatch."""

from uuid import uuid4
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, func, update, text
from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from app.api.v1 import alerts
from app.core.database import get_db
from app.core.security import create_access_token
from app.core.exceptions import NotFoundError, ValidationError
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.models.rider import Rider
from app.services.notification_service import NotificationService
from app.services.alert_service import AlertService


@pytest.fixture
async def inbox_db(pg_wallets):
    sessions, _, riders = pg_wallets
    async with sessions() as db:
        conn = await db.connection()
        await conn.run_sync(
            lambda c: Rider.__table__.c.status.type.create(c, checkfirst=True)
        )
        await db.execute(
            text("ALTER TABLE riders ADD COLUMN status riderstatus DEFAULT 'ACTIVO'")
        )
        await conn.run_sync(Notification.__table__.create)
        ids = [
            await db.scalar(select(Rider.user_id).where(Rider.id == rid))
            for rid in riders
        ]
        await db.commit()
    app = FastAPI()
    app.include_router(alerts.router, prefix="/api/v1")

    async def database():
        async with sessions() as db:
            try:
                yield db
            finally:
                await db.rollback()

    app.dependency_overrides[get_db] = database
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://inbox.test"
    ) as client:
        yield sessions, ids, riders, client


def auth(uid):
    return {"Authorization": "Bearer " + create_access_token(uid)}


async def create(sessions, uid, **kwargs):
    async with sessions() as db:
        return await NotificationService(db).create_notification(
            uid, NotificationType.ALERTA_OPERACIONAL, "Aviso", "Mensaje", **kwargs
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["in_app", "push", "email", "sms"])
async def test_channel_requests_are_persisted_without_claiming_external_acceptance(
    inbox_db, channel, monkeypatch
):
    from unittest.mock import AsyncMock

    sessions, users, _, _ = inbox_db
    provider = AsyncMock()
    monkeypatch.setattr("app.services.notification_providers.send_push", provider)
    monkeypatch.setattr("app.services.notification_providers.send_sms", provider)
    result = await create(
        sessions, users[0], channel=channel, data={"order_id": "known", "count": 0}
    )
    async with sessions() as db:
        row = await db.get(Notification, result.id)
        assert row.user_id == users[0] and row.channels == channel
        assert row.data == {"order_id": "known", "count": 0}
        assert (
            row.is_sent is False and row.sent_at is None and row.sent_channels is None
        )
    provider.assert_not_called()


@pytest.mark.asyncio
async def test_caller_owned_creation_cannot_commit_unrelated_changes(inbox_db):
    sessions, users, _, _ = inbox_db
    async with sessions() as db:
        user = await db.get(User, users[0])
        user.first_name = "Uncommitted"
        await NotificationService(db).create_notification(
            users[0], "SISTEMA", "Aviso", "Mensaje", commit=False
        )
        async with sessions() as observer:
            assert (
                await observer.scalar(
                    select(User.first_name).where(User.id == users[0])
                )
                == "Test"
            )
            assert (
                await observer.scalar(select(func.count()).select_from(Notification))
                == 0
            )
        await db.rollback()
    async with sessions() as db:
        assert (
            await db.scalar(select(User.first_name).where(User.id == users[0]))
            == "Test"
        )
        assert await db.scalar(select(func.count()).select_from(Notification)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["flush", "commit"])
async def test_owned_creation_rolls_back_on_late_failures(
    inbox_db, failure, monkeypatch
):
    sessions, users, _, _ = inbox_db
    async with sessions() as db:

        async def broken(*args, **kwargs):
            raise RuntimeError("injected inbox failure")

        monkeypatch.setattr(db, failure, broken)
        with pytest.raises(RuntimeError):
            await NotificationService(db).create_notification(
                users[0], "SISTEMA", "Aviso", "Mensaje"
            )
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Notification)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("recipient", ["missing", "inactive"])
async def test_missing_or_inactive_recipient_has_no_orphan_record(inbox_db, recipient):
    sessions, users, _, _ = inbox_db
    uid = uuid4() if recipient == "missing" else users[0]
    if recipient == "inactive":
        async with sessions() as db:
            await db.execute(update(User).where(User.id == uid).values(is_active=False))
            await db.commit()
    with pytest.raises(NotFoundError):
        await create(sessions, uid)
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Notification)) == 0


@pytest.mark.asyncio
async def test_rider_helpers_resolve_user_identity_and_real_notification_enums(
    inbox_db,
):
    sessions, users, riders, _ = inbox_db
    assert users[0] != riders[0]
    async with sessions() as db:
        service = NotificationService(db)
        order = await service.notify_order_assigned(riders[0], uuid4())
        warning = await service.notify_sla_warning(riders[0], uuid4(), 3)
        payment = await service.notify_payment_received(riders[0], 12.50)
        assert all(
            row.user_id == users[0] and row.is_sent is False
            for row in (order, warning, payment)
        )
        assert [row.notification_type for row in (order, warning, payment)] == [
            NotificationType.ASIGNACION_PEDIDO,
            NotificationType.SLA_WARNING,
            NotificationType.PAGO_RECIBIDO,
        ]
        assert "R$" not in payment.message


@pytest.mark.asyncio
async def test_recipient_scope_and_read_timestamp_are_idempotent(inbox_db):
    sessions, users, _, client = inbox_db
    own = await create(sessions, users[0])
    other = await create(sessions, users[1])
    listing = await client.get("/api/v1/alerts", headers=auth(users[0]))
    assert listing.status_code == 200, listing.text
    assert [row["id"] for row in listing.json()] == [str(own.id)]
    denied = await client.patch(
        f"/api/v1/alerts/{other.id}/read", headers=auth(users[0])
    )
    assert denied.status_code == 404
    first = await client.patch(f"/api/v1/alerts/{own.id}/read", headers=auth(users[0]))
    assert first.status_code == 200, first.text
    async with sessions() as db:
        moment = (await db.get(Notification, own.id)).read_at
        assert moment is not None
    assert (
        await client.patch(f"/api/v1/alerts/{own.id}/read", headers=auth(users[0]))
    ).status_code == 200
    async with sessions() as db:
        assert (await db.get(Notification, own.id)).read_at == moment
        assert (await db.get(Notification, other.id)).is_read is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        True,
        123,
        "broken json",
        '{"alert_type":"legacy","severity":"alta"}',
        {"alert_type": 123, "severity": []},
    ],
)
async def test_legacy_json_shapes_and_unknown_timestamps_do_not_break_alert_listing(
    inbox_db, payload
):
    sessions, users, _, client = inbox_db
    result = await create(sessions, users[0])
    async with sessions() as db:
        await db.execute(
            update(Notification)
            .where(Notification.id == result.id)
            .values(data=payload)
        )
        await db.execute(
            text("UPDATE notifications SET created_at=NULL,is_read=NULL WHERE id=:id"),
            {"id": result.id},
        )
        await db.commit()
    response = await client.get("/api/v1/alerts?status=UNREAD", headers=auth(users[0]))
    assert response.status_code == 200, response.text
    row = response.json()[0]
    assert (
        row["id"] == str(result.id)
        and row["createdAt"] == ""
        and row["isRead"] is False
    )
    assert row["type"] == (
        "legacy" if isinstance(payload, str) and payload.startswith("{") else "SYSTEM"
    )


@pytest.mark.asyncio
async def test_mark_all_preserves_other_users_and_other_notification_types(inbox_db):
    sessions, users, _, client = inbox_db
    own = await create(sessions, users[0])
    other = await create(sessions, users[1])
    async with sessions() as db:
        system = await NotificationService(db).create_notification(
            users[0], "SISTEMA", "Sistema", "Mensaje"
        )
    response = await client.post("/api/v1/alerts/read-all", headers=auth(users[0]))
    assert response.status_code == 200 and response.json()["count"] == 1
    async with sessions() as db:
        assert (await db.get(Notification, own.id)).read_at is not None
        assert (await db.get(Notification, other.id)).is_read is False
        assert (await db.get(Notification, system.id)).is_read is False


@pytest.mark.asyncio
async def test_alerts_accept_uuid_recipients_and_references_without_silent_orphans(
    inbox_db,
):
    sessions, users, _, _ = inbox_db
    oid = uuid4()
    async with sessions() as db:
        await AlertService().create_alert(
            db,
            "operations",
            "alta",
            "Título",
            "Mensaje",
            related_entity_id=oid,
            related_entity_type="order",
            recipient_user_ids=[users[0], str(users[0]), users[1]],
        )
    async with sessions() as db:
        rows = list((await db.scalars(select(Notification))).all())
        assert len(rows) == 2
        assert {row.user_id for row in rows} == set(users)
        assert all(
            row.related_id == str(oid) and row.data["related_order_id"] == str(oid)
            for row in rows
        )


@pytest.mark.asyncio
async def test_default_alert_audience_is_active_management(inbox_db):
    sessions, users, _, _ = inbox_db
    async with sessions() as db:
        await db.execute(
            update(User).where(User.id == users[0]).values(role=UserRole.GERENTE)
        )
        await db.commit()
        row = await AlertService().create_alert(
            db, "operations", "medium", "Título", "Mensaje"
        )
        assert row.user_id == users[0]
        assert await db.scalar(select(func.count()).select_from(Notification)) == 1


@pytest.mark.asyncio
async def test_mixed_valid_and_unknown_audience_cannot_partially_persist(inbox_db):
    sessions, users, _, _ = inbox_db
    async with sessions() as db:
        with pytest.raises(NotFoundError):
            await AlertService().create_alert(
                db,
                "operations",
                "medium",
                "Título",
                "Mensaje",
                recipient_user_ids=[users[0], uuid4()],
            )
        assert await db.scalar(select(func.count()).select_from(Notification)) == 0
