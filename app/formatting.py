from __future__ import annotations

from datetime import datetime

from app.models import SlotConfig

API_ERROR_TEXT = "⚠️ 政府系統異常，無法取得正確的資訊，請稍後再試。"
NEAR_ARRIVAL_SECONDS = 60
NO_DATA_TEXT = "暫時查不到該站班次"
MAX_BUSES = 3


def source_time(entry: dict) -> datetime | None:
    for key in ("SrcUpdateTime", "DataTime"):
        raw = entry.get(key)
        if raw:
            try:
                dt = datetime.fromisoformat(raw)
            except (ValueError, TypeError):
                continue
            if dt.tzinfo is not None:
                return dt
    return None


def adjusted_seconds(entry: dict, now: datetime) -> int | None:
    est = entry.get("EstimateTime")
    if est is None:
        return None
    src = source_time(entry)
    if src is not None:
        est = est - (now - src).total_seconds()
    return max(0, int(est))


def _plate(entry: dict) -> str:
    return (entry.get("PlateNumb") or "").strip()


def _multi_line(adj: int, status: int, plate: str) -> str:
    if status == 1:  # 尚未發車：台南 TDX 逐站給到站估計
        if adj <= NEAR_ARRIVAL_SECONDS:
            return "・ 尚未發車，即將發車"
        return f"・ 尚未發車，估計 {adj // 60} 分鐘到站"
    if adj <= NEAR_ARRIVAL_SECONDS:
        return f"・ 即將進站的公車:{plate}" if plate else "・ 即將進站"
    mins = adj // 60
    return f"・ {plate} 預估 {mins} 分鐘" if plate else f"・ 預估 {mins} 分鐘"


def _single_line(cfg: SlotConfig, adj: int, status: int, plate: str) -> str:
    bus, name = cfg.bus, cfg.stop_name
    if status == 1:  # 尚未發車
        if adj <= NEAR_ARRIVAL_SECONDS:
            return f"🚌 {bus} - 尚未發車，即將發車（{name}）"
        return f"🚌 {bus} - 尚未發車，估計 {adj // 60} 分鐘到「{name}」"
    if adj <= NEAR_ARRIVAL_SECONDS:
        return (f"🚌 {bus} - {plate} 即將進站到「{name}」" if plate
                else f"🚌 {bus} - 進站中，即將到「{name}」")
    mins = adj // 60
    return (f"🚌 {bus} - {plate} 預估 {mins} 分鐘到「{name}」" if plate
            else f"🚌 {bus} - 預估 {mins} 分鐘到「{name}」")


def format_eta_message(cfg: SlotConfig, matches: list[dict], now: datetime) -> str:
    if not matches:
        return NO_DATA_TEXT

    predictions = []  # (adjusted_seconds, status, plate)
    for e in matches:
        status = int(e.get("StopStatus", 0))
        if status not in (0, 1):  # 交管/末班/未營運不是到站預測
            continue
        adj = adjusted_seconds(e, now)
        if adj is None:
            continue
        predictions.append((adj, status, _plate(e)))
    predictions.sort(key=lambda x: x[0])
    predictions = predictions[:MAX_BUSES]

    if len(predictions) >= 2:
        lines = [f"🚌 {cfg.bus} 到「{cfg.stop_name}」"]
        lines += [_multi_line(adj, status, plate) for adj, status, plate in predictions]
        return "\n".join(lines)
    if len(predictions) == 1:
        adj, status, plate = predictions[0]
        return _single_line(cfg, adj, status, plate)

    # 0 台可搭 → 依狀態優先序給單一狀態訊息
    statuses = {int(e.get("StopStatus", 0)) for e in matches}
    if 4 in statuses:
        return f"{cfg.bus} - 今日未營運"
    if 3 in statuses:
        return f"🌙 {cfg.bus} - 末班車已過"
    if 2 in statuses:
        return f"🚧 {cfg.bus} - 交管不停靠（{cfg.stop_name}）"
    if 1 in statuses:
        return f"🚌 {cfg.bus} - 尚未發車（{cfg.stop_name}）"
    return NO_DATA_TEXT
