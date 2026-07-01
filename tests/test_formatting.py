from app.models import SLOT_DEFAULTS
from app.formatting import format_eta_message, API_ERROR_TEXT

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
