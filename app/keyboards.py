from __future__ import annotations

from app.models import VALID_INTERVALS

DAY_LABELS = {1: "週一", 2: "週二", 3: "週三", 4: "週四", 5: "週五", 6: "週六", 7: "週日"}
SLOT_LABELS = {"morning": "上班", "evening": "下班"}

# 底部常駐鍵盤的按鈕文字（同時作為 webhook 訊息路由的 key）
BTN_PUSH_NOW = "立即推播"
BTN_SETTINGS = "設定"
BTN_MANUAL = "說明書"


def push_inline_keyboard(slot: str) -> dict:
    return {
        "inline_keyboard": [[
            {"text": "停止推播", "callback_data": f"stop:{slot}"},
            {"text": "推播間隔", "callback_data": f"interval:{slot}"},
        ]]
    }


def interval_picker_keyboard(scope: str, slot: str) -> dict:
    row = [{"text": f"{v}分", "callback_data": f"setint:{scope}:{slot}:{v}"} for v in VALID_INTERVALS]
    return {"inline_keyboard": [row]}


def settings_reply_keyboard() -> dict:
    """底部常駐鍵盤：立即推播、設定、說明書。"""
    return {
        "keyboard": [[{"text": BTN_PUSH_NOW}, {"text": BTN_SETTINGS}, {"text": BTN_MANUAL}]],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def settings_menu_keyboard() -> dict:
    """點「設定」後用訊息展開的功能選單。"""
    return {
        "inline_keyboard": [[
            {"text": "推播間隔", "callback_data": "menu:interval"},
            {"text": "推播時間", "callback_data": "menu:days"},
            {"text": "公車站與時段", "callback_data": "menu:stops"},
        ]]
    }


def slot_choice_keyboard(action: str) -> dict:
    row = [{"text": SLOT_LABELS[s], "callback_data": f"slotpick:{action}:{s}"} for s in ("morning", "evening")]
    return {"inline_keyboard": [row]}


def days_to_mask(days: list[int]) -> int:
    mask = 0
    for d in days:
        mask |= 1 << (d - 1)
    return mask


def mask_to_days(mask: int) -> list[int]:
    return [d for d in range(1, 8) if mask & (1 << (d - 1))]


def day_picker_keyboard(mask: int) -> dict:
    """星期複選：已選為「✅ 週X」、未選為「週X」（再點一下取消）；
    最後一列為外觀明顯不同的「保存設定」按鈕。"""
    buttons = []
    for d in range(1, 8):
        selected = bool(mask & (1 << (d - 1)))
        label = f"✅ {DAY_LABELS[d]}" if selected else DAY_LABELS[d]
        buttons.append({"text": label, "callback_data": f"day:{d}:{mask}"})
    rows = [buttons[0:4], buttons[4:7], [{"text": "⏰ 保存設定", "callback_data": f"daysub:{mask}"}]]
    return {"inline_keyboard": rows}
