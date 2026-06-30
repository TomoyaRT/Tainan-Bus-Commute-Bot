# 台南公車通知 Bot — Plan 3：服務邏輯 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 串起排程推播邏輯（`/tick`）、Telegram 互動處理（`/webhook`）與 FastAPI 入口，產出可在本機實際運作的服務。

**Architecture:** `scheduler.py` 負責「每次 tick 決定誰要推播」的純編排（注入 store/tdx/telegram）；`webhook.py` 處理按鈕 callback 與指令；`main.py` 用 FastAPI 接 `/tick`、`/webhook` 並做存取驗證。整合測試以 `InMemoryStore` + 假 TDX/Telegram 驗證行為。前置依賴：Plan 1、Plan 2。

**Tech Stack:** FastAPI、uvicorn、httpx、pytest-asyncio。

## Global Constraints

- 同 Plan 1/2。
- `FAIL_THRESHOLD = 2`：同一時段當天連續失敗達 2 次 → 推一次 `API_ERROR_TEXT` 並停該時段。
- 時段判定順序：先 morning 後 evening；兩者窗口不重疊。
- 自動停：超過窗口結束時間後 `active_slot` 回傳 `None`，當次 tick 不推播（等同自動停）。
- `/tick` 以標頭 `X-Tick-Token` 驗證（比對環境變數 `TICK_AUTH_TOKEN`）。
- `/webhook` 以標頭 `X-Telegram-Bot-Api-Secret-Token` 驗證（比對 `TELEGRAM_WEBHOOK_SECRET`）。
- 「日複選」採 stateless mask：callback `day:{d}:{mask}` 切換、`daysub:{mask}` 送出。

---

### Task 9: 排程推播邏輯 `scheduler`

**Files:**
- Create: `app/scheduler.py`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `app.timeutil.in_window/is_due`、`app.formatting.format_eta_message/API_ERROR_TEXT`、`app.keyboards.push_inline_keyboard`、`app.tdx.select_stop/TDXError`
- Produces:
  - `FAIL_THRESHOLD = 2`
  - `active_slot(now: datetime, settings: UserSettings) -> str | None`
  - `async process_user(now, settings, store, tdx, telegram, city, route) -> None`
  - `async run_tick(now, store, tdx, telegram, city, route) -> None`

- [ ] **Step 1: 寫失敗測試 `tests/test_scheduler.py`**

```python
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
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.scheduler'`

- [ ] **Step 3: 實作 `app/scheduler.py`**

```python
from __future__ import annotations

from datetime import datetime

from app.formatting import API_ERROR_TEXT, format_eta_message
from app.keyboards import push_inline_keyboard
from app.models import UserSettings
from app.tdx import TDXError, select_stop
from app.timeutil import in_window, is_due

FAIL_THRESHOLD = 2


def active_slot(now: datetime, settings: UserSettings) -> str | None:
    for name in ("morning", "evening"):
        cfg = settings.slots[name]
        if in_window(now, cfg.window_start, cfg.window_end):
            return name
    return None


async def process_user(now, settings, store, tdx, telegram, city, route) -> None:
    if now.isoweekday() not in settings.enabled_days:
        return
    slot = active_slot(now, settings)
    if slot is None:
        return

    date_str = now.strftime("%Y-%m-%d")
    runtime = await store.get_runtime(settings.chat_id, date_str)
    sr = runtime.slot(slot)
    cfg = settings.slots[slot]

    if sr.stopped:
        return

    interval = sr.interval_override or cfg.default_interval
    if not is_due(now, sr.last_push_at, interval):
        return

    try:
        entries = await tdx.get_eta(city, route, now)
        match = select_stop(entries, cfg.stop_name)
        if match is None:
            raise TDXError("target stop not found")
        sr.fail_count = 0
        status = int(match.get("StopStatus", 0))
        estimate = match.get("EstimateTime")
        text = format_eta_message(cfg, status, estimate)
        await telegram.send_message(settings.chat_id, text, push_inline_keyboard(slot))
        sr.last_push_at = now
    except TDXError:
        sr.fail_count += 1
        if sr.fail_count >= FAIL_THRESHOLD:
            await telegram.send_message(settings.chat_id, API_ERROR_TEXT)
            sr.stopped = True

    await store.save_runtime(settings.chat_id, date_str, runtime)


async def run_tick(now, store, tdx, telegram, city, route) -> None:
    for settings in await store.list_users():
        await process_user(now, settings, store, tdx, telegram, city, route)
```

