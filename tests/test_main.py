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
    tdx = FakeTDX([{"StopName": {"Zh_tw": "臺南高工"},
                    "SubRouteName": {"Zh_tw": "70左 永華市政中心 → 永華市政中心"},
                    "StopStatus": 0, "EstimateTime": 300}])
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
    asyncio.run(store.save_user(UserSettings.default(1)))
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
