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
    return [{"StopName": {"Zh_tw": "台南高工"}, "StopStatus": status, "EstimateTime": estimate}]


async def _seed_user(store, chat_id=1):
    await store.save_user(UserSettings.default(chat_id))


def test_active_slot_picks_window():
    u = UserSettings.default(1)
    assert active_slot(_tue(8, 0), u) == "morning"
    assert active_slot(_tue(18, 45), u) == "evening"
    assert active_slot(_tue(12, 0), u) is None
    assert active_slot(_tue(9, 30), u) is None  # 窗口結束，自動停


async def test_first_push_sends_and_records_lastpush():
    store, tdx, tg = InMemoryStore(), FakeTDX(_morning_entry(420)), FakeTelegram()
    await _seed_user(store)
    await process_user(_tue(8, 0), await store.get_user(1), store, tdx, tg, "Tainan", "70")
    assert len(tg.sent) == 1
    assert "預估 7 分鐘到「台南高工」" in tg.sent[0][1]
    rt = await store.get_runtime(1, "2026-06-30")
    assert rt.morning.last_push_at == _tue(8, 0)


async def test_skips_when_not_due():
    store, tdx, tg = InMemoryStore(), FakeTDX(_morning_entry()), FakeTelegram()
    await _seed_user(store)
    # 先推一次
    await process_user(_tue(8, 0), await store.get_user(1), store, tdx, tg, "Tainan", "70")
    # 5 分鐘後、預設間隔 10 分 → 不該再推
    await process_user(_tue(8, 5), await store.get_user(1), store, tdx, tg, "Tainan", "70")
    assert len(tg.sent) == 1


async def test_skips_when_day_not_enabled():
    store, tdx, tg = InMemoryStore(), FakeTDX(_morning_entry()), FakeTelegram()
    u = UserSettings.default(1)
    u.enabled_days = [1]  # 只有週一
    await store.save_user(u)
    await process_user(_tue(8, 0), u, store, tdx, tg, "Tainan", "70")
    assert tg.sent == []


async def test_stopped_slot_is_skipped():
    store, tdx, tg = InMemoryStore(), FakeTDX(_morning_entry()), FakeTelegram()
    await _seed_user(store)
    rt = await store.get_runtime(1, "2026-06-30")
    rt.morning.stopped = True
    await store.save_runtime(1, "2026-06-30", rt)
    await process_user(_tue(8, 0), await store.get_user(1), store, tdx, tg, "Tainan", "70")
    assert tg.sent == []


async def test_interval_override_applies():
    store, tdx, tg = InMemoryStore(), FakeTDX(_morning_entry()), FakeTelegram()
    await _seed_user(store)
    rt = await store.get_runtime(1, "2026-06-30")
    rt.morning.interval_override = 5
    rt.morning.last_push_at = _tue(8, 0)
    await store.save_runtime(1, "2026-06-30", rt)
    # 5 分鐘後、override=5 → 應推
    await process_user(_tue(8, 5), await store.get_user(1), store, tdx, tg, "Tainan", "70")
    assert len(tg.sent) == 1


async def test_failure_below_threshold_is_silent():
    from app.tdx import TDXError
    store, tdx, tg = InMemoryStore(), FakeTDX(error=TDXError("boom")), FakeTelegram()
    await _seed_user(store)
    await process_user(_tue(8, 0), await store.get_user(1), store, tdx, tg, "Tainan", "70")
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
    await process_user(_tue(8, 0), await store.get_user(1), store, tdx, tg, "Tainan", "70")
    # 第二次失敗（推一次錯誤並停）
    await process_user(_tue(8, 10), await store.get_user(1), store, tdx, tg, "Tainan", "70")
    assert tg.sent == [(1, API_ERROR_TEXT, None)]
    rt = await store.get_runtime(1, "2026-06-30")
    assert rt.morning.stopped is True


async def test_success_resets_fail_count():
    from app.tdx import TDXError
    store, tg = InMemoryStore(), FakeTelegram()
    await _seed_user(store)
    failing = FakeTDX(error=TDXError("boom"))
    await process_user(_tue(8, 0), await store.get_user(1), store, failing, tg, "Tainan", "70")
    ok = FakeTDX(_morning_entry())
    await process_user(_tue(8, 10), await store.get_user(1), store, ok, tg, "Tainan", "70")
    rt = await store.get_runtime(1, "2026-06-30")
    assert rt.morning.fail_count == 0


async def test_run_tick_iterates_all_users():
    store, tdx, tg = InMemoryStore(), FakeTDX(_morning_entry()), FakeTelegram()
    await store.save_user(UserSettings.default(1))
    await store.save_user(UserSettings.default(2))
    await run_tick(_tue(8, 0), store, tdx, tg, "Tainan", "70")
    assert {s[0] for s in tg.sent} == {1, 2}
