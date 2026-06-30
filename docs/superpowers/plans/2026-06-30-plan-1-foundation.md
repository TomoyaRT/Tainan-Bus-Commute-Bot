# 台南公車通知 Bot — Plan 1：基礎層（純邏輯）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立專案骨架與所有「純函式」基礎模組（時間判定、領域模型、文案、鍵盤），全部以單元測試覆蓋。

**Architecture:** 單一 Python 套件 `app/`，本計畫只做無外部相依的純邏輯：時間/時段/到期計算、資料模型與序列化、TDX 狀態→文案、Telegram 鍵盤 JSON 結構。後續計畫再接 TDX/Telegram/Firestore 與 FastAPI。

**Tech Stack:** Python 3.12、pytest、pytest-asyncio（後續計畫用）。

## Global Constraints

- Python 版本：3.12
- 時區：`Asia/Taipei`（常數 `TZ`，定義於 `app/timeutil.py`）
- ISO 星期：1=週一 … 7=週日；預設推播日 `[2,3,4,5,6]`（週二~週六）
- 合法推播間隔：`(5, 10, 15, 20)` 分鐘
- 路線/城市：`ROUTE="70"`、`CITY="Tainan"`
- 失敗門檻：連續第 2 次失敗即停（常數 `FAIL_THRESHOLD=2`，後續計畫使用）
- 站牌/時段預設（固定）：
  - 上班 morning：`70左`／`台南高工`／`08:00–09:30`／預設 10 分
  - 下班 evening：`70右`／`中華西路二段`／`18:30–21:00`／預設 5 分
- API 失敗文案（常數 `API_ERROR_TEXT`）：`⚠️ 政府API出狀況，暫時無法取得正確的資訊。`
- 所有時間判定函式接收 tz-aware `datetime`（Asia/Taipei），不在純函式內呼叫 `datetime.now()`

---

### Task 1: 專案骨架 + 時間工具 `timeutil`

**Files:**
- Create: `pyproject.toml`
- Create: `app/__init__.py`（空檔）
- Create: `app/timeutil.py`
- Create: `tests/__init__.py`（空檔）
- Test: `tests/test_timeutil.py`

**Interfaces:**
- Produces:
  - `TZ: ZoneInfo`
  - `hhmm_to_minutes(value: str) -> int`
  - `minutes_of_day(now: datetime) -> int`
  - `in_window(now: datetime, window_start: str, window_end: str) -> bool`（`start <= now < end`）
  - `is_due(now: datetime, last_push_at: datetime | None, interval_min: int) -> bool`

- [ ] **Step 1: 建立 `pyproject.toml`**

```toml
[project]
name = "tainan-bus"
version = "0.1.0"
requires-python = ">=3.12"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: 建立空套件檔**

建立 `app/__init__.py` 與 `tests/__init__.py`，內容皆為空。

- [ ] **Step 3: 寫失敗測試 `tests/test_timeutil.py`**

```python
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.timeutil import TZ, hhmm_to_minutes, minutes_of_day, in_window, is_due

TPE = ZoneInfo("Asia/Taipei")

def _at(h, m):
    return datetime(2026, 6, 30, h, m, tzinfo=TPE)

def test_tz_is_taipei():
    assert TZ.key == "Asia/Taipei"

def test_hhmm_to_minutes():
    assert hhmm_to_minutes("08:00") == 480
    assert hhmm_to_minutes("09:30") == 570

def test_minutes_of_day():
    assert minutes_of_day(_at(8, 5)) == 485

def test_in_window_inclusive_start_exclusive_end():
    assert in_window(_at(8, 0), "08:00", "09:30") is True
    assert in_window(_at(9, 29), "08:00", "09:30") is True
    assert in_window(_at(9, 30), "08:00", "09:30") is False
    assert in_window(_at(7, 59), "08:00", "09:30") is False

def test_is_due_first_push_when_no_last():
    assert is_due(_at(8, 0), None, 10) is True

