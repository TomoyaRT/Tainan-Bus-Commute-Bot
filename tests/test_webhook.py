from datetime import datetime
from zoneinfo import ZoneInfo

from app.models import UserSettings
from app.store import InMemoryStore
from app.keyboards import days_to_mask
from app.webhook import handle_update, BTN_INTERVAL, BTN_STOPS, BTN_DAYS

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


def _msg(text, chat_id=1):
    return {"message": {"chat": {"id": chat_id}, "text": text}}


def _cb(data, chat_id=1, message_id=50, cb_id="cb"):
    return {"callback_query": {"id": cb_id, "data": data,
                               "message": {"chat": {"id": chat_id}, "message_id": message_id}}}


async def test_start_creates_user_and_shows_keyboard():
    store, tg = InMemoryStore(), FakeTelegram()
    await handle_update(_msg("/start"), store, tg, NOW)
    assert await store.get_user(1) is not None
    assert tg.sent[0][2]["is_persistent"] is True


async def test_stop_button_marks_slot_stopped_today():
    store, tg = InMemoryStore(), FakeTelegram()
    await store.save_user(UserSettings.default(1))
    await handle_update(_cb("stop:morning"), store, tg, NOW)
    rt = await store.get_runtime(1, "2026-06-30")
    assert rt.morning.stopped is True
    assert tg.answers[0][1] == "已停止今日上班推播"


async def test_interval_button_opens_today_picker():
    store, tg = InMemoryStore(), FakeTelegram()
    await store.save_user(UserSettings.default(1))
    await handle_update(_cb("interval:evening"), store, tg, NOW)
    datas = [b["callback_data"] for b in tg.sent[0][2]["inline_keyboard"][0]]
    assert datas[0] == "setint:today:evening:5"


async def test_setint_today_writes_override():
    store, tg = InMemoryStore(), FakeTelegram()
    await store.save_user(UserSettings.default(1))
    await handle_update(_cb("setint:today:evening:15"), store, tg, NOW)
    rt = await store.get_runtime(1, "2026-06-30")
    assert rt.evening.interval_override == 15


async def test_setint_default_writes_user_setting():
    store, tg = InMemoryStore(), FakeTelegram()
    await store.save_user(UserSettings.default(1))
    await handle_update(_cb("setint:default:morning:20"), store, tg, NOW)
    u = await store.get_user(1)
    assert u.slots["morning"].default_interval == 20


async def test_interval_reply_button_asks_slot():
    store, tg = InMemoryStore(), FakeTelegram()
    await store.save_user(UserSettings.default(1))
    await handle_update(_msg(BTN_INTERVAL), store, tg, NOW)
    datas = [b["callback_data"] for b in tg.sent[0][2]["inline_keyboard"][0]]
    assert datas == ["slotpick:defint:morning", "slotpick:defint:evening"]


async def test_stops_reply_button_shows_readonly_text():
    store, tg = InMemoryStore(), FakeTelegram()
    await store.save_user(UserSettings.default(1))
    await handle_update(_msg(BTN_STOPS), store, tg, NOW)
    assert "台南高工" in tg.sent[0][1]
    assert "中華西路二段" in tg.sent[0][1]


async def test_days_reply_button_shows_picker_with_current():
    store, tg = InMemoryStore(), FakeTelegram()
    await store.save_user(UserSettings.default(1))  # 預設 [2,3,4,5,6]
    await handle_update(_msg(BTN_DAYS), store, tg, NOW)
    submit = tg.sent[0][2]["inline_keyboard"][-1][0]
    assert submit["callback_data"] == f"daysub:{days_to_mask([2,3,4,5,6])}"


async def test_day_toggle_edits_keyboard():
    store, tg = InMemoryStore(), FakeTelegram()
    await store.save_user(UserSettings.default(1))
    mask = days_to_mask([2, 3, 4, 5, 6])
    await handle_update(_cb(f"day:1:{mask}"), store, tg, NOW)  # 開啟週一
    new_submit = tg.edits[0][2]["inline_keyboard"][-1][0]
    assert new_submit["callback_data"] == f"daysub:{days_to_mask([1,2,3,4,5,6])}"


async def test_daysub_persists_enabled_days():
    store, tg = InMemoryStore(), FakeTelegram()
    await store.save_user(UserSettings.default(1))
    await handle_update(_cb(f"daysub:{days_to_mask([1,2,3])}"), store, tg, NOW)
    u = await store.get_user(1)
    assert u.enabled_days == [1, 2, 3]
    assert tg.answers[0][1] == "已更新推播日"


async def test_malformed_callback_does_not_raise_and_answers():
    # 壞掉/過期的 callback_data（間隔值非數字）不應拋例外造成 webhook 500
    store, tg = InMemoryStore(), FakeTelegram()
    await store.save_user(UserSettings.default(1))
    await handle_update(_cb("setint:today:morning:abc"), store, tg, NOW)
    assert tg.answers and tg.answers[0][0] == "cb"  # 仍回應以停止載入圈


async def test_unknown_callback_kind_is_answered():
    store, tg = InMemoryStore(), FakeTelegram()
    await store.save_user(UserSettings.default(1))
    await handle_update(_cb("bogus:x"), store, tg, NOW)
    assert tg.answers == [("cb", None)]
