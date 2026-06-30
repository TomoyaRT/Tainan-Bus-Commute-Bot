# 台南公車通知 Bot — Plan 2：外部客戶端與儲存 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 實作 TDX 客戶端（OAuth token 快取 + 取得到站資料 + 解析目標站）、Telegram 客戶端（sendMessage 等），以及 Store 介面（記憶體版供測試 + Firestore 版供正式）。

**Architecture:** 外部 I/O 全部以 `httpx.AsyncClient` 進行，測試用 `respx` 攔截 HTTP，不打真實服務。Store 以 Protocol 定義介面，`InMemoryStore` 供測試與本機、`FirestoreStore` 供正式部署。前置依賴：Plan 1 的 `app/models.py`。

**Tech Stack:** httpx、respx、pytest-asyncio、google-cloud-firestore（正式）。

## Global Constraints

- 同 Plan 1（Python 3.12、`Asia/Taipei`、`FAIL_THRESHOLD=2` 等）。
- TDX token 端點：`https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token`
- TDX 到站端點：`https://tdx.transportdata.tw/api/basic/v2/Bus/EstimatedTimeOfArrival/City/{city}/{route}`，查詢參數 `$format=JSON`
- token 快取需保留至少 1 分鐘緩衝（過期前 1 分鐘即視為需重取）
- 所有外部失敗（HTTP 非 200、連線錯誤、JSON 解析失敗）一律轉成 `TDXError`
- TDX 回應 `StopName` 欄位可能為 `{"Zh_tw": "台南高工"}` 結構或字串，解析時都要處理

---

### Task 5: 新增測試相依

**Files:**
- Modify: `pyproject.toml`
- Create: `requirements-dev.txt`

**Interfaces:**
- Produces：可安裝的測試環境（httpx、respx、pytest、pytest-asyncio）

- [ ] **Step 1: 建立 `requirements-dev.txt`**

```text
httpx==0.27.2
respx==0.21.1
pytest==8.3.3
pytest-asyncio==0.24.0
google-cloud-firestore==2.19.0
```

- [ ] **Step 2: 安裝**

Run: `python -m pip install -r requirements-dev.txt`
Expected: 安裝成功

- [ ] **Step 3: Commit**

```bash
git add requirements-dev.txt
git commit -m "chore: 測試相依（httpx/respx/firestore）"
```

---

### Task 6: TDX 客戶端 `tdx`

**Files:**
- Create: `app/tdx.py`
- Test: `tests/test_tdx.py`

**Interfaces:**
- Produces:
  - `class TDXError(Exception)`
  - `select_stop(entries: list[dict], stop_name: str) -> dict | None`
  - `class TDXClient(client_id, client_secret, store, http)`：
    - `async _get_token(now: datetime) -> str`（讀寫 `store.get_tdx_token()/save_tdx_token()`）
    - `async get_eta(city: str, route: str, now: datetime) -> list[dict]`
- Consumes（Store 介面，於 Task 8 正式定義；本任務測試用一個簡單 fake）：
  - `await store.get_tdx_token() -> tuple[str, datetime] | None`
  - `await store.save_tdx_token(token: str, expires_at: datetime) -> None`

- [ ] **Step 1: 寫失敗測試 `tests/test_tdx.py`**

