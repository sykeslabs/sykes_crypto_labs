from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.config.settings import Settings
from app.database.models import Asset, SignalSource
from app.judge.context import JudgeContext, AssetJudgeContext, build_judge_context, render_prompt
from app.judge.provider import OpenRouterJudgeProvider
from app.judge.schemas import JudgeDecisionBatch, JudgeDecisionItem, JudgeDecisionRecord
from app.judge.service import JudgeService
from app.llm.assessment_schemas import ModelMarketAssessmentRecord
from app.llm.cost import CostGuard, CostLedgerRepository
from app.market_data.screening_schemas import MarketRegimeSnapshot, ScreenedAsset

VALID_DECISION = dict(
    asset="BTC",
    decision="BUY",
    confidence=0.67,
    target_allocation=0.06,
    expected_return=0.18,
    expected_alpha=0.09,
    risk_score=0.42,
    uncertainty=0.33,
    model_agreement=0.58,
    source_agreement=0.54,
    investment_horizon_days=90,
    key_evidence=["3/3 models bullish"],
    contradictory_evidence=["composite_factor_score is only middling"],
    key_risks=["macro risk-off could reverse this"],
    invalidation_conditions=["BTC closes below $70k"],
    requires_review=False,
    thesis="Consolidating within an uptrend.",
)


# --- schemas -----------------------------------------------------------------

def test_judge_decision_item_accepts_valid_payload():
    item = JudgeDecisionItem(**VALID_DECISION)
    assert item.decision == "BUY"
    assert item.model_agreement == 0.58


def test_judge_decision_item_rejects_invalid_decision():
    bad = dict(VALID_DECISION, decision="MAYBE")
    with pytest.raises(ValidationError):
        JudgeDecisionItem(**bad)


def test_judge_decision_item_accepts_no_trade():
    item = JudgeDecisionItem(**dict(VALID_DECISION, decision="NO_TRADE", target_allocation=0.0))
    assert item.decision == "NO_TRADE"


def test_judge_decision_item_rejects_confidence_out_of_range():
    bad = dict(VALID_DECISION, confidence=1.5)
    with pytest.raises(ValidationError):
        JudgeDecisionItem(**bad)


def test_judge_decision_batch_parses_list():
    batch = JudgeDecisionBatch(decisions=[VALID_DECISION, dict(VALID_DECISION, asset="ETH")])
    assert len(batch.decisions) == 2


def test_judge_decision_record_to_row_serializes_decimal_and_datetime():
    record = JudgeDecisionRecord(
        run_id="RUN-1", asset_id="a1", created_at=datetime(2026, 1, 1, tzinfo=UTC),
        decision="BUY", confidence=0.6, target_allocation=0.05, expected_return=0.1,
        expected_alpha=0.05, risk_score=0.4, uncertainty=0.3, model_agreement=0.8,
        source_agreement=0.7, investment_horizon_days=30, key_evidence=[], contradictory_evidence=[],
        key_risks=[], invalidation_conditions=[], requires_review=False, thesis="t",
        regime_id="r1", prompt_template_id="p1", estimated_cost=Decimal("0.01"),
    )
    row = record.to_row()
    assert row["estimated_cost"] == "0.01"
    assert isinstance(row["created_at"], str)


# --- context building: no silent fallback -----------------------------------

def _asset(symbol="BTC", asset_id="a1"):
    return Asset(id=asset_id, symbol=symbol, name=symbol, coingecko_id=symbol.lower(), active=True, in_asset=True, created_at=datetime.now(UTC))


def _screened(symbol="BTC", asset_id="a1", score=0.7, volatility=0.02):
    return ScreenedAsset(
        run_id="RUN-1", computed_at=datetime.now(UTC), symbol=symbol, coingecko_id=symbol.lower(),
        asset_id=asset_id, composite_factor_score=score, volatility_30d=volatility, is_top_candidate=True,
    )


def _assessment(asset_id="a1", provider="claude", model_agreement=0.667):
    return ModelMarketAssessmentRecord(
        run_id="RUN-1", asset_id=asset_id, provider=provider, model=f"model-{provider}",
        prompt_template_id="pt1", assessment_timestamp=datetime.now(UTC),
        data_cutoff_timestamp=datetime.now(UTC),
        short_term_direction="BULLISH", medium_term_direction="BULLISH", long_term_direction="NEUTRAL",
        short_term_confidence=0.6, medium_term_confidence=0.5, long_term_confidence=0.4,
        expected_return_7d=0.03, expected_return_30d=0.05, expected_return_90d=0.08,
        risk_score=0.4, risk_level="MEDIUM", market_regime="RISK_ON", model_agreement=model_agreement,
        overall_assessment="BULLISH", thesis="bullish thesis", key_drivers=[], key_risks=[],
        source_assessment=[], invalidation_conditions=[], raw_response=None, estimated_cost=Decimal("0.01"),
    )


