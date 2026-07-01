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
