from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.config.settings import Settings
from app.database.models import Asset
from app.llm.adversarial_schemas import (
    AdversarialResearchRecord,
    BearBatch,
    BearCase,
    BullBatch,
    BullCase,
    ScenarioBatch,
    ScenarioSet,
)
from app.llm.adversarial_context import (
    ResearchContext,
    AssetResearchContext,
    render_bear_prompt,
    render_bull_prompt,
    render_scenario_prompt,
)
from app.llm.adversarial_service import AdversarialService
from app.llm.cost import CostGuard, CostLedgerRepository
from app.llm.structured_provider import OpenRouterStructuredProvider, StructuredCallResult
from app.market_data.screening_schemas import ScreenedAsset

# --- CostGuard registration (locked-decision requirement, task 4a) ----------

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


def test_settings_require_adversarial_raises_without_key():
    settings = Settings(_env_file=None)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        settings.require_adversarial()


def test_settings_require_adversarial_raises_without_model():
    settings = Settings(_env_file=None, openrouter_api_key="key")
    with pytest.raises(RuntimeError, match="model"):
        settings.require_adversarial()


def test_settings_require_adversarial_defaults_to_claude_model():
    settings = Settings(_env_file=None, openrouter_api_key="key", claude_model="anthropic/claude-sonnet-5")
    api_key, model = settings.require_adversarial()
    assert api_key == "key"
    assert model == "anthropic/claude-sonnet-5"


# --- adversarial_context render functions -------------------------------------

def _research_context(bull_thesis="Strong demand", bear_attacks=None):
    return ResearchContext(
        run_id="RUN-1", as_of=datetime.now(UTC), regime=None,
        assets=[AssetResearchContext(asset=_asset(), screened=_screened())],
    )


def test_render_bull_prompt_includes_asset_and_evidence():
    context = _research_context()
    system_prompt, user_prompt = render_bull_prompt(context, "v1")
    assert "BTC" in user_prompt
    assert "strongest" in system_prompt.lower() or "bull" in system_prompt.lower()


def test_render_bull_prompt_includes_full_term_structure_curve_not_one_point():
    context = ResearchContext(
        run_id="RUN-1", as_of=datetime.now(UTC), regime=None,
        assets=[AssetResearchContext(
            asset=_asset(), screened=_screened(),
            term_structure_by_source={
                "deribit_futures_term_structure": [
                    {"instrument": "BTC-25SEP26", "annualized_carry_yield": 0.04},
                    {"instrument": "BTC-25DEC26", "annualized_carry_yield": 0.05},
                    {"instrument": "BTC-26MAR27", "annualized_carry_yield": 0.06},
                ],
            },
        )],
    )
    _, user_prompt = render_bull_prompt(context, "v1")
    assert "BTC-25SEP26" in user_prompt
    assert "BTC-25DEC26" in user_prompt
    assert "BTC-26MAR27" in user_prompt
    assert "3 distinct" in user_prompt


def test_render_bear_prompt_includes_bull_thesis_to_attack():
    context = _research_context()
    bull_batch = BullBatch(cases=[BullCase(asset="BTC", thesis="ETF demand is durable", catalysts=["ETF inflows"], evidence=["flow data"])])
    _, user_prompt = render_bear_prompt(context, bull_batch, "v1")
    assert "ETF demand is durable" in user_prompt
    assert "ETF inflows" in user_prompt


def test_render_scenario_prompt_includes_both_bull_and_bear():
    context = _research_context()
    bull_batch = BullBatch(cases=[BullCase(asset="BTC", thesis="ETF demand is durable", catalysts=[], evidence=[])])
    bear_batch = BearBatch(cases=[BearCase(asset="BTC", attack_points=["Crowded positioning"], evidence=[], attacks_bull_point=[])])
    _, user_prompt = render_scenario_prompt(context, bull_batch, bear_batch, "v1")
    assert "ETF demand is durable" in user_prompt
    assert "Crowded positioning" in user_prompt


def test_cost_guard_reflects_adversarial_research_row():
    client = FakeSupabaseClient({
        "adversarial_research": [{"created_at": datetime.now(UTC).isoformat(), "estimated_cost": "0.04"}],
    })
    settings = Settings(_env_file=None, max_daily_llm_cost=Decimal("0.03"), max_monthly_llm_cost=Decimal("50"))
    guard = CostGuard(settings, CostLedgerRepository(client))
    allowed, reason = guard.check()
    assert allowed is False
    assert "Daily" in reason

