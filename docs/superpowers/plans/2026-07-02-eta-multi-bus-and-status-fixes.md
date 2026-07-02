# 到站訊息多車顯示與狀態判斷修正 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓到站推播支援多台車顯示(車牌+到站分鐘)、修正狀態判斷 bug、並讓到站分鐘貼近實際。

**Architecture:** `select_matches` 回傳同站同子路線的所有到站筆數;`format_eta_message` 接收該清單與 `now`,做快照時間校正、無條件捨去分鐘、依可搭乘車數量組出單/多車或狀態訊息。「政府系統異常」僅在 TDX 真正失敗時觸發。

**Tech Stack:** Python 3、pytest(async)、httpx/respx(既有)。

## Global Constraints

- TDX `StopStatus` 定義(官方 swagger 逐字):`[0:'正常',1:'尚未發車',2:'交管不停靠',3:'末班車已過',4:'今日未營運']`。
- 狀態 1(尚未發車)的 EstimateTime 是「發車倒數」非到站時間 → 不得顯示為到站。
- 到站分鐘一律**無條件捨去**:`adjusted_seconds // 60`。
- 快照校正:`adjusted = max(0, EstimateTime - (now - 來源時間))`,來源時間取 `SrcUpdateTime`→`DataTime`→無則不校正。
- 多車顯示上限 `MAX_BUSES = 3`,依 adjusted 由小到大。
- 「即將進站」門檻 `NEAR_ARRIVAL_SECONDS = 60`(以 adjusted 判定)。
- 「暫時查不到該站班次」與各狀態訊息**不經** `TDXError`、不算失敗。
- 繁體中文文案;站名用設定值(如「臺南高工」)。

---

### Task 1: `select_matches` 回傳到站清單

**Files:**
- Modify: `app/tdx.py`(以 `select_matches` 取代 `select_stop`)
- Test: `tests/test_tdx.py`

**Interfaces:**
- Produces: `select_matches(entries: list[dict], stop_name: str, sub_route: str | None = None) -> list[dict]`
  回傳符合 (站名, 子路線前綴) 的**所有**筆數;不存在則回 `[]`。

- [ ] **Step 1: 改寫 test_tdx.py 中 select_stop 相關測試為 select_matches**

將檔頭 import 改為 `from app.tdx import TDXClient, TDXError, select_matches`,並以下列取代原三個 select_stop 測試:

```python
def test_select_matches_handles_dict_stopname():
    entries = [{"StopName": {"Zh_tw": "台南高工"}, "StopStatus": 0, "EstimateTime": 300}]
    got = select_matches(entries, "台南高工")
    assert len(got) == 1 and got[0]["EstimateTime"] == 300


def test_select_matches_missing_returns_empty():
    entries = [{"StopName": "中華西路二段", "StopStatus": 3}]
    assert select_matches(entries, "不存在") == []


def test_select_matches_disambiguates_by_sub_route():
    entries = [
        {"StopName": {"Zh_tw": "臺南高工"}, "SubRouteName": {"Zh_tw": "70左 …"}, "EstimateTime": 1700},
        {"StopName": {"Zh_tw": "臺南高工"}, "SubRouteName": {"Zh_tw": "70右 …"}, "EstimateTime": 900},
    ]
    assert [e["EstimateTime"] for e in select_matches(entries, "臺南高工", "70左")] == [1700]
    assert [e["EstimateTime"] for e in select_matches(entries, "臺南高工", "70右")] == [900]


def test_select_matches_returns_all_when_ambiguous():
    # 環狀頭尾同站或尖峰多車：同站同子路線多筆，全部回傳
    entries = [
        {"StopName": {"Zh_tw": "永華市政中心(府前路)"}, "SubRouteName": {"Zh_tw": "70左 …"}, "EstimateTime": 200},
        {"StopName": {"Zh_tw": "永華市政中心(府前路)"}, "SubRouteName": {"Zh_tw": "70左 …"}, "EstimateTime": 2400},
    ]
    assert len(select_matches(entries, "永華市政中心(府前路)", "70左")) == 2


def test_select_matches_against_real_fixture():
    import json, pathlib
    raw = json.loads((pathlib.Path(__file__).parent / "fixtures" / "route70_sample.json").read_text("utf-8"))
    m = select_matches(raw, "臺南高工", "70左")
    assert len(m) == 1 and m[0]["SubRouteName"]["Zh_tw"].startswith("70左")
    e = select_matches(raw, "中華西路二段", "70右")
    assert len(e) == 1 and e[0]["SubRouteName"]["Zh_tw"].startswith("70右")
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `pytest tests/test_tdx.py -q`
Expected: FAIL（`ImportError: cannot import name 'select_matches'`）

- [ ] **Step 3: 在 app/tdx.py 以 select_matches 取代 select_stop**

將原 `select_stop` 函式整段替換為:

```python
def select_matches(
    entries: list[dict], stop_name: str, sub_route: str | None = None
) -> list[dict]:
    """回傳同一 (站名, 子路線前綴) 的所有到站筆數。

    台南 70 是環狀路線,RouteName 皆為 "70",靠 SubRouteName("70左…"/"70右…")區分左右;
    同站名在兩子路線都會出現,故 sub_route 指定時以 SubRouteName 前綴過濾。
    尖峰多車或環狀頭尾同站會有多筆,一律全部回傳交由上層呈現;不存在則回 []。
    """
    matches = []
    for entry in entries:
        if _zh(entry.get("StopName")) != stop_name:
            continue
        if sub_route is not None and not (_zh(entry.get("SubRouteName")) or "").startswith(sub_route):
            continue
        matches.append(entry)
    return matches