```python
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from app.tdx import TDXClient, TDXError, select_stop

TPE = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 6, 30, 8, 0, tzinfo=TPE)
TOKEN_URL = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
ETA_URL = "https://tdx.transportdata.tw/api/basic/v2/Bus/EstimatedTimeOfArrival/City/Tainan/70"


class FakeTokenStore:
    def __init__(self):
        self.value = None

    async def get_tdx_token(self):
        return self.value

    async def save_tdx_token(self, token, expires_at):
        self.value = (token, expires_at)


def test_select_stop_handles_dict_stopname():
    entries = [{"StopName": {"Zh_tw": "台南高工"}, "StopStatus": 0, "EstimateTime": 300}]
    assert select_stop(entries, "台南高工")["EstimateTime"] == 300

def test_select_stop_handles_plain_string_and_missing():
    entries = [{"StopName": "中華西路二段", "StopStatus": 3}]
    assert select_stop(entries, "中華西路二段")["StopStatus"] == 3
    assert select_stop(entries, "不存在") is None


@respx.mock
async def test_get_eta_fetches_token_then_data():
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 86400}))
    route = respx.get(ETA_URL).mock(return_value=httpx.Response(200, json=[{"StopName": {"Zh_tw": "台南高工"}, "StopStatus": 0, "EstimateTime": 120}]))
    store = FakeTokenStore()
    async with httpx.AsyncClient() as http:
        client = TDXClient("id", "secret", store, http)
        entries = await client.get_eta("Tainan", "70", NOW)
    assert entries[0]["EstimateTime"] == 120
    assert route.calls.last.request.headers["authorization"] == "Bearer tok"
    assert store.value[0] == "tok"


@respx.mock
async def test_get_eta_reuses_cached_token():
    token_route = respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "fresh", "expires_in": 86400}))
    respx.get(ETA_URL).mock(return_value=httpx.Response(200, json=[]))
    store = FakeTokenStore()
    store.value = ("cached", NOW + timedelta(hours=5))
    async with httpx.AsyncClient() as http:
        client = TDXClient("id", "secret", store, http)
        await client.get_eta("Tainan", "70", NOW)
    assert token_route.called is False


@respx.mock
async def test_get_eta_raises_tdxerror_on_non_200():
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 86400}))
    respx.get(ETA_URL).mock(return_value=httpx.Response(500, text="boom"))
    store = FakeTokenStore()
    async with httpx.AsyncClient() as http:
        client = TDXClient("id", "secret", store, http)
        with pytest.raises(TDXError):
            await client.get_eta("Tainan", "70", NOW)
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python -m pytest tests/test_tdx.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.tdx'`

- [ ] **Step 3: 實作 `app/tdx.py`**

```python
from __future__ import annotations

from datetime import datetime, timedelta

import httpx

TOKEN_URL = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
ETA_URL = "https://tdx.transportdata.tw/api/basic/v2/Bus/EstimatedTimeOfArrival/City/{city}/{route}"
TOKEN_REFRESH_BUFFER = timedelta(minutes=1)


class TDXError(Exception):
    pass


def select_stop(entries: list[dict], stop_name: str) -> dict | None:
    for entry in entries:
        raw = entry.get("StopName")
        zh = raw.get("Zh_tw") if isinstance(raw, dict) else raw
        if zh == stop_name:
            return entry
    return None


class TDXClient:
    def __init__(self, client_id: str, client_secret: str, store, http: httpx.AsyncClient):
        self.client_id = client_id
        self.client_secret = client_secret
        self.store = store
        self.http = http

    async def _get_token(self, now: datetime) -> str:
        cached = await self.store.get_tdx_token()
        if cached and cached[1] > now + TOKEN_REFRESH_BUFFER:
            return cached[0]
        try:
            resp = await self.http.post(
                TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as exc:
            raise TDXError(f"token request failed: {exc}") from exc
        if resp.status_code != 200:
            raise TDXError(f"token status {resp.status_code}")
        try:
            data = resp.json()
            token = data["access_token"]
            expires_at = now + timedelta(seconds=int(data["expires_in"]))
        except (ValueError, KeyError) as exc:
            raise TDXError(f"token parse failed: {exc}") from exc
        await self.store.save_tdx_token(token, expires_at)
        return token

    async def get_eta(self, city: str, route: str, now: datetime) -> list[dict]:
        token = await self._get_token(now)
        try:
            resp = await self.http.get(
                ETA_URL.format(city=city, route=route),
                headers={"authorization": f"Bearer {token}"},
                params={"$format": "JSON"},
            )
        except httpx.HTTPError as exc:
            raise TDXError(f"eta request failed: {exc}") from exc
        if resp.status_code != 200:
            raise TDXError(f"eta status {resp.status_code}")
        try:
            return resp.json()
        except ValueError as exc:
            raise TDXError(f"eta json parse failed: {exc}") from exc
```

- [ ] **Step 4: 執行測試確認通過**

Run: `python -m pytest tests/test_tdx.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: Commit**

```bash
git add app/tdx.py tests/test_tdx.py
git commit -m "feat: TDX 客戶端（token 快取/取得到站/解析目標站）"
```

---

### Task 7: Telegram 客戶端 `telegram`

**Files:**
- Create: `app/telegram.py`
- Test: `tests/test_telegram.py`

**Interfaces:**
- Produces:
  - `class TelegramClient(token, http)`：
    - `async send_message(chat_id: int, text: str, reply_markup: dict | None = None) -> dict`
    - `async answer_callback_query(callback_query_id: str, text: str | None = None) -> dict`
    - `async edit_message_reply_markup(chat_id: int, message_id: int, reply_markup: dict) -> dict`

- [ ] **Step 1: 寫失敗測試 `tests/test_telegram.py`**

```python
import httpx
import respx