# --- schemas -----------------------------------------------------------------

def test_bull_case_valid():
    case = BullCase(asset="BTC", thesis="Strong demand", catalysts=["ETF"], evidence=["flow data"])
    assert case.asset == "BTC"


def test_bear_case_requires_no_specific_fields_but_parses():
    case = BearCase(asset="BTC", attack_points=["Crowded"], evidence=["funding"], attacks_bull_point=["ETF"])
    assert case.attacks_bull_point == ["ETF"]


def test_scenario_rejects_probability_out_of_range():
    with pytest.raises(ValidationError):
        ScenarioSet(
            asset="BTC",
            bull={"probability": 1.5, "expected_return": 0.5, "timeframe": "90d"},
            base={"probability": 0.4, "expected_return": 0.1, "timeframe": "90d"},
            bear={"probability": 0.3, "expected_return": -0.2, "timeframe": "90d"},
        )


def test_adversarial_research_record_to_row_serializes_decimal_and_datetime():
    record = AdversarialResearchRecord(
        run_id="RUN-1", asset_id="a1", prompt_template_id="pt1",
        bull_case={"thesis": "t"}, bear_case={"attack_points": []},
        scenarios={"bull": {}}, estimated_cost=Decimal("0.05"),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    row = record.to_row()
    assert row["estimated_cost"] == "0.05"
    assert isinstance(row["created_at"], str)
    assert row["bull_rebuttal"] is None


# --- OpenRouterStructuredProvider (HTTP + retry) ------------------------------

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


def test_structured_provider_valid_response_no_retry(monkeypatch):
    import json

    calls = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs)
        return FakeHttpResponse(_chat_payload(json.dumps({"cases": [{"asset": "BTC", "thesis": "t", "catalysts": [], "evidence": []}]})))

    monkeypatch.setattr("app.llm.structured_provider.httpx.post", fake_post)

    provider = OpenRouterStructuredProvider(
        name="adversarial", model="anthropic/claude-sonnet-5", api_key="key",
        base_url="https://openrouter.ai/api/v1", timeout_seconds=10,
    )
    result = provider.call("system", "user", BullBatch)

    assert len(calls) == 1
    assert result.error is None
    assert result.parsed.cases[0].asset == "BTC"


def test_structured_provider_retries_once_then_succeeds(monkeypatch):
    responses = [
        FakeHttpResponse(_chat_payload("not json")),
        FakeHttpResponse(_chat_payload('{"cases": []}')),
    ]
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs)
        return responses.pop(0)

    monkeypatch.setattr("app.llm.structured_provider.httpx.post", fake_post)

    provider = OpenRouterStructuredProvider(
        name="adversarial", model="anthropic/claude-sonnet-5", api_key="key",
        base_url="https://openrouter.ai/api/v1", timeout_seconds=10,
    )
    result = provider.call("system", "user", BearBatch)

    assert len(calls) == 2
    assert result.error is None
    assert result.parsed.cases == []
    assert result.token_usage.prompt_tokens == 200


def test_structured_provider_fails_twice_reports_error(monkeypatch):
    def fake_post(*args, **kwargs):
        return FakeHttpResponse(_chat_payload("still not json"))

    monkeypatch.setattr("app.llm.structured_provider.httpx.post", fake_post)

    provider = OpenRouterStructuredProvider(
        name="adversarial", model="anthropic/claude-sonnet-5", api_key="key",
        base_url="https://openrouter.ai/api/v1", timeout_seconds=10,
    )
    result = provider.call("system", "user", BullBatch)
    assert result.error is not None
    assert result.parsed is None


# --- AdversarialService orchestration -----------------------------------------

def _asset(symbol="BTC", asset_id="a1"):
    return Asset(id=asset_id, symbol=symbol, name=symbol, coingecko_id=symbol.lower(), active=True, in_asset=True, created_at=datetime.now(UTC))


def _screened(symbol="BTC", asset_id="a1"):
    return ScreenedAsset(run_id="RUN-1", computed_at=datetime.now(UTC), symbol=symbol, coingecko_id=symbol.lower(), asset_id=asset_id, composite_factor_score=0.7, is_top_candidate=True)


