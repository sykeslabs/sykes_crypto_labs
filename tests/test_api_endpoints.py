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
    get_portfolio_position_repo,
    get_reasoning_audit_repo,
    get_regime_repo,
    get_screened_universe_repo,
    get_settings_dependency,
    get_signal_source_repo,
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


def _judge_decision(decision_id="d1", asset_id="a1"):
    return JudgeDecisionRecord(
        id=decision_id, run_id="RUN-1", asset_id=asset_id, created_at=datetime.now(UTC),
        decision="BUY", confidence=0.6, target_allocation=0.05, expected_return=0.1,
        expected_alpha=0.05, risk_score=0.4, uncertainty=0.3, model_agreement=0.8,
        source_agreement=0.7, investment_horizon_days=30, key_evidence=["e1"],
        contradictory_evidence=[], key_risks=[], invalidation_conditions=[],
        requires_review=False, thesis="A real thesis.", macro_sensitivity="n/a",
        regime_id=None, prompt_template_id=None, estimated_cost=Decimal("0.02"),
        is_backfilled=False,
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


# --- calibration -----------------------------------------------------------------

def test_get_calibration_summary_reports_null_when_no_directional_data(client):
    class FakeOutcomeRepo:
        def get_recent(self, limit=2000, is_backfilled=None):
            return []

    class FakeJudgeRepo:
        def get_by_id(self, decision_id):
            return None

    app.dependency_overrides[get_decision_outcome_repo] = lambda: FakeOutcomeRepo()
    app.dependency_overrides[get_judge_decision_repo] = lambda: FakeJudgeRepo()
    response = client.get("/calibration/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["hit_rate"] is None
    assert body["directional_sample_size"] == 0
    assert "not computable" in body["by_regime_note"].lower()


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
    decisions = {"d1": _judge_decision("d1"), "d2": _judge_decision("d2")}

    class FakeOutcomeRepo:
        def get_recent(self, limit=2000, is_backfilled=None):
            return [outcome_correct, outcome_wrong]

    class FakeJudgeRepo:
        def get_by_id(self, decision_id):
            return decisions.get(decision_id)

    app.dependency_overrides[get_decision_outcome_repo] = lambda: FakeOutcomeRepo()
    app.dependency_overrides[get_judge_decision_repo] = lambda: FakeJudgeRepo()
    response = client.get("/calibration/summary")
    body = response.json()
    # Both are BUY decisions: d1 correct (positive return), d2 wrong (negative).
    assert body["directional_sample_size"] == 2
    assert body["hit_rate"] == pytest.approx(0.5)
    assert body["resolved_backfilled_count"] == 2


def test_get_recent_calibration_runs(client):
    record = CalibrationRunRecord(run_at=datetime.now(UTC), method="TEST_METHOD", sample_size=10, hit_rate=0.5, brier_score=0.2)

    class FakeRepo:
        def get_recent(self, limit=50):
            return [record]

    app.dependency_overrides[get_calibration_run_repo] = lambda: FakeRepo()
    response = client.get("/calibration/runs/recent")
    assert response.json()[0]["method"] == "TEST_METHOD"


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
        def get_cost_sum_by_table_since(self, since):
            return {"judge_decisions": Decimal("1.5"), "adversarial_research": Decimal("0.5")}

    settings = Settings(_env_file=None, max_daily_llm_cost=Decimal("12"), max_monthly_llm_cost=Decimal("30"))
    app.dependency_overrides[get_cost_ledger_repo] = lambda: FakeCostLedgerRepo()
    app.dependency_overrides[get_settings_dependency] = lambda: settings
    response = client.get("/cost/summary")
    body = response.json()
    assert body["daily"]["total_usd"] == "2.0"
    assert body["daily"]["cap_usd"] == "12"
    assert "not a live provider-billing balance" in body["note"]
    assert len(body["daily"]["by_table"]) == 2