class FakeRegimeRepoForContext:
    def __init__(self, regime=None):
        self._regime = regime

    def get_latest(self):
        return self._regime


class FakeEvidenceRepoForContext:
    def get_latest_by_asset(self, asset_id):
        return []


class FakeAssessmentRepoForContext:
    def __init__(self, assessments):
        self._assessments = assessments

    def get_latest_run_assessments(self):
        return self._assessments


class FakeLLMAnalysisRepoForContext:
    def get_latest_by_asset(self, asset_id, limit=3):
        return []


class FakeNewsRepoForContext:
    def get_recent_relevant_news(self, symbols, since, until, limit_per_asset):
        return {}


class FakeAssetStatusRepoForContext:
    def get_latest_status(self, asset_id):
        return None


class FakePortfolioPositionRepoForContext:
    def __init__(self, positions=None):
        self._positions = positions or {}

    def get_all(self):
        return self._positions


class FakeSignalSourceRepoForContext:
    def __init__(self, sources=None):
        self._sources = sources or []

    def get_all(self):
        return self._sources


def _build_context(candidates, assets_by_id, assessments, regime=None, positions=None, sources=None):
    settings = Settings(_env_file=None)
    return build_judge_context(
        "RUN-1", settings, candidates, assets_by_id,
        FakeRegimeRepoForContext(regime), FakeEvidenceRepoForContext(),
        FakeAssessmentRepoForContext(assessments), FakeLLMAnalysisRepoForContext(),
        FakeNewsRepoForContext(), FakeAssetStatusRepoForContext(),
        FakePortfolioPositionRepoForContext(positions), FakeSignalSourceRepoForContext(sources),
    )


def test_context_skips_candidate_without_any_assessment():
    btc = _asset("BTC", "a1")
    eth = _asset("ETH", "a2")
    candidates = [_screened("BTC", "a1"), _screened("ETH", "a2")]
    # Only BTC has a 3d assessment; ETH must be silently excluded, not faked.
    context = _build_context(candidates, {"a1": btc, "a2": eth}, [_assessment("a1")])
    assert [ac.asset.symbol for ac in context.assets] == ["BTC"]


def test_context_carries_model_agreement_from_assessment():
    btc = _asset("BTC", "a1")
    candidates = [_screened("BTC", "a1")]
    context = _build_context(candidates, {"a1": btc}, [_assessment("a1", model_agreement=0.667)])
    assert context.assets[0].model_agreement == pytest.approx(0.667)


def test_context_discloses_unavailable_sources():
    btc = _asset("BTC", "a1")
    candidates = [_screened("BTC", "a1")]
    sources = [
        SignalSource(name="Glassnode", enabled=False, status="NOT_IMPLEMENTED"),
        SignalSource(name="CoinGecko", enabled=True, status="OK"),
    ]
    context = _build_context(candidates, {"a1": btc}, [_assessment("a1")], sources=sources)
    assert context.unavailable_sources == ["Glassnode"]


# --- prompt rendering --------------------------------------------------------

def test_render_prompt_includes_regime_agreement_and_unavailable_sources():
    regime = MarketRegimeSnapshot(id="r1", run_id="RUN-1", computed_at=datetime.now(UTC), regime="RISK_ON", inputs={"btc_dominance": 0.5})
    context = JudgeContext(
        run_id="RUN-1", as_of=datetime.now(UTC), regime=regime, regime_id="r1",
        unavailable_sources=["Glassnode", "CoinAnk"],
        assets=[AssetJudgeContext(
            asset=_asset(), screened=_screened(), snapshot=None,
            assessments=[_assessment(model_agreement=0.667)], model_agreement=0.667,
        )],
    )
    system_prompt, user_prompt = render_prompt(context, "v1")
    assert "RISK_ON" in user_prompt
    assert "Glassnode" in user_prompt and "CoinAnk" in user_prompt
    assert "0.667" in user_prompt
    assert "NO_TRADE" in system_prompt


# --- CostGuard registration ---------------------------------------------------

class _FakeQueryResult:
    def __init__(self, data):
        self.data = data


class _FakeTableQuery:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *_a, **_k):
        return self

    def gte(self, column, value):
        self._rows = [r for r in self._rows if r.get(column, "") >= value]
        return self

    def execute(self):
        return _FakeQueryResult(self._rows)


class FakeSupabaseClient:
    def __init__(self, tables):
        self._tables = tables

    def table(self, name):
        return _FakeTableQuery(list(self._tables.get(name, [])))


def test_cost_guard_reflects_judge_decisions_row():
    client = FakeSupabaseClient({
        "judge_decisions": [{"created_at": datetime.now(UTC).isoformat(), "estimated_cost": "0.04"}],
    })
    settings = Settings(_env_file=None, max_daily_llm_cost=Decimal("0.03"), max_monthly_llm_cost=Decimal("50"))
    guard = CostGuard(settings, CostLedgerRepository(client))
    allowed, reason = guard.check()
    assert allowed is False
    assert "Daily" in reason


