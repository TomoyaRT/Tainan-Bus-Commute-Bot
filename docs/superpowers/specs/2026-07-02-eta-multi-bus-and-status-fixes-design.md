# 到站訊息:多車顯示 + 狀態判斷修正 設計文件

日期:2026-07-02
範圍:`app/formatting.py`、`app/tdx.py`、`app/scheduler.py`、`app/webhook.py`(+ 對應測試)

## 背景與問題

使用者回報兩個現象,診斷後確認根因(皆以線上 TDX 實測與 TDX 官方 swagger 佐證):

1. **排程推播偶發「政府系統異常」,但其他平台正常。**
   根因:`scheduler.py` 挑站用 `select_stop`,當同一 (站名, 子路線) 的到站筆數 ≠ 1 時回 `None` →
   丟 `TDXError("target stop not found")` → 因 `status_code` 為 `None` 走到 else 分支送出
   `API_ERROR_TEXT`(「政府系統異常」)。實際上 TDX 資料是好的,是挑站邏輯太嚴格:
   - 尖峰時同站同子路線可能同時有多台車 → 多筆。
   - 環狀線頭尾同站(如「永華市政中心(府前路)」為 70 左右的起點 seq 1 與終點 seq 41)恆為 2 筆。

2. **70 左/右到站時間比實際多 1~2 分鐘。**
   站名沒抓錯(實測 `matches=1`、StopUID 正確)。多出來的時間來自兩處:
   - `formatting.py` 用 `ceil()` 無條件進位(最多 +1 分)。
   - 直接使用原始 `EstimateTime`,未扣除「快照到現在」的經過時間。TDX 官方文件明載
     N1 資料不會自動遞減,需以 `EstimateTime - (收到資料時間 - 來源時間)` 校正。

另查出兩個既有邏輯 bug:

- **Bug A**:狀態 0(正常)且 `EstimateTime == 0`(車正進站)或 `None` 時,落入
  `if stop_status == 0: return API_ERROR_TEXT` → 車正到站卻報「政府系統異常」。
- **Bug B**:`formatting.py:14` 把狀態 1(尚未發車)且有 `EstimateTime` 的情形當到站時間顯示
  「預估 X 分鐘到站」。但 TDX 官方 swagger 明載此時 EstimateTime 是**「還要多久發車」**,
  非到站時間。臺南高工為中段站,顯示發車倒數會誤導使用者提早到站空等。

## 權威依據(TDX 官方 swagger)

`StopStatus` 定義(逐字):
`車輛狀態備註 : [0:'正常',1:'尚未發車',2:'交管不停靠',3:'末班車已過',4:'今日未營運']`

N1 到站資料說明(逐字節錄):
- 「當 StopStatus = 1(尚未發車) 且 EstimateTime > 0 時…提供的 EstimateTime 值為預計多久後**開始發車**之時間。」
- 「N1 僅於路線上有任一車輛離站時才重算發佈,使用者需自行處理時間遞減機制,或以
  `EstimateTime -(收到資料時間 - 來源時間)`(秒)作為實際預估抵達時間。」

現行程式 `status 2/3/4 → 交管不停靠/末班車已過/今日未營運` 的值對映**正確**,無須更動對映本身。

## 設計目標

- 多台車同時進站時,全部列出(上限 3 台),各自標示**車牌**與到站分鐘。
- 「政府系統異常」只在 TDX 真的取不到資料/錯誤狀態時出現。
- 修正 Bug A、Bug B。
- 到站分鐘改為**無條件捨去**,並扣除快照經過時間,貼近實際。

## 核心規則

### 1. 挑站:`select_stop` → `select_matches`(回傳 list)

`app/tdx.py`:新增/改為回傳**符合 (站名, 子路線前綴) 的所有筆數**(list),不再於多筆時回 `None`。
空 list 代表該站不在回傳資料中。保留 `_zh`、前綴比對邏輯不變。

> 保留舊 `select_stop` 名稱與否由實作決定;兩個呼叫點(scheduler、webhook)一律改用新版。

### 2. 到站秒數校正(共用工具)

對每筆 entry 計算「校正後秒數」:

```
adjusted = EstimateTime - (now - 來源時間).total_seconds()
adjusted = max(0, adjusted)          # 不為負
```

- 來源時間欄位:優先 `SrcUpdateTime`,無則 `DataTime`;兩者皆無則不校正(adjusted = EstimateTime)。
- 時間為 ISO8601 含時區,以 `datetime.fromisoformat` 解析;`now` 為 Asia/Taipei tz-aware。
- 分鐘顯示:`minutes = int(adjusted // 60)`(無條件捨去)。

