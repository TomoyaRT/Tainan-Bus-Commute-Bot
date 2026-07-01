from app.keyboards import (
    push_inline_keyboard, interval_picker_keyboard, settings_reply_keyboard,
    settings_menu_keyboard, slot_choice_keyboard, day_picker_keyboard,
    days_to_mask, mask_to_days, BTN_PUSH_NOW, BTN_SETTINGS,
)

def test_push_inline_keyboard_has_stop_and_interval():
    kb = push_inline_keyboard("morning")
    row = kb["inline_keyboard"][0]
    assert row[0]["callback_data"] == "stop:morning"
    assert row[1]["callback_data"] == "interval:morning"

def test_interval_picker_lists_all_intervals_with_scope():
    kb = interval_picker_keyboard("today", "evening")
    datas = [b["callback_data"] for b in kb["inline_keyboard"][0]]
    assert datas == ["setint:today:evening:5", "setint:today:evening:10",
                     "setint:today:evening:15", "setint:today:evening:20"]

def test_settings_reply_keyboard_is_persistent():
    kb = settings_reply_keyboard()
    assert kb["is_persistent"] is True
    labels = [b["text"] for b in kb["keyboard"][0]]
    assert labels == [BTN_PUSH_NOW, BTN_SETTINGS]  # 精簡為兩顆：立即推播、設定


def test_settings_menu_lists_three_functions():
    kb = settings_menu_keyboard()
    datas = [b["callback_data"] for b in kb["inline_keyboard"][0]]
    assert datas == ["menu:interval", "menu:days", "menu:stops"]

def test_slot_choice_keyboard_encodes_action():
    kb = slot_choice_keyboard("defint")
    datas = [b["callback_data"] for b in kb["inline_keyboard"][0]]
    assert datas == ["slotpick:defint:morning", "slotpick:defint:evening"]

def test_mask_roundtrip():
    assert days_to_mask([1]) == 0b0000001
    assert days_to_mask([2, 3, 4, 5, 6]) == 0b0111110
    assert mask_to_days(days_to_mask([1, 7])) == [1, 7]

def test_day_picker_marks_selected_and_carries_mask():
    mask = days_to_mask([2])
    kb = day_picker_keyboard(mask)
    flat = [b for row in kb["inline_keyboard"] for b in row]
    tue = next(b for b in flat if b["callback_data"].startswith("day:2:"))
    mon = next(b for b in flat if b["callback_data"].startswith("day:1:"))
    assert tue["text"] == "【週二】"   # 已選：括號標示，不用表情符號
    assert mon["text"] == "週一"       # 未選
    submit = flat[-1]
    assert submit["callback_data"] == f"daysub:{mask}"
    assert submit["text"] == "送出設定"  # 送出按鈕外觀明顯不同、無表情符號