# --- JudgeService orchestration ----------------------------------------------

class FakeAssetRepo:
    def __init__(self, assets):
        self._assets = assets

    def get_active_assets(self):
        return self._assets


class FakeScreenedUniverseRepoForService:
    def __init__(self, top_candidates):
        self._top_candidates = top_candidates

    def get_latest_top_candidates(self):
        return self._top_candidates


class FakePromptTemplateRepo:
    def __init__(self):
        self.calls = []
        self._next_id = 0

    def get_or_create(self, name, stage, version, template_hash):
        self.calls.append((name, stage, version))
        self._next_id += 1
        return f"template-{self._next_id}"


class FakeJudgeDecisionRepo:
    def __init__(self):
        self.inserted = []
        self._next_id = 0

    def insert(self, record):
        self._next_id += 1
        decision_id = f"decision-{self._next_id}"
        self.inserted.append(record)
        return decision_id


class FakeDecisionOutcomeRepo:
    def __init__(self):
        self.inserted = []

    def insert(self, outcome):
        self.inserted.append(outcome)


class FakeCostGuardForService:
    def __init__(self, allowed=True, reason=None):
        self._allowed = allowed
        self._reason = reason

    def check(self):
        return self._allowed, self._reason


class FakeJudgeProvider:
    def __init__(self, result):
        self.model = result.model
        self._result = result
        self.called = False

    def decide(self, system_prompt, user_prompt):
        self.called = True
        return self._result


def _judge_provider_result(decisions_payload, cost=Decimal("0.05"), error=None):
    from app.judge.provider import JudgeProviderResult
    from app.llm.schemas import TokenUsage

    if error:
        return JudgeProviderResult(
            provider="judge", model="model-x", batch=None, token_usage=None,
            estimated_cost=Decimal("0"), raw_response=None, error=error,
        )
    return JudgeProviderResult(
        provider="judge", model="model-x", batch=JudgeDecisionBatch(decisions=decisions_payload),
        token_usage=TokenUsage(prompt_tokens=200, completion_tokens=200),
        estimated_cost=cost, raw_response={"choices": [{"message": {"content": "{}"}}]}, error=None,
    )


def _make_service(
    top_candidates, assets, assessments, provider, prompt_repo=None,
    judge_decision_repo=None, decision_outcome_repo=None, cost_guard=None, regime=None,
):
    settings = Settings(_env_file=None)
    return JudgeService(
        settings=settings,
        asset_repo=FakeAssetRepo(assets),
        screened_universe_repo=FakeScreenedUniverseRepoForService(top_candidates),
        regime_repo=FakeRegimeRepoForContext(regime),
        evidence_repo=FakeEvidenceRepoForContext(),
        assessment_repo=FakeAssessmentRepoForContext(assessments),
        llm_analysis_repo=FakeLLMAnalysisRepoForContext(),
        news_repo=FakeNewsRepoForContext(),
        asset_status_repo=FakeAssetStatusRepoForContext(),
        portfolio_position_repo=FakePortfolioPositionRepoForContext(),
        signal_source_repo=FakeSignalSourceRepoForContext(),
        prompt_template_repo=prompt_repo or FakePromptTemplateRepo(),
        judge_decision_repo=judge_decision_repo or FakeJudgeDecisionRepo(),
        decision_outcome_repo=decision_outcome_repo or FakeDecisionOutcomeRepo(),
        cost_guard=cost_guard or FakeCostGuardForService(allowed=True),
        provider=provider,
    )


def test_service_returns_empty_when_no_top_candidates():
    service = _make_service([], [], [], FakeJudgeProvider(_judge_provider_result([])))
    result = service.run("RUN-1")
    assert result.stored == 0
    assert result.decided_assets == []


def test_service_warns_and_returns_empty_when_no_assessments_exist():
    btc = _asset("BTC", "a1")
    top = [_screened("BTC", "a1")]
    service = _make_service(top, [btc], [], FakeJudgeProvider(_judge_provider_result([])))
    result = service.run("RUN-1")
    assert result.stored == 0


def test_service_stores_decision_and_creates_outcome_row():
    btc = _asset("BTC", "a1")
    top = [_screened("BTC", "a1")]
    assessments = [_assessment("a1")]
    provider = FakeJudgeProvider(_judge_provider_result([VALID_DECISION]))
    decision_repo = FakeJudgeDecisionRepo()
    outcome_repo = FakeDecisionOutcomeRepo()

    service = _make_service(
        top, [btc], assessments, provider,
        judge_decision_repo=decision_repo, decision_outcome_repo=outcome_repo,
    )
    result = service.run("RUN-1")

    assert result.stored == 1
    assert decision_repo.inserted[0].asset_id == "a1"
    assert len(outcome_repo.inserted) == 1
    assert outcome_repo.inserted[0].in_holdout_window is True
    assert outcome_repo.inserted[0].outcome_label == "UNRESOLVED"


