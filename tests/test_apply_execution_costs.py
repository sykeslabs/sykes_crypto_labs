from datetime import UTC, datetime
from decimal import Decimal

import scripts.apply_execution_costs as apply_execution_costs_module
from app.benchmarks.schemas import DecisionOutcome
from app.judge.schemas import JudgeDecisionRecord
from scripts.apply_execution_costs import (
    HISTORICAL_FETCH_DAYS,
    TRAILING_WINDOW_DAYS,
    _required_fetch_days,
    fetch_decisions_by_id,
    fetch_historical_series,
    fetch_resolved_outcomes_without_net_of_costs,
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


# --- fetch_decisions_by_id: pagination-safe repository retrieval (2026-09-27) ---

def _decision_record(id_, decision="BUY", target_allocation=0.1, is_backfilled=False):
    record = JudgeDecisionRecord(
        run_id="RUN-TEST", asset_id="asset-1", created_at=datetime(2026, 9, 1, tzinfo=UTC),
        decision=decision, confidence=0.6, target_allocation=target_allocation, expected_return=0.1,
        expected_alpha=0.05, risk_score=0.4, uncertainty=0.3, model_agreement=0.8, source_agreement=0.7,
        investment_horizon_days=30, key_evidence=[], contradictory_evidence=[], key_risks=[],
        invalidation_conditions=[], requires_review=False, thesis="t", macro_sensitivity="n/a",
        regime_id=None, prompt_template_id="p1", estimated_cost=Decimal("0.01"), is_backfilled=is_backfilled,
    )
    record.id = id_
    return record


class _FakeJudgeDecisionRepository:
    """Records exactly how it was constructed/called -- proves the real
    consumer bug (a raw, unpaginated, unfiltered query) is replaced by the
    pagination-safe repository call with the correct population, not just
    that some value comes back."""

    last_calls: list[dict] = []

    def __init__(self, client):
        self._client = client

    def get_recent(self, limit=None, is_backfilled=None):
        _FakeJudgeDecisionRepository.last_calls.append({"limit": limit, "is_backfilled": is_backfilled})
        return _FakeJudgeDecisionRepository.records


def test_fetch_decisions_by_id_calls_repository_with_limit_none_and_no_backfill_filter(monkeypatch):
    _FakeJudgeDecisionRepository.last_calls = []
    _FakeJudgeDecisionRepository.records = []
    monkeypatch.setattr(apply_execution_costs_module, "JudgeDecisionRepository", _FakeJudgeDecisionRepository)

    fetch_decisions_by_id(client=object())

    assert _FakeJudgeDecisionRepository.last_calls == [{"limit": None, "is_backfilled": None}]


def test_fetch_decisions_by_id_accepts_both_live_and_backfilled_records(monkeypatch):
    live = _decision_record("live-1", is_backfilled=False)
    backfilled = _decision_record("bf-1", is_backfilled=True)
    _FakeJudgeDecisionRepository.records = [live, backfilled]
    monkeypatch.setattr(apply_execution_costs_module, "JudgeDecisionRepository", _FakeJudgeDecisionRepository)

    decisions = fetch_decisions_by_id(client=object())

    assert set(decisions) == {"live-1", "bf-1"}
    assert decisions["live-1"].is_backfilled is False
    assert decisions["bf-1"].is_backfilled is True


def test_fetch_decisions_by_id_downstream_lookup_uses_record_attributes(monkeypatch):
    # Proves the dict-access -> JudgeDecisionRecord-attribute migration is
    # real: main()'s own downstream line reads `decision_row.target_allocation`,
    # not `decision_row["target_allocation"]`.
    record = _decision_record("d-1", target_allocation=0.25)
    _FakeJudgeDecisionRepository.records = [record]
    monkeypatch.setattr(apply_execution_costs_module, "JudgeDecisionRepository", _FakeJudgeDecisionRepository)

    decisions = fetch_decisions_by_id(client=object())
    decision_row = decisions["d-1"]

    assert decision_row.target_allocation == 0.25
    order_size_usd = abs(decision_row.target_allocation or 0.0) * 10_000.0
    assert order_size_usd == 2500.0


def test_fetch_decisions_by_id_does_not_truncate_a_population_crossing_the_old_1000_row_boundary(monkeypatch):
    # Real regression guard: the old code was a single, unpaginated
    # `client.table("judge_decisions").execute()` call -- silently capped at
    # Supabase's real per-request row limit. This proves the consumer now
    # consumes the COMPLETE repository result, whatever size it is, rather
    # than assuming/re-truncating at some hardcoded boundary itself.
    records = [_decision_record(f"d-{i}") for i in range(1001)]
    _FakeJudgeDecisionRepository.records = records
    monkeypatch.setattr(apply_execution_costs_module, "JudgeDecisionRepository", _FakeJudgeDecisionRepository)

    decisions = fetch_decisions_by_id(client=object())

    assert len(decisions) == 1001


# --- fetch_resolved_outcomes_without_net_of_costs: DecisionOutcome
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

    def get_resolved_without_net_of_costs(self, limit=1000):
        self.calls.append(limit)
        return self._rows


def test_fetch_resolved_outcomes_without_net_of_costs_calls_repository_with_limit_none():
    repo = _FakeDecisionOutcomeRepo([])

    fetch_resolved_outcomes_without_net_of_costs(repo)

    assert repo.calls == [None]


def test_fetch_resolved_outcomes_without_net_of_costs_does_not_truncate_past_the_old_1000_row_boundary():
    # The repository's own pagination is already covered by
    # tests/test_repository_pagination.py -- this proves the CONSUMER
    # doesn't reintroduce a truncation on top of whatever it returns (e.g.
    # a stray [:1000] slice), by handing back more rows than the old
    # hardcoded limit ever allowed.
    rows = [_resolved_outcome(f"d-{i}") for i in range(1200)]
    repo = _FakeDecisionOutcomeRepo(rows)

    resolved = fetch_resolved_outcomes_without_net_of_costs(repo)

    assert len(resolved) == 1200
