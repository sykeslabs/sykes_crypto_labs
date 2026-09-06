import httpx

from app.config import Settings


class UpbitClient:
    """Wrapper around Upbit's public quotation API (no key required) —
    verified live: `/v1/ticker` returns real KRW-BTC trade data. Used for the
    regional exchange premium (3f) — a structural regional-flow signal
    distinct from 3b's ordinary cross-source (CoinGecko/CMC/Coinbase/Binance)
    disagreement, which is aggregation/venue noise across globally arbitraged
    venues.
    """

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.upbit_base_url

    def fetch_ticker(self, market: str) -> dict | None:
        """`market` is Upbit's own format, e.g. "KRW-BTC"."""
        with httpx.Client(timeout=15.0) as client:
            response = client.get(f"{self._base_url}/ticker", params={"markets": market})
            if response.status_code == 400:
                return None
            response.raise_for_status()
            data = response.json()
        return data[0] if data else None
