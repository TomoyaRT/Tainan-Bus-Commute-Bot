from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Taipei")


def hhmm_to_minutes(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def minutes_of_day(now: datetime) -> int:
    return now.hour * 60 + now.minute


def in_window(now: datetime, window_start: str, window_end: str) -> bool:
    current = minutes_of_day(now)
    return hhmm_to_minutes(window_start) <= current < hhmm_to_minutes(window_end)


def is_due(now: datetime, last_push_at: datetime | None, interval_min: int) -> bool:
    if last_push_at is None:
        return True
    return now - last_push_at >= timedelta(minutes=interval_min)
