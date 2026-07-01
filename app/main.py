from __future__ import annotations

import os
from datetime import datetime

from fastapi import FastAPI, Header, HTTPException, Request

from app import scheduler, webhook
from app.deps import build_runtime
from app.timeutil import TZ

CITY = "Tainan"

app = FastAPI()


def current_now() -> datetime:
    return datetime.now(TZ)


@app.get("/health")
async def health():
    # 注意：路徑不可用 /healthz——該字面路徑被 Google Front End 保留攔截，永遠打不到容器。
    return {"ok": True}


@app.post("/tick")
async def tick(x_tick_token: str = Header(default="")):
    if x_tick_token != os.environ.get("TICK_AUTH_TOKEN"):
        raise HTTPException(status_code=403, detail="forbidden")
    store, tdx, telegram = build_runtime()
    await scheduler.run_tick(current_now(), store, tdx, telegram, CITY)
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
    await webhook.handle_update(update, store, telegram, current_now(), tdx, CITY)
    return {"ok": True}
