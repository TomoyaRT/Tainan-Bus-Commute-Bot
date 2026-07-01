# 台南公車通知 Bot — 部署手冊（DEPLOY.md）

本手冊為一次性基礎建設設定與部署流程，可照做重現。所有機密一律走 Secret Manager，不進 git。
**完全免費原則**：僅使用 Cloud Run / Cloud Scheduler / Firestore / Secret Manager 的免費額度，不開啟需付費資源。

- 建議區域：`asia-east1`（台灣，低延遲）
- Cloud Scheduler 時區：`Asia/Taipei`、頻率 `*/5 * * * *`
- 需準備的機密：`TDX_CLIENT_ID`、`TDX_CLIENT_SECRET`、`TELEGRAM_BOT_TOKEN`、`TICK_AUTH_TOKEN`、`TELEGRAM_WEBHOOK_SECRET`

---

## 0. 事前準備：取得金鑰

### 如何取得 TDX 金鑰
1. 前往 TDX 運輸資料流通服務平臺（<https://tdx.transportdata.tw/>）註冊會員並登入。
2. 進入「會員專區 → 資料服務 → API 金鑰管理」，建立一組 API Key。
3. 取得 `Client Id` 與 `Client Secret`，分別對應機密 `TDX_CLIENT_ID`、`TDX_CLIENT_SECRET`。
4. 確認方案為「基礎服務（免費）」額度模式；本專案設計即以免費額度為前提（見上線檢查清單）。

### 如何建立 Telegram bot
1. 在 Telegram 與 [@BotFather](https://t.me/BotFather) 對話，送 `/newbot` 依指示命名。
2. 取得 bot token（形如 `123456789:AAxxxx...`），對應機密 `TELEGRAM_BOT_TOKEN`。
3. `TICK_AUTH_TOKEN` 與 `TELEGRAM_WEBHOOK_SECRET` 自行產生兩組隨機長字串（例如 `openssl rand -hex 32`）。

---

## 1. 啟用 API 並設定專案

```bash
export PROJECT_ID=<your-project>
export REGION=asia-east1
gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com cloudscheduler.googleapis.com \
  secretmanager.googleapis.com artifactregistry.googleapis.com firestore.googleapis.com
```

預期：`Operation finished successfully`。

## 2. 建立 Firestore（原生模式）與 Artifact Registry

```bash
gcloud firestore databases create --location="$REGION" --type=firestore-native
gcloud artifacts repositories create tainan-bus --repository-format=docker --location="$REGION"
```

預期：兩者皆建立成功（Firestore 若已存在會提示，可忽略）。

## 3. 建立機密

逐一將值貼入；`TICK_AUTH_TOKEN`、`TELEGRAM_WEBHOOK_SECRET` 用隨機長字串：

```bash
for s in TDX_CLIENT_ID TDX_CLIENT_SECRET TELEGRAM_BOT_TOKEN TICK_AUTH_TOKEN TELEGRAM_WEBHOOK_SECRET; do
  printf "set value for %s: " "$s"; read -r v; printf "%s" "$v" | gcloud secrets create "$s" --data-file=-;
done
```

預期：每個 secret 顯示 `Created secret [...]`。

## 4. 建立 Cloud Run 執行服務帳號並授權

```bash
gcloud iam service-accounts create tainan-bus-run --display-name="tainan-bus run"
export RUN_SA="tainan-bus-run@${PROJECT_ID}.iam.gserviceaccount.com"
for s in TDX_CLIENT_ID TDX_CLIENT_SECRET TELEGRAM_BOT_TOKEN TICK_AUTH_TOKEN TELEGRAM_WEBHOOK_SECRET; do
  gcloud secrets add-iam-policy-binding "$s" --member="serviceAccount:${RUN_SA}" --role=roles/secretmanager.secretAccessor;
done
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${RUN_SA}" --role=roles/datastore.user
```

預期：每筆 binding 回傳更新後的政策。服務帳號 `tainan-bus-run` 僅具「讀取上述機密」與「Firestore 使用者（datastore.user）」權限，符合最小權限原則。