def test_service_produces_reachable_no_trade():
    btc = _asset("BTC", "a1")
    top = [_screened("BTC", "a1")]
    assessments = [_assessment("a1")]
    no_trade_payload = dict(VALID_DECISION, decision="NO_TRADE", target_allocation=0.0)
    provider = FakeJudgeProvider(_judge_provider_result([no_trade_payload]))
    decision_repo = FakeJudgeDecisionRepo()

    service = _make_service(top, [btc], assessments, provider, judge_decision_repo=decision_repo)
    service.run("RUN-1")

    assert decision_repo.inserted[0].decision == "NO_TRADE"


def test_service_requires_review_flag_persisted():
    btc = _asset("BTC", "a1")
    top = [_screened("BTC", "a1")]
    assessments = [_assessment("a1")]
    flagged_payload = dict(VALID_DECISION, requires_review=True)
    provider = FakeJudgeProvider(_judge_provider_result([flagged_payload]))
    decision_repo = FakeJudgeDecisionRepo()

    service = _make_service(top, [btc], assessments, provider, judge_decision_repo=decision_repo)
    service.run("RUN-1")

    assert decision_repo.inserted[0].requires_review is True


def test_service_skips_when_cost_cap_exceeded():
    btc = _asset("BTC", "a1")
    top = [_screened("BTC", "a1")]
    assessments = [_assessment("a1")]
    provider = FakeJudgeProvider(_judge_provider_result([VALID_DECISION]))

    service = _make_service(
        top, [btc], assessments, provider,
        cost_guard=FakeCostGuardForService(allowed=False, reason="cap reached"),
    )
    result = service.run("RUN-1")

    assert result.skipped_cost_cap is True
    assert provider.called is False


def test_service_provider_failure_reported():
    btc = _asset("BTC", "a1")
    top = [_screened("BTC", "a1")]
    assessments = [_assessment("a1")]
    provider = FakeJudgeProvider(_judge_provider_result([], error="boom"))

    service = _make_service(top, [btc], assessments, provider)
    result = service.run("RUN-1")

    assert result.failed == "boom"
    assert result.stored == 0


def test_service_registers_prompt_template_with_correct_stage():
    btc = _asset("BTC", "a1")
    top = [_screened("BTC", "a1")]
    assessments = [_assessment("a1")]
    provider = FakeJudgeProvider(_judge_provider_result([VALID_DECISION]))
    prompt_repo = FakePromptTemplateRepo()

    service = _make_service(top, [btc], assessments, provider, prompt_repo=prompt_repo)
    service.run("RUN-1")

    assert prompt_repo.calls == [("judge_decision", "3e", "v2")]


# --- OpenRouterJudgeProvider (HTTP + retry) -----------------------------------

class FakeHttpResponse:
    def __init__(self, payload, status_ok=True):
        self._payload = payload
        self._status_ok = status_ok

    def raise_for_status(self):
        if not self._status_ok:
            import httpx
            raise httpx.HTTPStatusError("error", request=None, response=None)

    def json(self):
        return self._payload


def _chat_payload(content, prompt_tokens=100, completion_tokens=50):
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


def test_judge_provider_valid_response_no_retry(monkeypatch):
    import json

    calls = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs)
        return FakeHttpResponse(_chat_payload(json.dumps({"decisions": [VALID_DECISION]})))

    monkeypatch.setattr("app.judge.provider.httpx.post", fake_post)

    provider = OpenRouterJudgeProvider(
        name="judge", model="anthropic/claude-sonnet-5", api_key="key",
        base_url="https://openrouter.ai/api/v1", timeout_seconds=10,
    )
    result = provider.decide("system", "user")

    assert len(calls) == 1
    assert result.error is None
    assert result.batch.decisions[0].asset == "BTC"


def test_judge_provider_retries_once_then_succeeds(monkeypatch):
    responses = [
        FakeHttpResponse(_chat_payload("not json")),
        FakeHttpResponse(_chat_payload('{"decisions": []}')),
    ]
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs)
        return responses.pop(0)

    monkeypatch.setattr("app.judge.provider.httpx.post", fake_post)

    provider = OpenRouterJudgeProvider(
        name="judge", model="anthropic/claude-sonnet-5", api_key="key",
        base_url="https://openrouter.ai/api/v1", timeout_seconds=10,
    )
    result = provider.decide("system", "user")

    assert len(calls) == 2
    assert result.error is None
    assert result.batch.decisions == []
    assert result.token_usage.prompt_tokens == 200
