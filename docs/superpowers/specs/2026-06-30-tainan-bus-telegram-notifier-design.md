# 台南公車到站通知 Bot — 設計書

- 日期：2026-06-30
- 狀態：已與使用者確認，待寫實作計畫
- 時區：Asia/Taipei（全系統一致）

## 1. 目的與範圍

為通勤者提供台南市區公車「70 左」「70 右」的到站時間主動推播，透過 Telegram 通知。

- **上班時段**：70 左公車，站牌「台南高工」
- **下班時段**：70 右公車，站牌「中華西路二段」

使用範圍：**我與少數親友**（multi-user-lite，每位使用者各有專屬設定）。

### 範圍外（先不做，列為未來）

- QRCode 虛擬站牌「叫公車 / 智慧等車（通知司機站牌有人）」。官方智慧等車為市府內部系統，公開 API 拿不到，故本版不實作。

## 2. 需求摘要

### 上班（70 左 → 台南高工）
- 預設 08:00 開始通知，超過 09:30 自動停止
- 預設每 10 分鐘一次（窗口內以預設間隔約 9 次）
- 可手動「停止推播」（只停當天上班時段）

### 下班（70 右 → 中華西路二段）
- 預設 18:30 開始通知，最晚 21:00 後停止
- 預設每 5 分鐘一次（窗口內以預設間隔約 30 次）
- 可手動「停止推播」（只停當天下班時段）

### 共通
- 「停止推播」只停「當天、該時段」，**隔天自動恢復**正常推播。
- 每則推播可改「當天、該時段」的剩餘間隔為 5/10/15/20 分。
- 持久專屬設定可套用每一天。
- 運行日預設「週二～週六」，可由使用者自行調整。

## 3. 額度評估（TDX）

- 資料來源：TDX 運輸資料流通服務平臺，端點 `/v2/Bus/EstimatedTimeOfArrival/City/Tainan/70`。一次呼叫回傳整條 70 路所有站牌的預估到站秒數，篩出目標站即可，**每次推播僅需 1 次 API 呼叫**。
- 用量：上班 9 + 下班 30 = **39 次/日**；以上班日約 22 天/月計 ≈ **858 次/月**。
- 「3 點」免費額度結論：
  - 舊模式（多數會員仍適用）：每把金鑰 50 次/秒、無每日上限 → 綽綽有餘。
  - 點數新模式：3 點/月。若公車即時動態屬「基礎服務」(1 點=1500 次) → 4500 次/月，足夠；若屬「進階服務」(1 點=200 次) → 600 次/月，略不足，但點數 1 元/點，每月補幾元即可，或將間隔拉長即可塞進免費額度。
- 頻率限制（最壞每分鐘 5 次）對「每 5～10 分鐘一次」的分散呼叫無影響。
- **行動項**：部署前到 TDX 會員專區確認自己帳號實際適用的額度模式。

來源：
- TDX 官網 — https://tdx.transportdata.tw/
- TDX 介接指南 — https://bookdown.org/chiajungyeh/TDX_Guide/
- 點數制度討論 — https://www.threads.com/@darrell_tw_/post/DC3ocjty016
- API 授權驗證說明 — https://motc-ptx.gitbook.io/tdx-xin-shou-zhi-yin/api-shi-yong-shuo-ming/api-shou-quan-yan-zheng-yu-shi-yong-fang-shi

## 4. 系統架構

```
Cloud Scheduler ──每5分鐘(Asia/Taipei)──▶ POST /tick ─┐
                                                       ├─▶ Cloud Run (FastAPI, 單一服務)
Telegram ────webhook(按鈕/指令)──▶ POST /webhook ──────┘        │
                                                                ├─▶ TDX API (公車到站, OAuth token 快取)
                                                                ├─▶ Firestore (使用者設定 + 當日狀態 + token 快取)
                                                                └─▶ Telegram sendMessage / answerCallbackQuery
```

- **單一 Cloud Run 服務**，兩個端點：
  - `/tick`：Cloud Scheduler 觸發，掃描所有使用者並決定推播。
  - `/webhook`：接 Telegram 互動（callback_query 按鈕、指令）。
- 閒置可縮到 0，符合免費額度。
- **Firestore**（serverless 免費額度）存設定、當日狀態、TDX token 快取，取代資料庫。
- **Secret Manager** 存 TDX `client_id/secret`、Telegram bot token。
- **排程策略**：每 5 分鐘 tick 全量掃描，而非動態建排程。理由：所有間隔(5/10/15/20)皆為 5 的倍數、時段皆從 :00/:30 起算，對齊時鐘的 5 分鐘 tick 可涵蓋所有情況；邏輯單純、不需動態增刪 Scheduler job。

## 5. 資料模型（Firestore）

### 使用者持久設定 `users/{chatId}`
```
{
  chatId: number,
  enabledDays: number[],          // 預設 [2,3,4,5,6]（週二~週六；1=週一…7=週日）
  slots: {
    morning: { bus: "70左", stopName: "台南高工",     windowStart: "08:00", windowEnd: "09:30", defaultInterval: 10 },
    evening: { bus: "70右", stopName: "中華西路二段", windowStart: "18:30", windowEnd: "21:00", defaultInterval: 5 }
  }
}
```
- 推播間隔可分上班/下班各設一個（`slots.morning.defaultInterval` / `slots.evening.defaultInterval`），套用每一天。
- 站牌與時段固定，先用需求書預設值；「推播公車站」設定本版以唯讀展示為主。

