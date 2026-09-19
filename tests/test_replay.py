from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.benchmarks.historical_factors import HistoricalSeries, compute_point_in_time_factors, pct_change
from app.benchmarks.replay import (
    EVIDENCE_UNAVAILABLE_FOR_REPLAY,
    HistoricalReplayService,
    ReplayResult,
    _assign_model_agreement,
    _daily_cutoffs,
    estimate_replay_cost,
)
from app.benchmarks.replay_fakes import (
    AsOfAssetStatusRepo,
    AsOfLLMAnalysisRepo,
    InMemoryAllocationChangeRepo,
    InMemoryPortfolioPositionRepo,
)
from app.config.settings import Settings
from app.database.models import Asset
from app.judge.schemas import JudgeDecisionBatch
from app.llm.assessment_schemas import AssessmentBatch
from app.portfolio.schemas import PortfolioAllocationChange, PortfolioPosition


# --- historical_factors -------------------------------------------------------

def _dates(n, start):
    return [start + timedelta(days=i) for i in range(n)]


def test_historical_series_as_of_never_includes_future_points():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    series = HistoricalSeries(
        symbol="BTC", asset_id="a1", source="BINANCE",
        dates=_dates(10, start), closes=[float(i) for i in range(10)], volumes=[1.0] * 10,
    )
    dates, closes, volumes = series.as_of(start + timedelta(days=4))
    assert len(dates) == 5
    assert closes == [0.0, 1.0, 2.0, 3.0, 4.0]
    assert all(d <= start + timedelta(days=4) for d in dates)


def test_pct_change_none_when_insufficient_history():
    assert pct_change([100.0, 105.0], lookback_days=7) is None


def test_pct_change_basic():
    closes = [100.0] * 7 + [110.0]
    assert pct_change(closes, 7) == pytest.approx(10.0)


def test_compute_point_in_time_factors_none_safe_with_no_data():
    series = HistoricalSeries(symbol="X", asset_id="a1", source="BINANCE", dates=[], closes=[], volumes=[])
    factors = compute_point_in_time_factors(series, datetime.now(UTC), btc_momentum_30d=5.0)
    assert factors.price is None
    assert factors.momentum_30d is None


def test_compute_point_in_time_factors_relative_strength():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    n = 35
    closes = [100.0 * (1.01**i) for i in range(n)]  # steady uptrend
    series = HistoricalSeries(symbol="ETH", asset_id="a1", source="BINANCE", dates=_dates(n, start), closes=closes, volumes=[10.0] * n)
    cutoff = start + timedelta(days=n - 1)
    factors = compute_point_in_time_factors(series, cutoff, btc_momentum_30d=5.0)
    assert factors.momentum_30d is not None
    assert factors.relative_strength_30d == pytest.approx(factors.momentum_30d - 5.0)


# --- replay_fakes --------------------------------------------------------------

def test_in_memory_portfolio_position_repo_roundtrip():
    repo = InMemoryPortfolioPositionRepo()
    repo.upsert(PortfolioPosition(asset_id="a1", current_allocation=0.05, last_decision_id="d1"))
    positions = repo.get_all()
    assert positions["a1"].current_allocation == 0.05


def test_in_memory_allocation_change_repo_turnover_window():
    repo = InMemoryAllocationChangeRepo()
    now = datetime(2026, 1, 10, tzinfo=UTC)
    repo.insert(PortfolioAllocationChange(asset_id="a1", run_id="R", decision_id="d1", previous_allocation=0.0, new_allocation=0.05, changed_at=now))
    repo.insert(PortfolioAllocationChange(asset_id="a2", run_id="R", decision_id="d2", previous_allocation=0.0, new_allocation=0.03, changed_at=now - timedelta(days=10)))
    turnover = repo.get_turnover_since(now - timedelta(days=7))
    assert turnover == pytest.approx(0.05)  # only the in-window change counts


