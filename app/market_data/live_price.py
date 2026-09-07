"""Phase 5b: a genuinely live spot price for the dashboard, fetched at
request time — deliberately separate from `market_snapshots` (the last
*collected* price, used everywhere else: value_usd/allocation, the Risk
Engine, Portfolio Construction). Never conflated with those: this exists
only as its own clearly-labeled figure, per the user's explicit choice not
to make the stored-snapshot-based numbers live-fetched.

Same Binance-primary/Coinbase-fallback convention as 3b's volatility/
drawdown sourcing (`app/market_data/factors.py`) — reused here rather than
introducing a third venue, since both clients already exist and are
already known to handle this project's asset universe (HYPE/STORJ have no
Binance USDT pair, hence the fallback).
"""

from datetime import UTC, datetime
from typing import NamedTuple

from app.market_data.binance import BinanceClient
from app.market_data.coinbase import CoinbaseClient


class LivePrice(NamedTuple):
    price: float
    as_of: datetime
    source: str  # "binance" or "coinbase"


def fetch_live_price(
    symbol: str, binance_client: BinanceClient, coinbase_client: CoinbaseClient
) -> LivePrice | None:
    """Returns None only if neither venue lists `symbol` — never a
    fabricated or stale-substituted price."""
    ticker = binance_client.fetch_ticker_24hr(symbol)
    if ticker is not None and ticker.get("lastPrice") is not None:
        close_time_ms = ticker.get("closeTime")
        as_of = datetime.fromtimestamp(close_time_ms / 1000, tz=UTC) if close_time_ms else datetime.now(UTC)
        return LivePrice(price=float(ticker["lastPrice"]), as_of=as_of, source="binance")

    ticker = coinbase_client.fetch_ticker(symbol)
    if ticker is not None and ticker.get("price") is not None:
        time_raw = ticker.get("time")
        as_of = datetime.fromisoformat(time_raw.replace("Z", "+00:00")) if time_raw else datetime.now(UTC)
        return LivePrice(price=float(ticker["price"]), as_of=as_of, source="coinbase")

    return None