```

- [ ] **Step 4: 執行測試確認通過**

Run: `pytest tests/test_tdx.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/tdx.py tests/test_tdx.py
git commit -m "refactor: select_stop 改為 select_matches 回傳到站清單"
```

---

### Task 2: 快照時間校正輔助函式

**Files:**
- Modify: `app/formatting.py`
- Test: `tests/test_formatting.py`(新增,不動既有既存函式測試——本任務只加新函式)

**Interfaces:**
- Produces:
  - `adjusted_seconds(entry: dict, now: datetime) -> int | None`
    無 `EstimateTime` 回 `None`;否則回 `max(0, EstimateTime - (now - 來源時間)秒)`(整數)。
  - `source_time(entry: dict) -> datetime | None`(內部用,tz-aware 或 None)。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_formatting.py` 檔頭補上 import,並新增測試:

```python
from datetime import datetime
from zoneinfo import ZoneInfo
from app.formatting import adjusted_seconds

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
```

- [ ] **Step 2: 執行確認失敗**

Run: `pytest tests/test_formatting.py -q`
Expected: FAIL（`ImportError: cannot import name 'adjusted_seconds'`）

- [ ] **Step 3: 實作輔助函式**

在 `app/formatting.py` 檔頭補 import 與函式(放在 `format_eta_message` 之前):

```python
from datetime import datetime

def source_time(entry: dict) -> datetime | None:
    for key in ("SrcUpdateTime", "DataTime"):
        raw = entry.get(key)
        if raw:
            try:
                dt = datetime.fromisoformat(raw)
            except (ValueError, TypeError):
                continue
            if dt.tzinfo is not None:
                return dt
    return None


def adjusted_seconds(entry: dict, now: datetime) -> int | None:
    est = entry.get("EstimateTime")
    if est is None:
        return None
    src = source_time(entry)
    if src is not None:
        est = est - (now - src).total_seconds()
    return max(0, int(est))
```

- [ ] **Step 4: 執行確認通過**

Run: `pytest tests/test_formatting.py -q -k adjusted_seconds`
Expected: PASS（既有 format_eta_message 舊測試此時可能失敗,Task 3 一併改寫）

- [ ] **Step 5: Commit**

```bash
git add app/formatting.py tests/test_formatting.py
git commit -m "feat: 到站秒數快照校正輔助函式 adjusted_seconds"
```

---

### Task 3: 改寫 `format_eta_message`(多車/單車/狀態/floor/Bug A/B)

**Files:**
- Modify: `app/formatting.py`
- Test: `tests/test_formatting.py`(改寫既有 format 測試)

