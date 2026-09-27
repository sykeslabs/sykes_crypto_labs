from datetime import UTC, datetime

import pytest

from app.benchmarks.schemas import DecisionOutcome
from scripts.apply_benchmark_alpha import (
    HISTORICAL_FETCH_DAYS,
    _required_fetch_days,
    compute_benchmark_alpha,
    fetch_historical_series,
    fetch_resolved_outcomes_without_benchmark_alpha,
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


def test_required_fetch_days_reaches_back_past_an_old_decision():
    # Real bug this fixes: a decision from 2022-11 (the FTX-window ablation)
    # is ~1400 days before 2026-09-16 -- well past the old fixed 1000-day
    # boundary. The requested depth must reach back far enough to cover it.
    now = datetime(2026, 9, 16, tzinfo=UTC)
    oldest_needed = datetime(2022, 11, 8, tzinfo=UTC)
    days = _required_fetch_days(oldest_needed, now)
    assert days > HISTORICAL_FETCH_DAYS
    assert days >= (now - oldest_needed).days


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


def test_compute_benchmark_alpha_known_hand_computation():
    # BTC (benchmark) went 100 -> 110: benchmark_return = 0.10 exactly.
    # The decision's own realized_return was 0.25 -> effective_alpha = 0.15 exactly.
    benchmark_return, effective_alpha = compute_benchmark_alpha(entry_price=100.0, exit_price=110.0, realized_return=0.25)
    assert benchmark_return == pytest.approx(0.10)
    assert effective_alpha == pytest.approx(0.15)


def test_compute_benchmark_alpha_negative_alpha_when_benchmark_outperforms():
    # BTC went 100 -> 130 (0.30) while the decision only realized 0.05 --
    # a real negative alpha: the decision underperformed passively holding BTC.
    benchmark_return, effective_alpha = compute_benchmark_alpha(entry_price=100.0, exit_price=130.0, realized_return=0.05)
    assert benchmark_return == pytest.approx(0.30)
    assert effective_alpha == pytest.approx(-0.25)


def test_compute_benchmark_alpha_when_benchmark_fell():
    # BTC fell 100 -> 90 (-0.10) while the decision realized +0.05 -- alpha is
    # larger than the raw realized_return, since it beat a falling benchmark too.
    benchmark_return, effective_alpha = compute_benchmark_alpha(entry_price=100.0, exit_price=90.0, realized_return=0.05)
    assert benchmark_return == pytest.approx(-0.10)
    assert effective_alpha == pytest.approx(0.15)


# --- fetch_resolved_outcomes_without_benchmark_alpha: DecisionOutcome
# pagination migration, Phase 2/consumer batch 1 (2026-09-27) --------------

def _resolved_outcome(decision_id):
    return DecisionOutcome(
        decision_id=decision_id, asset_id="asset-1", decision_timestamp=datetime(2026, 9, 1, tzinfo=UTC),
        horizon_days=30, target_return=0.1, stop_return=-0.1, realized_return=0.05,
        outcome_label="HIT_TARGET", judge_confidence=0.6,
    )


class _FakeDecisionOutcomeRepo:
    def __init__(self, rows):
        self._rows = rows
        self.calls = []

    def get_resolved_without_benchmark_alpha(self, limit=1000):
        self.calls.append(limit)
        return self._rows


def test_fetch_resolved_outcomes_without_benchmark_alpha_calls_repository_with_limit_none():
    repo = _FakeDecisionOutcomeRepo([])

    fetch_resolved_outcomes_without_benchmark_alpha(repo)

    assert repo.calls == [None]


def test_fetch_resolved_outcomes_without_benchmark_alpha_does_not_truncate_past_the_old_1000_row_boundary():
    rows = [_resolved_outcome(f"d-{i}") for i in range(1200)]
    repo = _FakeDecisionOutcomeRepo(rows)

    resolved = fetch_resolved_outcomes_without_benchmark_alpha(repo)

    assert len(resolved) == 1200
