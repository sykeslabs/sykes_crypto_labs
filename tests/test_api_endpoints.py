from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.auth import verify_api_key
from app.api.dependencies import (
    get_adversarial_repo,
    get_asset_repo,
    get_assessment_repo,
    get_binance_client,
    get_calibration_run_repo,
    get_coinbase_client,
    get_coingecko_client,
    get_cost_ledger_repo,
    get_decision_outcome_repo,
    get_evidence_value_report_repo,
    get_judge_decision_repo,
    get_market_snapshot_repo,
    get_portfolio_allocation_change_repo,
    get_portfolio_position_repo,
    get_prompt_template_repo,
    get_reasoning_audit_repo,
    get_regime_repo,
    get_screened_universe_repo,
    get_settings_dependency,
    get_signal_source_repo,
    get_turnover_cap_event_repo,
)
from app.api.main import app
from app.benchmarks.schemas import (
    CalibrationRunRecord,
    DecisionOutcome,
    EvidenceValueReportRecord,
    JudgeReasoningAuditRecord,
)
from app.config.settings import Settings
from app.database.models import Asset, SignalSource
from app.judge.schemas import JudgeDecisionRecord
from app.llm.adversarial_schemas import AdversarialResearchRecord
from app.llm.assessment_schemas import ModelMarketAssessmentRecord
from app.market_data.screening_schemas import MarketRegimeSnapshot, ScreenedAsset
from app.portfolio.schemas import PortfolioPosition


@pytest.fixture(autouse=True)
def _bypass_auth():
    app.dependency_overrides[verify_api_key] = lambda: None
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _default_prompt_template_repo():
    # Calibration summary's by-prompt-version breakdown resolves each
    # decision's prompt_template_id through this repo -- default to "no
    # templates recorded" so tests that don't care about prompt-version
    # segmentation (prompt_template_id=None on _judge_decision's default)
    # don't need their own fake.
    app.dependency_overrides[get_prompt_template_repo] = lambda: type("R", (), {"get_all": lambda self: {}})()
    yield


@pytest.fixture(autouse=True)
def _default_price_clients():
    # Phase 5b: /portfolio/state now also looks up a stored snapshot and a
    # live Binance/Coinbase price per asset -- default to "nothing found"
    # so tests that don't care about pricing don't need their own fakes.
    app.dependency_overrides[get_market_snapshot_repo] = lambda: type("R", (), {"get_latest_snapshot": lambda self, a: None})()
    app.dependency_overrides[get_binance_client] = lambda: type("C", (), {"fetch_ticker_24hr": lambda self, s: None})()
    app.dependency_overrides[get_coinbase_client] = lambda: type("C", (), {"fetch_ticker": lambda self, s: None})()
    yield


@pytest.fixture
def client():
    return TestClient(app)


def _screened(symbol="BTC", asset_id="a1"):
    return ScreenedAsset(
        run_id="RUN-1", computed_at=datetime.now(UTC), symbol=symbol, coingecko_id=symbol.lower(),
        asset_id=asset_id, composite_factor_score=0.6, volatility_30d=0.02, is_top_candidate=True,
    )


def _judge_decision(decision_id="d1", asset_id="a1", is_backfilled=False, created_at=None):
    return JudgeDecisionRecord(
        id=decision_id, run_id="RUN-1", asset_id=asset_id, created_at=created_at or datetime.now(UTC),
        decision="BUY", confidence=0.6, target_allocation=0.05, expected_return=0.1,
        expected_alpha=0.05, risk_score=0.4, uncertainty=0.3, model_agreement=0.8,
        source_agreement=0.7, investment_horizon_days=30, key_evidence=["e1"],
        contradictory_evidence=[], key_risks=[], invalidation_conditions=[],
        requires_review=False, thesis="A real thesis.", macro_sensitivity="n/a",
        regime_id=None, prompt_template_id=None, estimated_cost=Decimal("0.02"),
        is_backfilled=is_backfilled,
    )


# --- screening -----------------------------------------------------------------

def test_get_candidates(client):
    class FakeRepo:
        def get_latest_top_candidates(self):
            return [_screened("BTC")]

    app.dependency_overrides[get_screened_universe_repo] = lambda: FakeRepo()
    response = client.get("/screening/candidates")
    assert response.status_code == 200
    assert response.json()[0]["symbol"] == "BTC"


def test_get_universe(client):
    class FakeRepo:
        def get_latest_full_universe(self):
            return [_screened("BTC"), _screened("ETH", "a2")]

    app.dependency_overrides[get_screened_universe_repo] = lambda: FakeRepo()
    response = client.get("/screening/universe")
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_get_tracked_assets_sorted_by_symbol(client):
    class FakeAssetRepoForTracked:
        def get_active_assets(self):
            return [
                Asset(id="a2", symbol="SOL", name="SOL", coingecko_id="sol", active=True, in_asset=True, created_at=datetime.now(UTC)),
                Asset(id="a1", symbol="BTC", name="BTC", coingecko_id="btc", active=True, in_asset=True, created_at=datetime.now(UTC)),
            ]

    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepoForTracked()
    response = client.get("/screening/tracked")
    assert response.status_code == 200
    assert [a["symbol"] for a in response.json()] == ["BTC", "SOL"]


# --- Phase 5b (addendum): live factor recompute -------------------------------

def test_get_live_factors_computes_from_live_data(client):
    class FakeScreenedRepo:
        def get_latest_for_symbol(self, symbol):
            assert symbol == "SOL"
            return _screened("SOL", asset_id="a1")  # coingecko_id="sol" per _screened()

    class FakeCoinGeckoWithMarkets:
        def fetch_markets(self, ids):
            assert set(ids) == {"sol", "bitcoin"}
            return {
                "sol": {"price_change_percentage_30d_in_currency": 10.0, "price_change_percentage_7d_in_currency": 2.0, "total_volume": 5_000_000.0},
                "bitcoin": {"price_change_percentage_30d_in_currency": 4.0},
            }

    class FakeBinanceWithOhlcv:
        def fetch_daily_ohlcv(self, symbol, days):
            assert symbol == "SOL"
            return [(100.0, 1.0), (105.0, 1.0), (98.0, 1.0)]

    app.dependency_overrides[get_screened_universe_repo] = lambda: FakeScreenedRepo()
    app.dependency_overrides[get_coingecko_client] = lambda: FakeCoinGeckoWithMarkets()
    app.dependency_overrides[get_binance_client] = lambda: FakeBinanceWithOhlcv()
    response = client.get("/screening/live-factors/SOL")
    assert response.status_code == 200
    body = response.json()
    assert body["momentum_30d"] == pytest.approx(10.0)
    assert body["momentum_7d"] == pytest.approx(2.0)
    assert body["relative_strength_30d"] == pytest.approx(6.0)  # 10.0 - 4.0
    assert body["volatility_drawdown_source"] == "BINANCE"
    assert body["volatility_30d"] is not None
    assert body["drawdown_30d"] is not None


