#!/bin/bash
set -e

# 載入 .env
if [ -f .env ]; then
  # 讀取並匯出環境變數
  export $(grep -v '^#' .env | xargs)
else
  echo "錯誤: 找不到 .env 檔案"
  exit 1
fi

if [ -z "$GCP_PROJECT_ID" ]; then
  echo "錯誤: .env 中未設定 GCP_PROJECT_ID"
  exit 1
fi

GCP_REGION=${GCP_REGION:-asia-east1}

echo "=================================================="
echo "  🚀 開始自動化部署至 GCP..."
echo "  - 專案 ID: $GCP_PROJECT_ID"
echo "  - 地區: $GCP_REGION"
echo "=================================================="

# 1. 設定 gcloud 預設專案
echo "1. 設定 gcloud 預設專案..."
gcloud config set project "$GCP_PROJECT_ID"

# 2. 啟用必要的 API 服務
echo "2. 啟用必要的 GCP API 服務..."
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  firestore.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  cloudscheduler.googleapis.com

# 3. 建立 Firestore 資料庫 (若尚未建立)
echo "3. 檢查並建立 Firestore 資料庫..."
# 取得目前資料庫列表並檢查 default 是否存在
DB_EXISTS=$(gcloud firestore databases list --format="value(name)" 2>/dev/null | grep -q "default" && echo "true" || echo "false")
if [ "$DB_EXISTS" = "false" ]; then
  echo "正在建立 Firestore 資料庫 (位置: $GCP_REGION)..."
  gcloud firestore databases create --location="$GCP_REGION" --type=firestore-native
else
  echo "Firestore 資料庫已存在，跳過建立。"
fi

# 4. 在 Secret Manager 建立並上傳密鑰值
echo "4. 上傳環境變數至 Secret Manager..."
upload_secret() {
  local name=$1
  local val=$2
  if [ -z "$val" ]; then
    echo "⚠️ 警告: $name 的值為空，跳過建立。"
    return
  fi
  # 檢查密鑰是否存在，不存在則建立
  SECRET_EXISTS=$(gcloud secrets list --filter="name ~ $name" --format="value(name)" 2>/dev/null)
  if [ -z "$SECRET_EXISTS" ]; then
    echo "建立密鑰: $name"
    gcloud secrets create "$name" --replication-policy="automatic"
  else
    echo "密鑰已存在: $name"
  fi
  # 新增版本值
  echo -n "$val" | gcloud secrets versions add "$name" --data-file=- >/dev/null
  echo "密鑰值已更新: $name"
}

upload_secret "TDX_CLIENT_ID" "$TDX_CLIENT_ID"
upload_secret "TDX_CLIENT_SECRET" "$TDX_CLIENT_SECRET"
upload_secret "TELEGRAM_BOT_TOKEN" "$TELEGRAM_BOT_TOKEN"
upload_secret "TICK_AUTH_TOKEN" "$TICK_AUTH_TOKEN"
upload_secret "TELEGRAM_WEBHOOK_SECRET" "$TELEGRAM_WEBHOOK_SECRET"

# 5. 配置 Service Account 權限
echo "5. 配置 IAM 服務帳號權限..."
PROJECT_NUMBER=$(gcloud projects describe "$GCP_PROJECT_ID" --format="value(projectNumber)")
SERVICE_ACCOUNT="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

echo "賦予服務帳號 $SERVICE_ACCOUNT 存取 Secret Manager 的權限..."
gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
  --member="serviceAccount:$SERVICE_ACCOUNT" \
  --role="roles/secretmanager.secretAccessor" >/dev/null

echo "賦予服務帳號 $SERVICE_ACCOUNT 使用 Datastore (Firestore) 的權限..."
gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
  --member="serviceAccount:$SERVICE_ACCOUNT" \
  --role="roles/datastore.user" >/dev/null

# 6. 使用 Cloud Build 建置並部署至 Cloud Run
echo "6. 使用 Cloud Build 編譯並部署至 Cloud Run..."
echo "正在發送至 Cloud Build 編譯並部署 (可能需要 2~3 分鐘，請稍候)..."
gcloud run deploy tainan-bus \
  --source . \
  --region="$GCP_REGION" \
  --allow-unauthenticated \
  --set-secrets="TDX_CLIENT_ID=TDX_CLIENT_ID:latest,TDX_CLIENT_SECRET=TDX_CLIENT_SECRET:latest,TELEGRAM_BOT_TOKEN=TELEGRAM_BOT_TOKEN:latest,TICK_AUTH_TOKEN=TICK_AUTH_TOKEN:latest,TELEGRAM_WEBHOOK_SECRET=TELEGRAM_WEBHOOK_SECRET:latest" \
  --quiet

# 7. 取得部署完成的服務網址
echo "7. 取得 Cloud Run 網址..."
SERVICE_URL=$(gcloud run services describe tainan-bus --region="$GCP_REGION" --format="value(status.url)")
echo "Cloud Run 服務網址為: $SERVICE_URL"

# 8. 建立 Cloud Scheduler 排程定時戳 /tick
echo "8. 建立 Cloud Scheduler 5分鐘排程..."
# 如果已存在，先刪除以避免衝突
JOB_EXISTS=$(gcloud scheduler jobs list --location="$GCP_REGION" --filter="name ~ tainan-bus-tick" --format="value(name)" 2>/dev/null)
if [ -n "$JOB_EXISTS" ]; then
  echo "刪除舊的排程工作..."
  gcloud scheduler jobs delete tainan-bus-tick --location="$GCP_REGION" --quiet
fi

gcloud scheduler jobs create http tainan-bus-tick \
  --location="$GCP_REGION" \
  --schedule="*/5 * * * *" \
  --uri="${SERVICE_URL}/tick" \
  --http-method=POST \
  --headers="X-Tick-Token=${TICK_AUTH_TOKEN}" \
  --time-zone="Asia/Taipei"

# 9. 註冊 Telegram Webhook
echo "9. 註冊 Webhook 網址給 Telegram..."
WEBHOOK_REG_URL="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook?url=${SERVICE_URL}/webhook&secret_token=${TELEGRAM_WEBHOOK_SECRET}"
REG_RESP=$(curl -s "$WEBHOOK_REG_URL")
echo "Telegram Webhook 註冊回應: $REG_RESP"

echo "=================================================="
echo "  🎉 GCP 雲端部署全部完成！"
echo "  - 服務狀態檢查: $SERVICE_URL/healthz"
echo "  - 請到 Telegram 打開您的 Bot，送出 /start 開始測試！"
echo "=================================================="
