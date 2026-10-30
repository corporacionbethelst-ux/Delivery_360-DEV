"""Invalid notification input must fail before persistence or provider access."""

from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import AsyncMock
import pytest
from app.core.exceptions import ValidationError
from app.models.notification import NotificationType
from app.services.notification_service import NotificationService
from app.services.notification_values import (
    notification_uuid,
    notification_text,
    notification_payload,
    notification_recipients,
)
from app.services.sla_monitor import lock_sla_deliveries


@pytest.mark.parametrize("value", [None, True, 1, -1, "", "not-a-uuid", object()])
def test_recipient_ids_are_real_uuids(value):
    with pytest.raises(ValidationError):
        notification_uuid(value, "Destinatario")


def test_recipient_lists_are_bounded_and_deduplicated():
    uid = uuid4()
    assert notification_recipients([uid, str(uid)]) == [uid]
    for invalid in (None, [], [uid] * 201, [True], ["bad"]):
        with pytest.raises(ValidationError):
            notification_recipients(invalid)


@pytest.mark.parametrize(
    "value", [None, 1, True, "", "   ", "abc\x00def", "bad\ud800text", "x" * 256]
)
def test_nonrepresentable_or_oversized_titles_are_rejected(value):
    with pytest.raises(ValidationError):
        notification_text(value, "Título", 255)


@pytest.mark.parametrize(
    "value",
    [
        [],
        "json string",
        {1: "bad"},
        {"bad": float("nan")},
        {"bad": float("inf")},
        {"too_big": "x" * 16384},
        {"bad": object()},
        {"bad": "\ud800"},
        {"\ud800": "bad"},
    ],
)
def test_payloads_are_json_objects_with_a_size_limit(value):
    with pytest.raises(ValidationError):
        notification_payload(value)


def test_payload_copy_does_not_follow_later_caller_mutations():
    original = {"nested": [1, {"key": "value"}]}
    copy = notification_payload(original)
    original["nested"].append(2)
    assert copy == {"nested": [1, {"key": "value"}]}
    recursive = {}
    recursive["self"] = recursive
    with pytest.raises(ValidationError):
        notification_payload(recursive)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "override",
    [
        {"user_id": True},
        {"user_id": "bad"},
        {"notification_type": "ORDER_ASSIGNED"},
        {"title": ""},
        {"message": ""},
        {"data": []},
        {"channel": "fax"},
        {"commit": 1},
    ],
)
async def test_bad_inputs_do_not_touch_the_database(override):
    db = AsyncMock()
    args = dict(
        user_id=uuid4(),
        notification_type=NotificationType.SISTEMA,
        title="Title",
        message="Message",
    )
    with pytest.raises(ValidationError):
        await NotificationService(db).create_notification(**{**args, **override})
    assert db.mock_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "options",
    [
        {"batch_size": True},
        {"batch_size": 0},
        {"batch_size": 101},
        {"delivery_id": "bad"},
        {"warning_minutes": True},
        {"warning_minutes": 0},
        {"warning_minutes": 61},
    ],
)
async def test_invalid_sla_bounds_do_not_acquire_locks(options):
    db = AsyncMock()
    with pytest.raises(ValueError):
        await lock_sla_deliveries(db, datetime(2026, 10, 30), **options)
    assert db.mock_calls == []


@pytest.mark.asyncio
async def test_sla_clock_must_be_utc_naive():
    db = AsyncMock()
    with pytest.raises(ValueError):
        await lock_sla_deliveries(db, datetime.now(timezone.utc))
    assert db.mock_calls == []