from app.telegram import TelegramClient

BASE = "https://api.telegram.org/bot123:ABC"


@respx.mock
async def test_send_message_includes_reply_markup():
    route = respx.post(f"{BASE}/sendMessage").mock(return_value=httpx.Response(200, json={"ok": True}))
    async with httpx.AsyncClient() as http:
        tg = TelegramClient("123:ABC", http)
        await tg.send_message(555, "嗨", reply_markup={"inline_keyboard": []})
    body = route.calls.last.request.read().decode()
    assert '"chat_id": 555' in body
    assert "reply_markup" in body


@respx.mock
async def test_send_message_without_markup_omits_key():
    route = respx.post(f"{BASE}/sendMessage").mock(return_value=httpx.Response(200, json={"ok": True}))
    async with httpx.AsyncClient() as http:
        tg = TelegramClient("123:ABC", http)
        await tg.send_message(555, "嗨")
    body = route.calls.last.request.read().decode()
    assert "reply_markup" not in body


@respx.mock
async def test_answer_callback_query():
    route = respx.post(f"{BASE}/answerCallbackQuery").mock(return_value=httpx.Response(200, json={"ok": True}))
    async with httpx.AsyncClient() as http:
        tg = TelegramClient("123:ABC", http)
        await tg.answer_callback_query("cb1", "已停止")
    body = route.calls.last.request.read().decode()
    assert '"callback_query_id": "cb1"' in body


@respx.mock
async def test_edit_message_reply_markup():
    route = respx.post(f"{BASE}/editMessageReplyMarkup").mock(return_value=httpx.Response(200, json={"ok": True}))
    async with httpx.AsyncClient() as http:
        tg = TelegramClient("123:ABC", http)
        await tg.edit_message_reply_markup(555, 99, {"inline_keyboard": []})
    body = route.calls.last.request.read().decode()
    assert '"message_id": 99' in body
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python -m pytest tests/test_telegram.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.telegram'`

- [ ] **Step 3: 實作 `app/telegram.py`**

```python
from __future__ import annotations

import httpx

API_URL = "https://api.telegram.org/bot{token}/{method}"


class TelegramClient:
    def __init__(self, token: str, http: httpx.AsyncClient):
        self.token = token
        self.http = http

    async def _call(self, method: str, payload: dict) -> dict:
        resp = await self.http.post(API_URL.format(token=self.token, method=method), json=payload)
        resp.raise_for_status()
        return resp.json()

    async def send_message(self, chat_id: int, text: str, reply_markup: dict | None = None) -> dict:
        payload: dict = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return await self._call("sendMessage", payload)

    async def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> dict:
        payload: dict = {"callback_query_id": callback_query_id}
        if text is not None:
            payload["text"] = text
        return await self._call("answerCallbackQuery", payload)

    async def edit_message_reply_markup(self, chat_id: int, message_id: int, reply_markup: dict) -> dict:
        return await self._call(
            "editMessageReplyMarkup",
            {"chat_id": chat_id, "message_id": message_id, "reply_markup": reply_markup},
        )
```

- [ ] **Step 4: 執行測試確認通過**

Run: `python -m pytest tests/test_telegram.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add app/telegram.py tests/test_telegram.py
git commit -m "feat: Telegram 客戶端 sendMessage/answerCallbackQuery/editMessageReplyMarkup"
```

---

### Task 8: 儲存介面與實作 `store`

**Files:**
- Create: `app/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `app.models.UserSettings`、`DayRuntime`
- Produces:
  - `class Store(Protocol)`：
    - `async get_user(chat_id: int) -> UserSettings | None`
    - `async save_user(settings: UserSettings) -> None`
    - `async list_users() -> list[UserSettings]`
    - `async get_runtime(chat_id: int, date_str: str) -> DayRuntime`（無資料回傳預設 `DayRuntime()`）
    - `async save_runtime(chat_id: int, date_str: str, runtime: DayRuntime) -> None`
    - `async get_tdx_token() -> tuple[str, datetime] | None`
    - `async save_tdx_token(token: str, expires_at: datetime) -> None`
  - `class InMemoryStore`（實作上述全部，供測試/本機）
  - `class FirestoreStore(db)`（實作上述全部，供正式；以 `google.cloud.firestore.AsyncClient` 注入）

- [ ] **Step 1: 寫失敗測試 `tests/test_store.py`**（只測 InMemoryStore，Firestore 版於部署環境驗證）

```python
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
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python -m pytest tests/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.store'`

