from __future__ import annotations

from datetime import datetime, timedelta

import httpx

TOKEN_URL = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
ETA_URL = "https://tdx.transportdata.tw/api/basic/v2/Bus/EstimatedTimeOfArrival/City/{city}/{route}"
TOKEN_REFRESH_BUFFER = timedelta(minutes=1)


class TDXError(Exception):
    pass


def select_stop(
    entries: list[dict], stop_name: str, direction: int | None = None
) -> dict | None:
    """從到站清單挑出目標站。

    direction 指定時只取該方向；未指定時，若同站名跨多個 Direction（左右環狀
    可能同時回傳），無法判斷是哪一向的車，回傳 None（寧可不推，也不推錯方向）。
    """
    matches = []
    for entry in entries:
        raw = entry.get("StopName")
        zh = raw.get("Zh_tw") if isinstance(raw, dict) else raw
        if zh != stop_name:
            continue
        if direction is not None and entry.get("Direction") != direction:
            continue
        matches.append(entry)
    if not matches:
        return None
    if len({e.get("Direction") for e in matches}) > 1:
        return None
    return matches[0]


class TDXClient:
    def __init__(self, client_id: str, client_secret: str, store, http: httpx.AsyncClient):
        self.client_id = client_id
        self.client_secret = client_secret
        self.store = store
        self.http = http

    async def _get_token(self, now: datetime) -> str:
        cached = await self.store.get_tdx_token()
        if cached and cached[1] > now + TOKEN_REFRESH_BUFFER:
            return cached[0]
        try:
            resp = await self.http.post(
                TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as exc:
            raise TDXError(f"token request failed: {exc}") from exc
        if resp.status_code != 200:
            raise TDXError(f"token status {resp.status_code}")
        try:
            data = resp.json()
            token = data["access_token"]
            expires_at = now + timedelta(seconds=int(data["expires_in"]))
        except (ValueError, KeyError) as exc:
            raise TDXError(f"token parse failed: {exc}") from exc
        await self.store.save_tdx_token(token, expires_at)
        return token

    async def get_eta(self, city: str, route: str, now: datetime) -> list[dict]:
        token = await self._get_token(now)
        try:
            resp = await self.http.get(
                ETA_URL.format(city=city, route=route),
                headers={"authorization": f"Bearer {token}"},
                params={"$format": "JSON"},
            )
        except httpx.HTTPError as exc:
            raise TDXError(f"eta request failed: {exc}") from exc
        if resp.status_code != 200:
            raise TDXError(f"eta status {resp.status_code}")
        try:
            return resp.json()
        except ValueError as exc:
            raise TDXError(f"eta json parse failed: {exc}") from exc
