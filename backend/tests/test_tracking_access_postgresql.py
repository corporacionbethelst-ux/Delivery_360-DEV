"""Tracking ownership and live authorization with native UUID/enums."""

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import raiseload
from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from tests.test_document_uploads_postgresql import pg_documents  # noqa: F401
from tests.test_fleet_assignment_postgresql import pg_fleet  # noqa: F401
from app.models.user import User, UserRole
from app.models.rider import Rider, RiderStatus
from app.models.order import Order
from app.models.delivery import Delivery
from app.api.v1.auth import get_current_user
from app.core.security import create_access_token
from app.services.tracking_access import resolve_tracking_channel


@pytest.fixture
async def tracking_fleet(pg_fleet):
    sessions, riders, _ = pg_fleet
    async with sessions() as db:
        conn = await db.connection()
        for model in [Order, Delivery]:
            await conn.run_sync(model.__table__.create)
        await db.execute(update(Rider).values(status=RiderStatus.ACTIVO))
        users = list((await db.scalars(select(Rider.user_id).order_by(Rider.id))).all())
        own = await db.scalar(select(Rider.id).where(Rider.user_id == users[0]))
        other = await db.scalar(select(Rider.id).where(Rider.user_id == users[1]))
        await db.execute(
            update(User).where(User.id == users[1]).values(role=UserRole.GERENTE)
        )
        order = Order(
            customer_name="Customer",
            customer_phone="123",
            pickup_address="Start",
            delivery_address="End",
            assigned_rider_id=own,
        )
        db.add(order)
        await db.flush()
        delivery = Delivery(order_id=order.id, rider_id=own)
        db.add(delivery)
        await db.commit()
        ids = {
            "owner": users[0],
            "manager": users[1],
            "rider": own,
            "other_rider": other,
            "order": order.id,
            "delivery": delivery.id,
        }
    return sessions, ids


@pytest.mark.asyncio
async def test_native_order_alias_and_individual_ownership(tracking_fleet):
    sessions, ids = tracking_fleet
    async with sessions() as db:
        owner = await get_current_user(token=create_access_token(ids["owner"]), db=db)
        requested, physical = await resolve_tracking_channel(
            db, owner, f"order:{ids['order']}"
        )
        assert (
            requested == f"order:{ids['order']}" and physical == f"rider:{ids['rider']}"
        )
        with pytest.raises(HTTPException) as error:
            await resolve_tracking_channel(db, owner, f"rider:{ids['other_rider']}")
        assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_order_reassignment_is_visible_to_the_next_check(tracking_fleet):
    sessions, ids = tracking_fleet
    async with sessions() as observer:
        manager = await get_current_user(
            token=create_access_token(ids["manager"]), db=observer
        )
        channel = f"order:{ids['order']}"
        before = await resolve_tracking_channel(observer, manager, channel)
        async with sessions() as writer:
            await writer.execute(
                update(Order)
                .where(Order.id == ids["order"])
                .values(assigned_rider_id=ids["other_rider"])
            )
            await writer.execute(
                update(Delivery)
                .where(Delivery.id == ids["delivery"])
                .values(rider_id=ids["other_rider"])
            )
            await writer.commit()
        after = await resolve_tracking_channel(observer, manager, channel)
        assert before[0] == after[0] and before[1] != after[1]
        assert after[1] == f"rider:{ids['other_rider']}"


@pytest.mark.asyncio
async def test_new_authorization_session_rejects_a_deactivated_account(tracking_fleet):
    sessions, ids = tracking_fleet
    token = create_access_token(ids["manager"])
    async with sessions() as db:
        assert (await get_current_user(token=token, db=db)).id == ids["manager"]
        await db.execute(
            update(User).where(User.id == ids["manager"]).values(is_active=False)
        )
        await db.commit()
    async with sessions() as db:
        with pytest.raises(HTTPException) as error:
            await get_current_user(token=token, db=db)
        assert error.value.status_code == 401