def test_get_live_factors_falls_back_to_coinbase(client):
    class FakeScreenedRepo:
        def get_latest_for_symbol(self, symbol):
            return _screened("SOL", asset_id="a1")

    class FakeCoinGeckoEmpty:
        def fetch_markets(self, ids):
            return {}

    class FakeBinanceNoListing:
        def fetch_daily_ohlcv(self, symbol, days):
            return None

    class FakeCoinbaseWithOhlcv:
        def fetch_daily_ohlcv(self, symbol, days):
            return [(100.0, 1.0), (110.0, 1.0)]

    app.dependency_overrides[get_screened_universe_repo] = lambda: FakeScreenedRepo()
    app.dependency_overrides[get_coingecko_client] = lambda: FakeCoinGeckoEmpty()
    app.dependency_overrides[get_binance_client] = lambda: FakeBinanceNoListing()
    app.dependency_overrides[get_coinbase_client] = lambda: FakeCoinbaseWithOhlcv()
    response = client.get("/screening/live-factors/SOL")
    assert response.status_code == 200
    assert response.json()["volatility_drawdown_source"] == "COINBASE"


def test_get_live_factors_404s_for_a_symbol_never_screened(client):
    class FakeScreenedRepoEmpty:
        def get_latest_for_symbol(self, symbol):
            return None

    app.dependency_overrides[get_screened_universe_repo] = lambda: FakeScreenedRepoEmpty()
    response = client.get("/screening/live-factors/NOTREAL")
    assert response.status_code == 404


def test_get_regime_returns_null_when_none_computed(client):
    class FakeRepo:
        def get_latest(self):
            return None

    app.dependency_overrides[get_regime_repo] = lambda: FakeRepo()
    response = client.get("/screening/regime")
    assert response.status_code == 200
    assert response.json() is None


def test_get_regime_returns_real_snapshot(client):
    class FakeRepo:
        def get_latest(self):
            return MarketRegimeSnapshot(id="r1", run_id="RUN-1", computed_at=datetime.now(UTC), regime="RISK_ON", inputs={})

    app.dependency_overrides[get_regime_repo] = lambda: FakeRepo()
    response = client.get("/screening/regime")
    assert response.json()["regime"] == "RISK_ON"


# --- assessments -----------------------------------------------------------------

def test_get_latest_assessments(client):
    record = ModelMarketAssessmentRecord(
        run_id="RUN-1", asset_id="a1", provider="claude", model="m", prompt_template_id="p",
        assessment_timestamp=datetime.now(UTC), data_cutoff_timestamp=datetime.now(UTC),
        short_term_direction="BULLISH", medium_term_direction="BULLISH", long_term_direction="NEUTRAL",
        short_term_confidence=0.6, medium_term_confidence=0.5, long_term_confidence=0.4,
        expected_return_7d=0.03, expected_return_30d=0.05, expected_return_90d=0.08,
        risk_score=0.4, risk_level="MEDIUM", market_regime="RISK_ON", model_agreement=1.0,
        overall_assessment="BULLISH", thesis="t", key_drivers=[], key_risks=[],
        source_assessment=[], invalidation_conditions=[], raw_response=None, estimated_cost=Decimal("0.01"),
    )

    class FakeRepo:
        def get_latest_run_assessments(self):
            return [record]

    app.dependency_overrides[get_assessment_repo] = lambda: FakeRepo()
    response = client.get("/assessments/latest")
    assert response.status_code == 200
    assert response.json()[0]["provider"] == "claude"


def test_get_recent_research(client):
    from app.api.dependencies import get_llm_analysis_repo
    from app.llm.schemas import LLMAnalysisRecord

    record = LLMAnalysisRecord(
        run_id="RUN-1", asset_id="a1", provider="claude", model="m", prompt_version="1.0",
        timestamp=datetime.now(UTC), input_hash="h", response={}, action="BUY", confidence=0.6,
        target_allocation=0.05, investment_horizon="medium", bull_case="b", bear_case="b",
        catalysts=[], risks=[], invalidation_conditions=[], token_usage=None, estimated_cost=Decimal("0.01"),
    )

    class FakeRepo:
        def get_recent(self, limit=None):
            return [record]

    app.dependency_overrides[get_llm_analysis_repo] = lambda: FakeRepo()
    response = client.get("/assessments/research/recent")
    assert response.status_code == 200
    assert response.json()[0]["provider"] == "claude"


def test_get_adversarial_research_for_asset_null_when_none(client):
    class FakeRepo:
        def get_latest_by_asset(self, asset_id):
            return None

    app.dependency_overrides[get_adversarial_repo] = lambda: FakeRepo()
    response = client.get("/assessments/adversarial/asset/a1")
    assert response.status_code == 200
    assert response.json() is None


# --- judge -----------------------------------------------------------------

def test_get_recent_decisions(client):
    asset = Asset(id="a1", symbol="BTC", name="Bitcoin", coingecko_id="bitcoin", active=True, in_asset=True, created_at=datetime.now(UTC))

    class FakeRepo:
        def get_recent(self, limit=50, is_backfilled=None):
            return [_judge_decision()]

    app.dependency_overrides[get_judge_decision_repo] = lambda: FakeRepo()
    app.dependency_overrides[get_asset_repo] = lambda: type("R", (), {"get_active_assets": lambda self: [asset]})()
    response = client.get("/judge/decisions/recent")
    assert response.status_code == 200
    entry = response.json()[0]
    # Phase 5b: asset_id is a raw UUID on the record itself -- symbol is the real join
    assert entry["symbol"] == "BTC"
    assert entry["decision"]["thesis"] == "A real thesis."


