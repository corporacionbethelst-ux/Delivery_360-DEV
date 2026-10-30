"""Task registry, closed-day scheduling, safe boundaries and loop-owned resources."""

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from pydantic import ValidationError
from app.core.config import settings, Settings
from app.workers import (
    runtime,
    productivity_worker,
    sla_monitor_worker,
    notification_worker,
    report_worker,
    alert_worker,
    cleanup_worker,
    liquidation_worker,
)
from app.workers.celery_app import celery_app, WORKER_MODULES, build_beat_schedule
from tests.orm_contract import detailed_mapping_contract


@pytest.fixture
def flags(monkeypatch):
    for name in (
        "CELERY_BEAT_ENABLED",
        "WORKER_SLA_MONITOR_ENABLED",
        "WORKER_PRODUCTIVITY_ENABLED",
        "WORKER_REPORTS_ENABLED",
        "WORKER_NOTIFICATION_RETRY_ENABLED",
    ):
        monkeypatch.setattr(settings, name, False)
    monkeypatch.setattr(settings, "CELERY_TIMEZONE", "UTC")


def test_original_schema_contract_is_preserved():
    expected = json.loads(
        (Path(__file__).parent / "fixtures/orm_worker_baseline.json").read_text()
    )
    assert detailed_mapping_contract(tuple(expected)) == expected


def test_alert_compatibility_import_uses_one_canonical_table():
    from app.models.alert import Alert as Compatible
    from app.models.notification import Alert

    assert Compatible is Alert and Compatible.__table__ is Alert.__table__


@pytest.mark.asyncio
async def test_enabled_retry_worker_delegates_existing_persisted_pipeline(
    flags, monkeypatch
):
    from contextlib import asynccontextmanager

    received = []
    db = object()

    @asynccontextmanager
    async def session():
        yield db

    async def process(batch):
        received.append(batch)
        return 3

    def manager(actual):
        assert actual is db
        return SimpleNamespace(process_retry_queue=process)

    monkeypatch.setattr(notification_worker, "worker_session", session)
    monkeypatch.setattr(notification_worker, "OmnichannelNotificationService", manager)
    monkeypatch.setattr(settings, "WORKER_NOTIFICATION_RETRY_ENABLED", True)
    result = await asyncio.to_thread(
        notification_worker.process_notification_retries.run, 25
    )
    assert result["processed_logs"] == 3 and received == [25]


@pytest.mark.asyncio
@pytest.mark.parametrize("batch", [0, 101, True, "5"])
async def test_invalid_retry_batch_is_rejected_before_dispatch(
    flags, monkeypatch, batch
):
    monkeypatch.setattr(settings, "WORKER_NOTIFICATION_RETRY_ENABLED", True)
    assert (
        await asyncio.to_thread(
            notification_worker.process_notification_retries.run, batch
        )
    )["reason"] == "manual_review_required"


def test_canonical_modules_import_and_every_beat_task_is_registered(flags, monkeypatch):
    celery_app.loader.import_default_modules()
    assert len(WORKER_MODULES) == 8 and not any(
        m.startswith("backend.") for m in WORKER_MODULES
    )
    assert build_beat_schedule() == {}
    monkeypatch.setattr(settings, "CELERY_BEAT_ENABLED", True)
    assert build_beat_schedule() == {}
    for name in ("WORKER_SLA_MONITOR_ENABLED", "WORKER_PRODUCTIVITY_ENABLED"):
        monkeypatch.setattr(settings, name, True)
    schedule = build_beat_schedule()
    assert len(schedule) == 2
    assert all(job["task"] in celery_app.tasks for job in schedule.values())
    assert not any(
        word in str(schedule) for word in ("liquidation", "cleanup", "notification")
    )
    assert (
        liquidation_worker.calculate_daily_productivity
        is productivity_worker.calculate_daily_productivity
    )


@pytest.mark.parametrize(
    "zone,day,hours",
    [
        ("UTC", date(2026, 3, 8), 24),
        ("America/New_York", date(2026, 3, 8), 23),
        ("America/New_York", date(2026, 11, 1), 25),
        ("America/Caracas", date(2026, 10, 29), 24),
    ],
)
def test_calendar_windows_are_half_open_utc_and_follow_dst(
    flags, monkeypatch, zone, day, hours
):
    monkeypatch.setattr(settings, "CELERY_TIMEZONE", zone)
    start, end = runtime.period(day)
    assert start.tzinfo is end.tzinfo is None
    assert (end - start).total_seconds() == hours * 3600
    assert runtime.period(day + timedelta(days=1))[0] == end