- [ ] **Step 3: 實作 `app/store.py`**

```python
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.models import UserSettings, DayRuntime


class Store(Protocol):
    async def get_user(self, chat_id: int) -> UserSettings | None: ...
    async def save_user(self, settings: UserSettings) -> None: ...
    async def list_users(self) -> list[UserSettings]: ...
    async def get_runtime(self, chat_id: int, date_str: str) -> DayRuntime: ...
    async def save_runtime(self, chat_id: int, date_str: str, runtime: DayRuntime) -> None: ...
    async def get_tdx_token(self) -> tuple[str, datetime] | None: ...
    async def save_tdx_token(self, token: str, expires_at: datetime) -> None: ...


class InMemoryStore:
    def __init__(self) -> None:
        self._users: dict[int, dict] = {}
        self._runtime: dict[tuple[int, str], dict] = {}
        self._token: tuple[str, datetime] | None = None

    async def get_user(self, chat_id: int) -> UserSettings | None:
        raw = self._users.get(chat_id)
        return UserSettings.from_dict(raw) if raw else None

    async def save_user(self, settings: UserSettings) -> None:
        self._users[settings.chat_id] = settings.to_dict()

    async def list_users(self) -> list[UserSettings]:
        return [UserSettings.from_dict(raw) for raw in self._users.values()]

    async def get_runtime(self, chat_id: int, date_str: str) -> DayRuntime:
        raw = self._runtime.get((chat_id, date_str))
        return DayRuntime.from_dict(raw) if raw else DayRuntime()

    async def save_runtime(self, chat_id: int, date_str: str, runtime: DayRuntime) -> None:
        self._runtime[(chat_id, date_str)] = runtime.to_dict()

    async def get_tdx_token(self) -> tuple[str, datetime] | None:
        return self._token

    async def save_tdx_token(self, token: str, expires_at: datetime) -> None:
        self._token = (token, expires_at)


class FirestoreStore:
    """正式環境用，注入 google.cloud.firestore.AsyncClient。"""

    def __init__(self, db) -> None:
        self.db = db

    async def get_user(self, chat_id: int) -> UserSettings | None:
        snap = await self.db.collection("users").document(str(chat_id)).get()
        return UserSettings.from_dict(snap.to_dict()) if snap.exists else None

    async def save_user(self, settings: UserSettings) -> None:
        await self.db.collection("users").document(str(settings.chat_id)).set(settings.to_dict())

    async def list_users(self) -> list[UserSettings]:
        users = []
        async for snap in self.db.collection("users").stream():
            users.append(UserSettings.from_dict(snap.to_dict()))
        return users

    async def get_runtime(self, chat_id: int, date_str: str) -> DayRuntime:
        snap = await (
            self.db.collection("users").document(str(chat_id))
            .collection("runtime").document(date_str).get()
        )
        return DayRuntime.from_dict(snap.to_dict()) if snap.exists else DayRuntime()

    async def save_runtime(self, chat_id: int, date_str: str, runtime: DayRuntime) -> None:
        await (
            self.db.collection("users").document(str(chat_id))
            .collection("runtime").document(date_str).set(runtime.to_dict())
        )

    async def get_tdx_token(self) -> tuple[str, datetime] | None:
        snap = await self.db.collection("system").document("tdxToken").get()
        if not snap.exists:
            return None
        data = snap.to_dict()
        return data["access_token"], datetime.fromisoformat(data["expires_at"])

    async def save_tdx_token(self, token: str, expires_at: datetime) -> None:
        await self.db.collection("system").document("tdxToken").set(
            {"access_token": token, "expires_at": expires_at.isoformat()}
        )
```

- [ ] **Step 4: 執行測試確認通過**

Run: `python -m pytest tests/test_store.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 全套件測試**

Run: `python -m pytest -v`
Expected: PASS（Plan 1 + Plan 2 全部）

- [ ] **Step 6: Commit**

```bash
git add app/store.py tests/test_store.py
git commit -m "feat: Store 介面 + InMemory/Firestore 實作"
```

---

## 計畫自我檢查（對照 spec）

- TDX token 快取（24h、過期前 1 分鐘重取）+ 取得到站 + 解析目標站（含 dict/字串 StopName）→ Task 6
- Telegram 推播/回應 callback/編輯鍵盤 → Task 7
- Firestore 使用者設定 + 當日狀態（含 failCount）+ token 快取，並提供可測的 InMemory 版 → Task 8
- 排程 tick、webhook 互動、FastAPI 端點 → 見 Plan 3