def test_get_decision_by_id_404_when_not_found(client):
    class FakeRepo:
        def get_by_id(self, decision_id):
            return None

    app.dependency_overrides[get_judge_decision_repo] = lambda: FakeRepo()
    response = client.get("/judge/decisions/nonexistent")
    assert response.status_code == 404


def test_get_decision_by_id_found(client):
    class FakeRepo:
        def get_by_id(self, decision_id):
            return _judge_decision(decision_id=decision_id)

    app.dependency_overrides[get_judge_decision_repo] = lambda: FakeRepo()
    response = client.get("/judge/decisions/d1")
    assert response.status_code == 200
    assert response.json()["id"] == "d1"


def test_get_reasoning_audits_for_decision(client):
    audit = JudgeReasoningAuditRecord(
        run_at=datetime.now(UTC), decision_id="d1", audit_model="m", supported=False,
        unsupported_claims=["claim x"], notes="n", estimated_cost=Decimal("0.001"), created_at=datetime.now(UTC),
    )

    class FakeRepo:
        def get_by_decision_id(self, decision_id):
            return [audit]

    app.dependency_overrides[get_reasoning_audit_repo] = lambda: FakeRepo()
    response = client.get("/judge/reasoning-audits/decision/d1")
    assert response.status_code == 200
    assert response.json()[0]["supported"] is False


# --- portfolio -----------------------------------------------------------------

def test_get_portfolio_state_joins_position_with_outcome(client):
    asset = Asset(id="a1", symbol="BTC", name="Bitcoin", coingecko_id="bitcoin", active=True, in_asset=True, created_at=datetime.now(UTC))
    position = PortfolioPosition(asset_id="a1", current_allocation=0.05, last_decision_id="d1", updated_at=datetime.now(UTC))
    outcome = DecisionOutcome(
        decision_id="d1", asset_id="a1", decision_timestamp=datetime.now(UTC), horizon_days=30,
        target_return=0.1, stop_return=-0.1, realized_return=0.05, realized_return_net_of_costs=0.048,
        assumed_fill_method="VOLATILITY_SCALED_ESTIMATE", outcome_label="HIT_TARGET",
        judge_confidence=0.6, is_backfilled=False, regime_at_decision="r1",
    )

    class FakeAssetRepo:
        def get_active_assets(self):
            return [asset]

    class FakePositionRepo:
        def get_all(self):
            return {"a1": position}

    class FakeOutcomeRepo:
        def get_by_decision_id(self, decision_id):
            return outcome

    class FakeRegimeRepo:
        def get_by_id(self, regime_id):
            assert regime_id == "r1"
            return type("Snapshot", (), {"regime": "RISK_ON"})()

    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo()
    app.dependency_overrides[get_portfolio_position_repo] = lambda: FakePositionRepo()
    app.dependency_overrides[get_decision_outcome_repo] = lambda: FakeOutcomeRepo()
    app.dependency_overrides[get_regime_repo] = lambda: FakeRegimeRepo()
    response = client.get("/portfolio/state")
    assert response.status_code == 200
    entry = response.json()[0]
    assert entry["symbol"] == "BTC"
    assert entry["outcome"]["assumed_fill_method"] == "VOLATILITY_SCALED_ESTIMATE"
    assert entry["outcome"]["realized_return_net_of_costs"] == pytest.approx(0.048)
    # Phase 5b: regime_at_decision is a raw snapshot id ("r1" here), never
    # the human-readable label directly -- regime_label is the real join.
    assert entry["outcome"]["regime_at_decision"] == "r1"
    assert entry["regime_label"] == "RISK_ON"


def test_get_portfolio_state_includes_stored_and_live_price(client):
    asset = Asset(id="a1", symbol="BTC", name="Bitcoin", coingecko_id="bitcoin", active=True, in_asset=True, created_at=datetime.now(UTC))
    position = PortfolioPosition(asset_id="a1", current_allocation=0.05, last_decision_id=None, updated_at=datetime.now(UTC))

    class FakeSnapshotRepo:
        def get_latest_snapshot(self, asset_id):
            return type("Snapshot", (), {"price": Decimal("79910"), "timestamp": datetime.now(UTC)})()

    class FakeBinanceWithTicker:
        def fetch_ticker_24hr(self, symbol):
            return {"lastPrice": "80000.00", "closeTime": 1700000000000}

    app.dependency_overrides[get_asset_repo] = lambda: type("R", (), {"get_active_assets": lambda self: [asset]})()
    app.dependency_overrides[get_portfolio_position_repo] = lambda: type("R", (), {"get_all": lambda self: {"a1": position}})()
    app.dependency_overrides[get_decision_outcome_repo] = lambda: type("R", (), {"get_by_decision_id": lambda self, d: None})()
    app.dependency_overrides[get_market_snapshot_repo] = lambda: FakeSnapshotRepo()
    app.dependency_overrides[get_binance_client] = lambda: FakeBinanceWithTicker()
    response = client.get("/portfolio/state")
    assert response.status_code == 200
    entry = response.json()[0]
    # Stored (last-collected) price stays separate from the live spot price
    assert entry["price_usd"] == pytest.approx(79910.0)
    assert entry["price_as_of"] is not None
    assert entry["live_price_usd"] == pytest.approx(80000.0)
    assert entry["live_price_source"] == "binance"


def test_get_portfolio_state_omits_zero_allocation_positions(client):
    asset = Asset(id="a1", symbol="BTC", name="Bitcoin", coingecko_id="bitcoin", active=True, in_asset=True, created_at=datetime.now(UTC))
    position = PortfolioPosition(asset_id="a1", current_allocation=0.0, last_decision_id=None, updated_at=None)

    app.dependency_overrides[get_asset_repo] = lambda: type("R", (), {"get_active_assets": lambda self: [asset]})()
    app.dependency_overrides[get_portfolio_position_repo] = lambda: type("R", (), {"get_all": lambda self: {"a1": position}})()
    app.dependency_overrides[get_decision_outcome_repo] = lambda: type("R", (), {"get_by_decision_id": lambda self, d: None})()
    app.dependency_overrides[get_regime_repo] = lambda: type("R", (), {"get_by_id": lambda self, r: None})()
    response = client.get("/portfolio/state")
    assert response.json() == []