def test_in_memory_allocation_change_repo_excludes_risk_control_rows():
    # Mirrors the real repository's 2026-09-17 change_reason fix -- replay
    # backtests must not double-count WATCH/NO_TRADE risk-control
    # corrections as strategy turnover either.
    repo = InMemoryAllocationChangeRepo()
    now = datetime(2026, 1, 10, tzinfo=UTC)
    repo.insert(PortfolioAllocationChange(
        asset_id="a1", run_id="R", decision_id="d1", previous_allocation=0.0, new_allocation=0.05,
        changed_at=now, change_reason="strategy",
    ))
    repo.insert(PortfolioAllocationChange(
        asset_id="a2", run_id="R", decision_id="d2", previous_allocation=0.30, new_allocation=0.15,
        changed_at=now, change_reason="risk_control",
    ))
    turnover = repo.get_turnover_since(now - timedelta(days=7))
    assert turnover == pytest.approx(0.05)  # the risk_control row is excluded


class _FakeAsOfRepoBackend:
    def get_latest_by_asset_as_of(self, asset_id, as_of, limit=3):
        return [("called", asset_id, as_of, limit)]

    def get_latest_status_as_of(self, asset_id, as_of):
        return ("status_called", asset_id, as_of)


def test_as_of_llm_analysis_repo_delegates_with_fixed_cutoff():
    backend = _FakeAsOfRepoBackend()
    cutoff = datetime(2026, 1, 1, tzinfo=UTC)
    wrapper = AsOfLLMAnalysisRepo(backend, cutoff)
    assert wrapper.get_latest_by_asset("a1", limit=5) == [("called", "a1", cutoff, 5)]


def test_as_of_asset_status_repo_delegates_with_fixed_cutoff():
    backend = _FakeAsOfRepoBackend()
    cutoff = datetime(2026, 1, 1, tzinfo=UTC)
    wrapper = AsOfAssetStatusRepo(backend, cutoff)
    assert wrapper.get_latest_status("a1") == ("status_called", "a1", cutoff)


# --- cost estimate & date generation --------------------------------------------

def test_estimate_replay_cost_scales_linearly_with_days():
    assert estimate_replay_cost(1) == Decimal("0.575")
    assert estimate_replay_cost(28) == Decimal("16.10")


def test_daily_cutoffs_inclusive_range():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 1, 3, tzinfo=UTC)
    cutoffs = _daily_cutoffs(start, end)
    assert cutoffs == [start, start + timedelta(days=1), start + timedelta(days=2)]


def _fake_assessment_record(asset_id, overall_assessment, expected_return_30d):
    from app.llm.assessment_schemas import ModelMarketAssessmentRecord

    return ModelMarketAssessmentRecord(
        run_id="BACKFILL-2026-01-01", asset_id=asset_id, provider="claude", model="m1",
        prompt_template_id=None, assessment_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        data_cutoff_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        short_term_direction="NEUTRAL", medium_term_direction="NEUTRAL", long_term_direction="NEUTRAL",
        short_term_confidence=0.5, medium_term_confidence=0.5, long_term_confidence=0.5,
        expected_return_7d=0.0, expected_return_30d=expected_return_30d, expected_return_90d=0.0,
        risk_score=0.5, risk_level="MEDIUM", market_regime="RISK_ON",
        model_agreement=1.0, overall_assessment=overall_assessment, thesis="t",
        key_drivers=[], key_risks=[], source_assessment=[], invalidation_conditions=[],
        raw_response=None, estimated_cost=Decimal("0.01"),
    )


def test_assign_model_agreement_also_assigns_return_dispersion():
    import statistics

    records = [
        _fake_assessment_record("a1", "BULLISH", 0.05),
        _fake_assessment_record("a1", "BULLISH", -0.15),
        _fake_assessment_record("a2", "BEARISH", 0.02),
    ]
    _assign_model_agreement(records)

    a1_records = [r for r in records if r.asset_id == "a1"]
    a2_records = [r for r in records if r.asset_id == "a2"]

    assert all(r.model_agreement == pytest.approx(1.0) for r in a1_records)
    expected_dispersion_a1 = statistics.pstdev([0.05, -0.15])
    assert all(r.expected_return_dispersion_30d == pytest.approx(expected_dispersion_a1) for r in a1_records)

    # A single model for a2 -- nothing to compute a spread from.
    assert a2_records[0].expected_return_dispersion_30d is None


# --- HistoricalReplayService orchestration --------------------------------------

class FakeAssetRepoForReplay:
    def __init__(self, assets):
        self._assets = assets

    def get_active_assets(self):
        return self._assets


class FakeNewsRepoForReplay:
    def get_recent_relevant_news(self, symbols, since, until, limit_per_asset):
        return {}


