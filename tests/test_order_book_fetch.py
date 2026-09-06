import httpx

from app.config.settings import Settings
from app.market_data.binance import BinanceClient
from app.market_data.coinbase import CoinbaseClient


class FakeHttpResponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)


def test_binance_fetch_order_book_depth_parses_real_response_shape(monkeypatch):
    payload = {"bids": [["100.0", "1.5"], ["99.9", "2.0"]], "asks": [["100.1", "1.0"], ["100.2", "3.0"]]}

    def fake_get(self, url, params=None):
        assert params["symbol"] == "BTCUSDT"
        return FakeHttpResponse(payload)

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    client = BinanceClient(Settings(_env_file=None))
    book = client.fetch_order_book_depth("BTC")
    assert book.source == "BINANCE"
    assert book.bids[0].price == 100.0
    assert book.asks[0].quantity == 1.0


def test_binance_fetch_order_book_depth_returns_none_for_unlisted_pair(monkeypatch):
    def fake_get(self, url, params=None):
        return FakeHttpResponse({}, status_code=400)

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    client = BinanceClient(Settings(_env_file=None))
    assert client.fetch_order_book_depth("NOTREAL") is None


def test_coinbase_fetch_order_book_depth_parses_real_response_shape(monkeypatch):
    payload = {"bids": [["100.0", "1.5", 2]], "asks": [["100.1", "1.0", 1]]}

    def fake_get(self, url, params=None, headers=None):
        return FakeHttpResponse(payload)

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    client = CoinbaseClient(Settings(_env_file=None))
    book = client.fetch_order_book_depth("BTC")
    assert book.source == "COINBASE"
    assert book.bids[0].price == 100.0
    assert book.asks[0].quantity == 1.0


def test_coinbase_fetch_order_book_depth_returns_none_for_unlisted_pair(monkeypatch):
    def fake_get(self, url, params=None, headers=None):
        return FakeHttpResponse({}, status_code=404)

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    client = CoinbaseClient(Settings(_env_file=None))
    assert client.fetch_order_book_depth("NOTREAL") is None
