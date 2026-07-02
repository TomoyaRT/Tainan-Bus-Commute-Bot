from __future__ import annotations

from datetime import datetime
from math import ceil

from app.models import SlotConfig

API_ERROR_TEXT = "⚠️ 政府系統異常，無法取得正確的資訊，請稍後再試。"
NEAR_ARRIVAL_SECONDS = 60


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


def format_eta_message(slot: SlotConfig, stop_status: int, estimate_time: int | None) -> str:
    bus = slot.bus
    name = slot.stop_name
    if stop_status in (0, 1) and estimate_time is not None and estimate_time > 0:
        if estimate_time <= NEAR_ARRIVAL_SECONDS:
            return f"🚌 {bus} - 進站中，即將到「{name}」"
        return f"🚌 {bus} - 預估 {ceil(estimate_time / 60)} 分鐘到「{name}」"
    if stop_status == 0:
        return API_ERROR_TEXT
    if stop_status == 1:
        return f"🚌 {bus} - 尚未發車（{name}）"
    if stop_status == 2:
        return f"🚧 {bus} - 交管不停靠（{name}）"
    if stop_status == 3:
        return f"🌙 {bus} - 末班車已過"
    if stop_status == 4:
        return f"{bus} - 今日未營運"
    return API_ERROR_TEXT
