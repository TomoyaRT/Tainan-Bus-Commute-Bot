from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from app.tdx import TDXClient, TDXError, select_stop

TPE = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 6, 30, 8, 0, tzinfo=TPE)
TOKEN_URL = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
ETA_URL = "https://tdx.transportdata.tw/api/basic/v2/Bus/EstimatedTimeOfArrival/City/Tainan/70"


class FakeTokenStore:
    def __init__(self):
        self.value = None

    async def get_tdx_token(self):
        return self.value

    async def save_tdx_token(self, token, expires_at):
        self.value = (token, expires_at)


def test_select_stop_handles_dict_stopname():
    entries = [{"StopName": {"Zh_tw": "台南高工"}, "StopStatus": 0, "EstimateTime": 300}]
    assert select_stop(entries, "台南高工")["EstimateTime"] == 300

def test_select_stop_handles_plain_string_and_missing():
    entries = [{"StopName": "中華西路二段", "StopStatus": 3}]
    assert select_stop(entries, "中華西路二段")["StopStatus"] == 3
    assert select_stop(entries, "不存在") is None


def test_select_stop_disambiguates_by_sub_route():
    # 環狀 70：同站名在 70左/70右 都出現，靠 SubRouteName 前綴消歧
    entries = [
        {"StopName": {"Zh_tw": "臺南高工"}, "SubRouteName": {"Zh_tw": "70左 …"}, "EstimateTime": 1700},
        {"StopName": {"Zh_tw": "臺南高工"}, "SubRouteName": {"Zh_tw": "70右 …"}, "EstimateTime": 900},
    ]
    assert select_stop(entries, "臺南高工", "70左")["EstimateTime"] == 1700
    assert select_stop(entries, "臺南高工", "70右")["EstimateTime"] == 900
    # 不指定 sub_route、同站名多筆 → 不猜，回 None
    assert select_stop(entries, "臺南高工") is None


def test_select_stop_against_real_fixture():
    import json
    import pathlib

    raw = json.loads((pathlib.Path(__file__).parent / "fixtures" / "route70_sample.json").read_text("utf-8"))
    # 上班：70左 的臺南高工（真實資料 Direction=1、StopStatus=0）
    m = select_stop(raw, "臺南高工", "70左")
    assert m is not None and m["SubRouteName"]["Zh_tw"].startswith("70左") and m["StopStatus"] == 0
    # 下班：70右 的中華西路二段（真實資料 Direction=255、StopStatus=1）
    e = select_stop(raw, "中華西路二段", "70右")
    assert e is not None and e["SubRouteName"]["Zh_tw"].startswith("70右")


@respx.mock
async def test_get_eta_fetches_token_then_data():
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 86400}))
    route = respx.get(ETA_URL).mock(return_value=httpx.Response(200, json=[{"StopName": {"Zh_tw": "台南高工"}, "StopStatus": 0, "EstimateTime": 120}]))
    store = FakeTokenStore()
    async with httpx.AsyncClient() as http:
        client = TDXClient("id", "secret", store, http)
        entries = await client.get_eta("Tainan", "70", NOW)
    assert entries[0]["EstimateTime"] == 120
    assert route.calls.last.request.headers["authorization"] == "Bearer tok"
    assert store.value[0] == "tok"
    assert route.calls.last.request.url.params["$format"] == "JSON"


@respx.mock
async def test_get_eta_reuses_cached_token():
    token_route = respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "fresh", "expires_in": 86400}))
    respx.get(ETA_URL).mock(return_value=httpx.Response(200, json=[]))
    store = FakeTokenStore()
    store.value = ("cached", NOW + timedelta(hours=5))
    async with httpx.AsyncClient() as http:
        client = TDXClient("id", "secret", store, http)
        await client.get_eta("Tainan", "70", NOW)
    assert token_route.called is False


@respx.mock
async def test_get_eta_raises_tdxerror_on_non_200():
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 86400}))
    respx.get(ETA_URL).mock(return_value=httpx.Response(500, text="boom"))
    store = FakeTokenStore()
    async with httpx.AsyncClient() as http:
        client = TDXClient("id", "secret", store, http)
        with pytest.raises(TDXError):
            await client.get_eta("Tainan", "70", NOW)


@respx.mock
async def test_get_token_raises_on_non_json_body():
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, text="not json"))
    store = FakeTokenStore()
    async with httpx.AsyncClient() as http:
        client = TDXClient("id", "secret", store, http)
        with pytest.raises(TDXError):
            await client.get_eta("Tainan", "70", NOW)


@respx.mock
async def test_get_token_raises_on_missing_access_token():
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={"expires_in": 86400}))
    store = FakeTokenStore()
    async with httpx.AsyncClient() as http:
        client = TDXClient("id", "secret", store, http)
        with pytest.raises(TDXError):
            await client.get_eta("Tainan", "70", NOW)
