from __future__ import annotations

from datetime import datetime, timedelta

import httpx

TOKEN_URL = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
ETA_URL = "https://tdx.transportdata.tw/api/basic/v2/Bus/EstimatedTimeOfArrival/City/{city}/{route}"
TOKEN_REFRESH_BUFFER = timedelta(minutes=1)


class TDXError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _zh(value):
    return value.get("Zh_tw") if isinstance(value, dict) else value


def select_matches(
    entries: list[dict], stop_name: str, sub_route: str | None = None
) -> list[dict]:
    """回傳同一 (站名，子路線前綴) 的所有到站筆數。

    台南 70 是環狀路線，RouteName 皆為 "70"，靠 SubRouteName("70左…"/"70右…")區分左右；
    同站名在兩子路線都會出現，故 sub_route 指定時以 SubRouteName 前綴過濾。
    尖峰多車或環狀頭尾同站會有多筆，一律全部回傳交由上層呈現；不存在則回 []。
    """
    matches = []
    for entry in entries:
        if _zh(entry.get("StopName")) != stop_name:
            continue
        if sub_route is not None and not (_zh(entry.get("SubRouteName")) or "").startswith(sub_route):
            continue
        matches.append(entry)
    return matches


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
            raise TDXError(f"token status {resp.status_code}", status_code=resp.status_code)
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
            raise TDXError(f"eta status {resp.status_code}", status_code=resp.status_code)
        try:
            return resp.json()
        except ValueError as exc:
            raise TDXError(f"eta json parse failed: {exc}") from exc