**Interfaces:**
- Consumes: `adjusted_seconds`(Task 2)、`SlotConfig`(既有)。
- Produces: `format_eta_message(cfg: SlotConfig, matches: list[dict], now: datetime) -> str`
- 常數:`API_ERROR_TEXT`(保留)、`NO_DATA_TEXT = "暫時查不到該站班次"`、`MAX_BUSES = 3`、`NEAR_ARRIVAL_SECONDS = 60`。

- [ ] **Step 1: 改寫 test_formatting.py 的 format 測試**

刪除原本針對舊簽章 `format_eta_message(slot, status, estimate)` 的所有測試(第 7–33 行那批),
保留 Task 2 新增的 adjusted_seconds 測試,並加入:

```python
from app.models import SLOT_DEFAULTS
from app.formatting import format_eta_message, NO_DATA_TEXT

M = SLOT_DEFAULTS["morning"]  # 70左 / 臺南高工
E = SLOT_DEFAULTS["evening"]  # 70右 / 中華西路二段


def _bus(status=0, est=None, plate=None):
    e = {"StopStatus": status, "EstimateTime": est}
    if plate is not None:
        e["PlateNumb"] = plate
    return e


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
```

- [ ] **Step 2: 執行確認失敗**

Run: `pytest tests/test_formatting.py -q`
Expected: FAIL（舊 `format_eta_message` 簽章不符 / `NO_DATA_TEXT` 未定義）

- [ ] **Step 3: 改寫 format_eta_message 與輔助**

將 `app/formatting.py` 中舊的 `format_eta_message` 整段替換為:

```python
from math import floor  # 若未使用可省略；分鐘用整除即可

NO_DATA_TEXT = "暫時查不到該站班次"
MAX_BUSES = 3


def _plate(entry: dict) -> str:
    return (entry.get("PlateNumb") or "").strip()


def _multi_line(adj: int, plate: str) -> str:
    if adj <= NEAR_ARRIVAL_SECONDS:
        return f"・ 即將進站的公車:{plate}" if plate else "・ 即將進站"
    mins = adj // 60
    return f"・ {plate} 預估 {mins} 分鐘" if plate else f"・ 預估 {mins} 分鐘"


def _single_line(cfg: SlotConfig, adj: int, plate: str) -> str:
    bus, name = cfg.bus, cfg.stop_name
    if adj <= NEAR_ARRIVAL_SECONDS:
        return (f"🚌 {bus} - {plate} 即將進站到「{name}」" if plate
                else f"🚌 {bus} - 進站中，即將到「{name}」")
    mins = adj // 60
    return (f"🚌 {bus} - {plate} 預估 {mins} 分鐘到「{name}」" if plate
            else f"🚌 {bus} - 預估 {mins} 分鐘到「{name}」")


def format_eta_message(cfg: SlotConfig, matches: list[dict], now: datetime) -> str:
    if not matches:
        return NO_DATA_TEXT

    runnable = []  # (adjusted_seconds, plate)
    for e in matches:
        if int(e.get("StopStatus", 0)) != 0:
            continue
        adj = adjusted_seconds(e, now)
        if adj is None:
            continue
        runnable.append((adj, _plate(e)))
    runnable.sort(key=lambda x: x[0])
    runnable = runnable[:MAX_BUSES]

    if len(runnable) >= 2:
        lines = [f"🚌 {cfg.bus} 到「{cfg.stop_name}」"]
        lines += [_multi_line(adj, plate) for adj, plate in runnable]
        return "\n".join(lines)
    if len(runnable) == 1:
        adj, plate = runnable[0]
        return _single_line(cfg, adj, plate)

    # 0 台可搭 → 依狀態優先序給單一狀態訊息
    statuses = {int(e.get("StopStatus", 0)) for e in matches}
    if 4 in statuses:
        return f"{cfg.bus} - 今日未營運"
    if 3 in statuses:
        return f"🌙 {cfg.bus} - 末班車已過"
    if 2 in statuses:
        return f"🚧 {cfg.bus} - 交管不停靠（{cfg.stop_name}）"
    if 1 in statuses:
        return f"🚌 {cfg.bus} - 尚未發車（{cfg.stop_name}）"
    return NO_DATA_TEXT
```

