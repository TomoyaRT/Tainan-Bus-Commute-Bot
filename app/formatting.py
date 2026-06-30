from __future__ import annotations

from math import ceil

from app.models import SlotConfig

API_ERROR_TEXT = "⚠️ 政府API出狀況，暫時無法取得正確的資訊。"
NEAR_ARRIVAL_SECONDS = 60


def format_eta_message(slot: SlotConfig, stop_status: int, estimate_time: int | None) -> str:
    bus = slot.bus
    name = slot.stop_name
    if stop_status == 0:
        if estimate_time is not None and estimate_time <= NEAR_ARRIVAL_SECONDS:
            return f"🚌 {bus} - 進站中，即將到「{name}」"
        if estimate_time is not None:
            return f"🚌 {bus} - 預估 {ceil(estimate_time / 60)} 分鐘到「{name}」"
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