class FakeAsOfBackendForReplay:
    def get_latest_by_asset_as_of(self, asset_id, as_of, limit=3):
        return []

    def get_latest_status_as_of(self, asset_id, as_of):
        return None


class FakeSignalSourceRepoForReplay:
    def get_all(self):
        return []


class FakePromptTemplateRepoForReplay:
    def __init__(self):
        self.calls = []

    def get_or_create(self, name, stage, version, template_hash):
        self.calls.append((name, stage, version))
        return f"template-{name}-{stage}"


class FakeJudgeDecisionRepoForReplay:
    def __init__(self):
        self.inserted = []

    def insert(self, record):
        self.inserted.append(record)
        return f"decision-{len(self.inserted)}"


class FakeDecisionOutcomeRepoForReplay:
    def __init__(self):
        self.inserted = []
        self.updated = []

    def insert(self, outcome):
        self.inserted.append(outcome)

    def update_outcome(self, decision_id, realized_return, outcome_label, evaluated_at):
        self.updated.append((decision_id, realized_return, outcome_label, evaluated_at))


class FakeMarketRegimeRepoForReplay:
    def __init__(self):
        self.inserted = []

    def insert(self, snapshot):
        self.inserted.append(snapshot)
        return f"regime-{len(self.inserted)}"


class FakeScreenedUniverseRepoForReplay:
    def __init__(self):
        self.inserted_batches = []

    def insert_many(self, rows):
        self.inserted_batches.append(rows)


class FakeCostGuardForReplay:
    def check(self):
        return True, None

    def remaining_budget(self):
        return Decimal("100"), Decimal("1000")


class FakeAssessmentProviderForReplay:
    def __init__(self, symbols):
        self._symbols = symbols
        self.name = "claude"
        self.model = "fake-model"

    def analyze(self, system_prompt, user_prompt):
        from app.llm.assessment_provider import AssessmentProviderResult
        from app.llm.schemas import TokenUsage

        assessments = [_valid_assessment_payload(symbol) for symbol in self._symbols]
        return AssessmentProviderResult(
            provider=self.name, model=self.model, batch=AssessmentBatch(assessments=assessments),
            token_usage=TokenUsage(prompt_tokens=100, completion_tokens=100),
            estimated_cost=Decimal("0.14"), raw_response={}, error=None,
        )


class FakeJudgeProviderForReplay:
    def __init__(self, symbols):
        self._symbols = symbols
        self.model = "fake-judge-model"

    def decide(self, system_prompt, user_prompt):
        from app.judge.provider import JudgeProviderResult
        from app.llm.schemas import TokenUsage

        decisions = [_valid_decision_payload(symbol) for symbol in self._symbols]
        return JudgeProviderResult(
            provider="judge", model=self.model, batch=JudgeDecisionBatch(decisions=decisions),
            token_usage=TokenUsage(prompt_tokens=200, completion_tokens=200),
            estimated_cost=Decimal("0.15"), raw_response={}, error=None,
        )


class FakeAdversarialProviderForReplay:
    """Same duck-typed `.call(system_prompt, user_prompt, response_model)`
    interface as the real `OpenRouterStructuredProvider` -- returns a valid
    bull/bear/scenario batch for every symbol regardless of prompt content,
    matching every other fake provider in this file."""

    def __init__(self, symbols):
        self._symbols = symbols

    def call(self, system_prompt, user_prompt, response_model):
        from app.llm.adversarial_schemas import BearBatch, BearCase, BullBatch, BullCase, ScenarioBatch, ScenarioSet
        from app.llm.structured_provider import StructuredCallResult

        if response_model is BullBatch:
            batch = BullBatch(cases=[BullCase(asset=s, thesis="t", catalysts=[], evidence=[]) for s in self._symbols])
            return StructuredCallResult("adversarial", "fake-model", batch, None, Decimal("0.05"), {}, None)
        if response_model is BearBatch:
            batch = BearBatch(cases=[BearCase(asset=s, attack_points=[], evidence=[], attacks_bull_point=[]) for s in self._symbols])
            return StructuredCallResult("adversarial", "fake-model", batch, None, Decimal("0.05"), {}, None)
        batch = ScenarioBatch(scenarios=[
            ScenarioSet(
                asset=s,
                bull={"probability": 0.3, "expected_return": 0.5, "timeframe": "90d"},
                base={"probability": 0.4, "expected_return": 0.1, "timeframe": "90d"},
                bear={"probability": 0.3, "expected_return": -0.2, "timeframe": "90d"},
            )
            for s in self._symbols
        ])
        return StructuredCallResult("adversarial", "fake-model", batch, None, Decimal("0.08"), {}, None)


