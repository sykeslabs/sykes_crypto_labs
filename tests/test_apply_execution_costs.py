from datetime import UTC, datetime

from scripts.apply_execution_costs import (
    HISTORICAL_FETCH_DAYS,
    TRAILING_WINDOW_DAYS,
    _required_fetch_days,
    fetch_historical_series,
)


class FakeBinanceClient:
    """Records how it was called -- used to prove the real bug (unpaginated,
    today-anchored fetch) is actually fixed, not just that some value comes
    back."""

    def __init__(self, rows: list[tuple[datetime, float, float]] | None):
        self._rows = rows
        self.paginated_calls: list[tuple[str, int]] = []

    def fetch_daily_ohlcv_paginated(self, symbol: str, total_days: int, end_time=None):
        self.paginated_calls.append((symbol, total_days))
        return self._rows

    def fetch_daily_ohlcv_with_timestamps(self, symbol: str, days: int):
        raise AssertionError("must use the paginated method, not the old unpaginated one")


class FakeCoinbaseClient:
    def __init__(self, rows: list[tuple[datetime, float, float]] | None):
        self._rows = rows
        self.calls: list[tuple[str, int]] = []

    def fetch_daily_ohlcv_with_timestamps(self, symbol: str, days: int):
        self.calls.append((symbol, days))
        return self._rows


def test_required_fetch_days_uses_the_floor_for_a_recent_decision():
    now = datetime(2026, 9, 16, tzinfo=UTC)
    oldest_needed = datetime(2026, 9, 10, tzinfo=UTC)  # 6 days ago
    assert _required_fetch_days(oldest_needed, now) == HISTORICAL_FETCH_DAYS


def test_required_fetch_days_reaches_back_past_an_old_decision_plus_trailing_window():
    # Real bug this fixes: a decision from 2022-11 (the FTX-window ablation)
    # is ~1400 days before 2026-09-16 -- well past the old fixed 1000-day
    # boundary. Unlike apply_benchmark_alpha.py, this script also needs
    # TRAILING_WINDOW_DAYS of history *before* the oldest decision for its
    # own volatility lookback to be meaningful.
    now = datetime(2026, 9, 16, tzinfo=UTC)
    oldest_needed = datetime(2022, 11, 8, tzinfo=UTC)
    days = _required_fetch_days(oldest_needed, now)
    assert days > HISTORICAL_FETCH_DAYS
    assert days >= (now - oldest_needed).days + TRAILING_WINDOW_DAYS


def test_fetch_historical_series_uses_the_paginated_binance_method_with_the_requested_depth():
    rows = [(datetime(2023, 1, 1, tzinfo=UTC), 100.0, 10.0), (datetime(2023, 1, 2, tzinfo=UTC), 101.0, 11.0)]
    binance = FakeBinanceClient(rows)
    coinbase = FakeCoinbaseClient(None)

    series = fetch_historical_series(binance, coinbase, "BTC", "asset-1", total_days=1500)

    assert series is not None
    assert series.source == "BINANCE"
    assert binance.paginated_calls == [("BTC", 1500)]
    assert coinbase.calls == []  # Binance succeeded -- Coinbase must not be touched


def test_fetch_historical_series_falls_back_to_coinbase_when_binance_has_no_pair():
    binance = FakeBinanceClient(None)
    rows = [(datetime(2023, 1, 1, tzinfo=UTC), 100.0, 10.0)]
    coinbase = FakeCoinbaseClient(rows)

    series = fetch_historical_series(binance, coinbase, "BTW", "asset-2", total_days=1500)

    assert series is not None
    assert series.source == "COINBASE"
    assert coinbase.calls == [("BTW", HISTORICAL_FETCH_DAYS)]


def test_fetch_historical_series_returns_none_when_neither_source_has_data():
    binance = FakeBinanceClient(None)
    coinbase = FakeCoinbaseClient(None)

    assert fetch_historical_series(binance, coinbase, "BTW", "asset-2", total_days=1500) is None
