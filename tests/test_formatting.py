from datetime import datetime
from zoneinfo import ZoneInfo
from app.models import SLOT_DEFAULTS
from app.formatting import format_eta_message, API_ERROR_TEXT, adjusted_seconds

M = SLOT_DEFAULTS["morning"]   # 70左 / 臺南高工
E = SLOT_DEFAULTS["evening"]   # 70右 / 中華西路二段

def test_normal_eta_rounds_up_minutes():
    assert format_eta_message(M, 0, 400) == "🚌 70左 - 預估 7 分鐘到「臺南高工」"

def test_near_arrival_within_60s():
    assert format_eta_message(M, 0, 30) == "🚌 70左 - 進站中，即將到「臺南高工」"
    assert format_eta_message(M, 0, 60) == "🚌 70左 - 進站中，即將到「臺南高工」"

def test_not_departed():
    assert format_eta_message(M, 1, None) == "🚌 70左 - 尚未發車（臺南高工）"

def test_not_departed_with_estimate():
    assert format_eta_message(M, 1, 600) == "🚌 70左 - 預估 10 分鐘到「臺南高工」"

def test_traffic_control():
    assert format_eta_message(M, 2, None) == "🚧 70左 - 交管不停靠（臺南高工）"

def test_last_bus_passed():
    assert format_eta_message(E, 3, None) == "🌙 70右 - 末班車已過"

def test_not_in_service():
    assert format_eta_message(E, 4, None) == "70右 - 今日未營運"

def test_unknown_status_falls_back_to_error_text():
    assert format_eta_message(E, 99, None) == API_ERROR_TEXT

def test_status0_none_estimate_falls_back_to_error_text():
    assert format_eta_message(M, 0, None) == API_ERROR_TEXT


TPE = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 6, 30, 8, 0, tzinfo=TPE)


def test_adjusted_seconds_none_when_no_estimate():
    assert adjusted_seconds({"EstimateTime": None}, NOW) is None
    assert adjusted_seconds({}, NOW) is None


def test_adjusted_seconds_without_source_time_uses_raw():
    assert adjusted_seconds({"EstimateTime": 630}, NOW) == 630


def test_adjusted_seconds_subtracts_snapshot_elapsed():
    # 來源時間比 now 早 90 秒 → 630 - 90 = 540
    entry = {"EstimateTime": 630, "SrcUpdateTime": "2026-06-30T07:58:30+08:00"}
    assert adjusted_seconds(entry, NOW) == 540


def test_adjusted_seconds_clamped_to_zero():
    entry = {"EstimateTime": 30, "SrcUpdateTime": "2026-06-30T07:58:30+08:00"}
    assert adjusted_seconds(entry, NOW) == 0


def test_adjusted_seconds_falls_back_to_datatime():
    entry = {"EstimateTime": 600, "DataTime": "2026-06-30T07:59:00+08:00"}
    assert adjusted_seconds(entry, NOW) == 540
