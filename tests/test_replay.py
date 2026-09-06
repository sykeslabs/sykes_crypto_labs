from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.benchmarks.historical_factors import HistoricalSeries, compute_point_in_time_factors, pct_change
from app.benchmarks.replay import (
    EVIDENCE_UNAVAILABLE_FOR_REPLAY,
    HistoricalReplayService,
    ReplayResult,
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
    )


def _synthetic_series(symbol, asset_id, n_days, end_date, drift=1.005):
    start = end_date - timedelta(days=n_days - 1)
    dates = _dates(n_days, start)
    closes = [100.0 * (drift**i) for i in range(n_days)]
    volumes = [1000.0] * n_days
    return HistoricalSeries(symbol=symbol, asset_id=asset_id, source="BINANCE", dates=dates, closes=closes, volumes=volumes)


def _make_service(assets, series_by_symbol, judge_repo=None, outcome_repo=None, prompt_repo=None):
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
        cost_guard=FakeCostGuardForReplay(),
        assessment_providers=[FakeAssessmentProviderForReplay(symbols)],
        judge_provider=FakeJudgeProviderForReplay(symbols),
        historical_series_fetcher=series_fetcher,
        funding_rate_fetcher=funding_fetcher,
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
