import httpx
import pytest

from app.config.settings import Settings
from app.market_data.nansen import SMART_MONEY_CHAINS, NansenClient


class FakeHttpResponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)


def _client(api_key="k") -> NansenClient:
    settings = Settings(_env_file=None, nansen_api_key=api_key)
    return NansenClient(settings)


def test_not_configured_without_key():
    settings = Settings(_env_file=None, nansen_api_key=None)
    client = NansenClient(settings)
    assert client.is_configured is False
    assert client.fetch_smart_money_netflow("ethereum") is None


def test_fetch_smart_money_netflow_parses_real_response_shape(monkeypatch):
    payload = {"data": [
        {"token_address": "0xabc", "token_symbol": "ENA", "net_flow_7d_usd": 482390.8, "trader_count": 8},
    ], "pagination": {"page": 1, "per_page": 100, "is_last_page": True}}

    def fake_post(self, url, headers=None, json=None):
        assert headers["apikey"] == "k"
        assert json["chains"] == ["ethereum"]
        return FakeHttpResponse(payload)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    client = _client()
    rows = client.fetch_smart_money_netflow("ethereum")
    assert rows[0]["token_symbol"] == "ENA"


def test_fetch_smart_money_netflow_returns_none_on_http_error(monkeypatch):
    def fake_post(self, url, headers=None, json=None):
        return FakeHttpResponse({"error": "bad"}, status_code=500)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    client = _client()
    assert client.fetch_smart_money_netflow("ethereum") is None


def test_smart_money_chains_excludes_bitcoin():
    # Real, disclosed coverage gap -- verified live against Nansen's docs.
    assert "bitcoin" not in SMART_MONEY_CHAINS
    assert "ethereum" in SMART_MONEY_CHAINS
    assert "solana" in SMART_MONEY_CHAINS
