# 台南公車通知 Bot — Plan 4：容器化與部署 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把服務容器化、用 GitHub Actions 部署到 Cloud Run、設定 Cloud Scheduler 每 5 分鐘觸發 `/tick`、設定 Telegram webhook，並寫一份可照做的部署手冊。

**Architecture:** 單一容器跑 FastAPI（uvicorn）；機密走 Secret Manager 並以環境變數注入；Cloud Scheduler 帶自訂標頭 `X-Tick-Token` 打 `/tick`；Telegram webhook 帶 `secret_token` 打 `/webhook`。CI/CD 以 Workload Identity Federation 免長期金鑰。前置依賴：Plan 1–3 全數完成且測試通過。

**Tech Stack:** Docker、Google Cloud Run、Cloud Scheduler、Secret Manager、Artifact Registry、GitHub Actions。

## Global Constraints

- 完全免費原則：使用 Cloud Run / Scheduler / Firestore / Secret Manager 免費額度，不開啟需付費資源。
- 機密：`TDX_CLIENT_ID`、`TDX_CLIENT_SECRET`、`TELEGRAM_BOT_TOKEN`、`TICK_AUTH_TOKEN`、`TELEGRAM_WEBHOOK_SECRET` 一律放 Secret Manager，不進 git。
- Cloud Run 區域建議 `asia-east1`（台灣，低延遲）。
- Cloud Scheduler 時區 `Asia/Taipei`、頻率 `*/5 * * * *`。
- 容器需讀 `PORT` 環境變數（Cloud Run 注入，預設 8080）。

---

### Task 12: 容器化與本機冒煙測試

**Files:**
- Create: `requirements.txt`（正式 runtime 相依）
- Create: `Dockerfile`
- Create: `.dockerignore`
- Create: `.gitignore`

**Interfaces:**
- Produces：可建置並在本機跑起來的容器映像；`GET /healthz` 回 200。

- [ ] **Step 1: 建立 `requirements.txt`**

```text
fastapi==0.115.5
uvicorn[standard]==0.32.1
httpx==0.27.2
google-cloud-firestore==2.19.0
```

- [ ] **Step 2: 建立 `.gitignore`**

```text
__pycache__/
*.pyc
.venv/
.env
*.egg-info/
.pytest_cache/
```

- [ ] **Step 3: 建立 `.dockerignore`**

```text
.git
.venv
tests
docs
__pycache__
.pytest_cache
*.md
```

- [ ] **Step 4: 建立 `Dockerfile`**

```dockerfile
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
```

- [ ] **Step 5: 本機建置映像**

Run: `docker build -t tainan-bus:local .`
Expected: 建置成功（最後一行 `naming to docker.io/library/tainan-bus:local`）

- [ ] **Step 6: 本機冒煙測試 `/healthz`**

Run:
```bash
docker run -d --name tainan-bus-smoke -p 8080:8080 \
  -e TICK_AUTH_TOKEN=x -e TELEGRAM_WEBHOOK_SECRET=y tainan-bus:local
sleep 3
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/healthz
docker rm -f tainan-bus-smoke
```
Expected: 輸出 `200`

- [ ] **Step 7: Commit**

```bash
git add requirements.txt Dockerfile .dockerignore .gitignore
git commit -m "chore: 容器化（Dockerfile/requirements/ignore）"
```

---

### Task 13: GCP 資源與機密（手動一次性設定，寫入手冊）

**Files:**
- Create: `docs/DEPLOY.md`

**Interfaces:**
- Produces：一次性建立的 GCP 資源（Artifact Registry、Secret Manager、Firestore、服務帳號與 WIF）；步驟記錄於 `docs/DEPLOY.md` 供重現。

> 註：本任務為基礎建設設定，無單元測試；每步以實際指令輸出作為驗證。請將 `PROJECT_ID` 換成自己的專案。

- [ ] **Step 1: 設定變數並啟用 API**

Run:
```bash
export PROJECT_ID=<your-project>
export REGION=asia-east1
gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com cloudscheduler.googleapis.com \
  secretmanager.googleapis.com artifactregistry.googleapis.com firestore.googleapis.com
```
Expected: `Operation finished successfully`

- [ ] **Step 2: 建立 Firestore（原生模式）與 Artifact Registry**

Run:
```bash
gcloud firestore databases create --location="$REGION" --type=firestore-native
gcloud artifacts repositories create tainan-bus --repository-format=docker --location="$REGION"
```
Expected: 兩者皆建立成功（Firestore 若已存在會提示，可忽略）

- [ ] **Step 3: 建立機密**