class FakeAdversarialRepoForReplay:
    def __init__(self):
        self.inserted = []

    def insert(self, record):
        self.inserted.append(record)


def _valid_assessment_payload(symbol):
    return dict(
        asset=symbol, assessment_timestamp="2026-01-01T00:00:00Z",
        horizon={"short_term_days": 7, "medium_term_days": 30, "long_term_days": 90},
        direction={"short_term": "BULLISH", "medium_term": "NEUTRAL", "long_term": "NEUTRAL"},
        confidence={"short_term": 0.6, "medium_term": 0.5, "long_term": 0.45},
        expected_return={"7d": 0.03, "30d": 0.05, "90d": 0.08},
        risk={"score": 0.5, "level": "MEDIUM"}, market_regime="RISK_ON",
        key_drivers=[], key_risks=[], source_assessment=[], thesis="t",
        invalidation_conditions=[], overall_assessment="BULLISH",
    )


def _valid_decision_payload(symbol):
    return dict(
        asset=symbol, decision="BUY", confidence=0.6, target_allocation=0.05,
        expected_return=0.1, expected_alpha=0.05, risk_score=0.4, uncertainty=0.3,
        model_agreement=1.0, source_agreement=0.6, investment_horizon_days=14,
        key_evidence=[], contradictory_evidence=[], key_risks=[],
        invalidation_conditions=[], requires_review=False, thesis="t",
        macro_sensitivity="n/a",
    )


def _synthetic_series(symbol, asset_id, n_days, end_date, drift=1.005):
    start = end_date - timedelta(days=n_days - 1)
    dates = _dates(n_days, start)
    closes = [100.0 * (drift**i) for i in range(n_days)]
    volumes = [1000.0] * n_days
    return HistoricalSeries(symbol=symbol, asset_id=asset_id, source="BINANCE", dates=dates, closes=closes, volumes=volumes)


def _make_service(
    assets, series_by_symbol, judge_repo=None, outcome_repo=None, prompt_repo=None, regime_repo=None,
    screened_universe_repo=None, adversarial_provider=None, adversarial_repo=None,
):
    settings = Settings(_env_file=None)
    symbols = [a.symbol for a in assets]

    def series_fetcher(asset):
        return series_by_symbol.get(asset.symbol)

    def funding_fetcher(asset):
        return []

    return HistoricalReplayService(
        settings=settings,
        asset_repo=FakeAssetRepoForReplay(assets),
        news_repo=FakeNewsRepoForReplay(),
        llm_analysis_repo=FakeAsOfBackendForReplay(),
        asset_status_repo=FakeAsOfBackendForReplay(),
        signal_source_repo=FakeSignalSourceRepoForReplay(),
        prompt_template_repo=prompt_repo or FakePromptTemplateRepoForReplay(),
        judge_decision_repo=judge_repo or FakeJudgeDecisionRepoForReplay(),
        decision_outcome_repo=outcome_repo or FakeDecisionOutcomeRepoForReplay(),
        regime_repo=regime_repo or FakeMarketRegimeRepoForReplay(),
        screened_universe_repo=screened_universe_repo or FakeScreenedUniverseRepoForReplay(),
        cost_guard=FakeCostGuardForReplay(),
        assessment_providers=[FakeAssessmentProviderForReplay(symbols)],
        judge_provider=FakeJudgeProviderForReplay(symbols),
        historical_series_fetcher=series_fetcher,
        funding_rate_fetcher=funding_fetcher,
        adversarial_provider=adversarial_provider,
        adversarial_repo=adversarial_repo,
    )


def _assets():
    now = datetime.now(UTC)
    return [
        Asset(id="a-btc", symbol="BTC", name="Bitcoin", coingecko_id="bitcoin", active=True, in_asset=True, created_at=now),
        Asset(id="a-eth", symbol="ETH", name="Ethereum", coingecko_id="ethereum", active=True, in_asset=True, created_at=now),
        Asset(id="a-link", symbol="LINK", name="Chainlink", coingecko_id="chainlink", active=True, in_asset=True, created_at=now),
    ]


