from datetime import datetime
from zoneinfo import ZoneInfo
from app.models import SLOT_DEFAULTS
from app.formatting import format_eta_message, NO_DATA_TEXT, adjusted_seconds

M = SLOT_DEFAULTS["morning"]   # 70左 / 臺南高工
E = SLOT_DEFAULTS["evening"]   # 70右 / 中華西路二段


def _bus(status=0, est=None, plate=None):
    e = {"StopStatus": status, "EstimateTime": est}
    if plate is not None:
        e["PlateNumb"] = plate
    return e


TPE = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 6, 30, 8, 0, tzinfo=TPE)


def test_single_running_with_plate_floors_minutes():
    # 920s -> floor 15 分（非 ceil 16）
    assert format_eta_message(M, [_bus(0, 920, "EAA-732")], NOW) == \
        "🚌 70左 - EAA-732 預估 15 分鐘到「臺南高工」"


def test_single_running_without_plate():
    assert format_eta_message(M, [_bus(0, 400)], NOW) == \
        "🚌 70左 - 預估 6 分鐘到「臺南高工」"


def test_single_near_arrival_with_plate_has_station():
    assert format_eta_message(M, [_bus(0, 30, "EAA-732")], NOW) == \
        "🚌 70左 - EAA-732 即將進站到「臺南高工」"


def test_bug_a_status0_est0_is_near_arrival_not_error():
    assert format_eta_message(M, [_bus(0, 0, "EAA-732")], NOW) == \
        "🚌 70左 - EAA-732 即將進站到「臺南高工」"


def test_bug_a_status0_none_estimate_is_no_data():
    assert format_eta_message(M, [_bus(0, None)], NOW) == NO_DATA_TEXT


def test_bug_b_status1_with_estimate_shows_not_departed():
    assert format_eta_message(M, [_bus(1, 1726)], NOW) == "🚌 70左 - 尚未發車（臺南高工）"


def test_multi_two_running_sorted_with_plates():
    matches = [_bus(0, 1080, "EAA-728"), _bus(0, 480, "EAA-732")]
    assert format_eta_message(M, matches, NOW) == (
        "🚌 70左 到「臺南高工」\n"
        "・ EAA-732 預估 8 分鐘\n"
        "・ EAA-728 預估 18 分鐘"
    )


def test_multi_caps_at_three():
    matches = [_bus(0, 60 + 60 * i, f"P{i}") for i in range(1, 6)]  # 5 台
    out = format_eta_message(M, matches, NOW)
    assert out.count("・") == 3


def test_multi_near_arrival_line_uses_plate_phrase():
    matches = [_bus(0, 30, "EAA-732"), _bus(0, 1080, "EAA-728")]
    assert format_eta_message(M, matches, NOW) == (
        "🚌 70左 到「臺南高工」\n"
        "・ 即將進站的公車:EAA-732\n"
        "・ EAA-728 預估 18 分鐘"
    )


def test_multi_skips_not_departed_entries():
    # 一台行駛中 + 一台尚未發車(status1) → 只顯示單車格式
    matches = [_bus(0, 480, "EAA-732"), _bus(1, 1726)]
    assert format_eta_message(M, matches, NOW) == \
        "🚌 70左 - EAA-732 預估 8 分鐘到「臺南高工」"


def test_all_not_departed_shows_not_departed():
    assert format_eta_message(M, [_bus(1, None), _bus(1, None)], NOW) == \
        "🚌 70左 - 尚未發車（臺南高工）"


def test_status_precedence_prefers_terminal_states():
    # 末班車已過(3) 應蓋過殘留的尚未發車(1)
    assert format_eta_message(E, [_bus(1, None), _bus(3, None)], NOW) == \
        "🌙 70右 - 末班車已過"


def test_traffic_control():
    assert format_eta_message(M, [_bus(2, None)], NOW) == "🚧 70左 - 交管不停靠（臺南高工）"


def test_not_in_service():
    assert format_eta_message(E, [_bus(4, None)], NOW) == "70右 - 今日未營運"


def test_empty_matches_is_no_data():
    assert format_eta_message(M, [], NOW) == NO_DATA_TEXT


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


def test_end_to_end_staleness_and_floor():
    # EstimateTime=630、來源時間比 NOW 早 90 秒 → adjusted=540 → floor 9 分鐘
    entry = {"StopStatus": 0, "EstimateTime": 630,
             "SrcUpdateTime": "2026-06-30T07:58:30+08:00", "PlateNumb": "EAA-9"}
    assert format_eta_message(M, [entry], NOW) == "🚌 70左 - EAA-9 預估 9 分鐘到「臺南高工」"


def test_status_precedence_traffic_over_not_departed():
    assert format_eta_message(M, [_bus(1, None), _bus(2, None)], NOW) == \
        "🚧 70左 - 交管不停靠（臺南高工）"


def test_status_precedence_not_in_service_over_last_bus():
    assert format_eta_message(E, [_bus(3, None), _bus(4, None)], NOW) == "70右 - 今日未營運"


def test_multi_running_without_plates_uses_plain_lines():
    matches = [_bus(0, 480), _bus(0, 1080)]
    assert format_eta_message(M, matches, NOW) == (
        "🚌 70左 到「臺南高工」\n"
        "・ 預估 8 分鐘\n"
        "・ 預估 18 分鐘"
    )


def test_adjusted_seconds_ignores_naive_source_time():
    # naive(無時區)來源時間應被忽略,回退為原始秒數,不崩潰
    from app.formatting import adjusted_seconds
    entry = {"EstimateTime": 600, "SrcUpdateTime": "2026-06-30T07:59:00"}
    assert adjusted_seconds(entry, NOW) == 600
