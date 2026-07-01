from __future__ import annotations

from datetime import datetime, timedelta

from app.formatting import API_ERROR_TEXT, format_eta_message
from app.keyboards import (
    BTN_PUSH_NOW, BTN_SETTINGS, DAY_LABELS, SLOT_LABELS,
    day_picker_keyboard, days_to_mask, interval_picker_keyboard,
    mask_to_days, settings_menu_keyboard, settings_reply_keyboard, slot_choice_keyboard,
)
from app.models import UserSettings
from app.tdx import TDXError, select_stop

MANUAL_PUSH_COOLDOWN = timedelta(minutes=5)


async def handle_update(update: dict, store, telegram, now: datetime, tdx=None, city: str = "Tainan") -> None:
    if "callback_query" in update:
        await _handle_callback(update["callback_query"], store, telegram, now)
    elif "message" in update:
        await _handle_message(update["message"], store, telegram, now, tdx, city)


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


def _fmt_remaining(delta: timedelta) -> str:
    total = max(0, int(delta.total_seconds()))
    m, s = divmod(total, 60)
    return f"{m} 分 {s} 秒"


async def _manual_push(chat_id: int, store, telegram, now: datetime, tdx, city: str) -> None:
    """「立即推播」：查目前兩時段到站並主動推一次；帶冷卻，避免連點燒 TDX 額度。"""
    if tdx is None:
        return
    user = await _ensure_user(store, chat_id)
    date_str = now.strftime("%Y-%m-%d")
    runtime = await store.get_runtime(chat_id, date_str)

    last = runtime.last_manual_push_at
    if last is not None and now - last < MANUAL_PUSH_COOLDOWN:
        remaining = MANUAL_PUSH_COOLDOWN - (now - last)
        await telegram.send_message(
            chat_id, f"剛叫過車，還需等 {_fmt_remaining(remaining)} 才能再次點「{BTN_PUSH_NOW}」。"
        )
        return

    # 一律先進入冷卻（成功或失敗都已佔用一次 TDX 額度）
    runtime.last_manual_push_at = now
    await store.save_runtime(chat_id, date_str, runtime)

    try:
        cache: dict[str, list] = {}
        lines = []
        for name in ("morning", "evening"):
            cfg = user.slots[name]
            if cfg.route not in cache:
                cache[cfg.route] = await tdx.get_eta(city, cfg.route, now)
            match = select_stop(cache[cfg.route], cfg.stop_name, cfg.sub_route)
            if match is None:
                lines.append(f"{cfg.bus}｜{cfg.stop_name}：查無資料")
            else:
                lines.append(format_eta_message(cfg, int(match.get("StopStatus", 0)), match.get("EstimateTime")))
    except TDXError:
        await telegram.send_message(chat_id, API_ERROR_TEXT)
        return

    mins = int(MANUAL_PUSH_COOLDOWN.total_seconds() // 60)
    await telegram.send_message(chat_id, "\n".join(lines) + f"\n（{mins} 分鐘後可再次叫車）")


async def _handle_message(message: dict, store, telegram, now: datetime, tdx, city: str) -> None:
    chat_id = message["chat"]["id"]
    text = message.get("text", "")
    if text.startswith("/start"):
        await _ensure_user(store, chat_id)
        await telegram.send_message(
            chat_id,
            "歡迎！已開啟 70左/70右 到站通知。\n"
            "點「立即推播」即時查到站，點「設定」調整推播間隔／時間／公車站。",
            settings_reply_keyboard(),
        )
    elif text == BTN_PUSH_NOW:
        await _manual_push(chat_id, store, telegram, now, tdx, city)
    elif text == BTN_SETTINGS:
        await telegram.send_message(chat_id, "請選擇要設定的項目：", settings_menu_keyboard())


async def _handle_callback(cb: dict, store, telegram, now: datetime) -> None:
    data = cb["data"]
    cb_id = cb["id"]
    chat_id = cb["message"]["chat"]["id"]
    message_id = cb["message"]["message_id"]
    parts = data.split(":")
    kind = parts[0]
    date_str = now.strftime("%Y-%m-%d")

    try:
        if kind == "menu":
            what = parts[1]
            await telegram.answer_callback_query(cb_id)
            if what == "interval":
                await telegram.send_message(chat_id, "要設定哪個時段的每日預設間隔？", slot_choice_keyboard("defint"))
            elif what == "days":
                user = await _ensure_user(store, chat_id)
                await telegram.send_message(
                    chat_id,
                    "選擇要推播的星期（點一下選取、再點一下取消），完成後按「送出設定」：",
                    day_picker_keyboard(days_to_mask(user.enabled_days)),
                )
            elif what == "stops":
                user = await _ensure_user(store, chat_id)
                await telegram.send_message(chat_id, _bus_stop_text(user))

        elif kind == "stop":
            slot = parts[1]
            runtime = await store.get_runtime(chat_id, date_str)
            runtime.slot(slot).stopped = True
            await store.save_runtime(chat_id, date_str, runtime)
            await telegram.answer_callback_query(cb_id, f"已停止今日{SLOT_LABELS[slot]}推播")
            await telegram.send_message(chat_id, f"已停止今日{SLOT_LABELS[slot]}推播，明天會自動恢復。")

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
                await telegram.answer_callback_query(cb_id)
                await telegram.send_message(chat_id, f"已設定今日{SLOT_LABELS[slot]}剩餘推播間隔為 {val} 分鐘。")
            else:
                user = await _ensure_user(store, chat_id)
                user.slots[slot].default_interval = val
                await store.save_user(user)
                await telegram.answer_callback_query(cb_id)
                await telegram.send_message(chat_id, f"已設定{SLOT_LABELS[slot]}每日推播間隔為 {val} 分鐘。")

        elif kind == "slotpick":
            action, slot = parts[1], parts[2]
            await telegram.answer_callback_query(cb_id)
            if action == "defint":
                await telegram.send_message(
                    chat_id, f"設定{SLOT_LABELS[slot]}每日預設間隔：",
                    interval_picker_keyboard("default", slot),
                )

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
            if user.enabled_days:
                names = "、".join(DAY_LABELS[d] for d in user.enabled_days)
                await telegram.send_message(chat_id, f"已更新推播日為：{names}。")
            else:
                await telegram.send_message(chat_id, "已清空推播日，目前不會推播。")

        else:
            # 未知類型（多半是改版後殘留的舊按鈕）→ 仍回應以停止載入圈
            await telegram.answer_callback_query(cb_id)

    except (ValueError, IndexError, KeyError):
        # callback_data 格式損壞/過期 → 回應以停止載入圈，不讓 /webhook 回 500 造成重試風暴
        await telegram.answer_callback_query(cb_id)
