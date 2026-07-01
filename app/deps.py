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
