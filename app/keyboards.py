from __future__ import annotations

from app.models import VALID_INTERVALS

DAY_LABELS = {1: "週一", 2: "週二", 3: "週三", 4: "週四", 5: "週五", 6: "週六", 7: "週日"}
SLOT_LABELS = {"morning": "上班", "evening": "下班"}


def push_inline_keyboard(slot: str) -> dict:
    return {
        "inline_keyboard": [[
            {"text": "⏹ 停止推播", "callback_data": f"stop:{slot}"},
            {"text": "⏱ 推播間隔", "callback_data": f"interval:{slot}"},
        ]]
    }


def interval_picker_keyboard(scope: str, slot: str) -> dict:
    row = [{"text": f"{v}分", "callback_data": f"setint:{scope}:{slot}:{v}"} for v in VALID_INTERVALS]
    return {"inline_keyboard": [row]}


def settings_reply_keyboard() -> dict:
    return {
        "keyboard": [[
            {"text": "⏱ 推播間隔"},
            {"text": "🚏 推播公車站"},
            {"text": "📅 推播時間"},
        ]],
        "resize_keyboard": True,
        "is_persistent": True,
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
    buttons = []
    for d in range(1, 8):
        checked = "✅" if mask & (1 << (d - 1)) else ""
        buttons.append({"text": f"{checked}{DAY_LABELS[d]}", "callback_data": f"day:{d}:{mask}"})
    rows = [buttons[0:4], buttons[4:7], [{"text": "✅ 送出", "callback_data": f"daysub:{mask}"}]]
    return {"inline_keyboard": rows}