def test_is_due_respects_interval():
    last = _at(8, 0)
    assert is_due(last + timedelta(minutes=9), last, 10) is False
    assert is_due(last + timedelta(minutes=10), last, 10) is True
```

- [ ] **Step 4: 執行測試確認失敗**

Run: `python -m pytest tests/test_timeutil.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.timeutil'`

- [ ] **Step 5: 實作 `app/timeutil.py`**

```python
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Taipei")


def hhmm_to_minutes(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def minutes_of_day(now: datetime) -> int:
    return now.hour * 60 + now.minute


def in_window(now: datetime, window_start: str, window_end: str) -> bool:
    current = minutes_of_day(now)
    return hhmm_to_minutes(window_start) <= current < hhmm_to_minutes(window_end)


def is_due(now: datetime, last_push_at: datetime | None, interval_min: int) -> bool:
    if last_push_at is None:
        return True
    return now - last_push_at >= timedelta(minutes=interval_min)
```

- [ ] **Step 6: 執行測試確認通過**

Run: `python -m pytest tests/test_timeutil.py -v`
Expected: PASS（7 passed）

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml app/__init__.py app/timeutil.py tests/__init__.py tests/test_timeutil.py
git commit -m "feat: 專案骨架與時間工具 timeutil"
```

---

### Task 2: 領域模型 `models`

**Files:**
- Create: `app/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces:
  - 常數：`VALID_INTERVALS=(5,10,15,20)`、`DEFAULT_ENABLED_DAYS=[2,3,4,5,6]`、`SLOT_DEFAULTS: dict[str, SlotConfig]`
  - `SlotConfig(bus, stop_name, window_start, window_end, default_interval)` + `to_dict()/from_dict(d)`
  - `UserSettings(chat_id, enabled_days, slots)` + `default(chat_id)`、`to_dict()/from_dict(d)`
  - `SlotRuntime(stopped=False, interval_override=None, last_push_at=None, fail_count=0)` + `to_dict()/from_dict(d)`
  - `DayRuntime(morning, evening)` + `slot(name)->SlotRuntime`、`to_dict()/from_dict(d)`

- [ ] **Step 1: 寫失敗測試 `tests/test_models.py`**

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from app.models import (
    SlotConfig, UserSettings, SlotRuntime, DayRuntime,
    VALID_INTERVALS, DEFAULT_ENABLED_DAYS,
)

TPE = ZoneInfo("Asia/Taipei")

def test_constants():
    assert VALID_INTERVALS == (5, 10, 15, 20)
    assert DEFAULT_ENABLED_DAYS == [2, 3, 4, 5, 6]

def test_user_default_uses_spec_defaults():
    u = UserSettings.default(123)
    assert u.chat_id == 123
    assert u.enabled_days == [2, 3, 4, 5, 6]
    assert u.slots["morning"].bus == "70左"
    assert u.slots["morning"].stop_name == "台南高工"
    assert u.slots["morning"].default_interval == 10
    assert u.slots["evening"].bus == "70右"
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
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models'`

- [ ] **Step 3: 實作 `app/models.py`**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

VALID_INTERVALS = (5, 10, 15, 20)
DEFAULT_ENABLED_DAYS = [2, 3, 4, 5, 6]


