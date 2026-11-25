"""Inbox clocks preserve their instant across Caracas and UTC midnight."""

from datetime import datetime, timezone, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from app.api.v1.notifications import _log_out
from app.core.serialization import utc_isoformat
from app.models.notification import (
    NotificationLog,
    NotificationChannel,
    OmnichannelStatus,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        (datetime(2026, 11, 25, 1), "2026-11-25T01:00:00+00:00"),
        (
            datetime(2026, 11, 24, 21, tzinfo=timezone(timedelta(hours=-4))),
            "2026-11-25T01:00:00+00:00",
        ),
        (
            datetime(2026, 11, 25, 4, tzinfo=timezone(timedelta(hours=3))),
            "2026-11-25T01:00:00+00:00",
        ),
    ],
)
def test_inbox_and_read_dates_expose_explicit_utc_without_inventing_missing_dates(
    value, expected
):
    log = NotificationLog(
        id=uuid4(),
        user_id=uuid4(),
        template_code="entrega_completada",
        channel=NotificationChannel.IN_APP,
        status=OmnichannelStatus.ENVIADO,
        created_at=value,
        read_at=value,
    )
    output = _log_out(log)
    assert output.created_at == output.read_at == utc_isoformat(value) == expected
    if expected:
        local = datetime.fromisoformat(expected).astimezone(ZoneInfo("America/Caracas"))
        assert (local.year, local.month, local.day, local.hour) == (2026, 11, 24, 21)