def test_replay_produces_backfilled_decisions_and_outcomes():
    assets = _assets()
    end_date = datetime(2026, 3, 1, tzinfo=UTC)
    series_by_symbol = {a.symbol: _synthetic_series(a.symbol, a.id, 90, end_date) for a in assets}
    judge_repo = FakeJudgeDecisionRepoForReplay()
    outcome_repo = FakeDecisionOutcomeRepoForReplay()

    service = _make_service(assets, series_by_symbol, judge_repo=judge_repo, outcome_repo=outcome_repo)
    start = end_date - timedelta(days=10)
    end = end_date - timedelta(days=8)  # a 3-day window, well inside the fetched series

    result = service.run(start, end)

    assert isinstance(result, ReplayResult)
    assert len(result.days) == 3
    assert all(d.decisions_stored == 3 for d in result.days)  # BTC/ETH/LINK every day
    assert len(judge_repo.inserted) == 9

    # Every row this sub-phase creates must be tagged is_backfilled=true.
    assert all(r.is_backfilled is True for r in judge_repo.inserted)
    assert all(o.is_backfilled is True for o in outcome_repo.inserted)
    # And never marked in_holdout_window — backfilled rows are never
    # forward-tracked evidence.
    assert all(o.in_holdout_window is False for o in outcome_repo.inserted)
    # created_at must be the row's REAL insertion time, never the simulated
    # historical date (`cutoff`, which here is ~1970s-relative "2026-02-xx"
    # — far from real "now") — a real bug: CostGuard sums cost by
    # created_at >= today's midnight, so a historical created_at makes a
    # backfilled row invisible to the daily/monthly cap check.
    real_now = datetime.now(UTC)
    assert all(abs((r.created_at - real_now).total_seconds()) < 60 for r in judge_repo.inserted)


def test_replay_without_adversarial_opt_in_never_calls_adversarial_provider():
    # Default (adversarial_provider/adversarial_repo both None, matching
    # every real backfilled decision made before 2026-09-13) -- 3f must not
    # run at all, and no cost from it should appear.
    assets = _assets()
    end_date = datetime(2026, 3, 1, tzinfo=UTC)
    series_by_symbol = {a.symbol: _synthetic_series(a.symbol, a.id, 90, end_date) for a in assets}
    service = _make_service(assets, series_by_symbol)
    result = service.run(end_date - timedelta(days=10), end_date - timedelta(days=9))
    assert len(result.days) == 2
    assert all(d.decisions_stored == 3 for d in result.days)
    # Assessment (0.14) + Judge (0.15) per day only -- no adversarial cost.
    assert all(d.cost == pytest.approx(Decimal("0.29")) for d in result.days)


def test_replay_with_adversarial_opt_in_persists_real_3f_research_per_day():
    assets = _assets()
    end_date = datetime(2026, 3, 1, tzinfo=UTC)
    series_by_symbol = {a.symbol: _synthetic_series(a.symbol, a.id, 90, end_date) for a in assets}
    symbols = [a.symbol for a in assets]
    adversarial_repo = FakeAdversarialRepoForReplay()

    service = _make_service(
        assets, series_by_symbol,
        adversarial_provider=FakeAdversarialProviderForReplay(symbols),
        adversarial_repo=adversarial_repo,
    )
    start = end_date - timedelta(days=10)
    end = end_date - timedelta(days=9)  # a real 2-day window
    result = service.run(start, end)

    assert len(result.days) == 2
    assert all(d.decisions_stored == 3 for d in result.days)  # 3f didn't block the Judge stage

    # One real AdversarialResearchRecord per (day, symbol) -- 2 days x 3 symbols.
    assert len(adversarial_repo.inserted) == 6
    for record in adversarial_repo.inserted:
        assert record.run_id.startswith("BACKFILL-")
        assert record.bull_case["asset"] in symbols
        assert record.bear_case["asset"] == record.bull_case["asset"]
        assert record.scenarios["asset"] == record.bull_case["asset"]
        assert record.estimated_cost > 0

    # Real added cost (bull 0.05 + bear 0.05 + scenario 0.08 = 0.18/day) on
    # top of the existing assessment (0.14) + Judge (0.15) per day.
    assert all(d.cost == pytest.approx(Decimal("0.47")) for d in result.days)


