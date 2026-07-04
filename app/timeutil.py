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
    # 左閉右閉 [start, end]：結束時間那一分鐘（如 09:30、21:00）仍在窗內、仍會推最後一則
    return hhmm_to_minutes(window_start) <= current <= hhmm_to_minutes(window_end)


def is_due(now: datetime, last_push_at: datetime | None, interval_min: int, window_start: str) -> bool:
    now_mins = now.hour * 60 + now.minute
    start_mins = hhmm_to_minutes(window_start)
    minutes_since_start = now_mins - start_mins
    if minutes_since_start < 0:
        return False
    last_grid_mins = start_mins + (minutes_since_start // interval_min) * interval_min
    if last_push_at is None:
        # 當日首推也只在網格點觸發，避免冷啟/延遲造成 off-grid 首推
        return now_mins == last_grid_mins
    grid_time = now.replace(hour=last_grid_mins // 60, minute=last_grid_mins % 60, second=0, microsecond=0)
    if last_push_at >= grid_time:
        return False
    
    # 加入最小間隔防護：確保距離上次推播至少經過「設定間隔減1分鐘」的時間
    # 避免切換間隔時，因為剛好踩在下一個網格上而立刻觸發短間隔推播
    if (grid_time - last_push_at).total_seconds() < (interval_min - 1) * 60:
        return False
        
    return True
