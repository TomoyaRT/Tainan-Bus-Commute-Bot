from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.models import UserSettings
from app.store import InMemoryStore
from app.keyboards import days_to_mask, BTN_PUSH_NOW, BTN_SETTINGS
from app.webhook import handle_update

TPE = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 6, 30, 8, 0, tzinfo=TPE)


class FakeTelegram:
    def __init__(self):
        self.sent = []
        self.answers = []
        self.edits = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))

    async def answer_callback_query(self, cb_id, text=None):
        self.answers.append((cb_id, text))

    async def edit_message_reply_markup(self, chat_id, message_id, reply_markup):
        self.edits.append((chat_id, message_id, reply_markup))


class FakeTDX:
    def __init__(self, entries):
        self.entries = entries
        self.calls = 0

    async def get_eta(self, city, route, now):
        self.calls += 1
        return self.entries


def _both_stops_entries():
    return [
        {"StopName": {"Zh_tw": "臺南高工"}, "SubRouteName": {"Zh_tw": "70左 …"},
         "StopStatus": 0, "EstimateTime": 480},
        {"StopName": {"Zh_tw": "中華西路二段"}, "SubRouteName": {"Zh_tw": "70右 …"},
         "StopStatus": 0, "EstimateTime": 300},
    ]


def _msg(text, chat_id=1):
    return {"message": {"chat": {"id": chat_id}, "text": text}}


def _cb(data, chat_id=1, message_id=50, cb_id="cb"):
    return {"callback_query": {"id": cb_id, "data": data,
                               "message": {"chat": {"id": chat_id}, "message_id": message_id}}}


# ── 底部鍵盤與 /start ──

async def test_start_creates_user_and_shows_persistent_keyboard():
    store, tg = InMemoryStore(), FakeTelegram()
    await handle_update(_msg("/start"), store, tg, NOW)
    assert await store.get_user(1) is not None
    kb = tg.sent[0][2]
    assert kb["is_persistent"] is True
    assert [b["text"] for b in kb["keyboard"][0]] == [BTN_PUSH_NOW, BTN_SETTINGS]


async def test_settings_button_opens_menu():
    store, tg = InMemoryStore(), FakeTelegram()
    await store.save_user(UserSettings.default(1))
    await handle_update(_msg(BTN_SETTINGS), store, tg, NOW)
    datas = [b["callback_data"] for b in tg.sent[0][2]["inline_keyboard"][0]]
    assert datas == ["menu:interval", "menu:days", "menu:stops"]


# ── 設定選單各分支 ──

async def test_menu_interval_asks_slot():
    store, tg = InMemoryStore(), FakeTelegram()
    await store.save_user(UserSettings.default(1))
    await handle_update(_cb("menu:interval"), store, tg, NOW)
    datas = [b["callback_data"] for b in tg.sent[0][2]["inline_keyboard"][0]]
    assert datas == ["slotpick:defint:morning", "slotpick:defint:evening"]


async def test_menu_stops_shows_readonly_text():
    store, tg = InMemoryStore(), FakeTelegram()
    await store.save_user(UserSettings.default(1))
    await handle_update(_cb("menu:stops"), store, tg, NOW)
    assert "臺南高工" in tg.sent[0][1]
    assert "中華西路二段" in tg.sent[0][1]


async def test_menu_days_shows_picker_with_current():
    store, tg = InMemoryStore(), FakeTelegram()
    await store.save_user(UserSettings.default(1))  # 預設 [2,3,4,5,6]
    await handle_update(_cb("menu:days"), store, tg, NOW)
    submit = tg.sent[0][2]["inline_keyboard"][-1][0]
    assert submit["callback_data"] == f"daysub:{days_to_mask([2,3,4,5,6])}"
    assert submit["text"] == "⏰ 保存設定"


# ── 間隔設定（含確認訊息，回饋 1）──

async def test_setint_today_writes_override_and_confirms():
    store, tg = InMemoryStore(), FakeTelegram()
    await store.save_user(UserSettings.default(1))
    await handle_update(_cb("setint:today:evening:15"), store, tg, NOW)
    rt = await store.get_runtime(1, "2026-06-30")
    assert rt.evening.interval_override == 15
    assert any("15 分鐘" in s[1] for s in tg.sent)  # 有明確的完成回饋訊息


async def test_setint_default_writes_user_setting_and_confirms():
    store, tg = InMemoryStore(), FakeTelegram()
    await store.save_user(UserSettings.default(1))
    await handle_update(_cb("setint:default:morning:20"), store, tg, NOW)
    u = await store.get_user(1)
    assert u.slots["morning"].default_interval == 20
    assert any("20 分鐘" in s[1] for s in tg.sent)