def test_get_portfolio_state_regime_label_none_when_regime_at_decision_is_null(client):
    # The real, documented persistence gap (3e.1's replay never saved a
    # regime row) -- regime_label must stay None, never a guessed value.
    asset = Asset(id="a1", symbol="BTC", name="Bitcoin", coingecko_id="bitcoin", active=True, in_asset=True, created_at=datetime.now(UTC))
    position = PortfolioPosition(asset_id="a1", current_allocation=0.05, last_decision_id="d1", updated_at=datetime.now(UTC))
    outcome = DecisionOutcome(
        decision_id="d1", asset_id="a1", decision_timestamp=datetime.now(UTC), horizon_days=30,
        target_return=0.1, stop_return=-0.1, realized_return=None, realized_return_net_of_costs=None,
        assumed_fill_method=None, outcome_label="UNRESOLVED",
        judge_confidence=0.6, is_backfilled=True, regime_at_decision=None,
    )

    app.dependency_overrides[get_asset_repo] = lambda: type("R", (), {"get_active_assets": lambda self: [asset]})()
    app.dependency_overrides[get_portfolio_position_repo] = lambda: type("R", (), {"get_all": lambda self: {"a1": position}})()
    app.dependency_overrides[get_decision_outcome_repo] = lambda: type("R", (), {"get_by_decision_id": lambda self, d: outcome})()
    app.dependency_overrides[get_regime_repo] = lambda: type("R", (), {"get_by_id": lambda self, r: (_ for _ in ()).throw(AssertionError("should not be called"))})()
    response = client.get("/portfolio/state")
    assert response.status_code == 200
    assert response.json()[0]["regime_label"] is None


def test_get_recent_turnover_cap_events(client):
    from app.portfolio.schemas import TurnoverCapEvent

    event = TurnoverCapEvent(
        run_id="RUN-1", occurred_at=datetime.now(UTC), turnover_used_this_week=0.30000000000000004,
        max_weekly_turnover=0.3, remaining_budget=0.0, fully_blocked=True, capped_symbols=["ETH", "NEAR", "SOL"],
    )

    class FakeTurnoverCapEventRepo:
        def get_recent(self, limit=20):
            return [event]

    app.dependency_overrides[get_turnover_cap_event_repo] = lambda: FakeTurnoverCapEventRepo()
    response = client.get("/portfolio/turnover-cap-events/recent")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["fully_blocked"] is True
    assert body[0]["capped_symbols"] == ["ETH", "NEAR", "SOL"]


def test_get_recent_allocation_changes(client):
    from app.portfolio.schemas import PortfolioAllocationChange

    change = PortfolioAllocationChange(
        asset_id="a1", run_id="RUN-1", decision_id="d1", previous_allocation=0.1,
        new_allocation=0.25, actual_allocation_before=0.33, baseline_semantics="system_target",
        changed_at=datetime.now(UTC),
    )

    class FakePortfolioAllocationChangeRepo:
        def get_recent(self, limit=50):
            return [change]

    app.dependency_overrides[get_portfolio_allocation_change_repo] = lambda: FakePortfolioAllocationChangeRepo()
    response = client.get("/portfolio/allocation-changes/recent")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["previous_allocation"] == 0.1
    assert body[0]["new_allocation"] == 0.25
    assert body[0]["baseline_semantics"] == "system_target"


# --- calibration -----------------------------------------------------------------