Run（逐一將值貼入；`TICK_AUTH_TOKEN`、`TELEGRAM_WEBHOOK_SECRET` 用隨機長字串）：
```bash
for s in TDX_CLIENT_ID TDX_CLIENT_SECRET TELEGRAM_BOT_TOKEN TICK_AUTH_TOKEN TELEGRAM_WEBHOOK_SECRET; do
  printf "set value for %s: " "$s"; read -r v; printf "%s" "$v" | gcloud secrets create "$s" --data-file=-;
done
```
Expected: 每個 secret 顯示 `Created secret [...]`

- [ ] **Step 4: 建立 Cloud Run 執行服務帳號並授權讀取機密 + Firestore**

Run:
```bash
gcloud iam service-accounts create tainan-bus-run --display-name="tainan-bus run"
export RUN_SA="tainan-bus-run@${PROJECT_ID}.iam.gserviceaccount.com"
for s in TDX_CLIENT_ID TDX_CLIENT_SECRET TELEGRAM_BOT_TOKEN TICK_AUTH_TOKEN TELEGRAM_WEBHOOK_SECRET; do
  gcloud secrets add-iam-policy-binding "$s" --member="serviceAccount:${RUN_SA}" --role=roles/secretmanager.secretAccessor;
done
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${RUN_SA}" --role=roles/datastore.user
```
Expected: 每筆 binding 回傳更新後的政策

- [ ] **Step 5: 將以上步驟整理寫入 `docs/DEPLOY.md`**

把 Step 1–4 的指令與「需準備的機密清單、區域、服務帳號」整理成可重現手冊；並加一節「如何取得 TDX 金鑰」（到 TDX 會員專區建立 API Key）與「如何建立 Telegram bot」（與 @BotFather 對話取得 token）。

- [ ] **Step 6: Commit**

```bash
git add docs/DEPLOY.md
git commit -m "docs: GCP 一次性設定手冊 DEPLOY.md"
```

---

### Task 14: GitHub Actions 持續部署

**Files:**
- Create: `.github/workflows/deploy.yml`
- Modify: `docs/DEPLOY.md`（追加 WIF 與 GitHub 設定）

**Interfaces:**
- Produces：push 到 `main` → build 映像推 Artifact Registry → 部署 Cloud Run（注入 secrets）。

- [ ] **Step 1: 建立 WIF 與部署服務帳號（手冊步驟，寫入 `docs/DEPLOY.md`）**

Run（重點指令）：
```bash
gcloud iam service-accounts create gh-deployer --display-name="github deployer"
export DEPLOY_SA="gh-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${DEPLOY_SA}" --role=roles/run.admin
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${DEPLOY_SA}" --role=roles/artifactregistry.writer
gcloud iam service-accounts add-iam-policy-binding "$RUN_SA" --member="serviceAccount:${DEPLOY_SA}" --role=roles/iam.serviceAccountUser
gcloud iam workload-identity-pools create github --location=global
gcloud iam workload-identity-pools providers create-oidc github-oidc \
  --location=global --workload-identity-pool=github \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='<owner>/<repo>'"
```
然後綁定 repo 可模擬 `DEPLOY_SA`，並把 provider 資源名稱與 `DEPLOY_SA` 設為 GitHub repo 變數 `WIF_PROVIDER`、`DEPLOY_SA`、`GCP_PROJECT`。
Expected: 各資源建立成功；GitHub repo Variables 設定完成。

- [ ] **Step 2: 建立 `.github/workflows/deploy.yml`**

```yaml
name: deploy
on:
  push:
    branches: [main]

permissions:
  contents: read
  id-token: write

env:
  REGION: asia-east1
  SERVICE: tainan-bus

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements-dev.txt
      - run: python -m pytest -q

  deploy:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ vars.WIF_PROVIDER }}
          service_account: ${{ vars.DEPLOY_SA }}
      - uses: google-github-actions/setup-gcloud@v2
      - name: Build & push
        run: |
          IMAGE="${REGION}-docker.pkg.dev/${{ vars.GCP_PROJECT }}/tainan-bus/app:${GITHUB_SHA}"
          gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
          docker build -t "$IMAGE" .
          docker push "$IMAGE"
          echo "IMAGE=$IMAGE" >> "$GITHUB_ENV"
      - name: Deploy to Cloud Run
        run: |
          gcloud run deploy "$SERVICE" \
            --image "$IMAGE" \
            --region "$REGION" \
            --service-account "tainan-bus-run@${{ vars.GCP_PROJECT }}.iam.gserviceaccount.com" \
            --no-allow-unauthenticated \
            --set-secrets "TDX_CLIENT_ID=TDX_CLIENT_ID:latest,TDX_CLIENT_SECRET=TDX_CLIENT_SECRET:latest,TELEGRAM_BOT_TOKEN=TELEGRAM_BOT_TOKEN:latest,TICK_AUTH_TOKEN=TICK_AUTH_TOKEN:latest,TELEGRAM_WEBHOOK_SECRET=TELEGRAM_WEBHOOK_SECRET:latest"
```

