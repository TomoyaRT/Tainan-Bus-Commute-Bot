from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.timeutil import TZ, hhmm_to_minutes, minutes_of_day, in_window, is_due

TPE = ZoneInfo("Asia/Taipei")

def _at(h, m):
    return datetime(2026, 6, 30, h, m, tzinfo=TPE)

def test_tz_is_taipei():
    assert TZ.key == "Asia/Taipei"

def test_hhmm_to_minutes():
    assert hhmm_to_minutes("08:00") == 480
    assert hhmm_to_minutes("09:30") == 570

def test_minutes_of_day():
    assert minutes_of_day(_at(8, 5)) == 485

def test_in_window_inclusive_both_ends():
    assert in_window(_at(8, 0), "08:00", "09:30") is True
    assert in_window(_at(9, 29), "08:00", "09:30") is True
    assert in_window(_at(9, 30), "08:00", "09:30") is True   # 含結束點：最後一則
    assert in_window(_at(9, 31), "08:00", "09:30") is False  # 超過結束點才停
    assert in_window(_at(7, 59), "08:00", "09:30") is False

def test_is_due_first_push_when_no_last():
    assert is_due(_at(8, 0), None, 10, "08:00") is True


def test_is_due_first_push_aligns_to_grid():
    # 冷啟/延遲在 08:03 才首跑（window 08:00 / interval 10）→ 非網格點，不推
    assert is_due(_at(8, 3), None, 10, "08:00") is False
    # 08:10 為網格點 → 首推
    assert is_due(_at(8, 10), None, 10, "08:00") is True

def test_is_due_respects_interval():
    last = _at(8, 0)
    assert is_due(last + timedelta(minutes=9), last, 10, "08:00") is False
    assert is_due(last + timedelta(minutes=10), last, 10, "08:00") is True

def test_is_due_time_grid_alignment():
    # window_start is 17:00.
    # User sets interval to 5 min at 17:13.
    # Last push was at 17:10.
    last = _at(17, 10)
    
    # At 17:13, it should not trigger (since 17:13 is not at or after 17:15 grid)
    assert is_due(_at(17, 13), last, 5, "17:00") is False
    
    # At 17:15, it should trigger (since it is at/after 17:15 grid and last_push_at < 17:15)
    assert is_due(_at(17, 15), last, 5, "17:00") is True
