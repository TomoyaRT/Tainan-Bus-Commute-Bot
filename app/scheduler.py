from __future__ import annotations

from datetime import datetime

from app.formatting import API_ERROR_TEXT, format_eta_message
from app.keyboards import push_inline_keyboard
from app.models import UserSettings
from app.tdx import TDXError, select_matches
from app.timeutil import in_window, is_due

FAIL_THRESHOLD = 2


def active_slot(now: datetime, settings: UserSettings) -> str | None:
    for name in ("morning", "evening"):
        cfg = settings.slots[name]
        if in_window(now, cfg.window_start, cfg.window_end):
            return name
    return None


async def process_user(now, settings, store, tdx, telegram, city, cache: dict | None = None) -> None:
    if now.isoweekday() not in settings.enabled_days:
        return
    slot = active_slot(now, settings)
    if slot is None:
        return

    date_str = now.strftime("%Y-%m-%d")
    runtime = await store.get_runtime(settings.chat_id, date_str)
    sr = runtime.slot(slot)
    cfg = settings.slots[slot]

    if sr.stopped:
        return

    interval = sr.interval_override or cfg.default_interval
    if not is_due(now, sr.last_push_at, interval, cfg.window_start):
        return

    try:
        if cache is not None and cfg.route in cache:
            entries = cache[cfg.route]
        else:
            entries = await tdx.get_eta(city, cfg.route, now)
            if cache is not None:
                cache[cfg.route] = entries

        matches = select_matches(entries, cfg.stop_name, cfg.sub_route)
        sr.fail_count = 0
        text = format_eta_message(cfg, entries, matches, now)
        await telegram.send_message(settings.chat_id, text, push_inline_keyboard(slot))
        sr.last_push_at = now
    except TDXError as exc:
        sr.fail_count += 1
        if sr.fail_count >= FAIL_THRESHOLD:
            if exc.status_code in (403, 429):
                await telegram.send_message(settings.chat_id, "⚠️ TDX 公車 API 額度已用完，無法取得正確資訊。")
            else:
                await telegram.send_message(settings.chat_id, API_ERROR_TEXT)
            sr.stopped = True

    await store.save_runtime(settings.chat_id, date_str, runtime)


async def run_tick(now, store, tdx, telegram, city) -> None:
    cache = {}
    for settings in await store.list_users():
        await process_user(now, settings, store, tdx, telegram, city, cache)
