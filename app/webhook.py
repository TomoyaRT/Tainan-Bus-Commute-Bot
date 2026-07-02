from __future__ import annotations

from datetime import datetime, timedelta

from app.formatting import API_ERROR_TEXT, format_eta_message
from app.keyboards import (
    BTN_PUSH_NOW, BTN_SETTINGS, BTN_BOARDING, DAY_LABELS, SLOT_LABELS,
    day_picker_keyboard, days_to_mask, interval_picker_keyboard,
    mask_to_days, settings_main_keyboard, modify_settings_keyboard,
    info_settings_keyboard, settings_reply_keyboard, slot_choice_keyboard,
    slot_window_choice_keyboard, window_picker_keyboard, boarding_stop_keyboard,
)
from app.models import UserSettings
from app.tdx import TDXError, select_matches

MANUAL_PUSH_COOLDOWN = timedelta(minutes=1)
MANUAL_SLOT_HEADERS = {"morning": "🌅 上班", "evening": "🌃 下班"}


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
        "📌 目前推播公車站與時段：\n\n"
        f"🌅 上班通勤\n"
        f"• 公車站：{m.bus}（{m.stop_name}）\n"
        f"• 🕒 推播時段：{m.window_start} - {m.window_end}\n\n"
        f"🌃 下班通勤\n"
        f"• 公車站：{e.bus}（{e.stop_name}）\n"
        f"• 🕒 推播時段：{e.window_start} - {e.window_end}"
    )


def _manual_text(user: UserSettings) -> str:
    m = user.slots["morning"]
    e = user.slots["evening"]
    return (
        "📖 台南公車通勤機器人 - 使用說明書\n\n"
        "這是專為台南通勤族設計的公車到站自動通知機器人。\n\n"
        "💡 核心功能介紹：\n"
        "1. ⏰ 每日定時推播 (自動)\n"
        "   • 機器人會在您設定的推播日與通勤時段內，每隔固定時間主動發送公車到站資訊。\n"
        f"   • 上班時段：{m.window_start} - {m.window_end} (預設 {m.default_interval} 分鐘推播一次)\n"
        f"   • 下班時段：{e.window_start} - {e.window_end} (預設 {e.default_interval} 分鐘推播一次)\n"
        "   • 點擊推播訊息下方的「停止推播」，可暫停今日剩餘的自動通知，隔日會自動恢復。\n\n"
        "2. 🚀 立即推播 (手動)\n"
        "   • 點擊底部「立即推播」按鈕，即可查詢目前上班與下班時段的最新公車到站時間。\n"
        "   • 設有 1 分鐘冷卻時間防止重複查詢。\n\n"
        "3. ⚙️ 設定選單\n"
        "   • 點擊底部「控制台」按鈕：\n"
        "     - 推播間隔：修改上班/下班時段的每日預設通知頻率。\n"
        "     - 推播日：勾選啟用推播的星期（週一至週五）。\n"
        "     - 推播時段：自訂上班與下班開始與結束的通知區間。\n"
        f"     - 公車站與時段：查看目前追蹤的路線與站牌（目前為 {m.bus}「{m.stop_name}」與 {e.bus}「{e.stop_name}」）。\n\n"
        "💡 提示：\n"
        "第一次使用？您不需要進行任何設定，機器人已為您配置好預設路線，只需保持關注即可！"
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
            chat_id, f"剛推播過，需等待 {_fmt_remaining(remaining)} 才能再次使用。"
        )
        return

    # 一律先進入冷卻（成功或失敗都已佔用一次 TDX 額度）
    runtime.last_manual_push_at = now
    await store.save_runtime(chat_id, date_str, runtime)

    try:
        cache: dict[str, list] = {}
        blocks = []
        for name in ("morning", "evening"):
            cfg = user.slots[name]
            if cfg.route not in cache:
                cache[cfg.route] = await tdx.get_eta(city, cfg.route, now)
            matches = select_matches(cache[cfg.route], cfg.stop_name, cfg.sub_route)
            body = format_eta_message(cfg, matches, now)
            blocks.append(f"{MANUAL_SLOT_HEADERS[name]}\n{body}")
    except TDXError as exc:
        if exc.status_code in (403, 429):
            await telegram.send_message(chat_id, "⚠️ TDX 公車 API 額度已用完，無法取得正確資訊。")
        else:
            await telegram.send_message(chat_id, API_ERROR_TEXT)
        return

    await telegram.send_message(chat_id, "\n\n".join(blocks))