### 當日執行狀態 `users/{chatId}/runtime/{YYYY-MM-DD}`
```
{
  morning: { stopped: bool, intervalOverride: number|null, lastPushAt: timestamp|null },
  evening: { stopped: bool, intervalOverride: number|null, lastPushAt: timestamp|null }
}
```
- `stopped`：手動或自動停 → true；隔天為新文件，自動恢復。
- `intervalOverride`：當天「推播間隔」按鈕設的值；隔天失效，回到 `defaultInterval`。
- `lastPushAt`：用於計算下一次是否到期。

### TDX token 快取
- 存於 Firestore（如 `system/tdxToken`）含 `accessToken` 與 `expiresAt`，避免每次 tick 重新認證（token 效期 24 小時）。

## 6. 排程與推播邏輯（`/tick`）

每次 tick，對每位使用者：
1. 今天（Asia/Taipei 星期）是否在 `enabledDays`？否 → 跳過。
2. 現在落在哪個時段窗口（早 08:00–09:30 / 晚 18:30–21:00）？都不在 → 跳過。
3. 該時段今天是否已 `stopped`？是 → 跳過。
4. 是否到期？（`lastPushAt` 為空＝窗口起點第一推；否則 `now − lastPushAt ≥ 有效間隔`，有效間隔 = `intervalOverride ?? defaultInterval`）→ 推播。
5. 呼叫 TDX → 取目標站 ETA → 套狀態文案 → `sendMessage`（附 2 顆 inline 按鈕）→ 更新 `lastPushAt`。
6. 現在 ≥ 窗口結束時間（09:30 / 21:00）→ 標記該時段 `stopped`（自動停）。

第一推對齊窗口起點：5 分鐘 tick 對齊時鐘，08:00 / 18:30 的 tick 觸發第一推。

## 7. 通知文案（依 TDX 狀態）

TDX `EstimatedTimeOfArrival` 主要欄位：`EstimateTime`（秒）、`StopStatus`（0 正常／1 尚未發車／2 交管不停靠／3 末班車已過／4 今日未營運）、`PlateNumb`。

| 狀況 | 判定 | 文案範例 |
|---|---|---|
| 正常有 ETA | StopStatus=0 且 EstimateTime 較大 | `🚌 70左 預估 7 分鐘到「台南高工」` |
| ETA 極短/進站 | StopStatus=0 且 EstimateTime 很小（約 ≤60 秒） | `🚌 70左 進站中，即將到「台南高工」` |
| 尚未發車 | StopStatus=1 | `🚌 70左 尚未發車（台南高工）` |
| 交管不停靠 | StopStatus=2 | `🚧 70左 交管不停靠（台南高工）` |
| 末班車已過 | StopStatus=3 | `🌙 70右 末班車已過` |
| 今日未營運 | StopStatus=4 | `70右 今日未營運` |
| API 異常/拉不到 | 呼叫失敗或無資料 | `⚠️ 政府API出狀況，暫時無法取得正確的資訊。` |

- ETA 分鐘以 `ceil(EstimateTime/60)` 計。
- 「站名」「路線」依該時段設定動態帶入。

## 8. Telegram 互動設計

### 每則推播底部 2 顆 inline 按鈕
- `⏹ 停止推播`：停掉「當天、該時段」主動推播（依推播來源時段判定早/晚），隔天自動恢復。
- `⏱ 推播間隔`：點開選 `5/10/15/20` 分，套用「當天、該時段」剩餘推播（寫入 `intervalOverride`）。

### 頻道底部專屬設定（常駐 reply 鍵盤）
常駐於輸入框上方，貼合「頻道底部」：
- `⏱ 推播間隔` → 先選上班/下班，再選 5/10/15/20（寫入持久 `defaultInterval`，套用每一天）。
- `🚏 推播公車站` → 選上班/下班，展示各自綁定站牌（本版以唯讀展示為主，預設需求書站牌）。
- `📅 推播時間` → 跳出「週一…週日」**inline 複選**，已選顯示打勾（`週一`／`✅週二`），點擊即時切換；底排 `✅ 送出` 才存檔到 `enabledDays`。

UI/UX 原則：複選日用 inline 按鈕即時切換打勾、狀態可見、一鍵送出，避免一次塞太多。

### 指令
- `/start`：註冊 `chatId`（建立預設 `users/{chatId}`），顯示常駐設定鍵盤與簡短說明。

## 9. 部署與 CI/CD

- **GitHub**：保存原始碼。
- **GitHub Actions**：push 主分支 → build 容器 → 部署 Cloud Run；以 Workload Identity Federation 取代長期金鑰；機密走 Secret Manager。
- **Cloud Scheduler**：每 5 分鐘（Asia/Taipei）POST `/tick`，帶驗證標頭（OIDC）。
- **Telegram webhook**：部署後設定 webhook 指向 `/webhook`。

## 10. 測試策略

- **單元測試（純函式）**：時段判定、間隔到期計算、`enabledDays` 比對、TDX 回應解析、狀態→文案對應。mock TDX 與 Telegram。
- **整合測試**：`/tick`（給定時間與使用者狀態 → 預期是否推播與內容）、`/webhook`（各 callback / 指令 → 預期狀態變更與回覆）。
- 以可注入的「現在時間」與外部 client 介面，讓邏輯可測。

## 11. 待辦/風險

- 部署前確認 TDX 帳號實際額度模式（基礎/進階點數）。
- 確認 70 左/70 右在 TDX 的 `RouteName` 與 `Direction`，以及目標站牌的正確 `StopName/StopID`（70 左去程、70 右回程方向）。
- Cloud Run 縮到 0 時的冷啟動延遲對 5 分鐘 tick 可接受。