def test_get_calibration_summary_reports_null_when_no_directional_data(client):
    class FakeOutcomeRepo:
        def get_recent(self, limit=2000, is_backfilled=None):
            return []

    class FakeJudgeRepo:
        def get_by_id(self, decision_id):
            return None

        def get_recent(self, limit=2000, is_backfilled=None):
            return []

    app.dependency_overrides[get_decision_outcome_repo] = lambda: FakeOutcomeRepo()
    app.dependency_overrides[get_judge_decision_repo] = lambda: FakeJudgeRepo()
    response = client.get("/calibration/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["hit_rate"] is None
    assert body["directional_sample_size"] == 0
    assert "not computable" in body["by_regime_note"].lower()
    assert body["hit_rate_backfilled"] is None
    assert body["hit_rate_live"] is None
    assert body["by_prompt_version"] == []
    assert "no live" in body["held_out_window_note"].lower()
    assert body["embargo_gap_days"] is None
    assert body["pct_live_within_own_horizon_of_training_end"] is None
    assert body["excluded_duplicate_group_decision_count"] == 0


def test_get_calibration_summary_computes_real_hit_rate_from_directional_decisions(client):
    outcome_correct = DecisionOutcome(
        decision_id="d1", asset_id="a1", decision_timestamp=datetime.now(UTC), horizon_days=30,
        target_return=0.1, stop_return=-0.1, realized_return=0.05, outcome_label="HIT_TARGET",
        judge_confidence=0.6, is_backfilled=True,
    )
    outcome_wrong = DecisionOutcome(
        decision_id="d2", asset_id="a1", decision_timestamp=datetime.now(UTC), horizon_days=30,
        target_return=0.1, stop_return=-0.1, realized_return=-0.03, outcome_label="HIT_STOP",
        judge_confidence=0.6, is_backfilled=True,
    )
    # Both backfilled -- is_backfilled=True on the decision too (matches
    # real production data, where an outcome and its own decision are
    # always tagged together), so B2's live-only duplicate-group check
    # never considers these two at all.
    decisions = {
        "d1": _judge_decision("d1", is_backfilled=True),
        "d2": _judge_decision("d2", is_backfilled=True),
    }

    class FakeOutcomeRepo:
        def get_recent(self, limit=2000, is_backfilled=None):
            return [outcome_correct, outcome_wrong]

    class FakeJudgeRepo:
        def get_by_id(self, decision_id):
            return decisions.get(decision_id)

        def get_recent(self, limit=2000, is_backfilled=None):
            values = decisions.values()
            if is_backfilled is not None:
                values = [d for d in values if d.is_backfilled == is_backfilled]
            return list(values)

    app.dependency_overrides[get_decision_outcome_repo] = lambda: FakeOutcomeRepo()
    app.dependency_overrides[get_judge_decision_repo] = lambda: FakeJudgeRepo()
    response = client.get("/calibration/summary")
    body = response.json()
    # Both are BUY decisions: d1 correct (positive return), d2 wrong (negative).
    assert body["directional_sample_size"] == 2
    assert body["hit_rate"] == pytest.approx(0.5)
    assert body["resolved_backfilled_count"] == 2
    assert body["excluded_duplicate_group_decision_count"] == 0
    # Both outcomes are backfilled -- the combined figure above should
    # exactly match the backfilled-only figure, and live should be empty,
    # not silently blended.
    assert body["directional_sample_size_backfilled"] == 2
    assert body["hit_rate_backfilled"] == pytest.approx(0.5)
    assert body["directional_sample_size_live"] == 0
    assert body["hit_rate_live"] is None


def test_get_calibration_summary_requests_the_complete_population_not_capped_at_2000(client):
    # 2026-09-27 final fix: this endpoint's own DecisionOutcome retrieval
    # was the one remaining consumer still hardcoded to limit=2000 after
    # the earlier batched migration (Phase 5q-5t). Proves BOTH that the
    # endpoint now requests limit=None, and that a population past the
    # old 2000 ceiling is genuinely processed in full -- not merely that
    # the mocked method was called with the right argument.
    n = 2005
    outcomes = [
        DecisionOutcome(
            decision_id=f"d-{i}", asset_id=f"a-{i}", decision_timestamp=datetime.now(UTC), horizon_days=30,
            target_return=0.1, stop_return=-0.1, realized_return=0.05, outcome_label="HIT_TARGET",
            judge_confidence=0.6, is_backfilled=True,
        )
        for i in range(n)
    ]
    decisions = {f"d-{i}": _judge_decision(f"d-{i}", asset_id=f"a-{i}", is_backfilled=True) for i in range(n)}

    class FakeOutcomeRepo:
        def __init__(self):
            self.calls = []

        def get_recent(self, limit=2000, is_backfilled=None):
            self.calls.append(limit)
            return outcomes

    class FakeJudgeRepo:
        def get_by_id(self, decision_id):
            return decisions.get(decision_id)

        def get_recent(self, limit=2000, is_backfilled=None):
            values = decisions.values()
            if is_backfilled is not None:
                values = [d for d in values if d.is_backfilled == is_backfilled]
            return list(values)

    outcome_repo = FakeOutcomeRepo()
    app.dependency_overrides[get_decision_outcome_repo] = lambda: outcome_repo
    app.dependency_overrides[get_judge_decision_repo] = lambda: FakeJudgeRepo()
    response = client.get("/calibration/summary")
    body = response.json()

    assert outcome_repo.calls == [None]  # limit=None, not the old hardcoded 2000
    # Every one of the 2005 real, resolved, directional (BUY, correct)
    # decisions must be counted -- if the old limit=2000 ceiling were still
    # in effect, this would silently cap at 2000.
    assert body["resolved_backfilled_count"] == n
    assert body["directional_sample_size"] == n
    assert body["hit_rate"] == pytest.approx(1.0)


def test_get_calibration_summary_segments_backfilled_and_live_and_by_prompt_version(client):
    outcome_backfilled = DecisionOutcome(
        decision_id="d1", asset_id="a1", decision_timestamp=datetime.now(UTC), horizon_days=30,
        target_return=0.1, stop_return=-0.1, realized_return=0.05, outcome_label="HIT_TARGET",
        judge_confidence=0.6, is_backfilled=True,
    )
    outcome_live = DecisionOutcome(
        decision_id="d2", asset_id="a1", decision_timestamp=datetime.now(UTC), horizon_days=30,
        target_return=0.1, stop_return=-0.1, realized_return=-0.03, outcome_label="HIT_STOP",
        judge_confidence=0.6, is_backfilled=False,
    )
    decision_backfilled = _judge_decision("d1", is_backfilled=True)
    decision_backfilled.prompt_template_id = "tmpl-v1"
    decision_live = _judge_decision("d2", is_backfilled=False)
    decision_live.prompt_template_id = "tmpl-v2"
    decisions = {"d1": decision_backfilled, "d2": decision_live}

    class FakeOutcomeRepo:
        def get_recent(self, limit=2000, is_backfilled=None):
            return [outcome_backfilled, outcome_live]

    class FakeJudgeRepo:
        def get_by_id(self, decision_id):
            return decisions.get(decision_id)

        def get_recent(self, limit=2000, is_backfilled=None):
            values = decisions.values()
            if is_backfilled is not None:
                values = [d for d in values if d.is_backfilled == is_backfilled]
            return list(values)

    class FakePromptTemplateRepo:
        def get_all(self):
            return {"tmpl-v1": {"id": "tmpl-v1", "version": "v1"}, "tmpl-v2": {"id": "tmpl-v2", "version": "v2"}}

    app.dependency_overrides[get_decision_outcome_repo] = lambda: FakeOutcomeRepo()
    app.dependency_overrides[get_judge_decision_repo] = lambda: FakeJudgeRepo()
    app.dependency_overrides[get_prompt_template_repo] = lambda: FakePromptTemplateRepo()
    response = client.get("/calibration/summary")
    body = response.json()

    # Combined pools both (1 correct, 1 wrong); backfilled/live each isolate
    # their own single decision instead of being blended into one figure.
    assert body["directional_sample_size"] == 2
    assert body["hit_rate"] == pytest.approx(0.5)
    assert body["directional_sample_size_backfilled"] == 1
    assert body["hit_rate_backfilled"] == pytest.approx(1.0)
    assert body["directional_sample_size_live"] == 1
    assert body["hit_rate_live"] == pytest.approx(0.0)
    # A single live decision for asset a1 today -- not a duplicate group.
    assert body["excluded_duplicate_group_decision_count"] == 0

    # By-prompt-version breakdown surfaces both real versions separately.
    versions = {b["version"]: b for b in body["by_prompt_version"]}
    assert set(versions) == {"v1", "v2"}
    assert versions["v1"]["resolved_count"] == 1
    assert versions["v2"]["resolved_count"] == 1

    # A resolved live decision now exists -- the note must say so, not
    # claim (falsely) that every live decision is still unresolved.
    assert "1 of 1 live" in body["held_out_window_note"]
    assert "no meaningful embargo" in body["held_out_window_note"].lower()

    # Both decision_timestamps were captured moments apart in this same test
    # (backfilled first, then live) -- a real, tiny, non-negative gap, not a
    # negative/overlapping one (see the dedicated overlap test below for that).
    assert body["embargo_gap_days"] == pytest.approx(0.0, abs=0.01)
    # The live decision's timestamp is a fraction of a second after the
    # backfilled one, well within its own 30-day horizon.
    assert body["pct_live_within_own_horizon_of_training_end"] == pytest.approx(1.0)


def test_get_calibration_summary_computes_negative_embargo_gap_when_windows_overlap(client):
    training_end = datetime(2026, 6, 1, tzinfo=UTC)
    holdout_start = datetime(2026, 5, 27, tzinfo=UTC)  # 5 real days BEFORE training_end -- overlap, not embargo
    outcome_backfilled = DecisionOutcome(
        decision_id="d1", asset_id="a1", decision_timestamp=training_end, horizon_days=30,
        target_return=0.1, stop_return=-0.1, realized_return=0.05, outcome_label="HIT_TARGET",
        judge_confidence=0.6, is_backfilled=True,
    )
    outcome_live = DecisionOutcome(
        decision_id="d2", asset_id="a1", decision_timestamp=holdout_start, horizon_days=30,
        target_return=0.1, stop_return=-0.1, realized_return=-0.03, outcome_label="HIT_STOP",
        judge_confidence=0.6, is_backfilled=False,
    )
    decisions = {
        "d1": _judge_decision("d1", is_backfilled=True, created_at=training_end),
        "d2": _judge_decision("d2", is_backfilled=False, created_at=holdout_start),
    }

    class FakeOutcomeRepo:
        def get_recent(self, limit=2000, is_backfilled=None):
            return [outcome_backfilled, outcome_live]

    class FakeJudgeRepo:
        def get_by_id(self, decision_id):
            return decisions.get(decision_id)

        def get_recent(self, limit=2000, is_backfilled=None):
            values = decisions.values()
            if is_backfilled is not None:
                values = [d for d in values if d.is_backfilled == is_backfilled]
            return list(values)

    app.dependency_overrides[get_decision_outcome_repo] = lambda: FakeOutcomeRepo()
    app.dependency_overrides[get_judge_decision_repo] = lambda: FakeJudgeRepo()
    response = client.get("/calibration/summary")
    body = response.json()

    assert body["embargo_gap_days"] == pytest.approx(-5.0)
    assert body["excluded_duplicate_group_decision_count"] == 0
    # holdout_start is BEFORE training_end, so the live decision is well
    # within its own 30-day horizon of the training-window boundary.
    assert body["pct_live_within_own_horizon_of_training_end"] == pytest.approx(1.0)
    assert "overlap" in body["held_out_window_note"].lower()


# --- B2: same-day duplicate live Judge decisions excluded from calibration ---

def test_excluded_duplicate_group_decision_count_has_a_self_documenting_openapi_description():
    # Issue 2 fix (2026-09-16): the field's meaning must be discoverable
    # from the OpenAPI/Pydantic schema itself, not only from a Python
    # source comment invisible to real API consumers.
    from app.api.schemas import CalibrationSummary

    schema = CalibrationSummary.model_json_schema()
    field = schema["properties"]["excluded_duplicate_group_decision_count"]

    assert field["type"] == "integer"
    description = field.get("description")
    assert description  # non-empty
    # Must make clear this counts decision ROWS, not groups.
    assert "row" in description.lower()
    assert "group" in description.lower()


def _fake_judge_repo(decisions: dict):
    class FakeJudgeRepo:
        def get_by_id(self, decision_id):
            return decisions.get(decision_id)

        def get_recent(self, limit=2000, is_backfilled=None):
            values = decisions.values()
            if is_backfilled is not None:
                values = [d for d in values if d.is_backfilled == is_backfilled]
            return list(values)

    return FakeJudgeRepo()


def test_calibration_excludes_entire_live_duplicate_group_end_to_end(client):
    # Real B2 scenario: BTC has 3 live decisions the same UTC day (only 1
    # resolved, the other 2 still pending) -- all 3 must be excluded from
    # every directional/calibration figure, but the raw resolved/unresolved
    # AUDIT counts (a distinct, deliberately unfiltered statistic) still
    # reflect every real decision_outcomes row that exists.
    day = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
    btc_outcome_resolved = DecisionOutcome(
        decision_id="btc-1", asset_id="btc-id", decision_timestamp=day, horizon_days=30,
        target_return=0.1, stop_return=-0.1, realized_return=0.05, outcome_label="HIT_TARGET",
        judge_confidence=0.6, is_backfilled=False,
    )
    btc_outcome_unresolved_a = DecisionOutcome(
        decision_id="btc-2", asset_id="btc-id", decision_timestamp=day.replace(hour=11), horizon_days=30,
        target_return=0.1, stop_return=-0.1, realized_return=None, outcome_label="UNRESOLVED",
        judge_confidence=0.6, is_backfilled=False,
    )
    # ETH: a single, non-duplicate live decision, resolved and directionally correct.
    eth_outcome = DecisionOutcome(
        decision_id="eth-1", asset_id="eth-id", decision_timestamp=day, horizon_days=30,
        target_return=0.1, stop_return=-0.1, realized_return=0.02, outcome_label="HIT_TARGET",
        judge_confidence=0.6, is_backfilled=False,
    )
    decisions = {
        "btc-1": _judge_decision("btc-1", asset_id="btc-id", is_backfilled=False, created_at=day),
        "btc-2": _judge_decision("btc-2", asset_id="btc-id", is_backfilled=False, created_at=day.replace(hour=11)),
        "eth-1": _judge_decision("eth-1", asset_id="eth-id", is_backfilled=False, created_at=day),
    }
    # btc-3: the third member of BTC's duplicate group has no decision_outcomes
    # row loaded here (mirrors get_recent's real scope over judge_decisions,
    # independent of outcome resolution) -- group membership must still be
    # detected correctly since it comes from ALL live decisions, not just
    # resolved ones.
    decisions["btc-3"] = _judge_decision("btc-3", asset_id="btc-id", is_backfilled=False, created_at=day.replace(hour=12))

    class FakeOutcomeRepo:
        def get_recent(self, limit=2000, is_backfilled=None):
            return [btc_outcome_resolved, btc_outcome_unresolved_a, eth_outcome]

    app.dependency_overrides[get_decision_outcome_repo] = lambda: FakeOutcomeRepo()
    app.dependency_overrides[get_judge_decision_repo] = lambda: _fake_judge_repo(decisions)
    response = client.get("/calibration/summary")
    body = response.json()

    # ETH is the only real directional observation left -- BTC's resolved
    # decision (btc-1) is excluded entirely despite being real, resolved,
    # and directionally correct, because it belongs to a 3-member same-day
    # duplicate group.
    assert body["directional_sample_size_live"] == 1
    assert body["hit_rate_live"] == pytest.approx(1.0)
    assert body["excluded_duplicate_group_decision_count"] == 3

    # Raw audit counts are UNCHANGED -- they still reflect every real
    # decision_outcomes row (btc-1 resolved, btc-2 unresolved, eth-1
    # resolved), regardless of duplicate-group membership.
    assert body["resolved_live_count"] == 2
    assert body["unresolved_live_count"] == 1


def test_calibration_duplicate_exclusion_is_stable_after_the_remaining_row_resolves(client):
    # Same BTC group as above, but now ALL THREE have resolved. The excluded
    # set must be identical to when only one had resolved -- membership
    # depends only on judge_decisions (asset/day/is_backfilled), never on
    # decision_outcomes' resolution status.
    day = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
    outcomes = [
        DecisionOutcome(
            decision_id=f"btc-{i}", asset_id="btc-id", decision_timestamp=day.replace(hour=10 + i),
            horizon_days=30, target_return=0.1, stop_return=-0.1, realized_return=0.05,
            outcome_label="HIT_TARGET", judge_confidence=0.6, is_backfilled=False,
        )
        for i in range(1, 4)
    ]
    decisions = {
        f"btc-{i}": _judge_decision(f"btc-{i}", asset_id="btc-id", is_backfilled=False, created_at=day.replace(hour=10 + i))
        for i in range(1, 4)
    }

    class FakeOutcomeRepo:
        def get_recent(self, limit=2000, is_backfilled=None):
            return outcomes

    app.dependency_overrides[get_decision_outcome_repo] = lambda: FakeOutcomeRepo()
    app.dependency_overrides[get_judge_decision_repo] = lambda: _fake_judge_repo(decisions)
    response = client.get("/calibration/summary")
    body = response.json()

    assert body["directional_sample_size_live"] == 0  # all 3 still excluded, now that all 3 resolved
    assert body["excluded_duplicate_group_decision_count"] == 3
    assert body["resolved_live_count"] == 3  # raw audit count reflects all 3 real resolved rows
    assert body["unresolved_live_count"] == 0


def test_calibration_duplicate_exclusion_applies_before_directional_type_filtering(client):
    # A same-day duplicate pair where one decision is WATCH (never
    # directional anyway) and the other is a real resolved BUY -- confirms
    # the B2 filter and the pre-existing BUY/SELL filter compose correctly:
    # the BUY sibling is excluded via duplicate-group membership, and WATCH
    # was never going to count regardless. Neither becomes a directional
    # observation, for two independent, correct reasons.
    day = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
    watch_outcome = DecisionOutcome(
        decision_id="d1", asset_id="btc-id", decision_timestamp=day, horizon_days=30,
        target_return=0.1, stop_return=-0.1, realized_return=None, outcome_label="UNRESOLVED",
        judge_confidence=0.5, is_backfilled=False,
    )
    buy_outcome = DecisionOutcome(
        decision_id="d2", asset_id="btc-id", decision_timestamp=day.replace(hour=11), horizon_days=30,
        target_return=0.1, stop_return=-0.1, realized_return=0.05, outcome_label="HIT_TARGET",
        judge_confidence=0.6, is_backfilled=False,
    )
    watch_decision = _judge_decision("d1", asset_id="btc-id", is_backfilled=False, created_at=day)
    watch_decision.decision = "WATCH"
    decisions = {
        "d1": watch_decision,
        "d2": _judge_decision("d2", asset_id="btc-id", is_backfilled=False, created_at=day.replace(hour=11)),
    }

    class FakeOutcomeRepo:
        def get_recent(self, limit=2000, is_backfilled=None):
            return [watch_outcome, buy_outcome]

    app.dependency_overrides[get_decision_outcome_repo] = lambda: FakeOutcomeRepo()
    app.dependency_overrides[get_judge_decision_repo] = lambda: _fake_judge_repo(decisions)
    response = client.get("/calibration/summary")
    body = response.json()

    assert body["directional_sample_size_live"] == 0
    assert body["excluded_duplicate_group_decision_count"] == 2
    assert body["resolved_live_count"] == 1  # d2's real resolved row is still counted in the raw audit total
    assert body["unresolved_live_count"] == 1


def test_get_recent_calibration_runs(client):
    record = CalibrationRunRecord(run_at=datetime.now(UTC), method="TEST_METHOD", sample_size=10, hit_rate=0.5, brier_score=0.2)

    class FakeRepo:
        def get_recent(self, limit=50):
            return [record]

    app.dependency_overrides[get_calibration_run_repo] = lambda: FakeRepo()
    response = client.get("/calibration/runs/recent")
    assert response.json()[0]["method"] == "TEST_METHOD"


def test_get_recent_outcomes_default_permits_complete_retrieval(client):
    # 2026-09-27 follow-up: the route's own default changed from a bounded
    # 200 to limit=None (matching /judge/decisions/recent and
    # /assessments/research/recent's identical, already-established
    # convention) -- calling with no query param at all must now request
    # the repository's own unlimited path, not silently cap at 200.
    outcome = DecisionOutcome(
        decision_id="d1", asset_id="a1", decision_timestamp=datetime.now(UTC), horizon_days=30,
        target_return=0.15, stop_return=-0.15, judge_confidence=0.6,
    )

    class FakeRepo:
        def get_recent(self, limit=200, is_backfilled=None):
            assert limit is None  # the route's new default, not the old 200
            return [outcome]

    app.dependency_overrides[get_decision_outcome_repo] = lambda: FakeRepo()
    response = client.get("/calibration/outcomes/recent")
    assert response.status_code == 200
    assert response.json()[0]["decision_id"] == "d1"


def test_get_recent_outcomes_explicit_limit_still_works(client):
    outcome = DecisionOutcome(
        decision_id="d1", asset_id="a1", decision_timestamp=datetime.now(UTC), horizon_days=30,
        target_return=0.15, stop_return=-0.15, judge_confidence=0.6,
    )

    class FakeRepo:
        def get_recent(self, limit=200, is_backfilled=None):
            assert limit == 50
            return [outcome]

    app.dependency_overrides[get_decision_outcome_repo] = lambda: FakeRepo()
    response = client.get("/calibration/outcomes/recent?limit=50")
    assert response.status_code == 200
    assert response.json()[0]["decision_id"] == "d1"


def test_get_recent_outcomes_newest_first_ordering_preserved(client):
    # The endpoint itself doesn't re-sort -- ordering is entirely the
    # repository's own responsibility (already covered by
    # tests/test_repository_pagination.py's DecisionOutcomeRepository
    # tests). This just confirms the route passes through whatever order
    # the repository returns, unchanged.
    older = DecisionOutcome(
        decision_id="older", asset_id="a1", decision_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        horizon_days=30, target_return=0.15, stop_return=-0.15, judge_confidence=0.6,
    )
    newer = DecisionOutcome(
        decision_id="newer", asset_id="a1", decision_timestamp=datetime(2026, 9, 1, tzinfo=UTC),
        horizon_days=30, target_return=0.15, stop_return=-0.15, judge_confidence=0.6,
    )

    class FakeRepo:
        def get_recent(self, limit=200, is_backfilled=None):
            return [newer, older]  # already newest-first, as the real repository guarantees

    app.dependency_overrides[get_decision_outcome_repo] = lambda: FakeRepo()
    response = client.get("/calibration/outcomes/recent")
    body = response.json()
    assert [o["decision_id"] for o in body] == ["newer", "older"]


def test_get_recent_evidence_value_reports(client):
    record = EvidenceValueReportRecord(
        run_at=datetime.now(UTC), method="full_history_logistic_regression", sample_size=36,
        sufficient_sample=False, notes="insufficient data",
    )

    class FakeRepo:
        def get_recent(self, limit=50):
            return [record]

    app.dependency_overrides[get_evidence_value_report_repo] = lambda: FakeRepo()
    response = client.get("/calibration/evidence-value/recent")
    assert response.json()[0]["sufficient_sample"] is False


# --- signal_sources -----------------------------------------------------------------

def test_get_signal_sources(client):
    class FakeRepo:
        def get_all(self):
            return [SignalSource(name="Etherscan", status="NOT_IMPLEMENTED")]

    app.dependency_overrides[get_signal_source_repo] = lambda: FakeRepo()
    response = client.get("/signal-sources")
    assert response.json()[0]["status"] == "NOT_IMPLEMENTED"


# --- cost -----------------------------------------------------------------

def test_get_cost_summary_reports_by_table_breakdown_and_note(client):
    class FakeCostLedgerRepo:
        def get_cost_and_count_by_table_since(self, since):
            return {"judge_decisions": (Decimal("1.5"), 3), "adversarial_research": (Decimal("0.5"), 1)}

    settings = Settings(_env_file=None, max_daily_llm_cost=Decimal("12"), max_monthly_llm_cost=Decimal("30"))
    app.dependency_overrides[get_cost_ledger_repo] = lambda: FakeCostLedgerRepo()
    app.dependency_overrides[get_settings_dependency] = lambda: settings
    response = client.get("/cost/summary")
    body = response.json()
    assert body["daily"]["total_usd"] == "2.0"
    assert body["daily"]["cap_usd"] == "12"
    assert "not a live provider-billing balance" in body["note"]
    assert len(body["daily"]["by_table"]) == 2
    judge_row = next(t for t in body["daily"]["by_table"] if t["table"] == "judge_decisions")
    assert judge_row["call_count"] == 3


def test_get_cost_summary_reports_pricing_and_fee_rate_staleness(client, monkeypatch):
    from datetime import UTC, timedelta

    class FakeCostLedgerRepo:
        def get_cost_and_count_by_table_since(self, since):
            return {}

    stale_date = (datetime.now(UTC) - timedelta(days=200)).date()
    monkeypatch.setattr("app.llm.cost.PRICING_LAST_VERIFIED", stale_date)
    monkeypatch.setattr("app.trading.fill_simulator.FEE_RATES_LAST_VERIFIED", stale_date)
    settings = Settings(_env_file=None, max_daily_llm_cost=Decimal("12"), max_monthly_llm_cost=Decimal("30"))
    app.dependency_overrides[get_cost_ledger_repo] = lambda: FakeCostLedgerRepo()
    app.dependency_overrides[get_settings_dependency] = lambda: settings
    response = client.get("/cost/summary")
    body = response.json()
    assert "200 days ago" in body["pricing_staleness_note"]
    assert "200 days ago" in body["fee_rate_staleness_note"]


def test_get_cost_by_day_reports_every_real_day_table_bucket(client):
    class FakeCostLedgerRepo:
        def get_cost_and_count_by_table_and_day_since(self, since):
            return {
                ("2026-01-02", "judge_decisions"): (Decimal("1.5"), 3),
                ("2026-01-03", "judge_decisions"): (Decimal("0.5"), 1),
            }

    app.dependency_overrides[get_cost_ledger_repo] = lambda: FakeCostLedgerRepo()
    response = client.get("/cost/by-day")
    body = response.json()
    assert len(body) == 2
    jan3 = next(r for r in body if r["date"] == "2026-01-03")
    assert jan3["table"] == "judge_decisions"
    assert jan3["cost_usd"] == "0.5"
    assert jan3["call_count"] == 1