async def _handle_message(message: dict, store, telegram, now: datetime, tdx, city: str) -> None:
    chat_id = message["chat"]["id"]
    text = message.get("text", "")
    if text.startswith("/start"):
        await _ensure_user(store, chat_id)
        await telegram.send_message(
            chat_id,
            "歡迎使用台南公車通勤機器人～\n我會在工作日期間通知您公車的時間！",
            settings_reply_keyboard(),
        )
    elif text == BTN_PUSH_NOW:
        await _manual_push(chat_id, store, telegram, now, tdx, city)
    elif text == BTN_BOARDING:
        await telegram.send_message(chat_id, "請問您要上車的公車站是？", boarding_stop_keyboard())
    elif text == BTN_SETTINGS:
        await telegram.send_message(chat_id, "請選擇操作項目：", settings_main_keyboard())


async def _handle_callback(cb: dict, store, telegram, now: datetime) -> None:
    data = cb["data"]
    cb_id = cb["id"]
    chat_id = cb["message"]["chat"]["id"]
    message_id = cb["message"]["message_id"]
    parts = data.split(":")
    kind = parts[0]
    date_str = now.strftime("%Y-%m-%d")

    try:
        if kind == "noop":
            await telegram.answer_callback_query(cb_id)
            return

        if kind == "menu":
            what = parts[1]
            await telegram.answer_callback_query(cb_id)
            if what == "modify_menu":
                await telegram.edit_message_reply_markup(chat_id, message_id, modify_settings_keyboard())
            elif what == "info_menu":
                await telegram.edit_message_reply_markup(chat_id, message_id, info_settings_keyboard())
            elif what == "interval":
                await telegram.send_message(chat_id, "要設定哪個時段的每日預設間隔？", slot_choice_keyboard("defint"))
            elif what == "days":
                user = await _ensure_user(store, chat_id)
                await telegram.send_message(
                    chat_id,
                    "選擇要推播的星期（點一下選取、再點一下取消），完成後按「保存設定」：",
                    day_picker_keyboard(days_to_mask(user.enabled_days)),
                )
            elif what == "window":
                await telegram.edit_message_reply_markup(chat_id, message_id, slot_window_choice_keyboard())
            elif what == "stops":
                user = await _ensure_user(store, chat_id)
                await telegram.send_message(chat_id, _bus_stop_text(user))
            elif what == "manual":
                user = await _ensure_user(store, chat_id)
                await telegram.send_message(chat_id, _manual_text(user))

        elif kind == "stop":
            slot = parts[1]
            runtime = await store.get_runtime(chat_id, date_str)
            runtime.slot(slot).stopped = True
            await store.save_runtime(chat_id, date_str, runtime)
            await telegram.answer_callback_query(cb_id, f"已停止今日{SLOT_LABELS[slot]}推播")
            await telegram.send_message(chat_id, f"已停止今日{SLOT_LABELS[slot]}推播，明天會自動恢復。")

        elif kind == "slotwin":
            slot = parts[1]
            user = await _ensure_user(store, chat_id)
            cfg = user.slots[slot]
            await telegram.answer_callback_query(cb_id)
            await telegram.edit_message_reply_markup(
                chat_id, message_id,
                window_picker_keyboard(slot, cfg.window_start, cfg.window_end)
            )

        elif kind == "winopt":
            slot = parts[1]
            s = f"{parts[2]}:{parts[3]}"
            e = f"{parts[4]}:{parts[5]}"
            await telegram.answer_callback_query(cb_id)
            await telegram.edit_message_reply_markup(
                chat_id, message_id,
                window_picker_keyboard(slot, s, e)
            )

        elif kind == "winsub":
            slot = parts[1]
            s = f"{parts[2]}:{parts[3]}"
            e = f"{parts[4]}:{parts[5]}"
            user = await _ensure_user(store, chat_id)
            user.slots[slot].window_start = s
            user.slots[slot].window_end = e
            await store.save_user(user)
            await telegram.answer_callback_query(cb_id, "設定已保存")
            await telegram.send_message(chat_id, f"已更新{SLOT_LABELS[slot]}推播時段為：{s} - {e}")

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
                await telegram.send_message(chat_id, "無選擇任何推播日，便不再進行推播。")

        else:
            # 未知類型（多半是改版後殘留的舊按鈕）→ 仍回應以停止載入圈
            await telegram.answer_callback_query(cb_id)

    except (ValueError, IndexError, KeyError):
        # callback_data 格式損壞/過期 → 回應以停止載入圈，不讓 /webhook 回 500 造成重試風暴
        await telegram.answer_callback_query(cb_id)