- [ ] **Step 4: 執行測試確認通過**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: PASS（11 passed）

- [ ] **Step 5: Commit**

```bash
git add app/scheduler.py tests/test_scheduler.py
git commit -m "feat: 排程推播邏輯 scheduler（到期/失敗即停/自動停）"
```

---

### Task 10: Webhook 互動處理 `webhook`

**Files:**
- Create: `app/webhook.py`
- Test: `tests/test_webhook.py`

**Interfaces:**
- Consumes: `app.keyboards.*`、`app.models.UserSettings`
- Produces:
  - 常數 `BTN_INTERVAL`、`BTN_STOPS`、`BTN_DAYS`
  - `async handle_update(update: dict, store, telegram, now: datetime) -> None`

互動規格：
- 指令 `/start`：建立預設使用者（若無）→ 送歡迎詞 + 常駐設定鍵盤。
- reply 鍵盤文字：
  - `⏱ 推播間隔` → 送 `slot_choice_keyboard("defint")`
  - `🚏 推播公車站` → 送唯讀站牌說明
  - `📅 推播時間` → 送 `day_picker_keyboard(目前 enabled_days mask)`
- callback：
  - `stop:{slot}` → 設當天該時段 `stopped=True`，answer「已停止今日{時段}推播」
  - `interval:{slot}` → answer + 送 `interval_picker_keyboard("today", slot)`
  - `setint:today:{slot}:{val}` → 設當天 `interval_override`，answer
  - `setint:default:{slot}:{val}` → 設使用者 `default_interval`，answer
  - `slotpick:defint:{slot}` → answer + 送 `interval_picker_keyboard("default", slot)`
  - `day:{d}:{mask}` → 編輯訊息鍵盤為 `day_picker_keyboard(mask ^ bit)`，answer
  - `daysub:{mask}` → 設 `enabled_days = mask_to_days(mask)`，answer「已更新推播日」

- [ ] **Step 1: 寫失敗測試 `tests/test_webhook.py`**

```python
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
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python -m pytest tests/test_webhook.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.webhook'`

- [ ] **Step 3: 實作 `app/webhook.py`**

