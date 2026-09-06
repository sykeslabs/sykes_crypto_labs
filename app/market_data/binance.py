from datetime import UTC, datetime

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
        self._futures_base_url = settings.binance_futures_base_url

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

    def fetch_daily_ohlcv_with_timestamps(self, symbol: str, days: int) -> list[tuple[datetime, float, float]] | None:
        """Same as `fetch_daily_ohlcv` but keeps each candle's date — added
        for 3e.1's replay (needs to know which close/volume value was known
        as of a specific past date, not just the values themselves). A new,
        additive method so the existing live-used `fetch_daily_ohlcv` is
        untouched."""
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
        return [
            (datetime.fromtimestamp(row[0] / 1000, tz=UTC), float(row[4]), float(row[5]))
            for row in rows
        ]

    def fetch_historical_funding_rates(self, symbol: str, limit: int = 1000) -> list[dict]:
        """Real historical funding-rate observations (not today's rate
        backdated) for 3e.1's replay — genuinely point-in-time reconstructable,
        unlike most of 3c's other evidence. Returns
        [{funding_time, funding_rate}], oldest first, empty if no perpetual."""
        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                f"{self._futures_base_url}/fapi/v1/fundingRate",
                params={"symbol": f"{symbol}USDT", "limit": limit},
            )
            if response.status_code == 400:
                return []
            response.raise_for_status()
            rows = response.json()
        return [
            {
                "funding_time": datetime.fromtimestamp(row["fundingTime"] / 1000, tz=UTC),
                "funding_rate": float(row["fundingRate"]),
            }
            for row in rows
        ]

    # --- Futures (3c): funding rate, open interest, dated-futures term structure ---
    # Verified live: premiumIndex/openInterest/fundingRate/exchangeInfo all
    # work with no key. Perpetuals exist for 18 of the 21 currently tracked
    # assets (missing STORJ, BONK, WBT); dated (quarterly) futures exist for
    # BTC/ETH only — Binance doesn't list dated futures for any other
    # currently-tracked asset (verified against exchangeInfo).

    def list_perpetual_symbols(self) -> set[str]:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(f"{self._futures_base_url}/fapi/v1/exchangeInfo")
            response.raise_for_status()
            data = response.json()
        return {
            s["baseAsset"]
            for s in data["symbols"]
            if s["status"] == "TRADING" and s["quoteAsset"] == "USDT" and s["contractType"] == "PERPETUAL"
        }

    def fetch_funding_rate(self, symbol: str) -> dict | None:
        """Current funding rate + next funding time for `<symbol>USDT` perpetual."""
        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                f"{self._futures_base_url}/fapi/v1/premiumIndex", params={"symbol": f"{symbol}USDT"}
            )
            if response.status_code == 400:
                return None
            response.raise_for_status()
            return response.json()

    def fetch_open_interest(self, symbol: str) -> float | None:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                f"{self._futures_base_url}/fapi/v1/openInterest", params={"symbol": f"{symbol}USDT"}
            )
            if response.status_code == 400:
                return None
            response.raise_for_status()
            return float(response.json()["openInterest"])

    def list_dated_futures(self, symbol: str) -> list[dict]:
        """Returns [{symbol, delivery_date}] for `symbol`'s dated (quarterly)
        futures contracts — empty if none exist (true for every currently
        tracked asset except BTC/ETH)."""
        with httpx.Client(timeout=15.0) as client:
            response = client.get(f"{self._futures_base_url}/fapi/v1/exchangeInfo")
            response.raise_for_status()
            data = response.json()
        return [
            {"symbol": s["symbol"], "delivery_date": s["deliveryDate"]}
            for s in data["symbols"]
            if s["baseAsset"] == symbol
            and s["quoteAsset"] == "USDT"
            and s["status"] == "TRADING"
            and s["contractType"] != "PERPETUAL"
        ]

    def fetch_futures_price(self, futures_symbol: str) -> float | None:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                f"{self._futures_base_url}/fapi/v1/ticker/price", params={"symbol": futures_symbol}
            )
            if response.status_code == 400:
                return None
            response.raise_for_status()
            return float(response.json()["price"])
