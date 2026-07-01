#!/bin/bash

# 載入 .env 環境變數
if [ -f .env ]; then
  # 讀取並匯出環境變數
  export $(grep -v '^#' .env | xargs)
else
  echo "錯誤: 找不到 .env 檔案，請先建立並填入機密。"
  exit 1
fi

# 確認必要變數
if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ -z "$TELEGRAM_WEBHOOK_SECRET" ] || [ -z "$TICK_AUTH_TOKEN" ]; then
  echo "錯誤: .env 中缺少必要環境變數 (TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET, 或 TICK_AUTH_TOKEN)"
  exit 1
fi

echo "==============================================="
echo "  🚀 正在啟動 台南公車通知 Bot 本地開發環境...  "
echo "==============================================="

# 清理資源的函式
cleanup() {
  echo ""
  echo "==============================================="
  echo "  🛑 正在關閉所有本地服務...                   "
  echo "==============================================="
  
  # 註銷 Telegram Webhook，避免關閉後 Telegram 仍持續送訊息到過期的 ngrok 網址
  echo "正在向 Telegram 註銷 Webhook..."
  curl -s -S "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/deleteWebhook" > /dev/null
  echo "已註銷 Webhook。"
  
  # 殺死背景程序
  if [ -n "$TICK_PID" ]; then
    echo "正在關閉定時推播模擬器 (PID: $TICK_PID)..."
    kill $TICK_PID 2>/dev/null
  fi
  if [ -n "$NGROK_PID" ]; then
    echo "正在關閉 ngrok 穿透 (PID: $NGROK_PID)..."
    kill $NGROK_PID 2>/dev/null
  fi
  if [ -n "$UVICORN_PID" ]; then
    echo "正在關閉 FastAPI 伺服器 (PID: $UVICORN_PID)..."
    kill $UVICORN_PID 2>/dev/null
  fi
  
  echo "==============================================="
  echo "  ✅ 已成功安全關閉所有服務。                     "
  echo "==============================================="
  exit 0
}

# 註冊 Ctrl+C (SIGINT) 與 結束 (SIGTERM) 訊號
trap cleanup INT TERM EXIT

# 1. 啟動 FastAPI 伺服器 (Uvicorn)
echo "1. 正在啟動 FastAPI (Uvicorn) 伺服器在 port 8000..."
uvicorn app.main:app --port 8000 --reload > uvicorn.log 2>&1 &
UVICORN_PID=$!
echo "FastAPI 已啟動 (PID: $UVICORN_PID)，日誌寫入至 uvicorn.log"

# 2. 啟動 ngrok 穿透
if command -v ngrok &> /dev/null; then
  echo "2. 正在啟動 ngrok 穿透在 port 8000..."
  ngrok http 8000 > /dev/null 2>&1 &
  NGROK_PID=$!
  echo "ngrok 已啟動 (PID: $NGROK_PID)"
  
  # 偵測 ngrok 啟動完成並獲取其網址
  echo "等待 ngrok 分配公開 HTTPS 網址..."
  NGROK_URL=""
  for i in {1..10}; do
    sleep 1
    # 嘗試從 ngrok 本地 API 取得公開網址
    NGROK_URL=$(python3 -c "
import urllib.request, json
try:
    with urllib.request.urlopen('http://127.0.0.1:4040/api/tunnels') as res:
        tunnels = json.loads(res.read().decode())['tunnels']
        for t in tunnels:
            if t['public_url'].startswith('https://'):
                print(t['public_url'])
                break
except Exception:
    pass
" 2>/dev/null)
    if [ -n "$NGROK_URL" ]; then
      break
    fi
  done

  if [ -n "$NGROK_URL" ]; then
    echo "成功取得 ngrok 公開網址: $NGROK_URL"
    
    # 3. 自動向 Telegram 註冊 Webhook
    echo "3. 正在自動向 Telegram 註冊 Webhook..."
    WEBHOOK_URL="${NGROK_URL}/webhook"
    REG_RESP=$(curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook?url=${WEBHOOK_URL}&secret_token=${TELEGRAM_WEBHOOK_SECRET}")
    echo "Telegram Webhook 註冊狀態: $REG_RESP"
  else
    echo "⚠️ 警告: 無法取得 ngrok 網址。您可能需要手動綁定 Webhook。"
  fi
else
  echo "⚠️ 警告: 系統中找不到 ngrok 指令，將跳過內網穿透與 Webhook 自動註冊。"
fi

# 4. 啟動定時推播模擬器 (Tick, 每 5 分鐘檢查一次)
echo "4. 正在啟動定時推播模擬器 (Tick, 每 300 秒觸發一次)..."
# 啟動時先立即觸發一次確保功能運作
(
  sleep 2
  curl -s -X POST http://127.0.0.1:8000/tick -H "X-Tick-Token: ${TICK_AUTH_TOKEN}" > /dev/null
  while true; do
    sleep 300
    curl -s -X POST http://127.0.0.1:8000/tick -H "X-Tick-Token: ${TICK_AUTH_TOKEN}" > /dev/null
  done
) &
TICK_PID=$!

echo "==============================================="
echo "  🎉 本地開發伺服器已全數啟動！"
echo "  - 按 Ctrl + C 即可一鍵關閉所有服務並註銷 Webhook"
echo "==============================================="

# 保持腳本運行，等待 Ctrl+C
while true; do
  sleep 1
done