```python
from __future__ import annotations

from datetime import datetime

from app.keyboards import (
    SLOT_LABELS, day_picker_keyboard, days_to_mask, interval_picker_keyboard,
    mask_to_days, settings_reply_keyboard, slot_choice_keyboard,
)
from app.models import UserSettings

BTN_INTERVAL = "⏱ 推播間隔"
BTN_STOPS = "🚏 推播公車站"
BTN_DAYS = "📅 推播時間"


async def handle_update(update: dict, store, telegram, now: datetime) -> None:
    if "callback_query" in update:
        await _handle_callback(update["callback_query"], store, telegram, now)
    elif "message" in update:
        await _handle_message(update["message"], store, telegram)


async def _ensure_user(store, chat_id: int) -> UserSettings:
    user = await store.get_user(chat_id)
    if user is None:
        user = UserSettings.default(chat_id)
        await store.save_user(user)
    return user


def _bus_stop_text(user: UserSettings) -> str:
    m = user.slots["morning"]
    e = user.slots["evening"]
    return (
        "目前推播公車站（預設）：\n"
        f"上班：{m.bus}（{m.stop_name}）\n"
        f"下班：{e.bus}（{e.stop_name}）"
    )


async def _handle_message(message: dict, store, telegram) -> None:
    chat_id = message["chat"]["id"]
    text = message.get("text", "")
    if text.startswith("/start"):
        await _ensure_user(store, chat_id)
        await telegram.send_message(
            chat_id,
            "歡迎！已開啟 70左/70右 到站通知。可用下方按鈕調整設定。",
            settings_reply_keyboard(),
        )
    elif text == BTN_INTERVAL:
        await telegram.send_message(chat_id, "要設定哪個時段的每日預設間隔？", slot_choice_keyboard("defint"))
    elif text == BTN_STOPS:
        user = await _ensure_user(store, chat_id)
        await telegram.send_message(chat_id, _bus_stop_text(user))
    elif text == BTN_DAYS:
        user = await _ensure_user(store, chat_id)
        await telegram.send_message(
            chat_id, "選擇要推播的星期，完成後按送出：",
            day_picker_keyboard(days_to_mask(user.enabled_days)),
        )


async def _handle_callback(cb: dict, store, telegram, now: datetime) -> None:
    data = cb["data"]
    cb_id = cb["id"]
    chat_id = cb["message"]["chat"]["id"]
    message_id = cb["message"]["message_id"]
    parts = data.split(":")
    kind = parts[0]
    date_str = now.strftime("%Y-%m-%d")

    if kind == "stop":
        slot = parts[1]
        runtime = await store.get_runtime(chat_id, date_str)
        runtime.slot(slot).stopped = True
        await store.save_runtime(chat_id, date_str, runtime)
        await telegram.answer_callback_query(cb_id, f"已停止今日{SLOT_LABELS[slot]}推播")

    elif kind == "interval":
        slot = parts[1]
        await telegram.answer_callback_query(cb_id)
        await telegram.send_message(
            chat_id, f"設定今日{SLOT_LABELS[slot]}剩餘推播間隔：",
            interval_picker_keyboard("today", slot),
        )

    elif kind == "setint":
        scope, slot, val = parts[1], parts[2], int(parts[3])
        if scope == "today":
            runtime = await store.get_runtime(chat_id, date_str)
            runtime.slot(slot).interval_override = val
            await store.save_runtime(chat_id, date_str, runtime)
            await telegram.answer_callback_query(cb_id, f"今日{SLOT_LABELS[slot]}間隔改為{val}分")
        else:
            user = await _ensure_user(store, chat_id)
            user.slots[slot].default_interval = val
            await store.save_user(user)
            await telegram.answer_callback_query(cb_id, f"{SLOT_LABELS[slot]}每日間隔改為{val}分")

    elif kind == "slotpick":
        action, slot = parts[1], parts[2]
        if action == "defint":
            await telegram.answer_callback_query(cb_id)
            await telegram.send_message(
                chat_id, f"設定{SLOT_LABELS[slot]}每日預設間隔：",
                interval_picker_keyboard("default", slot),
            )

    elif kind == "day":
        d, mask = int(parts[1]), int(parts[2])
        new_mask = mask ^ (1 << (d - 1))
        await telegram.edit_message_reply_markup(chat_id, message_id, day_picker_keyboard(new_mask))
        await telegram.answer_callback_query(cb_id)

    elif kind == "daysub":
        mask = int(parts[1])
        user = await _ensure_user(store, chat_id)
        user.enabled_days = mask_to_days(mask)
        await store.save_user(user)
        await telegram.answer_callback_query(cb_id, "已更新推播日")
```

- [ ] **Step 4: 執行測試確認通過**

Run: `python -m pytest tests/test_webhook.py -v`
Expected: PASS（10 passed）

- [ ] **Step 5: Commit**

```bash
git add app/webhook.py tests/test_webhook.py
git commit -m "feat: webhook 互動處理（停止/間隔/設定/日複選）"
```

---

### Task 11: FastAPI 入口 `main` + 整合測試

**Files:**
- Create: `app/main.py`
- Create: `app/deps.py`
- Test: `tests/test_main.py`
- Modify: `requirements-dev.txt`（加 `fastapi`、`uvicorn`）

**Interfaces:**
- Consumes: `app.scheduler.run_tick`、`app.webhook.handle_update`
- Produces:
  - `app/deps.py`：`build_runtime() -> tuple[store, tdx, telegram]`（正式環境組裝，可於測試 monkeypatch）
  - `app/main.py`：FastAPI `app`，端點 `POST /tick`、`POST /webhook`、`GET /healthz`
  - 常數 `CITY="Tainan"`、`ROUTE="70"`

- [ ] **Step 1: 在 `requirements-dev.txt` 追加**

```text
fastapi==0.115.5
uvicorn==0.32.1
```

Run: `python -m pip install fastapi==0.115.5 uvicorn==0.32.1`

- [ ] **Step 2: 寫失敗測試 `tests/test_main.py`**

