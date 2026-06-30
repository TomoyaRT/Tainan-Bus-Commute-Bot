import httpx
import respx

from app.telegram import TelegramClient

BASE = "https://api.telegram.org/bot123:ABC"


@respx.mock
async def test_send_message_includes_reply_markup():
    route = respx.post(f"{BASE}/sendMessage").mock(return_value=httpx.Response(200, json={"ok": True}))
    async with httpx.AsyncClient() as http:
        tg = TelegramClient("123:ABC", http)
        await tg.send_message(555, "嗨", reply_markup={"inline_keyboard": []})
    body = route.calls.last.request.read().decode()
    assert '"chat_id": 555' in body
    assert "reply_markup" in body


@respx.mock
async def test_send_message_without_markup_omits_key():
    route = respx.post(f"{BASE}/sendMessage").mock(return_value=httpx.Response(200, json={"ok": True}))
    async with httpx.AsyncClient() as http:
        tg = TelegramClient("123:ABC", http)
        await tg.send_message(555, "嗨")
    body = route.calls.last.request.read().decode()
    assert "reply_markup" not in body


@respx.mock
async def test_answer_callback_query():
    route = respx.post(f"{BASE}/answerCallbackQuery").mock(return_value=httpx.Response(200, json={"ok": True}))
    async with httpx.AsyncClient() as http:
        tg = TelegramClient("123:ABC", http)
        await tg.answer_callback_query("cb1", "已停止")
    body = route.calls.last.request.read().decode()
    assert '"callback_query_id": "cb1"' in body


@respx.mock
async def test_edit_message_reply_markup():
    route = respx.post(f"{BASE}/editMessageReplyMarkup").mock(return_value=httpx.Response(200, json={"ok": True}))
    async with httpx.AsyncClient() as http:
        tg = TelegramClient("123:ABC", http)
        await tg.edit_message_reply_markup(555, 99, {"inline_keyboard": []})
    body = route.calls.last.request.read().decode()
    assert '"message_id": 99' in body
