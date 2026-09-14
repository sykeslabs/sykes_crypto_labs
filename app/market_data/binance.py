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

    def fetch_daily_ohlcv_paginated(
        self, symbol: str, total_days: int, end_time: datetime | None = None,
    ) -> list[tuple[datetime, float, float]] | None:
        """Same (date, close, volume) shape as `fetch_daily_ohlcv_with_timestamps`,
        oldest first, but pages backward past the `/klines` endpoint's real
        1000-candle-per-call cap using `endTime` -- lets a caller reach
        further back than one call allows (e.g. stress-testing against
        BTC's real 2022 drawdown, previously unreachable at exactly that
        cap -- see README/dashboard TODO). Stops once `total_days` candles
        are collected, or once the exchange returns fewer rows than
        requested for a page (the symbol's own real listing date has been
        reached) -- never invents data past either real boundary.

        `end_time` (default `None`, meaning "now", the original behavior)
        anchors the LATEST candle fetched -- without it, every call is
        implicitly "the most recent `total_days` days ending today", which
        silently produces no data at all for a historical window once real
        wall-clock time has moved far enough past it (a real bug found
        live: `HistoricalReplayService`'s own historical-series fetcher
        used the unpaginated, un-anchored `fetch_daily_ohlcv_with_timestamps`
        and returned zero candidates -- not an error, just silently empty --
        for any replay window older than its own trailing-lookback buffer
        relative to the real current date; see README/dashboard TODO)."""
        all_rows: list[tuple[datetime, float, float]] = []
        end_time_ms: int | None = int(end_time.timestamp() * 1000) if end_time is not None else None
        with httpx.Client(timeout=15.0) as client:
            while len(all_rows) < total_days:
                page_limit = min(1000, total_days - len(all_rows))
                params = {"symbol": f"{symbol}USDT", "interval": "1d", "limit": page_limit}
                if end_time_ms is not None:
                    params["endTime"] = end_time_ms
                response = client.get(f"{self._base_url}/api/v3/klines", params=params)
                if response.status_code == 400:
                    break  # no such pair -- return whatever real pages were already collected, if any
                response.raise_for_status()
                page_rows = response.json()
                if not page_rows:
                    break

                page = [
                    (datetime.fromtimestamp(row[0] / 1000, tz=UTC), float(row[4]), float(row[5]))
                    for row in page_rows
                ]
                all_rows = page + all_rows  # this page is strictly older than what's already collected
                end_time_ms = page_rows[0][0] - 1  # just before this page's earliest open_time
                if len(page_rows) < page_limit:
                    break  # exchange had fewer real candles than requested -- real history start reached

        return all_rows or None

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

    def fetch_order_book_depth(self, symbol: str, limit: int = 100) -> "OrderBookSnapshot | None":
        """Phase 4: real public order-book depth for `<symbol>USDT` — no key
        required. Verified live: `/api/v3/depth` returns real bids/asks
        (100 levels each at `limit=100`). None if no such pair."""
        from app.trading.fill_simulator import OrderBookLevel, OrderBookSnapshot

        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                f"{self._base_url}/api/v3/depth", params={"symbol": f"{symbol}USDT", "limit": limit}
            )
            if response.status_code == 400:
                return None
            response.raise_for_status()
            data = response.json()

        return OrderBookSnapshot(
            bids=[OrderBookLevel(float(p), float(q)) for p, q in data["bids"]],
            asks=[OrderBookLevel(float(p), float(q)) for p, q in data["asks"]],
            source="BINANCE",
        )
