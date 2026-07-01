from app.keyboards import (
    push_inline_keyboard, interval_picker_keyboard, settings_reply_keyboard,
    settings_main_keyboard, modify_settings_keyboard, info_settings_keyboard,
    slot_window_choice_keyboard, window_picker_keyboard,
    slot_choice_keyboard, day_picker_keyboard, boarding_stop_keyboard,
    days_to_mask, mask_to_days, BTN_PUSH_NOW, BTN_BOARDING, BTN_SETTINGS,
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
    assert labels == [BTN_PUSH_NOW, BTN_BOARDING, BTN_SETTINGS]


def test_boarding_stop_keyboard_has_url_buttons():
    kb = boarding_stop_keyboard()
    rows = kb["inline_keyboard"]
    # 上班（台南高工）在上、下班（中華西路二段）在下，各自一列
    assert rows[0][0]["text"] == "台南高工" and rows[0][0]["url"].endswith("code=0551")
    assert rows[1][0]["text"] == "中華西路二段" and "code=1046" in rows[1][0]["url"]
    assert all(b["url"].startswith("https://qrcode2384.tainan.gov.tw") for row in rows for b in row)


def test_settings_menu_keyboards():
    kb_main = settings_main_keyboard()
    datas_main = [b["callback_data"] for b in kb_main["inline_keyboard"][0]]
    assert datas_main == ["menu:modify_menu", "menu:info_menu"]

    kb_modify = modify_settings_keyboard()
    datas_modify = [b["callback_data"] for b in kb_modify["inline_keyboard"][0]]
    assert datas_modify == ["menu:interval", "menu:days", "menu:window"]
    assert kb_modify["inline_keyboard"][0][1]["text"] == "推播日"
    assert len(kb_modify["inline_keyboard"]) == 1  # 已移除返回鍵

    kb_info = info_settings_keyboard()
    datas_info = [b["callback_data"] for b in kb_info["inline_keyboard"][0]]
    assert datas_info == ["menu:stops", "menu:manual"]
    assert len(kb_info["inline_keyboard"]) == 1  # 已移除返回鍵

    kb_choice = slot_window_choice_keyboard()
    assert kb_choice["inline_keyboard"][0][0]["callback_data"] == "slotwin:morning"
    assert len(kb_choice["inline_keyboard"]) == 1  # 已移除返回鍵

    kb_picker = window_picker_keyboard("morning", "08:00", "09:30")
    flat = [b for row in kb_picker["inline_keyboard"] for b in row]
    assert any(b["text"] == "✅ 08:00" for b in flat)
    assert any(b["text"] == "✅ 09:30" for b in flat)
    assert any(b["callback_data"] == "winsub:morning:08:00:09:30" for b in flat)

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
    assert tue["text"] == "✅ 週二"   # 已選：✅ 前綴
    assert mon["text"] == "週一"       # 未選
    submit = flat[-1]
    assert submit["callback_data"] == f"daysub:{mask}"
    assert submit["text"] == "⏰ 保存設定"  # 保存按鈕外觀明顯不同
