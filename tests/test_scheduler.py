from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.models import UserSettings
from app.store import InMemoryStore
from app.scheduler import run_tick, process_user, active_slot

TPE = ZoneInfo("Asia/Taipei")

def _tue(h, m):
    # 2026-06-30 是週二（在預設 enabled_days 內）
    return datetime(2026, 6, 30, h, m, tzinfo=TPE)


class FakeTDX:
    def __init__(self, entries=None, error=None):
        self.entries = entries or []
        self.error = error
        self.calls = 0

    async def get_eta(self, city, route, now):
        self.calls += 1
        if self.error:
            raise self.error
        return self.entries


class FakeTelegram:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))


def _morning_entry(estimate=300, status=0):
    return [{"StopName": {"Zh_tw": "臺南高工"},
             "SubRouteName": {"Zh_tw": "70左 永華市政中心 → 永華市政中心"},
             "StopStatus": status, "EstimateTime": estimate}]


async def _seed_user(store, chat_id=1):
    await store.save_user(UserSettings.default(chat_id))


def test_active_slot_picks_window():
    u = UserSettings.default(1)
    assert active_slot(_tue(8, 0), u) == "morning"
    assert active_slot(_tue(18, 45), u) == "evening"
    assert active_slot(_tue(12, 0), u) is None
    assert active_slot(_tue(9, 30), u) == "morning"  # 含結束點：09:30 仍推最後一則
    assert active_slot(_tue(9, 31), u) is None       # 超過 09:30 才停


async def test_first_push_sends_and_records_lastpush():
    store, tdx, tg = InMemoryStore(), FakeTDX(_morning_entry(420)), FakeTelegram()
    await _seed_user(store)
    await process_user(_tue(8, 0), await store.get_user(1), store, tdx, tg, "Tainan")
    assert len(tg.sent) == 1
    assert "預估 7 分鐘到「臺南高工」" in tg.sent[0][1]
    rt = await store.get_runtime(1, "2026-06-30")
    assert rt.morning.last_push_at == _tue(8, 0)


async def test_skips_when_not_due():
    store, tdx, tg = InMemoryStore(), FakeTDX(_morning_entry()), FakeTelegram()
    await _seed_user(store)
    # 先推一次
    await process_user(_tue(8, 0), await store.get_user(1), store, tdx, tg, "Tainan")
    # 5 分鐘後、預設間隔 10 分 → 不該再推
    await process_user(_tue(8, 5), await store.get_user(1), store, tdx, tg, "Tainan")
    assert len(tg.sent) == 1


async def test_skips_when_day_not_enabled():
    store, tdx, tg = InMemoryStore(), FakeTDX(_morning_entry()), FakeTelegram()
    u = UserSettings.default(1)
    u.enabled_days = [1]  # 只有週一
    await store.save_user(u)
    await process_user(_tue(8, 0), u, store, tdx, tg, "Tainan")
    assert tg.sent == []


async def test_stopped_slot_is_skipped():
    store, tdx, tg = InMemoryStore(), FakeTDX(_morning_entry()), FakeTelegram()
    await _seed_user(store)
    rt = await store.get_runtime(1, "2026-06-30")
    rt.morning.stopped = True
    await store.save_runtime(1, "2026-06-30", rt)
    await process_user(_tue(8, 0), await store.get_user(1), store, tdx, tg, "Tainan")
    assert tg.sent == []


async def test_interval_override_applies():
    store, tdx, tg = InMemoryStore(), FakeTDX(_morning_entry()), FakeTelegram()
    await _seed_user(store)
    rt = await store.get_runtime(1, "2026-06-30")
    rt.morning.interval_override = 5
    rt.morning.last_push_at = _tue(8, 0)
    await store.save_runtime(1, "2026-06-30", rt)
    # 5 分鐘後、override=5 → 應推
    await process_user(_tue(8, 5), await store.get_user(1), store, tdx, tg, "Tainan")
    assert len(tg.sent) == 1


async def test_failure_below_threshold_is_silent():
    from app.tdx import TDXError
    store, tdx, tg = InMemoryStore(), FakeTDX(error=TDXError("boom")), FakeTelegram()
    await _seed_user(store)
    await process_user(_tue(8, 0), await store.get_user(1), store, tdx, tg, "Tainan")
    assert tg.sent == []
    rt = await store.get_runtime(1, "2026-06-30")
    assert rt.morning.fail_count == 1
    assert rt.morning.stopped is False