@pytest.mark.parametrize(
    "value",
    [
        "",
        "2026-1-01",
        "2026-02-30",
        "2026-10-30",
        "9999-12-31",
        "0001-01-01",
        "../../etc/passwd",
        42,
    ],
)
def test_unclosed_or_invalid_days_are_not_started(flags, value):
    with pytest.raises(ValueError):
        runtime.closed_day(value, datetime(2026, 10, 30, tzinfo=timezone.utc))


def test_previous_closed_day_depends_on_configured_zone(flags, monkeypatch):
    monkeypatch.setattr(settings, "CELERY_TIMEZONE", "America/Caracas")
    now = datetime(2026, 10, 30, 2, tzinfo=timezone.utc)
    assert runtime.closed_day(None, now) == date(2026, 10, 28)
    assert runtime.closed_day("2026-10-28", now) == date(2026, 10, 28)


@pytest.mark.parametrize("zone", ["not-a-zone", "../UTC", ""])
def test_invalid_timezone_is_a_configuration_error(zone):
    with pytest.raises(ValidationError):
        Settings(SECRET_KEY="test-only-key", CELERY_TIMEZONE=zone, _env_file=None)


@pytest.mark.parametrize(
    "task,args",
    [
        (productivity_worker.calculate_rider_productivity, ("bad", "bad")),
        (productivity_worker.calculate_daily_productivity, ()),
        (sla_monitor_worker.check_sla_breaches, ()),
        (notification_worker.process_notification_retries, ()),
        (report_worker.generate_daily_report, ("bad",)),
        (alert_worker.generate_operational_alert, ("bad", "bad", {})),
    ],
)
def test_disabled_tasks_return_before_any_database_or_transport(flags, task, args):
    assert task.run(*args) == {"success": False, "reason": "worker_disabled"}


@pytest.mark.parametrize(
    "task,args,reason",
    [
        (
            notification_worker.send_push_notification,
            ("private-user", "secret-title", "private-body"),
            "persisted_notification_required",
        ),
        (
            notification_worker.send_email_notification,
            ("private@example.test", "subject", "body"),
            "persisted_notification_required",
        ),
        (
            notification_worker.send_sms_notification,
            ("private-phone", "private-message"),
            "persisted_notification_required",
        ),
        (liquidation_worker.run_daily_liquidation, (), "verified_settlement_required"),
        (cleanup_worker.cleanup_old_data, (), "reviewed_retention_policy_required"),
    ],
)
def test_legacy_placeholders_cannot_claim_success_or_print_payload(
    task, args, reason, capsys
):
    result = task.run(*args)
    assert result["success"] is False and result["reason"] == reason
    assert not capsys.readouterr().out


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_worker_session_closes_and_disposes_on_every_result(monkeypatch, failure):
    db = AsyncMock()
    context = AsyncMock()
    context.__aenter__.return_value = db
    engine = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(runtime, "create_async_engine", MagicMock(return_value=engine))
    monkeypatch.setattr(runtime, "async_sessionmaker", lambda *a, **kw: lambda: context)
    if failure:
        with pytest.raises(RuntimeError):
            async with runtime.worker_session():
                raise RuntimeError("private-db-url")
        db.rollback.assert_awaited_once()
    else:
        async with runtime.worker_session() as session:
            assert session is db
    context.__aexit__.assert_awaited_once()
    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_task_retry_stores_generic_error_and_validation_is_not_retried():
    task = SimpleNamespace(retry=MagicMock(side_effect=RuntimeError("retry-marker")))

    async def invalid():
        raise ValueError("private-input")

    assert (await asyncio.to_thread(runtime.execute_task, task, invalid))[
        "reason"
    ] == "manual_review_required"
    task.retry.assert_not_called()

    async def failure():
        raise RuntimeError("private-database-url")

    with pytest.raises(RuntimeError, match="retry-marker") as raised:
        await asyncio.to_thread(runtime.execute_task, task, failure)
    assert str(task.retry.call_args.kwargs["exc"]) == "Worker operation unavailable"
    assert raised.value.__context__ is None


@pytest.mark.parametrize("kind", ["financial", "../../escape", "unknown"])
def test_unsupported_reports_never_create_files(flags, monkeypatch, kind):
    monkeypatch.setattr(settings, "WORKER_REPORTS_ENABLED", True)
    assert (
        report_worker.generate_daily_report.run("2026-10-28", kind)["success"] is False
    )


@pytest.mark.parametrize(
    "severity,details",
    [(None, {}), ("high", {}), ("high", {"delivery_id": 42}), ("normal", {})],
)
def test_invalid_alerts_do_not_attempt_database(flags, monkeypatch, severity, details):
    monkeypatch.setattr(settings, "WORKER_SLA_MONITOR_ENABLED", True)
    assert (
        alert_worker.generate_operational_alert.run("sla_warning", severity, details)[
            "success"
        ]
        is False
    )
