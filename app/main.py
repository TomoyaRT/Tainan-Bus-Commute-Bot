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


from fastapi.responses import HTMLResponse

@app.get("/boarding_redirect")
async def boarding_redirect(code: str, fw: str = ""):
    fw_param = f"&fw={fw}" if fw else ""
    target_url = f"https://qrcode2384.tainan.gov.tw/QRCode/rsvStop.html?code={code}{fw_param}"
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>跳轉中...</title>
        <script src="https://telegram.org/js/telegram-web-app.js"></script>
        <script>
            window.onload = function() {{
                Telegram.WebApp.ready();
            }};
            
            function doOpen() {{
                // 使用者手動點擊後，iOS 允許跳轉
                Telegram.WebApp.openLink('{target_url}', {{try_instant_view: false}});
                Telegram.WebApp.close();
            }}
        </script>
        <style>
            body {{
                background-color: #f0f0f0; 
                display: flex; 
                flex-direction: column;
                justify-content: center; 
                align-items: center; 
                height: 100vh; 
                font-family: sans-serif; 
                margin: 0;
            }}
            .loader {{
                text-align: center;
                color: #555;
            }}
            .btn {{
                margin-top: 20px;
                padding: 12px 24px;
                background-color: #007aff;
                color: white;
                text-decoration: none;
                border-radius: 8px;
                font-size: 16px;
                border: none;
                cursor: pointer;
            }}
        </style>
    </head>
    <body>
        <div class="loader">
            <h2>🚌</h2>
            <p>即將前往台南公車預約系統</p>
            <button class="btn" onclick="doOpen()">開啟公車網頁</button>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(default=""),
):
    if x_telegram_bot_api_secret_token != os.environ.get("TELEGRAM_WEBHOOK_SECRET"):
        raise HTTPException(status_code=403, detail="forbidden")
    update = await request.json()
    store, tdx, telegram = build_runtime()
    
    base_url = str(request.base_url).rstrip("/")
    if base_url.startswith("http://") and "localhost" not in base_url:
        base_url = base_url.replace("http://", "https://")
        
    await webhook.handle_update(update, store, telegram, current_now(), tdx, CITY, base_url)
    return {"ok": True}
