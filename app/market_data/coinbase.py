from datetime import UTC, datetime

import httpx

from app.config import Settings

_HEADERS = {"User-Agent": "crypto-ai-portfolio"}


class CoinbaseClient:
    """Wrapper around Coinbase's public Exchange API (no key required for
    market data). Exchange-native venue data — real trades/order book on
    this specific venue, independent of CoinGecko/CMC's aggregated view.

    Verified live: `/products` (837 products), `/products/{id}/ticker`
    (price/bid/ask/volume), `/products/{id}/candles` (200+ days of daily
    history for every asset in the current 16-asset universe, including
    HYPE and STORJ — this venue is the fallback source for volatility/
    drawdown when an asset isn't listed on Binance).
    """

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.coinbase_base_url

    def list_usd_products(self) -> set[str]:
        """Returns the set of base-currency symbols with an online USD product."""
        with httpx.Client(timeout=15.0, headers=_HEADERS) as client:
            response = client.get(f"{self._base_url}/products")
            response.raise_for_status()
            products = response.json()
        return {
            p["base_currency"]
            for p in products
            if p.get("quote_currency") == "USD" and p.get("status") == "online"
        }

    def fetch_ticker(self, symbol: str) -> dict | None:
        """Returns the raw ticker for `<symbol>-USD`, or None if not listed."""
        with httpx.Client(timeout=15.0, headers=_HEADERS) as client:
            response = client.get(f"{self._base_url}/products/{symbol}-USD/ticker")
            if response.status_code in (400, 404):
                return None
            response.raise_for_status()
            return response.json()

    def fetch_daily_ohlcv(self, symbol: str, days: int) -> list[tuple[float, float]] | None:
        """Returns up to `days` daily (close, volume) pairs for `<symbol>-USD`,
        oldest first, or None if the product doesn't exist/has no candle
        data. Each raw candle row is [time, low, high, open, close, volume]."""
        with httpx.Client(timeout=15.0, headers=_HEADERS) as client:
            response = client.get(
                f"{self._base_url}/products/{symbol}-USD/candles",
                params={"granularity": 86400},
            )
            if response.status_code in (400, 404):
                return None
            response.raise_for_status()
            rows = response.json()

        if not rows:
            return None
        # Coinbase returns newest-first; take the most recent `days` rows and
        # reverse to oldest-first for return-series computation.
        recent = rows[:days]
        recent.reverse()
        return [(float(row[4]), float(row[5])) for row in recent]

    def fetch_daily_ohlcv_with_timestamps(self, symbol: str, days: int) -> list[tuple[datetime, float, float]] | None:
        """Same as `fetch_daily_ohlcv` but keeps each candle's date — added
        for 3e.1's replay. A new, additive method; the existing
        live-used `fetch_daily_ohlcv` is untouched."""
        with httpx.Client(timeout=15.0, headers=_HEADERS) as client:
            response = client.get(
                f"{self._base_url}/products/{symbol}-USD/candles",
                params={"granularity": 86400},
            )
            if response.status_code in (400, 404):
                return None
            response.raise_for_status()
            rows = response.json()

        if not rows:
            return None
        recent = rows[:days]
        recent.reverse()
        return [
            (datetime.fromtimestamp(row[0], tz=UTC), float(row[4]), float(row[5]))
            for row in recent
        ]
