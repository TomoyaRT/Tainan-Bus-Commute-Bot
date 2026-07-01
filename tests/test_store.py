from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.models import UserSettings, DayRuntime
from app.store import InMemoryStore

TPE = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 6, 30, 8, 0, tzinfo=TPE)


async def test_user_save_get_list():
    store = InMemoryStore()
    assert await store.get_user(1) is None
    await store.save_user(UserSettings.default(1))
    await store.save_user(UserSettings.default(2))
    got = await store.get_user(1)
    assert got.chat_id == 1
    assert {u.chat_id for u in await store.list_users()} == {1, 2}


async def test_runtime_defaults_when_missing():
    store = InMemoryStore()
    rt = await store.get_runtime(1, "2026-06-30")
    assert isinstance(rt, DayRuntime)
    assert rt.morning.stopped is False


async def test_runtime_save_and_roundtrip():
    store = InMemoryStore()
    rt = DayRuntime()
    rt.evening.interval_override = 15
    rt.evening.last_push_at = NOW
    await store.save_runtime(1, "2026-06-30", rt)
    again = await store.get_runtime(1, "2026-06-30")
    assert again.evening.interval_override == 15
    assert again.evening.last_push_at == NOW


async def test_runtime_isolated_per_date():
    store = InMemoryStore()
    rt = DayRuntime()
    rt.morning.stopped = True
    await store.save_runtime(1, "2026-06-30", rt)
    other = await store.get_runtime(1, "2026-07-01")
    assert other.morning.stopped is False


async def test_token_save_get():
    store = InMemoryStore()
    assert await store.get_tdx_token() is None
    exp = NOW + timedelta(hours=24)
    await store.save_tdx_token("tok", exp)
    assert await store.get_tdx_token() == ("tok", exp)