```python
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.models import UserSettings
from app.store import InMemoryStore

TPE = ZoneInfo("Asia/Taipei")


class FakeTDX:
    def __init__(self, entries):
        self.entries = entries

    async def get_eta(self, city, route, now):
        return self.entries


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


@pytest.fixture
def client(monkeypatch):
    os.environ["TICK_AUTH_TOKEN"] = "ticksecret"
    os.environ["TELEGRAM_WEBHOOK_SECRET"] = "hooksecret"
    import app.main as main

    store = InMemoryStore()
    tg = FakeTelegram()
    tdx = FakeTDX([{"StopName": {"Zh_tw": "台南高工"}, "StopStatus": 0, "EstimateTime": 300}])
    monkeypatch.setattr(main, "build_runtime", lambda: (store, tdx, tg))
    # 固定 now 在週二上班窗口
    monkeypatch.setattr(main, "current_now", lambda: datetime(2026, 6, 30, 8, 0, tzinfo=TPE))
    return TestClient(main.app), store, tg


def test_tick_rejects_bad_token(client):
    c, store, tg = client
    resp = c.post("/tick", headers={"X-Tick-Token": "wrong"})
    assert resp.status_code == 403


def test_tick_pushes_to_seeded_user(client):
    c, store, tg = client
    import asyncio
    asyncio.get_event_loop().run_until_complete(store.save_user(UserSettings.default(1)))
    resp = c.post("/tick", headers={"X-Tick-Token": "ticksecret"})
    assert resp.status_code == 200
    assert tg.sent and tg.sent[0][0] == 1


def test_webhook_rejects_bad_secret(client):
    c, store, tg = client
    resp = c.post("/webhook", headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"}, json={})
    assert resp.status_code == 403


def test_webhook_handles_start(client):
    c, store, tg = client
    resp = c.post(
        "/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "hooksecret"},
        json={"message": {"chat": {"id": 7}, "text": "/start"}},
    )
    assert resp.status_code == 200
    assert tg.sent and tg.sent[0][0] == 7
```

- [ ] **Step 3: 執行測試確認失敗**

Run: `python -m pytest tests/test_main.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 4: 實作 `app/deps.py`**

```python
from __future__ import annotations

import os

import httpx

from app.store import FirestoreStore
from app.tdx import TDXClient
from app.telegram import TelegramClient


def build_runtime():
    """正式環境組裝；測試會以 monkeypatch 取代。"""
    from google.cloud import firestore

    http = httpx.AsyncClient(timeout=10)
    store = FirestoreStore(firestore.AsyncClient())
    tdx = TDXClient(os.environ["TDX_CLIENT_ID"], os.environ["TDX_CLIENT_SECRET"], store, http)
    telegram = TelegramClient(os.environ["TELEGRAM_BOT_TOKEN"], http)
    return store, tdx, telegram
```

- [ ] **Step 5: 實作 `app/main.py`**

```python
from __future__ import annotations

import os
from datetime import datetime

from fastapi import FastAPI, Header, HTTPException, Request

from app import scheduler, webhook
from app.deps import build_runtime
from app.timeutil import TZ

CITY = "Tainan"
ROUTE = "70"

app = FastAPI()


def current_now() -> datetime:
    return datetime.now(TZ)


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.post("/tick")
async def tick(x_tick_token: str = Header(default="")):
    if x_tick_token != os.environ.get("TICK_AUTH_TOKEN"):
        raise HTTPException(status_code=403, detail="forbidden")
    store, tdx, telegram = build_runtime()
    await scheduler.run_tick(current_now(), store, tdx, telegram, CITY, ROUTE)
    return {"ok": True}


@app.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(default=""),
):
    if x_telegram_bot_api_secret_token != os.environ.get("TELEGRAM_WEBHOOK_SECRET"):
        raise HTTPException(status_code=403, detail="forbidden")
    update = await request.json()
    store, tdx, telegram = build_runtime()
    await webhook.handle_update(update, store, telegram, current_now())
    return {"ok": True}
```

- [ ] **Step 6: 執行測試確認通過**

Run: `python -m pytest tests/test_main.py -v`
Expected: PASS（4 passed）

- [ ] **Step 7: 全套件測試**

Run: `python -m pytest -v`
Expected: PASS（Plan 1+2+3 全部）

- [ ] **Step 8: Commit**

```bash
git add app/deps.py app/main.py tests/test_main.py requirements-dev.txt
git commit -m "feat: FastAPI 入口 /tick /webhook /healthz + 整合測試"
```

---

## 計畫自我檢查（對照 spec）

- 排程 tick：enabledDays 過濾、時段窗口、到期、自動停、失敗即停 → Task 9
- Telegram 互動：推播按鈕（停止/間隔）、reply 設定鍵盤（間隔/站牌/日複選）、stateless 日 mask → Task 10
- FastAPI `/tick`（OIDC/Token 驗證）、`/webhook`（secret 驗證）→ Task 11
- 容器化、CI/CD、Cloud Scheduler 與 webhook 設定 → 見 Plan 4