class FakeAssetRepo:
    def __init__(self, assets):
        self._assets = assets

    def get_active_assets(self):
        return self._assets


class FakeScreenedUniverseRepo:
    def __init__(self, candidates):
        self._candidates = candidates

    def get_latest_top_candidates(self):
        return self._candidates


class FakeRegimeRepo:
    def get_latest(self):
        return None


class FakeEvidenceRepo:
    def get_latest_by_asset(self, asset_id):
        return []


class FakeAssessmentRepo:
    def __init__(self, assessments):
        self._assessments = assessments

    def get_latest_run_assessments(self):
        return self._assessments


class FakePromptTemplateRepo:
    def __init__(self):
        self.calls = []

    def get_or_create(self, name, stage, version, template_hash):
        self.calls.append((name, stage, version))
        return "template-1"


class FakeAdversarialRepo:
    def __init__(self):
        self.inserted = []

    def insert(self, record):
        self.inserted.append(record)


class FakeCostGuard:
    def __init__(self, allowed=True):
        self._allowed = allowed
        self.calls = 0

    def check(self):
        self.calls += 1
        return self._allowed, None if self._allowed else "cap reached"


class FakeStructuredProvider:
    def __init__(self, bull_batch=None, bear_batch=None, scenario_batch=None, fail_stage=None):
        self._bull_batch = bull_batch
        self._bear_batch = bear_batch
        self._scenario_batch = scenario_batch
        self._fail_stage = fail_stage
        self.calls = []

    def call(self, system_prompt, user_prompt, response_model):
        self.calls.append(response_model)
        if response_model is BullBatch:
            if self._fail_stage == "bull":
                return StructuredCallResult("adversarial", "m", None, None, Decimal("0.05"), None, "bull failed")
            return StructuredCallResult("adversarial", "m", self._bull_batch, None, Decimal("0.10"), {}, None)
        if response_model is BearBatch:
            if self._fail_stage == "bear":
                return StructuredCallResult("adversarial", "m", None, None, Decimal("0.05"), None, "bear failed")
            return StructuredCallResult("adversarial", "m", self._bear_batch, None, Decimal("0.10"), {}, None)
        if self._fail_stage == "scenario":
            return StructuredCallResult("adversarial", "m", None, None, Decimal("0.05"), None, "scenario failed")
        return StructuredCallResult("adversarial", "m", self._scenario_batch, None, Decimal("0.15"), {}, None)


def _valid_bundle():
    bull = BullBatch(cases=[BullCase(asset="BTC", thesis="Strong demand", catalysts=["ETF"], evidence=["flow"])])
    bear = BearBatch(cases=[BearCase(asset="BTC", attack_points=["Crowded"], evidence=["funding"], attacks_bull_point=["ETF"])])
    scenario = ScenarioBatch(scenarios=[ScenarioSet(
        asset="BTC",
        bull={"probability": 0.3, "expected_return": 0.5, "timeframe": "90d"},
        base={"probability": 0.4, "expected_return": 0.1, "timeframe": "90d"},
        bear={"probability": 0.3, "expected_return": -0.2, "timeframe": "90d"},
    )])
    return bull, bear, scenario


def _make_service(candidates, assets, assessments, provider, prompt_repo=None, adversarial_repo=None, cost_guard=None):
    settings = Settings(_env_file=None)
    return AdversarialService(
        settings=settings,
        asset_repo=FakeAssetRepo(assets),
        screened_universe_repo=FakeScreenedUniverseRepo(candidates),
        regime_repo=FakeRegimeRepo(),
        evidence_repo=FakeEvidenceRepo(),
        assessment_repo=FakeAssessmentRepo(assessments),
        prompt_template_repo=prompt_repo or FakePromptTemplateRepo(),
        adversarial_repo=adversarial_repo or FakeAdversarialRepo(),
        cost_guard=cost_guard or FakeCostGuard(allowed=True),
        provider=provider,
    )