移除不再使用的 `from math import ceil`(改用整除)。若 `floor` 未實際使用亦刪除該 import。

- [ ] **Step 4: 執行確認通過**

Run: `pytest tests/test_formatting.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/formatting.py tests/test_formatting.py
git commit -m "feat: format_eta_message 支援多車顯示與狀態修正(floor/BugA/BugB)"
```

---

### Task 4: 排程 `process_user` 接上新介面

**Files:**
- Modify: `app/scheduler.py`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `select_matches`(Task 1)、`format_eta_message(cfg, matches, now)`(Task 3)。

- [ ] **Step 1: 更新受影響的 scheduler 測試**

在 `tests/test_scheduler.py`:
把原 `test_wrong_sub_route_is_not_pushed` 替換為新語意(0 match → 送「暫時查不到」、不累加 fail_count):

```python
async def test_wrong_sub_route_sends_no_data_not_failure():
    from app.formatting import NO_DATA_TEXT
    entries = [{"StopName": {"Zh_tw": "臺南高工"},
                "SubRouteName": {"Zh_tw": "70右 …"}, "StopStatus": 0, "EstimateTime": 300}]
    store, tdx, tg = InMemoryStore(), FakeTDX(entries), FakeTelegram()
    await _seed_user(store)
    await process_user(_tue(8, 0), await store.get_user(1), store, tdx, tg, "Tainan")
    assert tg.sent[0][1] == NO_DATA_TEXT
    rt = await store.get_runtime(1, "2026-06-30")
    assert rt.morning.fail_count == 0
    assert rt.morning.last_push_at == _tue(8, 0)
```

新增多車不再誤報系統異常的測試:

```python
async def test_multiple_buses_same_stop_not_error():
    entries = [
        {"StopName": {"Zh_tw": "臺南高工"}, "SubRouteName": {"Zh_tw": "70左 …"},
         "StopStatus": 0, "EstimateTime": 480, "PlateNumb": "EAA-732"},
        {"StopName": {"Zh_tw": "臺南高工"}, "SubRouteName": {"Zh_tw": "70左 …"},
         "StopStatus": 0, "EstimateTime": 1080, "PlateNumb": "EAA-728"},
    ]
    store, tdx, tg = InMemoryStore(), FakeTDX(entries), FakeTelegram()
    await _seed_user(store)
    await process_user(_tue(8, 0), await store.get_user(1), store, tdx, tg, "Tainan")
    text = tg.sent[0][1]
    assert "EAA-732" in text and "EAA-728" in text
    assert "政府系統異常" not in text
```

- [ ] **Step 2: 執行確認失敗**

Run: `pytest tests/test_scheduler.py -q`
Expected: FAIL（`select_stop` 已不存在 / 舊行為不符）

- [ ] **Step 3: 更新 app/scheduler.py**

改 import:

```python
from app.tdx import TDXError, select_matches
```

把 `process_user` 的 try 區塊(原第 41–65 行)改為:

```python
    try:
        if cache is not None and cfg.route in cache:
            entries = cache[cfg.route]
        else:
            entries = await tdx.get_eta(city, cfg.route, now)
            if cache is not None:
                cache[cfg.route] = entries

        matches = select_matches(entries, cfg.stop_name, cfg.sub_route)
        sr.fail_count = 0
        text = format_eta_message(cfg, matches, now)
        await telegram.send_message(settings.chat_id, text, push_inline_keyboard(slot))
        sr.last_push_at = now
    except TDXError as exc:
        sr.fail_count += 1
        if sr.fail_count >= FAIL_THRESHOLD:
            if exc.status_code in (403, 429):
                await telegram.send_message(settings.chat_id, "⚠️ TDX 公車 API 額度已用完，無法取得正確資訊。")
            else:
                await telegram.send_message(settings.chat_id, API_ERROR_TEXT)
            sr.stopped = True
```

(其餘不變。`format_eta_message` 已 import 於檔頭。)

- [ ] **Step 4: 執行確認通過**

Run: `pytest tests/test_scheduler.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/scheduler.py tests/test_scheduler.py
git commit -m "feat: 排程改用 select_matches + 多車格式,0 match 不再誤報異常"
```

