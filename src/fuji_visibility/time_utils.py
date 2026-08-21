"""Timezone-safe parsing and formatting helpers."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import TIMEZONE

JST = ZoneInfo(TIMEZONE)


def ensure_aware(value: datetime, default_zone: ZoneInfo = JST) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=default_zone)
    return value


def to_jst(value: datetime) -> datetime:
    return ensure_aware(value).astimezone(JST)


def parse_datetime(value: str, *, default_zone: ZoneInfo = JST) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    return ensure_aware(parsed, default_zone)


def parse_date(value: str) -> date:
    return date.fromisoformat(value.strip())


def parse_clock(value: str) -> time:
    text = value.strip()
    parsed = time.fromisoformat(text)
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed.replace(second=0, microsecond=0)


def full_local_date_range(
    days: int,
    *,
    first_date: date | None = None,
) -> tuple[date, date]:
    """Return inclusive JST date bounds for a full-day forecast request.

    The Open-Meteo client always sends ``timezone=Asia/Tokyo``. Pairing these
    date bounds with that request parameter yields 00:00–23:00 JST for every
    forecast day, regardless of the dashboard's selected display range.
    """

    if days <= 0:
        raise ValueError("days must be positive")
    start = first_date or datetime.now(JST).date()
    return start, start + timedelta(days=days - 1)


def canonical_iso(value: datetime) -> str:
    """Return a stable JST ISO string for SQLite equality and display."""

    return to_jst(value).isoformat(timespec="seconds")


def display_datetime(value: datetime, with_seconds: bool = False) -> str:
    fmt = "%Y-%m-%d %H:%M:%S JST" if with_seconds else "%Y-%m-%d %H:%M JST"
    return to_jst(value).strftime(fmt)


def iter_run_times(start: datetime, end: datetime, interval_hours: int = 6) -> list[datetime]:
    """Generate UTC-aligned run times in an inclusive interval."""

    if interval_hours <= 0:
        raise ValueError("run interval must be positive")
    start_utc = ensure_aware(start).astimezone(timezone.utc)
    end_utc = ensure_aware(end).astimezone(timezone.utc)
    cursor = start_utc.replace(minute=0, second=0, microsecond=0)
    remainder = cursor.hour % interval_hours
    if remainder:
        cursor += timedelta(hours=interval_hours - remainder)
    result: list[datetime] = []
    while cursor <= end_utc:
        result.append(cursor)
        cursor += timedelta(hours=interval_hours)
    return result