> 註：`/webhook` 需可被 Telegram（外部）呼叫，但服務以 `--no-allow-unauthenticated` 保護。解法：webhook 端點靠 `X-Telegram-Bot-Api-Secret-Token` 驗證即可，因此實務上 `/webhook` 必須公開可達；可改為 `--allow-unauthenticated` 並完全依賴 secret token 驗證（兩端點都已自帶標頭驗證）。請在 `docs/DEPLOY.md` 標明此取捨，並採 `--allow-unauthenticated`。

- [ ] **Step 3: 修正部署旗標為 `--allow-unauthenticated`**

把 Step 2 的 `--no-allow-unauthenticated` 改為 `--allow-unauthenticated`（兩端點自帶 token/secret 標頭驗證），並於 `docs/DEPLOY.md` 記錄理由。

- [ ] **Step 4: 推送觸發部署並驗證**

Run:
```bash
git add .github/workflows/deploy.yml docs/DEPLOY.md
git commit -m "ci: GitHub Actions 部署到 Cloud Run"
git push origin main
```
到 GitHub Actions 確認 `test` 與 `deploy` 皆綠燈；取得 Cloud Run URL：
```bash
gcloud run services describe tainan-bus --region asia-east1 --format='value(status.url)'
curl -s -o /dev/null -w "%{http_code}" "<URL>/healthz"
```
Expected: Actions 綠燈；`/healthz` 回 `200`

---

### Task 15: Cloud Scheduler 與 Telegram webhook 串接

**Files:**
- Modify: `docs/DEPLOY.md`（追加排程與 webhook 設定 + 驗證）

**Interfaces:**
- Produces：每 5 分鐘觸發 `/tick`；Telegram 更新打到 `/webhook`。

- [ ] **Step 1: 建立 Cloud Scheduler job（帶自訂標頭）**

Run（`$URL` 為 Cloud Run URL；`$TICK` 為 `TICK_AUTH_TOKEN` 的值）：
```bash
gcloud scheduler jobs create http tainan-bus-tick \
  --location=asia-east1 \
  --schedule="*/5 * * * *" \
  --time-zone="Asia/Taipei" \
  --uri="${URL}/tick" \
  --http-method=POST \
  --headers="X-Tick-Token=${TICK}"
```
Expected: `Created job [tainan-bus-tick]`

- [ ] **Step 2: 手動觸發一次並驗證**

Run:
```bash
gcloud scheduler jobs run tainan-bus-tick --location=asia-east1
gcloud run services logs read tainan-bus --region asia-east1 --limit=20
```
Expected: log 顯示 `/tick` 200（窗口外時無推播屬正常）

- [ ] **Step 3: 設定 Telegram webhook（帶 secret token）**

Run（`$BOT` 為 bot token；`$HOOK` 為 `TELEGRAM_WEBHOOK_SECRET` 的值）：
```bash
curl -s "https://api.telegram.org/bot${BOT}/setWebhook" \
  -d "url=${URL}/webhook" \
  -d "secret_token=${HOOK}"
```
Expected: 回傳 `{"ok":true,"result":true,...}`

- [ ] **Step 4: 端到端驗證**

操作：在 Telegram 對 bot 送 `/start` → 應收到歡迎詞與常駐設定鍵盤。
驗證：
```bash
curl -s "https://api.telegram.org/bot${BOT}/getWebhookInfo"
```
Expected: `pending_update_count` 不持續累積、無 `last_error_message`；Telegram 端收到回覆。

- [ ] **Step 5: 在 `docs/DEPLOY.md` 補上「上線後檢查清單」**

包含：到 TDX 會員專區確認額度模式；確認 70左/70右 的 `RouteName`/方向與站名（`台南高工`、`中華西路二段`）與 TDX 實際 `StopName` 一致；首個上班日窗口（週二 08:00）觀察是否如期推播。

- [ ] **Step 6: Commit**

```bash
git add docs/DEPLOY.md
git commit -m "docs: Cloud Scheduler 與 Telegram webhook 串接與上線檢查清單"
```

---

## 計畫自我檢查（對照 spec）

- 容器化、`/healthz` 冒煙 → Task 12
- Secret Manager 機密、Firestore、服務帳號 → Task 13
- GitHub Actions CI（跑測試）+ CD（部署 Cloud Run，注入 secrets，WIF 免金鑰）→ Task 14
- Cloud Scheduler 每 5 分鐘（Asia/Taipei）打 `/tick`；Telegram webhook 帶 secret → Task 15
- 上線檢查：TDX 額度模式、路線/站名一致性 → Task 15 Step 5（呼應 spec 第 11 節待辦/風險）
