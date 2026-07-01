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


_runtime = None


def build_runtime():
    """正式環境組裝；測試會以 monkeypatch 取代。

    以模組層級單例快取：整個 Cloud Run instance 共用同一組 httpx/Firestore 用戶端，
    避免每次 /tick、/webhook 都新建連線而洩漏 socket，並讓 TDX token 的行程內快取得以跨 tick 重用。
    首次於請求（事件迴圈執行中）呼叫時才建立，確保用戶端綁定到運行中的 loop。
    """
    global _runtime
    if _runtime is None:
        from google.cloud import firestore

        http = httpx.AsyncClient(timeout=10)
        store = FirestoreStore(firestore.AsyncClient())
        tdx = TDXClient(os.environ["TDX_CLIENT_ID"], os.environ["TDX_CLIENT_SECRET"], store, http)
        telegram = TelegramClient(os.environ["TELEGRAM_BOT_TOKEN"], http)
        _runtime = (store, tdx, telegram)
    return _runtime