def test_replay_persists_regime_snapshot_and_screened_universe_now_joinable():
    """Regression test for a real persistence gap (README's Phase 3g/3h
    findings): _build_regime/_build_day_universe already compute a real
    regime classification and real composite factor scores in-memory for
    prompt-building, but neither used to be written to a joinable row --
    leaving regime_at_decision/composite_factor_score permanently
    unavailable for every backfilled decision. Now both must actually be
    persisted, and every stored decision/outcome must reference the real
    regime id that was inserted (not None)."""
    assets = _assets()
    end_date = datetime(2026, 3, 1, tzinfo=UTC)
    series_by_symbol = {a.symbol: _synthetic_series(a.symbol, a.id, 90, end_date) for a in assets}
    judge_repo = FakeJudgeDecisionRepoForReplay()
    outcome_repo = FakeDecisionOutcomeRepoForReplay()
    regime_repo = FakeMarketRegimeRepoForReplay()
    screened_universe_repo = FakeScreenedUniverseRepoForReplay()

    service = _make_service(
        assets, series_by_symbol, judge_repo=judge_repo, outcome_repo=outcome_repo,
        regime_repo=regime_repo, screened_universe_repo=screened_universe_repo,
    )
    start = end_date - timedelta(days=10)
    end = end_date - timedelta(days=8)  # a 3-day window

    service.run(start, end)

    # One real regime snapshot actually inserted per replayed day.
    assert len(regime_repo.inserted) == 3
    # One real screened_universe batch (one row per tracked asset) per day.
    assert len(screened_universe_repo.inserted_batches) == 3
    assert all(row.composite_factor_score is not None for batch in screened_universe_repo.inserted_batches for row in batch)

    # Every stored decision/outcome references a REAL regime id (the fake
    # repo's own "regime-N" id), never None.
    assert judge_repo.inserted
    assert all(r.regime_id is not None for r in judge_repo.inserted)
    assert all(o.regime_at_decision is not None for o in outcome_repo.inserted)
    # And the specific id used matches one this run actually inserted.
    inserted_regime_ids = {f"regime-{i}" for i in range(1, len(regime_repo.inserted) + 1)}
    assert all(r.regime_id in inserted_regime_ids for r in judge_repo.inserted)


class RealisticLedgerCostGuard:
    """Mimics the REAL CostLedgerRepository/CostGuard's actual behavior:
    sums `estimated_cost` from rows whose `created_at` falls within today's
    real window — reading directly from the same fake judge_decisions repo
    the replay inserts into. Deliberately reads ONLY judge_decisions (never
    model_market_assessments, since replay never writes there — mirroring
    production exactly), so it reproduces bug 2's under-counting even once
    bug 1 (created_at) is fixed."""

    def __init__(self, judge_repo, settings):
        self._judge_repo = judge_repo
        self._settings = settings

    def _spend_visible_today(self) -> Decimal:
        now = datetime.now(UTC)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return sum(
            (r.estimated_cost for r in self._judge_repo.inserted if r.created_at >= day_start),
            Decimal("0"),
        )

    def check(self):
        if self._spend_visible_today() >= self._settings.max_daily_llm_cost:
            return False, "Daily cap reached (ledger view)"
        return True, None

    def remaining_budget(self):
        remaining = max(Decimal("0"), self._settings.max_daily_llm_cost - self._spend_visible_today())
        return remaining, Decimal("1000")