---

### Task 5: 手動「立即推播」`_manual_push` 接上新介面

**Files:**
- Modify: `app/webhook.py`
- Test: `tests/test_webhook.py`

**Interfaces:**
- Consumes: `select_matches`(Task 1)、`format_eta_message(cfg, matches, now)`(Task 3)。

- [ ] **Step 1: 新增手動推播多車測試**

在 `tests/test_webhook.py` 末尾新增(沿用該檔既有的 `FakeTDX`/`FakeTelegram`/`_msg`/`BTN_PUSH_NOW`/`NOW` 慣例):

```python
async def test_manual_push_multi_bus_lists_plates():
    store, tg = InMemoryStore(), FakeTelegram()
    await store.save_user(UserSettings.default(1))
    entries = [
        {"StopName": {"Zh_tw": "臺南高工"}, "SubRouteName": {"Zh_tw": "70左 …"},
         "StopStatus": 0, "EstimateTime": 480, "PlateNumb": "EAA-732"},
        {"StopName": {"Zh_tw": "臺南高工"}, "SubRouteName": {"Zh_tw": "70左 …"},
         "StopStatus": 0, "EstimateTime": 1080, "PlateNumb": "EAA-728"},
        {"StopName": {"Zh_tw": "中華西路二段"}, "SubRouteName": {"Zh_tw": "70右 …"},
         "StopStatus": 0, "EstimateTime": 300, "PlateNumb": "EAA-500"},
    ]
    tdx = FakeTDX(entries)
    await handle_update(_msg(BTN_PUSH_NOW), store, tg, NOW, tdx, "Tainan")
    body = tg.sent[0][1]
    assert "EAA-732" in body and "EAA-728" in body
    assert "政府系統異常" not in body and "查無資料" not in body
```

- [ ] **Step 2: 執行確認失敗**

Run: `pytest tests/test_webhook.py -q`
Expected: FAIL

- [ ] **Step 3: 更新 app/webhook.py**

改 import:

```python
from app.tdx import TDXError, select_matches
```

把 `_manual_push` 內迴圈(原第 104–113 行)改為:

```python
        for name in ("morning", "evening"):
            cfg = user.slots[name]
            if cfg.route not in cache:
                cache[cfg.route] = await tdx.get_eta(city, cfg.route, now)
            matches = select_matches(cache[cfg.route], cfg.stop_name, cfg.sub_route)
            body = format_eta_message(cfg, matches, now)
            blocks.append(f"{MANUAL_SLOT_HEADERS[name]}\n{body}")
```

(移除 `match is None → "查無資料"` 分支;`format_eta_message` 已於檔頭 import。)

- [ ] **Step 4: 執行確認通過**

Run: `pytest tests/test_webhook.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/webhook.py tests/test_webhook.py
git commit -m "feat: 立即推播改用 select_matches + 多車格式"
```

---

### Task 6: 全測試回歸

**Files:** 無(僅執行)

- [ ] **Step 1: 跑全測試**

Run: `pytest -q`
Expected: 全數 PASS

- [ ] **Step 2: 確認無殘留 select_stop 參照**

Run: `grep -rn "select_stop\|from math import ceil\|format_eta_message(.*, .*, .*None)" app tests`
Expected: 無輸出(或僅預期內容)

- [ ] **Step 3: 若有殘留則修正並重跑,最後 Commit(如有變更)**

```bash
git add -A && git commit -m "test: ETA 多車與狀態修正全測試回歸綠燈"
```

## Self-Review 檢查結果

- **Spec coverage**:多車顯示(Task 3)、Bug A/B(Task 3)、floor+快照校正(Task 2/3)、
  「政府系統異常」僅 TDX 失敗(Task 4)、select 多筆(Task 1)、手動推播(Task 5)、狀態優先序(Task 3)皆有對應任務。
- **Placeholder scan**:無 placeholder,各步驟皆含完整程式碼與指令。
- **Type consistency**:`select_matches`、`adjusted_seconds`、`format_eta_message(cfg, matches, now)`、
  `NO_DATA_TEXT`、`MAX_BUSES` 在各任務間簽章一致。
