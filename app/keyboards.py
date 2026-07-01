from __future__ import annotations

from app.models import VALID_INTERVALS

DAY_LABELS = {1: "週一", 2: "週二", 3: "週三", 4: "週四", 5: "週五", 6: "週六", 7: "週日"}
SLOT_LABELS = {"morning": "上班", "evening": "下班"}

# 底部常駐鍵盤的按鈕文字（同時作為 webhook 訊息路由的 key）
BTN_PUSH_NOW = "立即推播"
BTN_SETTINGS = "控制台"
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
    """底部常駐鍵盤：立即推播、設定。"""
    return {
        "keyboard": [[{"text": BTN_PUSH_NOW}, {"text": BTN_SETTINGS}]],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def settings_main_keyboard() -> dict:
    """點「控制台」後顯示的第一層類別選單。"""
    return {
        "inline_keyboard": [
            [{"text": "修改設定", "callback_data": "menu:modify_menu"},
             {"text": "顯示資訊", "callback_data": "menu:info_menu"}]
        ]
    }


def modify_settings_keyboard() -> dict:
    """「修改設定」子選單。"""
    return {
        "inline_keyboard": [
            [{"text": "推播間隔", "callback_data": "menu:interval"},
             {"text": "推播星期", "callback_data": "menu:days"},
             {"text": "推播時段", "callback_data": "menu:window"}],
            [{"text": "⬅️ 返回", "callback_data": "menu:main"}]
        ]
    }


def info_settings_keyboard() -> dict:
    """「顯示資訊」子選單。"""
    return {
        "inline_keyboard": [
            [{"text": "公車站與時段", "callback_data": "menu:stops"},
             {"text": "說明書", "callback_data": "menu:manual"}],
            [{"text": "⬅️ 返回", "callback_data": "menu:main"}]
        ]
    }


def slot_window_choice_keyboard() -> dict:
    """選擇要設定時段的行程。"""
    return {
        "inline_keyboard": [
            [{"text": "上班時段", "callback_data": "slotwin:morning"},
             {"text": "下班時段", "callback_data": "slotwin:evening"}],
            [{"text": "⬅️ 返回", "callback_data": "menu:modify_menu"}]
        ]
    }


def window_picker_keyboard(slot: str, current_start: str, current_end: str) -> dict:
    """時段選擇器：以每半小時為一個區段讓使用者點選。"""
    if slot == "morning":
        starts = ["07:00", "07:30", "08:00", "08:30"]
        ends = ["09:00", "09:30", "10:00", "10:30"]
    else:
        starts = ["17:30", "18:00", "18:30", "19:00"]
        ends = ["20:00", "20:30", "21:00", "21:30"]

    keyboard = []
    
    # 開始時間
    start_buttons = []
    for s in starts:
        label = f"✅ {s}" if s == current_start else s
        start_buttons.append({"text": label, "callback_data": f"winopt:{slot}:{s}:{current_end}"})
    
    # 結束時間
    end_buttons = []
    for e in ends:
        label = f"✅ {e}" if e == current_end else e
        end_buttons.append({"text": label, "callback_data": f"winopt:{slot}:{current_start}:{e}"})

    keyboard.append([{"text": "🏁 開始時間：", "callback_data": "noop"}])
    keyboard.append(start_buttons)
    keyboard.append([{"text": "🏁 結束時間：", "callback_data": "noop"}])
    keyboard.append(end_buttons)
    
    keyboard.append([
        {"text": "⏰ 保存時段設定", "callback_data": f"winsub:{slot}:{current_start}:{current_end}"}
    ])
    keyboard.append([
        {"text": "⬅️ 返回", "callback_data": "menu:window"}
    ])
    
    return {"inline_keyboard": keyboard}


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