@dataclass
class SlotConfig:
    bus: str
    stop_name: str
    window_start: str
    window_end: str
    default_interval: int

    def to_dict(self) -> dict:
        return {
            "bus": self.bus,
            "stop_name": self.stop_name,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "default_interval": self.default_interval,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SlotConfig":
        return cls(
            bus=d["bus"],
            stop_name=d["stop_name"],
            window_start=d["window_start"],
            window_end=d["window_end"],
            default_interval=d["default_interval"],
        )


SLOT_DEFAULTS = {
    "morning": SlotConfig("70左", "台南高工", "08:00", "09:30", 10),
    "evening": SlotConfig("70右", "中華西路二段", "18:30", "21:00", 5),
}


@dataclass
class UserSettings:
    chat_id: int
    enabled_days: list[int]
    slots: dict[str, SlotConfig]

    @classmethod
    def default(cls, chat_id: int) -> "UserSettings":
        return cls(
            chat_id=chat_id,
            enabled_days=list(DEFAULT_ENABLED_DAYS),
            slots={name: SlotConfig.from_dict(cfg.to_dict()) for name, cfg in SLOT_DEFAULTS.items()},
        )

    def to_dict(self) -> dict:
        return {
            "chat_id": self.chat_id,
            "enabled_days": list(self.enabled_days),
            "slots": {name: cfg.to_dict() for name, cfg in self.slots.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "UserSettings":
        return cls(
            chat_id=d["chat_id"],
            enabled_days=list(d["enabled_days"]),
            slots={name: SlotConfig.from_dict(cfg) for name, cfg in d["slots"].items()},
        )


@dataclass
class SlotRuntime:
    stopped: bool = False
    interval_override: int | None = None
    last_push_at: datetime | None = None
    fail_count: int = 0

    def to_dict(self) -> dict:
        return {
            "stopped": self.stopped,
            "interval_override": self.interval_override,
            "last_push_at": self.last_push_at.isoformat() if self.last_push_at else None,
            "fail_count": self.fail_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SlotRuntime":
        raw = d.get("last_push_at")
        return cls(
            stopped=d.get("stopped", False),
            interval_override=d.get("interval_override"),
            last_push_at=datetime.fromisoformat(raw) if raw else None,
            fail_count=d.get("fail_count", 0),
        )


@dataclass
class DayRuntime:
    morning: SlotRuntime = field(default_factory=SlotRuntime)
    evening: SlotRuntime = field(default_factory=SlotRuntime)

    def slot(self, name: str) -> SlotRuntime:
        return getattr(self, name)

    def to_dict(self) -> dict:
        return {"morning": self.morning.to_dict(), "evening": self.evening.to_dict()}

    @classmethod
    def from_dict(cls, d: dict) -> "DayRuntime":
        return cls(
            morning=SlotRuntime.from_dict(d.get("morning", {})),
            evening=SlotRuntime.from_dict(d.get("evening", {})),
        )
```

- [ ] **Step 4: 執行測試確認通過**

Run: `python -m pytest tests/test_models.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: Commit**

```bash
git add app/models.py tests/test_models.py
git commit -m "feat: 領域模型 UserSettings/SlotConfig/Runtime 與序列化"
```

---

### Task 3: 文案 `formatting`

**Files:**
- Create: `app/formatting.py`
- Test: `tests/test_formatting.py`

**Interfaces:**
- Consumes: `app.models.SlotConfig`
- Produces:
  - `API_ERROR_TEXT: str`
  - `NEAR_ARRIVAL_SECONDS = 60`
  - `format_eta_message(slot: SlotConfig, stop_status: int, estimate_time: int | None) -> str`

- [ ] **Step 1: 寫失敗測試 `tests/test_formatting.py`**

```python
from app.models import SLOT_DEFAULTS
from app.formatting import format_eta_message, API_ERROR_TEXT

M = SLOT_DEFAULTS["morning"]   # 70左 / 台南高工
E = SLOT_DEFAULTS["evening"]   # 70右 / 中華西路二段

def test_normal_eta_rounds_up_minutes():
    assert format_eta_message(M, 0, 400) == "🚌 70左 - 預估 7 分鐘到「台南高工」"

def test_near_arrival_within_60s():
    assert format_eta_message(M, 0, 30) == "🚌 70左 - 進站中，即將到「台南高工」"
    assert format_eta_message(M, 0, 60) == "🚌 70左 - 進站中，即將到「台南高工」"

def test_not_departed():
    assert format_eta_message(M, 1, None) == "🚌 70左 - 尚未發車（台南高工）"

def test_traffic_control():
    assert format_eta_message(M, 2, None) == "🚧 70左 - 交管不停靠（台南高工）"

def test_last_bus_passed():
    assert format_eta_message(E, 3, None) == "🌙 70右 - 末班車已過"

def test_not_in_service():
    assert format_eta_message(E, 4, None) == "70右 - 今日未營運"

def test_unknown_status_falls_back_to_error_text():
    assert format_eta_message(E, 99, None) == API_ERROR_TEXT
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python -m pytest tests/test_formatting.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.formatting'`

- [ ] **Step 3: 實作 `app/formatting.py`**

```python
from __future__ import annotations

from math import ceil

from app.models import SlotConfig

API_ERROR_TEXT = "⚠️ 政府API出狀況，暫時無法取得正確的資訊。"
NEAR_ARRIVAL_SECONDS = 60


def format_eta_message(slot: SlotConfig, stop_status: int, estimate_time: int | None) -> str:
    bus = slot.bus
    name = slot.stop_name
    if stop_status == 0:
        if estimate_time is not None and estimate_time <= NEAR_ARRIVAL_SECONDS:
            return f"🚌 {bus} - 進站中，即將到「{name}」"
        minutes = ceil((estimate_time or 0) / 60)
        return f"🚌 {bus} - 預估 {minutes} 分鐘到「{name}」"
    if stop_status == 1:
        return f"🚌 {bus} - 尚未發車（{name}）"
    if stop_status == 2:
        return f"🚧 {bus} - 交管不停靠（{name}）"
    if stop_status == 3:
        return f"🌙 {bus} - 末班車已過"
    if stop_status == 4:
        return f"{bus} - 今日未營運"
    return API_ERROR_TEXT
```

- [ ] **Step 4: 執行測試確認通過**

Run: `python -m pytest tests/test_formatting.py -v`
Expected: PASS（7 passed）

- [ ] **Step 5: Commit**

```bash
git add app/formatting.py tests/test_formatting.py
git commit -m "feat: TDX 狀態對應通知文案 formatting"
```

---

### Task 4: Telegram 鍵盤建構 `keyboards`

**Files:**
- Create: `app/keyboards.py`
- Test: `tests/test_keyboards.py`

**Interfaces:**
- Consumes: `app.models.VALID_INTERVALS`
- Produces：
  - 常數 `DAY_LABELS: dict[int,str]`、`SLOT_LABELS: dict[str,str]`
  - `push_inline_keyboard(slot: str) -> dict`
  - `interval_picker_keyboard(scope: str, slot: str) -> dict`（scope: `"today"` / `"default"`）
  - `settings_reply_keyboard() -> dict`
  - `slot_choice_keyboard(action: str) -> dict`
  - `day_picker_keyboard(mask: int) -> dict`
  - `days_to_mask(days: list[int]) -> int`、`mask_to_days(mask: int) -> list[int]`

- [ ] **Step 1: 寫失敗測試 `tests/test_keyboards.py`**

```python
from app.keyboards import (
    push_inline_keyboard, interval_picker_keyboard, settings_reply_keyboard,
    slot_choice_keyboard, day_picker_keyboard, days_to_mask, mask_to_days,
)

def test_push_inline_keyboard_has_stop_and_interval():
    kb = push_inline_keyboard("morning")
    row = kb["inline_keyboard"][0]
    assert row[0]["callback_data"] == "stop:morning"
    assert row[1]["callback_data"] == "interval:morning"

def test_interval_picker_lists_all_intervals_with_scope():
    kb = interval_picker_keyboard("today", "evening")
    datas = [b["callback_data"] for b in kb["inline_keyboard"][0]]
    assert datas == ["setint:today:evening:5", "setint:today:evening:10",
                     "setint:today:evening:15", "setint:today:evening:20"]

def test_settings_reply_keyboard_is_persistent():
    kb = settings_reply_keyboard()
    assert kb["is_persistent"] is True
    labels = [b["text"] for b in kb["keyboard"][0]]
    assert labels == ["⏱ 推播間隔", "🚏 推播公車站", "📅 推播時間"]

def test_slot_choice_keyboard_encodes_action():
    kb = slot_choice_keyboard("defint")
    datas = [b["callback_data"] for b in kb["inline_keyboard"][0]]
    assert datas == ["slotpick:defint:morning", "slotpick:defint:evening"]

def test_mask_roundtrip():
    assert days_to_mask([1]) == 0b0000001
    assert days_to_mask([2, 3, 4, 5, 6]) == 0b0111110
    assert mask_to_days(days_to_mask([1, 7])) == [1, 7]

def test_day_picker_marks_selected_and_carries_mask():
    mask = days_to_mask([2])
    kb = day_picker_keyboard(mask)
    flat = [b for row in kb["inline_keyboard"] for b in row]
    tue = next(b for b in flat if b["callback_data"].startswith("day:2:"))
    mon = next(b for b in flat if b["callback_data"].startswith("day:1:"))
    assert tue["text"].startswith("✅")
    assert not mon["text"].startswith("✅")
    submit = flat[-1]
    assert submit["callback_data"] == f"daysub:{mask}"
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python -m pytest tests/test_keyboards.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.keyboards'`

- [ ] **Step 3: 實作 `app/keyboards.py`**

```python
from __future__ import annotations

from app.models import VALID_INTERVALS

DAY_LABELS = {1: "週一", 2: "週二", 3: "週三", 4: "週四", 5: "週五", 6: "週六", 7: "週日"}
SLOT_LABELS = {"morning": "上班", "evening": "下班"}


def push_inline_keyboard(slot: str) -> dict:
    return {
        "inline_keyboard": [[
            {"text": "⏹ 停止推播", "callback_data": f"stop:{slot}"},
            {"text": "⏱ 推播間隔", "callback_data": f"interval:{slot}"},
        ]]
    }


def interval_picker_keyboard(scope: str, slot: str) -> dict:
    row = [{"text": f"{v}分", "callback_data": f"setint:{scope}:{slot}:{v}"} for v in VALID_INTERVALS]
    return {"inline_keyboard": [row]}


def settings_reply_keyboard() -> dict:
    return {
        "keyboard": [[
            {"text": "⏱ 推播間隔"},
            {"text": "🚏 推播公車站"},
            {"text": "📅 推播時間"},
        ]],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def slot_choice_keyboard(action: str) -> dict:
    row = [{"text": SLOT_LABELS[s], "callback_data": f"slotpick:{action}:{s}"} for s in ("morning", "evening")]
    return {"inline_keyboard": [row]}


def days_to_mask(days: list[int]) -> int:
    mask = 0
    for d in days:
        mask |= 1 << (d - 1)
    return mask


def mask_to_days(mask: int) -> list[int]:
    return [d for d in range(1, 8) if mask & (1 << (d - 1))]


def day_picker_keyboard(mask: int) -> dict:
    buttons = []
    for d in range(1, 8):
        checked = "✅" if mask & (1 << (d - 1)) else ""
        buttons.append({"text": f"{checked}{DAY_LABELS[d]}", "callback_data": f"day:{d}:{mask}"})
    rows = [buttons[0:4], buttons[4:7], [{"text": "✅ 送出", "callback_data": f"daysub:{mask}"}]]
    return {"inline_keyboard": rows}
```

- [ ] **Step 4: 執行測試確認通過**

Run: `python -m pytest tests/test_keyboards.py -v`
Expected: PASS

- [ ] **Step 5: 全套件測試**

Run: `python -m pytest -v`
Expected: PASS（所有 Plan 1 測試）

- [ ] **Step 6: Commit**

```bash
git add app/keyboards.py tests/test_keyboards.py
git commit -m "feat: Telegram 鍵盤建構 keyboards（推播按鈕/間隔/設定/日複選）"
```

---

## 計畫自我檢查（對照 spec）

- 時段/間隔/到期計算 → Task 1
- 資料模型（含 failCount、enabledDays 預設週二~週六）→ Task 2
- 狀態→文案（含 API 異常文案）→ Task 3
- 推播按鈕（停止/間隔）、常駐設定鍵盤、日複選 stateless mask → Task 4
- 外部相依（TDX/Telegram/Firestore）與排程/webhook/FastAPI → 見 Plan 2、Plan 3