### 3. 「可搭乘的車」判定

一筆 entry 視為**可搭乘(行駛中)**須同時滿足:
- `StopStatus == 0`(正常),且
- `EstimateTime` 不為 `None`。

以**狀態**為準而非 PlateNumb:TDX 文件載明尚未發車者(status 1)PlateNumb 為空,故 status 0
即代表有車在跑、EstimateTime 為真到站時間。`PlateNumb` 僅作**顯示標示**——有值就顯示車牌,
空/缺就省略車牌那段(不影響到站分鐘顯示)。此設計亦避免測試/邊界資料缺車牌時被誤殺。

可搭乘清單依 `adjusted` 由小到大排序,取前 **3** 筆。
`adjusted <= 60` 秒者視為「即將進站」。

### 4. 訊息組裝(依可搭乘車數量)

以早上 70 左、站名「臺南高工」為例。

**A. 可搭乘 ≥ 2 台(多車):標題 + 每台一行,最多 3 行**
```
🚌 70左 到「臺南高工」
・ EAA-732 預估 8 分鐘
・ EAA-728 預估 18 分鐘
```
- 即將進站的那台:`・ 即將進站的公車:EAA-732`
- 車牌缺值時該行省略車牌:`・ 預估 8 分鐘`。
- 尚未發車(status 1)的筆數:不列入可搭乘清單(使用者可搭其他台)。

**B. 可搭乘 == 1 台(單車):維持單行**
- 行駛中(有車牌):`🚌 70左 - EAA-732 預估 8 分鐘到「臺南高工」`
- 行駛中(車牌缺值):`🚌 70左 - 預估 8 分鐘到「臺南高工」`
- 即將進站(≤60 秒,有車牌):`🚌 70左 - EAA-732 即將進站到「臺南高工」`
- 即將進站(≤60 秒,車牌缺值):`🚌 70左 - 進站中，即將到「臺南高工」`

**C. 可搭乘 == 0 台:依剩餘 entry 的狀態給單一狀態訊息**
優先序(高→低,取最終定局者優先,避免被殘留的尚未發車蓋過):
1. 有 `StopStatus == 4` → `{bus} - 今日未營運`
2. 有 `StopStatus == 3` → `🌙 {bus} - 末班車已過`
3. 有 `StopStatus == 2` → `🚧 {bus} - 交管不停靠（{name}）`
4. 有 `StopStatus == 1` → `🚌 {bus} - 尚未發車（{name}）`(不顯示發車倒數,不編造到站時間)
5. 其餘(例如僅有 status 0 但 EstimateTime 為 None 的異常筆)→ `暫時查不到該站班次`

**D. 0 筆 match(站不在回傳資料中)** → `暫時查不到該站班次`

> Bug A 修正:狀態 0 且 `EstimateTime == 0` 因 `adjusted<=60` 落入「即將進站」,不再誤報系統異常。
> Bug B 修正:狀態 1 只會走到 C-4「尚未發車」,絕不顯示「預估 X 分鐘到站」。

### 5. 「政府系統異常」的唯一觸發條件

僅在 `tdx.get_eta` 真正失敗(網路錯誤/JSON 解析失敗/非 200)時,由 `TDXError` 觸發:
- `status_code in (403, 429)` → 「⚠️ TDX 公車 API 額度已用完,無法取得正確資訊。」
- 其他 → `API_ERROR_TEXT`(「政府系統異常…」)。

「暫時查不到該站班次」「尚未發車」等**不經** `TDXError`,不算失敗。

## 介面變更

### `app/formatting.py`
- `format_eta_message(slot, stop_status, estimate_time)` →
  `format_eta_message(cfg: SlotConfig, matches: list[dict], now: datetime) -> str`
  內含:秒數校正、可搭乘判定、排序、多/單車與狀態訊息組裝(第 4 節)。
- 常數:保留 `API_ERROR_TEXT`、`NEAR_ARRIVAL_SECONDS = 60`;新增多車上限常數(如 `MAX_BUSES = 3`)。

### `app/tdx.py`
- `select_matches(entries, stop_name, sub_route) -> list[dict]`(多筆不再回 None)。

### `app/scheduler.py`(`process_user`)
- 改呼叫 `select_matches` + 新版 `format_eta_message(cfg, matches, now)`。
- 移除「`match is None` → `raise TDXError`」;`matches` 為空時交由 `format_eta_message` 產生
  「暫時查不到該站班次」正常送出。
