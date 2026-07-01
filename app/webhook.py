from __future__ import annotations

from datetime import datetime

from app.keyboards import (
    SLOT_LABELS, day_picker_keyboard, days_to_mask, interval_picker_keyboard,
    mask_to_days, settings_reply_keyboard, slot_choice_keyboard,
)
from app.models import UserSettings

BTN_INTERVAL = "⏱ 推播間隔"
BTN_STOPS = "🚏 推播公車站"
BTN_DAYS = "📅 推播時間"


async def handle_update(update: dict, store, telegram, now: datetime) -> None:
    if "callback_query" in update:
        await _handle_callback(update["callback_query"], store, telegram, now)
    elif "message" in update:
        await _handle_message(update["message"], store, telegram)


async def _ensure_user(store, chat_id: int) -> UserSettings:
    user = await store.get_user(chat_id)
    if user is None:
        user = UserSettings.default(chat_id)
        await store.save_user(user)
    return user


def _bus_stop_text(user: UserSettings) -> str:
    m = user.slots["morning"]
    e = user.slots["evening"]
    return (
        "目前推播公車站（預設）：\n"
        f"上班：{m.bus}（{m.stop_name}）\n"
        f"下班：{e.bus}（{e.stop_name}）"
    )


async def _handle_message(message: dict, store, telegram) -> None:
    chat_id = message["chat"]["id"]
    text = message.get("text", "")
    if text.startswith("/start"):
        await _ensure_user(store, chat_id)
        await telegram.send_message(
            chat_id,
            "歡迎！已開啟 70左/70右 到站通知。可用下方按鈕調整設定。",
            settings_reply_keyboard(),
        )
    elif text == BTN_INTERVAL:
        await telegram.send_message(chat_id, "要設定哪個時段的每日預設間隔？", slot_choice_keyboard("defint"))
    elif text == BTN_STOPS:
        user = await _ensure_user(store, chat_id)
        await telegram.send_message(chat_id, _bus_stop_text(user))
    elif text == BTN_DAYS:
        user = await _ensure_user(store, chat_id)
        await telegram.send_message(
            chat_id, "選擇要推播的星期，完成後按送出：",
            day_picker_keyboard(days_to_mask(user.enabled_days)),
        )


async def _handle_callback(cb: dict, store, telegram, now: datetime) -> None:
    data = cb["data"]
    cb_id = cb["id"]
    chat_id = cb["message"]["chat"]["id"]
    message_id = cb["message"]["message_id"]
    parts = data.split(":")
    kind = parts[0]
    date_str = now.strftime("%Y-%m-%d")

    try:
        if kind == "stop":
            slot = parts[1]
            runtime = await store.get_runtime(chat_id, date_str)
            runtime.slot(slot).stopped = True
            await store.save_runtime(chat_id, date_str, runtime)
            await telegram.answer_callback_query(cb_id, f"已停止今日{SLOT_LABELS[slot]}推播")

        elif kind == "interval":
            slot = parts[1]
            await telegram.answer_callback_query(cb_id)
            await telegram.send_message(
                chat_id, f"設定今日{SLOT_LABELS[slot]}剩餘推播間隔：",
                interval_picker_keyboard("today", slot),
            )

        elif kind == "setint":
            scope, slot, val = parts[1], parts[2], int(parts[3])
            if scope == "today":
                runtime = await store.get_runtime(chat_id, date_str)
                runtime.slot(slot).interval_override = val
                await store.save_runtime(chat_id, date_str, runtime)
                await telegram.answer_callback_query(cb_id, f"今日{SLOT_LABELS[slot]}間隔改為{val}分")
            else:
                user = await _ensure_user(store, chat_id)
                user.slots[slot].default_interval = val
                await store.save_user(user)
                await telegram.answer_callback_query(cb_id, f"{SLOT_LABELS[slot]}每日間隔改為{val}分")

        elif kind == "slotpick":
            action, slot = parts[1], parts[2]
            if action == "defint":
                await telegram.answer_callback_query(cb_id)
                await telegram.send_message(
                    chat_id, f"設定{SLOT_LABELS[slot]}每日預設間隔：",
                    interval_picker_keyboard("default", slot),
                )
            else:
                await telegram.answer_callback_query(cb_id)

        elif kind == "day":
            d, mask = int(parts[1]), int(parts[2])
            new_mask = mask ^ (1 << (d - 1))
            await telegram.edit_message_reply_markup(chat_id, message_id, day_picker_keyboard(new_mask))
            await telegram.answer_callback_query(cb_id)

        elif kind == "daysub":
            mask = int(parts[1])
            user = await _ensure_user(store, chat_id)
            user.enabled_days = mask_to_days(mask)
            await store.save_user(user)
            await telegram.answer_callback_query(cb_id, "已更新推播日")

        else:
            # 未知類型（多半是改版後殘留的舊按鈕）→ 仍回應以停止載入圈
            await telegram.answer_callback_query(cb_id)

    except (ValueError, IndexError, KeyError):
        # callback_data 格式損壞/過期（例如舊按鈕、非法 slot 名）→ 回應以停止載入圈，
        # 不讓例外冒泡使 /webhook 回 500，避免 Telegram 重試風暴。
        await telegram.answer_callback_query(cb_id)
