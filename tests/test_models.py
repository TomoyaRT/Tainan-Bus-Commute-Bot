from datetime import datetime
from zoneinfo import ZoneInfo

from app.models import (
    SlotConfig, UserSettings, SlotRuntime, DayRuntime,
    VALID_INTERVALS, DEFAULT_ENABLED_DAYS,
)

TPE = ZoneInfo("Asia/Taipei")

def test_constants():
    assert VALID_INTERVALS == (5, 10, 15, 20)
    assert DEFAULT_ENABLED_DAYS == [1, 2, 3, 4, 5]

def test_user_default_uses_spec_defaults():
    u = UserSettings.default(123)
    assert u.chat_id == 123
    assert u.enabled_days == [1, 2, 3, 4, 5]
    assert u.slots["morning"].bus == "70左"
    assert u.slots["morning"].route == "70"
    assert u.slots["morning"].sub_route == "70左"
    assert u.slots["morning"].stop_name == "臺南高工"  # TDX 用「臺」非「台」
    assert u.slots["morning"].default_interval == 10
    assert u.slots["evening"].bus == "70右"
    assert u.slots["evening"].route == "70"
    assert u.slots["evening"].sub_route == "70右"
    assert u.slots["evening"].stop_name == "中華西路二段"
    assert u.slots["evening"].default_interval == 5

def test_user_roundtrip():
    u = UserSettings.default(123)
    u.enabled_days = [1, 2, 3]
    restored = UserSettings.from_dict(u.to_dict())
    assert restored.enabled_days == [1, 2, 3]
    assert restored.slots["evening"].window_end == "21:00"

def test_default_returns_independent_copies():
    a = UserSettings.default(1)
    a.slots["morning"].default_interval = 99
    b = UserSettings.default(2)
    assert b.slots["morning"].default_interval == 10

def test_day_runtime_roundtrip_with_datetime():
    r = DayRuntime()
    r.morning.last_push_at = datetime(2026, 6, 30, 8, 0, tzinfo=TPE)
    r.morning.fail_count = 1
    r.evening.stopped = True
    restored = DayRuntime.from_dict(r.to_dict())
    assert restored.morning.last_push_at == datetime(2026, 6, 30, 8, 0, tzinfo=TPE)
    assert restored.morning.fail_count == 1
    assert restored.evening.stopped is True
    assert restored.evening.last_push_at is None

def test_day_runtime_slot_accessor():
    r = DayRuntime()
    assert r.slot("morning") is r.morning
    assert r.slot("evening") is r.evening
