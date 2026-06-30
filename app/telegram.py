from __future__ import annotations

import httpx

API_URL = "https://api.telegram.org/bot{token}/{method}"


class TelegramClient:
    def __init__(self, token: str, http: httpx.AsyncClient):
        self.token = token
        self.http = http

    async def _call(self, method: str, payload: dict) -> dict:
        resp = await self.http.post(API_URL.format(token=self.token, method=method), json=payload)
        resp.raise_for_status()
        return resp.json()

    async def send_message(self, chat_id: int, text: str, reply_markup: dict | None = None) -> dict:
        payload: dict = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return await self._call("sendMessage", payload)

    async def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> dict:
        payload: dict = {"callback_query_id": callback_query_id}
        if text is not None:
            payload["text"] = text
        return await self._call("answerCallbackQuery", payload)

    async def edit_message_reply_markup(self, chat_id: int, message_id: int, reply_markup: dict) -> dict:
        return await self._call(
            "editMessageReplyMarkup",
            {"chat_id": chat_id, "message_id": message_id, "reply_markup": reply_markup},
        )
