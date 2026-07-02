from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from app.tdx import TDXClient, TDXError, select_matches

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


def test_select_matches_handles_dict_stopname():
    entries = [{"StopName": {"Zh_tw": "台南高工"}, "StopStatus": 0, "EstimateTime": 300}]
    got = select_matches(entries, "台南高工")
    assert len(got) == 1 and got[0]["EstimateTime"] == 300


def test_select_matches_missing_returns_empty():
    entries = [{"StopName": "中華西路二段", "StopStatus": 3}]
    assert select_matches(entries, "不存在") == []


def test_select_matches_disambiguates_by_sub_route():
    entries = [
        {"StopName": {"Zh_tw": "臺南高工"}, "SubRouteName": {"Zh_tw": "70左 …"}, "EstimateTime": 1700},
        {"StopName": {"Zh_tw": "臺南高工"}, "SubRouteName": {"Zh_tw": "70右 …"}, "EstimateTime": 900},
    ]
    assert [e["EstimateTime"] for e in select_matches(entries, "臺南高工", "70左")] == [1700]
    assert [e["EstimateTime"] for e in select_matches(entries, "臺南高工", "70右")] == [900]


def test_select_matches_returns_all_when_ambiguous():
    # 環狀頭尾同站或尖峰多車：同站同子路線多筆，全部回傳
    entries = [
        {"StopName": {"Zh_tw": "永華市政中心(府前路)"}, "SubRouteName": {"Zh_tw": "70左 …"}, "EstimateTime": 200},
        {"StopName": {"Zh_tw": "永華市政中心(府前路)"}, "SubRouteName": {"Zh_tw": "70左 …"}, "EstimateTime": 2400},
    ]
    assert len(select_matches(entries, "永華市政中心(府前路)", "70左")) == 2


def test_select_matches_against_real_fixture():
    import json
    import pathlib
    raw = json.loads((pathlib.Path(__file__).parent / "fixtures" / "route70_sample.json").read_text("utf-8"))
    m = select_matches(raw, "臺南高工", "70左")
    assert len(m) == 1 and m[0]["SubRouteName"]["Zh_tw"].startswith("70左")
    e = select_matches(raw, "中華西路二段", "70右")
    assert len(e) == 1 and e[0]["SubRouteName"]["Zh_tw"].startswith("70右")


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