async def test_second_consecutive_failure_pushes_error_and_stops():
    from app.tdx import TDXError
    from app.formatting import API_ERROR_TEXT
    store, tdx, tg = InMemoryStore(), FakeTDX(error=TDXError("boom")), FakeTelegram()
    await _seed_user(store)
    # 第一次失敗（靜默）
    await process_user(_tue(8, 0), await store.get_user(1), store, tdx, tg, "Tainan")
    # 第二次失敗（推一次錯誤並停）
    await process_user(_tue(8, 10), await store.get_user(1), store, tdx, tg, "Tainan")
    assert tg.sent == [(1, API_ERROR_TEXT, None)]
    rt = await store.get_runtime(1, "2026-06-30")
    assert rt.morning.stopped is True


async def test_success_resets_fail_count():
    from app.tdx import TDXError
    store, tg = InMemoryStore(), FakeTelegram()
    await _seed_user(store)
    failing = FakeTDX(error=TDXError("boom"))
    await process_user(_tue(8, 0), await store.get_user(1), store, failing, tg, "Tainan")
    ok = FakeTDX(_morning_entry())
    await process_user(_tue(8, 10), await store.get_user(1), store, ok, tg, "Tainan")
    rt = await store.get_runtime(1, "2026-06-30")
    assert rt.morning.fail_count == 0


async def test_queries_slot_specific_route():
    class RouteRecordingTDX:
        def __init__(self, entries):
            self.entries = entries
            self.routes = []

        async def get_eta(self, city, route, now):
            self.routes.append(route)
            return self.entries

    store, tg = InMemoryStore(), FakeTelegram()
    tdx = RouteRecordingTDX(_morning_entry())
    await _seed_user(store)
    await process_user(_tue(8, 0), await store.get_user(1), store, tdx, tg, "Tainan")
    assert tdx.routes == ["70"]  # RouteName 一律 "70"，左右靠 SubRouteName 區分


async def test_wrong_sub_route_is_not_pushed():
    # 只有 70右 的臺南高工，但上班時段要的是 70左 → 過濾後無匹配 → 不推
    entries = [{"StopName": {"Zh_tw": "臺南高工"},
                "SubRouteName": {"Zh_tw": "70右 …"}, "StopStatus": 0, "EstimateTime": 300}]
    store, tdx, tg = InMemoryStore(), FakeTDX(entries), FakeTelegram()
    await _seed_user(store)
    await process_user(_tue(8, 0), await store.get_user(1), store, tdx, tg, "Tainan")
    assert tg.sent == []
    rt = await store.get_runtime(1, "2026-06-30")
    assert rt.morning.fail_count == 1


async def test_run_tick_iterates_all_users():
    store, tdx, tg = InMemoryStore(), FakeTDX(_morning_entry()), FakeTelegram()
    await store.save_user(UserSettings.default(1))
    await store.save_user(UserSettings.default(2))
    await run_tick(_tue(8, 0), store, tdx, tg, "Tainan")
    assert {s[0] for s in tg.sent} == {1, 2}


async def test_run_tick_caches_route_calls_across_users():
    store, tdx, tg = InMemoryStore(), FakeTDX(_morning_entry()), FakeTelegram()
    await store.save_user(UserSettings.default(1))
    await store.save_user(UserSettings.default(2))
    await run_tick(_tue(8, 0), store, tdx, tg, "Tainan")
    assert {s[0] for s in tg.sent} == {1, 2}
    assert tdx.calls == 1  # Verify that only 1 TDX query was made for both users due to caching!


async def test_quota_exhausted_consecutive_failure_pushes_quota_error():
    from app.tdx import TDXError
    store, tdx, tg = InMemoryStore(), FakeTDX(error=TDXError("quota", status_code=429)), FakeTelegram()
    await _seed_user(store)
    # 第一次失敗（靜默）
    await process_user(_tue(8, 0), await store.get_user(1), store, tdx, tg, "Tainan")
    # 第二次失敗（推額度用完警告）
    await process_user(_tue(8, 10), await store.get_user(1), store, tdx, tg, "Tainan")
    assert tg.sent == [(1, "⚠️ TDX 公車 API 額度已用完，無法取得正確資訊。", None)]

