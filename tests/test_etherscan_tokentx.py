import httpx

from app.config.settings import Settings
from app.market_data.etherscan import ERC20_CONTRACT_ADDRESS_BY_SYMBOL, EtherscanClient


class FakeHttpResponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)


def _client(configured=True) -> EtherscanClient:
    settings = Settings(_env_file=None, etherscan_api_key="k" if configured else None)
    return EtherscanClient(settings)


def test_fetch_token_transfers_not_configured_returns_none():
    client = _client(configured=False)
    assert client.fetch_token_transfers("0xabc") is None


def test_fetch_token_transfers_parses_real_response_shape(monkeypatch):
    payload = {"status": "1", "message": "OK", "result": [
        {"timeStamp": "1788686487", "from": "0xaaa", "to": "0xbbb", "tokenSymbol": "LINK"},
    ]}

    def fake_get(self, url, params=None):
        assert params["action"] == "tokentx"
        return FakeHttpResponse(payload)

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    client = _client()
    rows = client.fetch_token_transfers("0x514910771AF9Ca656af840dff83E8264EcF986CA")
    assert rows[0]["tokenSymbol"] == "LINK"


def test_fetch_token_transfers_returns_none_on_api_error_status(monkeypatch):
    payload = {"status": "0", "message": "NOTOK", "result": "rate limit"}

    def fake_get(self, url, params=None):
        return FakeHttpResponse(payload)

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    client = _client()
    assert client.fetch_token_transfers("0xabc") is None


def test_erc20_contract_map_has_no_placeholder_addresses():
    for symbol, address in ERC20_CONTRACT_ADDRESS_BY_SYMBOL.items():
        assert address.startswith("0x")
        assert len(address) == 42
