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

---

## 5. GitHub Actions 持續部署（WIF 免長期金鑰）

CI/CD 以 Workload Identity Federation（WIF）讓 GitHub Actions 直接聯合 GCP 身分，**不需下載長期服務帳號金鑰**。

### 5.1 建立部署服務帳號與授權

```bash
gcloud iam service-accounts create gh-deployer --display-name="github deployer"
export DEPLOY_SA="gh-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${DEPLOY_SA}" --role=roles/run.admin
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${DEPLOY_SA}" --role=roles/artifactregistry.writer
# 部署時需以 RUN_SA 身分佈署 Cloud Run，故 DEPLOY_SA 需可模擬 RUN_SA
gcloud iam service-accounts add-iam-policy-binding "$RUN_SA" --member="serviceAccount:${DEPLOY_SA}" --role=roles/iam.serviceAccountUser
```

### 5.2 建立 WIF pool 與 provider

```bash
gcloud iam workload-identity-pools create github --location=global
gcloud iam workload-identity-pools providers create-oidc github-oidc \
  --location=global --workload-identity-pool=github \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='<owner>/<repo>'"
```

`--attribute-condition` 將可聯合身分限定於本 repo，避免其他 repo 冒用。

### 5.3 允許本 repo 模擬 DEPLOY_SA

```bash
export PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
gcloud iam service-accounts add-iam-policy-binding "$DEPLOY_SA" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/attribute.repository/<owner>/<repo>"
```

### 5.4 設定 GitHub repo 變數（Settings → Secrets and variables → Actions → Variables）

- `WIF_PROVIDER`：`projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/github/providers/github-oidc`
- `DEPLOY_SA`：`gh-deployer@<PROJECT_ID>.iam.gserviceaccount.com`
- `GCP_PROJECT`：`<PROJECT_ID>`

### 5.5 workflow 說明

`.github/workflows/deploy.yml` 於 push 到 `main` 時：先跑 `test`（pytest），通過後 `deploy` build 映像推 Artifact Registry，再 `gcloud run deploy`。

**取捨（重要）**：`/webhook` 需可被 Telegram（外部）呼叫，故 Cloud Run 採 `--allow-unauthenticated`。安全性完全依賴端點自帶的標頭驗證——`/tick` 比對 `X-Tick-Token`、`/webhook` 比對 `X-Telegram-Bot-Api-Secret-Token`，兩者皆為 Secret Manager 中的長隨機字串。未帶正確標頭一律回 403。

### 5.6 觸發部署並驗證

```bash
git push origin main
# 到 GitHub Actions 確認 test 與 deploy 皆綠燈，取得 Cloud Run URL：
gcloud run services describe tainan-bus --region asia-east1 --format='value(status.url)'
curl -s -o /dev/null -w "%{http_code}" "<URL>/healthz"   # 預期 200
```

---

## 6. Cloud Scheduler 與 Telegram webhook 串接

以下 `$URL` 為 Cloud Run URL；`$TICK`、`$BOT`、`$HOOK` 分別為 `TICK_AUTH_TOKEN`、`TELEGRAM_BOT_TOKEN`、`TELEGRAM_WEBHOOK_SECRET` 的實際值。

### 6.1 建立 Cloud Scheduler job（帶自訂標頭）

```bash
gcloud scheduler jobs create http tainan-bus-tick \
  --location=asia-east1 \
  --schedule="*/5 * * * *" \
  --time-zone="Asia/Taipei" \
  --uri="${URL}/tick" \
  --http-method=POST \
  --headers="X-Tick-Token=${TICK}"
```

預期：`Created job [tainan-bus-tick]`。

### 6.2 手動觸發一次並驗證

```bash
gcloud scheduler jobs run tainan-bus-tick --location=asia-east1
gcloud run services logs read tainan-bus --region asia-east1 --limit=20
```

預期：log 顯示 `/tick` 200（窗口外時無推播屬正常）。

### 6.3 設定 Telegram webhook（帶 secret token）

```bash
curl -s "https://api.telegram.org/bot${BOT}/setWebhook" \
  -d "url=${URL}/webhook" \
  -d "secret_token=${HOOK}"
```

預期：回傳 `{"ok":true,"result":true,...}`。Telegram 之後每則更新都會在標頭帶上 `X-Telegram-Bot-Api-Secret-Token`，供 `/webhook` 驗證。

### 6.4 端到端驗證

在 Telegram 對 bot 送 `/start` → 應收到歡迎詞與常駐設定鍵盤。

```bash
curl -s "https://api.telegram.org/bot${BOT}/getWebhookInfo"
```

預期：`pending_update_count` 不持續累積、無 `last_error_message`。

---

## 7. 上線後檢查清單

- [ ] **TDX 額度模式**：到 TDX 會員專區確認所用 API 屬「基礎服務（免費）」；本專案每月約 858 次呼叫，在免費額度內。若額度不足，改為縮短推播窗口或拉長推播間隔，**不購買點數**。
- [ ] **路線與站名一致性**：確認 TDX 實際回傳的 70左／70右 `RouteName`、方向（`Direction`）與站名，與設定中的 `台南高工`（上班 70左）、`中華西路二段`（下班 70右）一致；若 TDX 的 `StopName` 用字不同，需同步調整 `app/models.py` 的 `SLOT_DEFAULTS`。
- [ ] **首個上班日觀察**：於首個週二 08:00–09:30 窗口觀察是否如期推播（約 9 次），下班於週二～週六 18:30–21:00 觀察（約 30 次）。
- [ ] **失敗行為**：確認政府 API 連續 2 次失敗時，會推一次「政府API出狀況」回饋訊息並停止當時段當日推播，隔天自動恢復。
- [ ] **費用**：於 GCP 帳單頁確認無非預期費用，維持完全免費。