def test_regression_incident_both_bugs_covered_together():
    """Reproduces the exact combined incident, not each bug in isolation:
    (1) created_at must be real 'now' so a judge_decisions-reading ledger
    can see cost at all (bug 1) — verified directly; (2) even with that
    fixed, a ledger that only ever reads judge_decisions structurally
    under-counts true spend, because the assessment stage's real cost is
    never persisted anywhere (bug 2) — verified by comparing what this
    realistic, judge_decisions-only ledger sees against the run's actual
    total spend, and confirming the run was still correctly bounded by the
    TRUE total (via local tracking), not by the ledger's undercount."""
    assets = _assets()
    end_date = datetime(2026, 3, 1, tzinfo=UTC)
    series_by_symbol = {a.symbol: _synthetic_series(a.symbol, a.id, 90, end_date) for a in assets}

    judge_repo = FakeJudgeDecisionRepoForReplay()
    cap = Decimal("0.6")  # a little more than one day's true combined cost (~0.575*3=1.725 for 3 assets... see below)
    settings = Settings(_env_file=None, max_daily_llm_cost=cap, max_monthly_llm_cost=Decimal("1000"))
    realistic_guard = RealisticLedgerCostGuard(judge_repo, settings)
    symbols = [a.symbol for a in assets]

    service = HistoricalReplayService(
        settings=settings, asset_repo=FakeAssetRepoForReplay(assets), news_repo=FakeNewsRepoForReplay(),
        llm_analysis_repo=FakeAsOfBackendForReplay(), asset_status_repo=FakeAsOfBackendForReplay(),
        signal_source_repo=FakeSignalSourceRepoForReplay(), prompt_template_repo=FakePromptTemplateRepoForReplay(),
        judge_decision_repo=judge_repo, decision_outcome_repo=FakeDecisionOutcomeRepoForReplay(),
        regime_repo=FakeMarketRegimeRepoForReplay(), screened_universe_repo=FakeScreenedUniverseRepoForReplay(),
        cost_guard=realistic_guard,
        assessment_providers=[FakeAssessmentProviderForReplay(symbols)], judge_provider=FakeJudgeProviderForReplay(symbols),
        historical_series_fetcher=lambda asset: series_by_symbol.get(asset.symbol),
        funding_rate_fetcher=lambda asset: [],
    )

    start = end_date - timedelta(days=20)  # simulated dates far from real "now"
    end = end_date - timedelta(days=10)
    result = service.run(start, end)

    # Bug 1, directly verified: every row's created_at is real "now", not a
    # date from the simulated 2026-02 range being replayed.
    real_now = datetime.now(UTC)
    assert all(abs((r.created_at - real_now).total_seconds()) < 60 for r in judge_repo.inserted)
    assert all(r.created_at.year == real_now.year and r.created_at.month == real_now.month for r in judge_repo.inserted)

    # Bug 2, directly verified: the realistic (judge_decisions-only) ledger
    # view under-counts true spend -- it never sees the assessment stage's
    # cost at all, because that's never persisted anywhere.
    true_total_spent = sum(d.cost for d in result.days)
    ledger_visible_spend = realistic_guard._spend_visible_today()
    assert ledger_visible_spend < true_total_spent

    # And yet the run was still correctly bounded by the TRUE total (local
    # tracking), not by what the under-counting ledger alone would have
    # permitted -- it stopped well short of the full 10-day request.
    assert result.stopped_early_reason == "CostGuard cap reached"
    assert len(result.days) < 10
    assert true_total_spent <= cap * 3  # bounded to the same order of magnitude as the cap, not runaway


def test_replay_local_budget_tracking_stops_even_when_db_ledger_is_blind():
    """Regression test for the exact incident this caught live: a CostGuard
    whose DB-backed check() always returns allowed (simulating the bug
    where backfilled rows were invisible to the ledger) must still be
    stopped by the replay's OWN in-process spend tracking against the
    budget that was available when the run started."""
    assets = _assets()
    end_date = datetime(2026, 3, 1, tzinfo=UTC)
    series_by_symbol = {a.symbol: _synthetic_series(a.symbol, a.id, 90, end_date) for a in assets}

    class BlindCostGuard:
        """Always says 'allowed' via check() — but a real remaining budget
        via remaining_budget(), just like CostGuard would report at the
        start of a run before its own spend accumulates invisibly."""

        def check(self):
            return True, None

        def remaining_budget(self):
            # Barely enough for one day's assessment+judge cost (~0.575).
            return Decimal("0.6"), Decimal("100")

    settings = Settings(_env_file=None)
    symbols = [a.symbol for a in assets]
    service = HistoricalReplayService(
        settings=settings, asset_repo=FakeAssetRepoForReplay(assets), news_repo=FakeNewsRepoForReplay(),
        llm_analysis_repo=FakeAsOfBackendForReplay(), asset_status_repo=FakeAsOfBackendForReplay(),
        signal_source_repo=FakeSignalSourceRepoForReplay(), prompt_template_repo=FakePromptTemplateRepoForReplay(),
        judge_decision_repo=FakeJudgeDecisionRepoForReplay(), decision_outcome_repo=FakeDecisionOutcomeRepoForReplay(),
        regime_repo=FakeMarketRegimeRepoForReplay(), screened_universe_repo=FakeScreenedUniverseRepoForReplay(),
        cost_guard=BlindCostGuard(),
        assessment_providers=[FakeAssessmentProviderForReplay(symbols)], judge_provider=FakeJudgeProviderForReplay(symbols),
        historical_series_fetcher=lambda asset: series_by_symbol.get(asset.symbol),
        funding_rate_fetcher=lambda asset: [],
    )

    start = end_date - timedelta(days=10)
    end = end_date - timedelta(days=5)  # 6 days requested
    result = service.run(start, end)

    assert result.stopped_early_reason == "CostGuard cap reached"
    assert len(result.days) < 6  # local tracking cut it off well before the full window