def _assessment_stub(asset_id="a1"):
    from app.llm.assessment_schemas import ModelMarketAssessmentRecord
    return ModelMarketAssessmentRecord(
        run_id="RUN-1", asset_id=asset_id, provider="claude", model="m",
        prompt_template_id=None, assessment_timestamp=datetime.now(UTC), data_cutoff_timestamp=datetime.now(UTC),
        short_term_direction="BULLISH", medium_term_direction="BULLISH", long_term_direction="NEUTRAL",
        short_term_confidence=0.6, medium_term_confidence=0.5, long_term_confidence=0.4,
        expected_return_7d=0.03, expected_return_30d=0.05, expected_return_90d=0.08,
        risk_score=0.4, risk_level="MEDIUM", market_regime="RISK_ON", model_agreement=1.0,
        overall_assessment="BULLISH", thesis="t", key_drivers=[], key_risks=[], source_assessment=[],
        invalidation_conditions=[], raw_response=None, estimated_cost=Decimal("0.01"),
    )


def test_service_returns_empty_when_no_top_candidates():
    provider = FakeStructuredProvider()
    result = _make_service([], [], [], provider).run("RUN-1")
    assert result.stored == 0
    assert result.researched_assets == []


def test_service_full_chain_persists_one_record():
    bull, bear, scenario = _valid_bundle()
    provider = FakeStructuredProvider(bull_batch=bull, bear_batch=bear, scenario_batch=scenario)
    adversarial_repo = FakeAdversarialRepo()
    btc = _asset("BTC", "a1")
    candidates = [_screened("BTC", "a1")]

    service = _make_service(candidates, [btc], [_assessment_stub("a1")], provider, adversarial_repo=adversarial_repo)
    result = service.run("RUN-1")

    assert result.stored == 1
    assert len(adversarial_repo.inserted) == 1
    record = adversarial_repo.inserted[0]
    assert record.bull_case["thesis"] == "Strong demand"
    assert record.bear_case["attack_points"] == ["Crowded"]
    assert record.estimated_cost == Decimal("0.35")  # 0.10 + 0.10 + 0.15, one asset
    assert [c for c in provider.calls] == [BullBatch, BearBatch, ScenarioBatch]


def test_service_stops_when_bull_stage_fails():
    provider = FakeStructuredProvider(fail_stage="bull")
    btc = _asset("BTC", "a1")
    candidates = [_screened("BTC", "a1")]
    result = _make_service(candidates, [btc], [_assessment_stub("a1")], provider).run("RUN-1")
    assert result.failed == "bull: bull failed"
    assert result.stored == 0


def test_service_stops_when_bear_stage_fails():
    bull, _, _ = _valid_bundle()
    provider = FakeStructuredProvider(bull_batch=bull, fail_stage="bear")
    btc = _asset("BTC", "a1")
    candidates = [_screened("BTC", "a1")]
    result = _make_service(candidates, [btc], [_assessment_stub("a1")], provider).run("RUN-1")
    assert result.failed == "bear: bear failed"


def test_service_stops_when_scenario_stage_fails():
    bull, bear, _ = _valid_bundle()
    provider = FakeStructuredProvider(bull_batch=bull, bear_batch=bear, fail_stage="scenario")
    btc = _asset("BTC", "a1")
    candidates = [_screened("BTC", "a1")]
    result = _make_service(candidates, [btc], [_assessment_stub("a1")], provider).run("RUN-1")
    assert result.failed == "scenario: scenario failed"


def test_service_skips_when_cost_cap_exceeded_before_bull_stage():
    provider = FakeStructuredProvider()
    btc = _asset("BTC", "a1")
    candidates = [_screened("BTC", "a1")]
    result = _make_service(
        candidates, [btc], [_assessment_stub("a1")], provider, cost_guard=FakeCostGuard(allowed=False),
    ).run("RUN-1")
    assert result.skipped_cost_cap is True


def test_service_registers_prompt_template_with_correct_stage():
    bull, bear, scenario = _valid_bundle()
    provider = FakeStructuredProvider(bull_batch=bull, bear_batch=bear, scenario_batch=scenario)
    prompt_repo = FakePromptTemplateRepo()
    btc = _asset("BTC", "a1")
    candidates = [_screened("BTC", "a1")]

    _make_service(candidates, [btc], [_assessment_stub("a1")], provider, prompt_repo=prompt_repo).run("RUN-1")

    assert prompt_repo.calls == [("adversarial_research", "3f", "v1")]
