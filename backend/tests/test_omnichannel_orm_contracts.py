"""Exact pre-refactor PostgreSQL DDL and persisted scalar/nullable contracts."""

import json
from datetime import datetime
from pathlib import Path
from uuid import UUID
import pytest
from sqlalchemy import select, update
from tests.orm_contract import detailed_mapping_contract
from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from tests.test_notification_dispatch_postgresql import dispatch_db  # noqa: F401
from app.models.notification import (
    NotificationTemplate,
    NotificationLog,
    UserDeviceToken,
    NotificationPreference,
    NotificationChannel,
    OmnichannelStatus,
)
from app.api.v1.notifications import _log_out

TABLES = (
    "notification_templates",
    "notification_logs",
    "user_device_tokens",
    "notification_preferences",
)


def test_four_typed_models_preserve_original_postgresql_contract():
    original = json.loads(
        (Path(__file__).parent / "fixtures/orm_omnichannel_contract.json").read_text()
    )
    assert detailed_mapping_contract(TABLES) == original


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", list(NotificationChannel))
async def test_roundtrip_preserves_uuid_enums_defaults_and_nullable_payloads(
    dispatch_db, channel
):
    sessions, uid = dispatch_db
    async with sessions() as db:
        log = NotificationLog(user_id=uid, channel=channel)
        preference = NotificationPreference(
            user_id=uid, event_code="typed_event", channel=channel
        )
        device = UserDeviceToken(user_id=uid, device_token="offline-contract-token")
        db.add_all([log, preference, device])
        await db.commit()
        lid, pid, did = log.id, preference.id, device.id
    async with sessions() as db:
        log, preference, device = (
            await db.get(NotificationLog, lid),
            await db.get(NotificationPreference, pid),
            await db.get(UserDeviceToken, did),
        )
        template = await db.scalar(
            select(NotificationTemplate).where(
                NotificationTemplate.code == "transaction_test"
            )
        )
        assert all(
            isinstance(value, UUID)
            for value in [log.id, log.user_id, preference.id, device.id]
        )
        assert log.channel is preference.channel is channel
        assert log.status is OmnichannelStatus.PENDIENTE
        assert type(log.retry_count) is int and log.retry_count == 0
        assert log.payload_json is log.title is log.body is log.template_code is None
        assert (
            log.sent_at is log.read_at is log.delivered_at is log.next_retry_at is None
        )
        assert isinstance(log.created_at, datetime) and log.created_at.tzinfo is None
        assert preference.enabled is device.is_active is template.is_active is True
        assert device.failure_count == 0 and device.platform == "web"
        assert isinstance(device.last_seen_at, datetime)
        assert (
            template.channel is NotificationChannel.EMAIL and template.language == "es"
        )
        out = _log_out(log)
        assert out.id == str(lid) and out.title is None and out.body is None


@pytest.mark.asyncio
async def test_nullable_timestamps_and_provider_fields_can_be_cleared(dispatch_db):
    sessions, uid = dispatch_db
    async with sessions() as db:
        now = datetime(2026, 10, 29, 1, 0)
        log = NotificationLog(
            user_id=uid,
            channel=NotificationChannel.EMAIL,
            provider_message_id="offline-id",
            error_message="generic failure",
            next_retry_at=now,
            sent_at=now,
        )
        db.add(log)
        await db.commit()
        lid = log.id
        log.provider_message_id = log.error_message = None
        log.next_retry_at = log.sent_at = None
        await db.commit()
    async with sessions() as db:
        log = await db.get(NotificationLog, lid)
        assert (
            log.provider_message_id
            is log.error_message
            is log.next_retry_at
            is log.sent_at
            is None
        )


@pytest.mark.asyncio
async def test_sql_updates_and_returning_still_expose_values(dispatch_db):
    sessions, uid = dispatch_db
    async with sessions() as db:
        log = NotificationLog(user_id=uid, channel=NotificationChannel.IN_APP)
        db.add(log)
        await db.commit()
        lid = log.id
        value = await db.scalar(
            update(NotificationLog)
            .where(NotificationLog.id == lid)
            .values(retry_count=NotificationLog.retry_count + 1)
            .returning(NotificationLog.retry_count)
            .execution_options(synchronize_session=False)
        )
        assert type(value) is int and value == 1
        await db.commit()
    async with sessions() as db:
        log = await db.get(NotificationLog, lid)
        assert log.retry_count == 1 and log.status is OmnichannelStatus.PENDIENTE