async def test_slot_interval_from_scheduled_push_opens_today_picker():
    store, tg = InMemoryStore(), FakeTelegram()
    await store.save_user(UserSettings.default(1))
    await handle_update(_cb("interval:evening"), store, tg, NOW)
    datas = [b["callback_data"] for b in tg.sent[0][2]["inline_keyboard"][0]]
    assert datas[0] == "setint:today:evening:5"


# ── 停止推播（含確認訊息）──

async def test_stop_button_marks_slot_stopped_today():
    store, tg = InMemoryStore(), FakeTelegram()
    await store.save_user(UserSettings.default(1))
    await handle_update(_cb("stop:morning"), store, tg, NOW)
    rt = await store.get_runtime(1, "2026-06-30")
    assert rt.morning.stopped is True
    assert tg.answers[0][1] == "已停止今日上班推播"
    assert any("已停止今日上班推播" in s[1] for s in tg.sent)


# ── 推播時間複選（回饋 2）──

async def test_day_toggle_edits_keyboard():
    store, tg = InMemoryStore(), FakeTelegram()
    await store.save_user(UserSettings.default(1))
    mask = days_to_mask([2, 3, 4, 5, 6])
    await handle_update(_cb(f"day:1:{mask}"), store, tg, NOW)  # 開啟週一
    new_submit = tg.edits[0][2]["inline_keyboard"][-1][0]
    assert new_submit["callback_data"] == f"daysub:{days_to_mask([1,2,3,4,5,6])}"


async def test_daysub_persists_and_confirms():
    store, tg = InMemoryStore(), FakeTelegram()
    await store.save_user(UserSettings.default(1))
    await handle_update(_cb(f"daysub:{days_to_mask([1,2,3])}"), store, tg, NOW)
    u = await store.get_user(1)
    assert u.enabled_days == [1, 2, 3]
    assert tg.answers[0][1] == "已更新推播日"
    assert any("週一、週二、週三" in s[1] for s in tg.sent)  # 明確列出已選


# ── 立即推播（回饋 3：主動按鈕 + 冷卻）──

async def test_push_now_sends_both_stops_with_single_tdx_call():
    store, tg = InMemoryStore(), FakeTelegram()
    await store.save_user(UserSettings.default(1))
    tdx = FakeTDX(_both_stops_entries())
    await handle_update(_msg(BTN_PUSH_NOW), store, tg, NOW, tdx, "Tainan")
    assert tdx.calls == 1  # 兩時段同 RouteName "70"，只打一次
    body = tg.sent[0][1]
    assert "臺南高工" in body and "中華西路二段" in body


async def test_push_now_cooldown_blocks_repeat_then_recovers():
    store, tg = InMemoryStore(), FakeTelegram()
    await store.save_user(UserSettings.default(1))
    tdx = FakeTDX(_both_stops_entries())
    await handle_update(_msg(BTN_PUSH_NOW), store, tg, NOW, tdx, "Tainan")
    # 冷卻內再點 → 不打 TDX，回倒數訊息
    await handle_update(_msg(BTN_PUSH_NOW), store, tg, NOW + timedelta(minutes=2), tdx, "Tainan")
    assert tdx.calls == 1
    assert "需等待" in tg.sent[-1][1]
    # 冷卻結束（5 分）後 → 可再推
    await handle_update(_msg(BTN_PUSH_NOW), store, tg, NOW + timedelta(minutes=6), tdx, "Tainan")
    assert tdx.calls == 2


# ── 防呆 ──

async def test_malformed_callback_does_not_raise_and_answers():
    store, tg = InMemoryStore(), FakeTelegram()
    await store.save_user(UserSettings.default(1))
    await handle_update(_cb("setint:today:morning:abc"), store, tg, NOW)
    assert tg.answers and tg.answers[0][0] == "cb"


async def test_unknown_callback_kind_is_answered():
    store, tg = InMemoryStore(), FakeTelegram()
    await store.save_user(UserSettings.default(1))
    await handle_update(_cb("bogus:x"), store, tg, NOW)
    assert tg.answers == [("cb", None)]


async def test_push_now_quota_exhausted_sends_quota_error():
    from app.tdx import TDXError
    store, tg = InMemoryStore(), FakeTelegram()
    await store.save_user(UserSettings.default(1))

    class QuotaFailingTDX:
        async def get_eta(self, city, route, now):
            raise TDXError("quota", status_code=429)

    await handle_update(_msg(BTN_PUSH_NOW), store, tg, NOW, QuotaFailingTDX(), "Tainan")
    assert tg.sent[-1][1] == "⚠️ TDX 公車 API 額度已用完，無法取得正確資訊。"

