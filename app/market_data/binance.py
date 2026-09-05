import httpx

from app.config import Settings


class BinanceClient:
    """Wrapper around Binance's public REST API (no key required for market
    data). Exchange-native venue data, broader small-cap coverage than
    Coinbase for most alts — but not universal: HYPE and STORJ have no
    Binance USDT pair (verified live against exchangeInfo), so callers must
    fall back (Coinbase) rather than treat a missing symbol as a failure.

    Verified live: `/exchangeInfo` (3692 symbols), `/ticker/24hr`,
    `/klines` — 14 sequential klines calls completed in 3.7s with zero
    rate-limiting, making this the primary source for the volatility/
    drawdown factors across the full screening universe (CoinGecko's
    per-asset historical endpoint rate-limits after ~5 rapid calls on the
    free tier and was rejected for this reason).
    """

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.binance_base_url

    def list_usdt_symbols(self) -> set[str]:
        """Returns the set of base-asset symbols with a TRADING USDT pair."""
        with httpx.Client(timeout=15.0) as client:
            response = client.get(f"{self._base_url}/api/v3/exchangeInfo")
            response.raise_for_status()
            data = response.json()
        return {
            s["baseAsset"]
            for s in data["symbols"]
            if s["status"] == "TRADING" and s["quoteAsset"] == "USDT"
        }

    def fetch_ticker_24hr(self, symbol: str) -> dict | None:
        """Returns the raw 24hr ticker for `<symbol>USDT`, or None if no such pair."""
        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                f"{self._base_url}/api/v3/ticker/24hr", params={"symbol": f"{symbol}USDT"}
            )
            if response.status_code == 400:
                return None
            response.raise_for_status()
            return response.json()

    def fetch_daily_ohlcv(self, symbol: str, days: int) -> list[tuple[float, float]] | None:
        """Returns up to `days` daily (close, volume) pairs for `<symbol>USDT`,
        oldest first, or None if no such pair exists. Each raw kline row is
        [open_time, open, high, low, close, volume, ...]."""
        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                f"{self._base_url}/api/v3/klines",
                params={"symbol": f"{symbol}USDT", "interval": "1d", "limit": days},
            )
            if response.status_code == 400:
                return None
            response.raise_for_status()
            rows = response.json()

        if not rows:
            return None
        return [(float(row[4]), float(row[5])) for row in rows]
