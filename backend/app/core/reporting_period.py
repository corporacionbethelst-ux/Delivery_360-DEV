"""Bounded local calendar windows, queried as half-open UTC timestamps."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from app.core.config import settings


def utc_naive(value: datetime) -> datetime:
    return (
        value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
    )


def aware_utc(value: datetime) -> datetime:
    return utc_naive(value).replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class ReportingWindow:
    start: datetime
    end: datetime
    zone: str
    dates: tuple[date, ...]


def calendar_window(days: int = 7, now: datetime | None = None) -> ReportingWindow:
    if type(days) is not int or not 1 <= days <= 31:
        raise ValueError("El período admite entre 1 y 31 días")
    clock = aware_utc(now or datetime.now(timezone.utc))
    zone = ZoneInfo(settings.CELERY_TIMEZONE)
    today = clock.astimezone(zone).date()
    first = today - timedelta(days=days - 1)
    start = (
        datetime.combine(first, time(), zone)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    return ReportingWindow(
        start,
        utc_naive(clock),
        zone.key,
        tuple(first + timedelta(days=i) for i in range(days)),
    )


def explicit_window(start: datetime, end: datetime) -> ReportingWindow:
    start, end = utc_naive(start), utc_naive(end)
    if end <= start or end - start > timedelta(days=32):
        raise ValueError("El intervalo debe ser positivo y no superar 32 días")
    zone = ZoneInfo(settings.CELERY_TIMEZONE)
    first = aware_utc(start).astimezone(zone).date()
    last = aware_utc(end - timedelta(microseconds=1)).astimezone(zone).date()
    return ReportingWindow(
        start,
        end,
        zone.key,
        tuple(first + timedelta(days=i) for i in range((last - first).days + 1)),
    )