def test_replay_stops_early_when_cost_cap_hit():
    assets = _assets()
    end_date = datetime(2026, 3, 1, tzinfo=UTC)
    series_by_symbol = {a.symbol: _synthetic_series(a.symbol, a.id, 90, end_date) for a in assets}

    class OneShotCostGuard:
        def __init__(self):
            self.calls = 0

        def check(self):
            self.calls += 1
            return (self.calls <= 2), "cap reached"

        def remaining_budget(self):
            return Decimal("100"), Decimal("1000")

    settings = Settings(_env_file=None)
    symbols = [a.symbol for a in assets]
    service = HistoricalReplayService(
        settings=settings, asset_repo=FakeAssetRepoForReplay(assets), news_repo=FakeNewsRepoForReplay(),
        llm_analysis_repo=FakeAsOfBackendForReplay(), asset_status_repo=FakeAsOfBackendForReplay(),
        signal_source_repo=FakeSignalSourceRepoForReplay(), prompt_template_repo=FakePromptTemplateRepoForReplay(),
        judge_decision_repo=FakeJudgeDecisionRepoForReplay(), decision_outcome_repo=FakeDecisionOutcomeRepoForReplay(),
        regime_repo=FakeMarketRegimeRepoForReplay(), screened_universe_repo=FakeScreenedUniverseRepoForReplay(),
        cost_guard=OneShotCostGuard(),
        assessment_providers=[FakeAssessmentProviderForReplay(symbols)], judge_provider=FakeJudgeProviderForReplay(symbols),
        historical_series_fetcher=lambda asset: series_by_symbol.get(asset.symbol),
        funding_rate_fetcher=lambda asset: [],
    )

    start = end_date - timedelta(days=10)
    end = end_date - timedelta(days=5)
    result = service.run(start, end)

    assert result.stopped_early_reason == "CostGuard cap reached"
    assert len(result.days) < 6  # did not run the full window


def test_replay_discloses_unavailable_sources_never_fabricates_them():
    assets = _assets()
    end_date = datetime(2026, 3, 1, tzinfo=UTC)
    series_by_symbol = {a.symbol: _synthetic_series(a.symbol, a.id, 90, end_date) for a in assets}

    captured_prompts = []

    class CapturingJudgeProvider(FakeJudgeProviderForReplay):
        def decide(self, system_prompt, user_prompt):
            captured_prompts.append(user_prompt)
            return super().decide(system_prompt, user_prompt)

    settings = Settings(_env_file=None)
    symbols = [a.symbol for a in assets]
    service = HistoricalReplayService(
        settings=settings, asset_repo=FakeAssetRepoForReplay(assets), news_repo=FakeNewsRepoForReplay(),
        llm_analysis_repo=FakeAsOfBackendForReplay(), asset_status_repo=FakeAsOfBackendForReplay(),
        signal_source_repo=FakeSignalSourceRepoForReplay(), prompt_template_repo=FakePromptTemplateRepoForReplay(),
        judge_decision_repo=FakeJudgeDecisionRepoForReplay(), decision_outcome_repo=FakeDecisionOutcomeRepoForReplay(),
        regime_repo=FakeMarketRegimeRepoForReplay(), screened_universe_repo=FakeScreenedUniverseRepoForReplay(),
        cost_guard=FakeCostGuardForReplay(),
        assessment_providers=[FakeAssessmentProviderForReplay(symbols)], judge_provider=CapturingJudgeProvider(symbols),
        historical_series_fetcher=lambda asset: series_by_symbol.get(asset.symbol),
        funding_rate_fetcher=lambda asset: [],
    )

    start = end_date - timedelta(days=10)
    end = start
    service.run(start, end)

    assert captured_prompts
    for source in EVIDENCE_UNAVAILABLE_FOR_REPLAY:
        assert source in captured_prompts[0]