- `fail_count` / `stopped` 只在 `get_eta` 的 `TDXError` 時累加(維持既有語意);
  「暫時查不到」不累加、不停推。

### `app/webhook.py`(`_manual_push`)
- 同步改用 `select_matches` + 新版 `format_eta_message(cfg, matches, now)`。
- 移除自組的「查無資料」字串,統一由 `format_eta_message` 產生文案。

## 測試計畫(TDD,先寫失敗測試)

`tests/test_formatting.py`(主要):
- 單車行駛中 → `EAA-732 預估 X 分鐘到「臺南高工」`。
- 單車即將進站(≤60s)→ `EAA-732 即將進站到「臺南高工」`。
- 多車 2 台 → 標題 + 兩行,依 ETA 排序。
- 多車 4 台 → 只列前 3 台(上限)。
- 多車其一即將進站 → 該行為「即將進站的公車:EAA-732」。
- 多車其一尚未發車(無車牌)→ 該筆被略過。
- 全部尚未發車 → 「尚未發車」。
- 狀態 2/3/4 → 交管不停靠/末班車已過/今日未營運。
- **Bug A**:狀態 0 + `EstimateTime == 0` → 「進站中/即將進站」,非系統異常;
  狀態 0 + `EstimateTime == None` → 「暫時查不到該站班次」,非系統異常。
- **Bug B**:狀態 1 + `EstimateTime = 1726` → 「尚未發車」,非「預估到站」。
- **floor**:`EstimateTime` 對應 15.3 分 → 顯示「15 分鐘」(非 16)。
- **快照校正**:`EstimateTime=630`、來源時間比 now 早 90s → adjusted=540 → 顯示 9 分鐘(非 10/11)。
- 空 matches → 「暫時查不到該站班次」。

`tests/test_tdx.py`:
- `select_matches` 唯一站 → 1 筆;環狀頭尾同站 → 2 筆;不存在 → 0 筆。

`tests/test_scheduler.py` / `tests/test_webhook.py`:
- 多筆 match 不再觸發「政府系統異常」;正常組出多車訊息。
- `get_eta` 拋 `TDXError(403/429)` → 額度訊息;其他 → 政府系統異常;達門檻停推。
- 空 match → 送「暫時查不到」,不累加 fail_count、不停推。

## 既有行為變更(需同步更新既有測試)

- `test_formatting.py`:`format_eta_message` 簽章改變,全檔改寫(floor、多/單車、Bug A/B)。
- `test_scheduler.py::test_wrong_sub_route_is_not_pushed`:0 match 不再靜默+累加 fail_count,
  改為送「暫時查不到該站班次」、`fail_count == 0`、`last_push_at` 更新。
- 其餘 scheduler 測試以 `in` 子字串斷言到站文字者(如 `test_first_push`),floor 後數字不變者續用;
  受 floor 影響的預期值需更新。

## 更新(2026-07-02 補):尚未發車顯示估計到站(部分反轉 Bug B)

線上實測確認:**台南 TDX 對「尚未發車(status 1)」的班次會逐站給出到站估計**
(status-1 各站 EstimateTime 隨 StopSequence 遞增;起點=發車時間,之後每站累加行駛時間)。
先前 Bug B 因引用 TDX 文件「[部分縣市] EstimateTime=發車時間」而保守地丟掉估計,對台南是過度保守。

修正:`format_eta_message` 的「預測清單」由「只收 status 0」擴為**收 status 0 與 1**(皆需有校正後秒數),
兩者一起依到站秒數升冪排序、混排(避免漏掉比行駛中更快的下一班)。渲染依 status 標示:

- status 0(行駛中):原樣(車牌+預估分鐘/即將進站)。
- status 1(尚未發車,有估計):
  - 單筆:`🚌 {bus} - 尚未發車，估計 {分} 分鐘到「{name}」`
  - 多筆行:`・ 尚未發車，估計 {分} 分鐘到站`
  - 估計 ≤60 秒:`尚未發車，即將發車`。
- status 1 **無**估計:仍走狀態優先序 → `尚未發車（{name}）`。
- status 2/3/4:不進預測清單,行為不變。

其他部分(scheduler/webhook/冷卻/鍵盤/status0 顯示)完全不受影響。

## 不做(YAGNI)

- 不推估「尚未發車」車輛到本站的時間(缺乏可靠行駛時間資料,易誤導)。
- 不改推播排程/時窗/間隔邏輯。
- 不改站名設定(已確認站名正確)。
