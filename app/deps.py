from __future__ import annotations

import os

import httpx
from dotenv import load_dotenv

from app.store import FirestoreStore
from app.tdx import TDXClient
from app.telegram import TelegramClient

# 本地開發：從專案根目錄 .env 載入所有機密（TDX/Telegram 等）。
# Cloud Run 正式環境沒有 .env，環境變數改由 Secret Manager 注入，load_dotenv() 為 no-op。
# override=False：已存在的環境變數（含測試 monkeypatch）優先，不被 .env 覆蓋。
load_dotenv(override=False)


def build_runtime():
    """正式環境組裝；測試會以 monkeypatch 取代。"""
    from google.cloud import firestore

    http = httpx.AsyncClient(timeout=10)
    store = FirestoreStore(firestore.AsyncClient())
    tdx = TDXClient(os.environ["TDX_CLIENT_ID"], os.environ["TDX_CLIENT_SECRET"], store, http)
    telegram = TelegramClient(os.environ["TELEGRAM_BOT_TOKEN"], http)
    return store, tdx, telegram
