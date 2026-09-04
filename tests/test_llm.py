import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from pydantic import ValidationError

from app.config.settings import Settings
from app.database.models import Asset
from app.llm.cost import DEFAULT_PRICING, CostGuard, compute_cost
from app.llm.provider import ProviderResult
from app.llm.research_context import build_research_context, compute_input_hash, render_prompt
from app.llm.openrouter_client import OpenRouterProvider
from app.llm.schemas import AnalysisBatch, InvestmentAnalysis, TokenUsage
from app.llm.service import LLMResearchService
from app.market_data.schemas import MarketSnapshot

# --- schemas ---------------------------------------------------------------

VALID_ANALYSIS = dict(
    asset_symbol="BTC",
    action="BUY",
    confidence=0.7,
    target_allocation=0.2,
    investment_horizon="medium term",
    thesis="ETF inflows strong",
    bull_case="Institutional demand",
    bear_case="Macro risk",
    catalysts=["ETF approval"],
    risks=["Regulation"],
    invalidation_conditions=["Inflows reverse"],
)


def test_investment_analysis_accepts_valid_payload():
    analysis = InvestmentAnalysis(**VALID_ANALYSIS)
    assert analysis.action == "BUY"


def test_investment_analysis_rejects_invalid_action():
    bad = dict(VALID_ANALYSIS, action="MAYBE")
    with pytest.raises(ValidationError):
        InvestmentAnalysis(**bad)


def test_investment_analysis_rejects_confidence_out_of_range():
    bad = dict(VALID_ANALYSIS, confidence=1.5)
    with pytest.raises(ValidationError):
        InvestmentAnalysis(**bad)


def test_analysis_batch_parses_list():
    batch = AnalysisBatch(analyses=[VALID_ANALYSIS, dict(VALID_ANALYSIS, asset_symbol="ETH")])
    assert len(batch.analyses) == 2


# --- cost --------------------------------------------------------------------

def test_compute_cost_known_model():
    cost = compute_cost("anthropic/claude-sonnet-5", 1000, 1000)
    assert cost == Decimal("0.002") + Decimal("0.01")


def test_compute_cost_unknown_model_uses_default():
    cost = compute_cost("some/unknown-model", 1000, 1000)
    expected = DEFAULT_PRICING[0] + DEFAULT_PRICING[1]
    assert cost == expected


def test_compute_cost_zero_tokens_is_zero():
    assert compute_cost("anthropic/claude-sonnet-4.5", 0, 0) == Decimal("0")


class FakeLLMAnalysisRepo:
    def __init__(self, daily=Decimal("0"), monthly=Decimal("0")):
        self._daily = daily
        self._monthly = monthly
        self.inserted = []

    def get_cost_sum_since(self, since):
        # Crude but sufficient for tests: treat "since >= start of today" as
        # the daily query, otherwise the monthly one.
        now = datetime.now(UTC)
        if since.date() == now.date():
            return self._daily
        return self._monthly

    def insert_analysis(self, record):
        self.inserted.append(record)


def test_cost_guard_allows_when_under_caps():
    settings = Settings(_env_file=None, max_daily_llm_cost=Decimal("5"), max_monthly_llm_cost=Decimal("50"))
    guard = CostGuard(settings, FakeLLMAnalysisRepo(daily=Decimal("1"), monthly=Decimal("10")))
    allowed, reason = guard.check()
    assert allowed is True
    assert reason is None


def test_cost_guard_blocks_when_daily_cap_reached():
    settings = Settings(_env_file=None, max_daily_llm_cost=Decimal("5"), max_monthly_llm_cost=Decimal("50"))
    guard = CostGuard(settings, FakeLLMAnalysisRepo(daily=Decimal("5"), monthly=Decimal("10")))
    allowed, reason = guard.check()
    assert allowed is False
    assert "Daily" in reason


def test_cost_guard_blocks_when_monthly_cap_reached():
    settings = Settings(_env_file=None, max_daily_llm_cost=Decimal("5"), max_monthly_llm_cost=Decimal("50"))
    guard = CostGuard(settings, FakeLLMAnalysisRepo(daily=Decimal("1"), monthly=Decimal("50")))
    allowed, reason = guard.check()
    assert allowed is False
    assert "Monthly" in reason


# --- research context / prompt ------------------------------------------------

def _asset(symbol, name, asset_id=None):
    return Asset(
        id=asset_id or f"id-{symbol}",
        symbol=symbol,
        name=name,
        coingecko_id=symbol.lower(),
        active=True,
        in_asset=True,
        created_at=datetime.now(UTC),
    )


class FakeSnapshotRepo:
    def __init__(self, snapshots):
        self._snapshots = snapshots

    def get_latest_snapshot(self, asset_id):
        return self._snapshots.get(asset_id)


class FakeNewsRepoForContext:
    def __init__(self):
        self.calls = []

    def get_recent_relevant_news(self, symbols, since, until, limit_per_asset):
        self.calls.append((symbols, since, until, limit_per_asset))
        return {}


def test_build_research_context_enforces_lookback_window_and_cutoff():
    settings = Settings(_env_file=None, news_lookback_hours=24, max_news_articles_per_asset=5)
    assets = [_asset("BTC", "Bitcoin")]
    news_repo = FakeNewsRepoForContext()
    snapshot_repo = FakeSnapshotRepo({})

    context = build_research_context("RUN-1", settings, assets, snapshot_repo, news_repo)

    assert len(news_repo.calls) == 1
    symbols, since, until, limit = news_repo.calls[0]
    assert symbols == ["BTC"]
    assert limit == 5
    assert until == context.as_of
    assert (until - since) == timedelta(hours=24)


def test_render_prompt_and_hash_deterministic_for_same_context():
    assets = [_asset("BTC", "Bitcoin", asset_id="a1")]
    snapshot = MarketSnapshot(
        asset_id="a1", timestamp=datetime.now(UTC), price=Decimal("100"),
        market_cap=Decimal("1000"), volume_24h=Decimal("10"),
        price_change_24h=Decimal("1"), price_change_7d=Decimal("2"), price_change_30d=Decimal("3"),
    )
    from app.llm.research_context import ResearchContext

    context = ResearchContext(
        run_id="RUN-1", as_of=datetime(2026, 9, 3, tzinfo=UTC), assets=assets,
        market_snapshots={"a1": snapshot}, news_by_symbol={},
    )

    system1, user1 = render_prompt(context, "v1")
    system2, user2 = render_prompt(context, "v1")
    assert compute_input_hash(system1, user1) == compute_input_hash(system2, user2)

    system3, user3 = render_prompt(context, "v2")
    assert compute_input_hash(system1, user1) != compute_input_hash(system3, user3)


# --- LLMResearchService --------------------------------------------------------

class FakeAssetRepo:
    def __init__(self, assets):
        self._assets = assets

    def get_active_assets(self):
        return self._assets


class FakeCostGuard:
    def __init__(self, allowed=True, reason=None):
        self._allowed = allowed
        self._reason = reason

    def check(self):
        return self._allowed, self._reason


class FakeProvider:
    def __init__(self, name, result: ProviderResult):
        self.name = name
        self.model = result.model
        self._result = result
        self.called_with = None

    def analyze(self, system_prompt, user_prompt):
        self.called_with = (system_prompt, user_prompt)
        return self._result


def _provider_result(provider, model, symbols, cost=Decimal("0.01"), error=None):
    if error:
        return ProviderResult(
            provider=provider, model=model, batch=None, token_usage=None,
            estimated_cost=Decimal("0"), raw_response=None, error=error,
        )
    analyses = [dict(VALID_ANALYSIS, asset_symbol=s) for s in symbols]
    return ProviderResult(
        provider=provider, model=model, batch=AnalysisBatch(analyses=analyses),
        token_usage=TokenUsage(prompt_tokens=100, completion_tokens=100),
        estimated_cost=cost, raw_response={"choices": [{"message": {"content": "{}"}}]}, error=None,
    )


def _llm_service(assets, providers, llm_repo=None, cost_guard=None):
    settings = Settings(_env_file=None)
    return LLMResearchService(
        settings=settings,
        asset_repo=FakeAssetRepo(assets),
        snapshot_repo=FakeSnapshotRepo({}),
        news_repo=FakeNewsRepoForContext(),
        llm_repo=llm_repo or FakeLLMAnalysisRepo(),
        cost_guard=cost_guard or FakeCostGuard(allowed=True),
        providers=providers,
    )


def test_service_stores_one_row_per_asset_per_successful_provider():
    assets = [_asset("BTC", "Bitcoin", "a1"), _asset("ETH", "Ethereum", "a2")]
    provider = FakeProvider("claude", _provider_result("claude", "model-x", ["BTC", "ETH"]))
    llm_repo = FakeLLMAnalysisRepo()

    result = _llm_service(assets, [provider], llm_repo=llm_repo).run("RUN-1")

    assert result.stored_by_provider == {"claude": 2}
    assert len(llm_repo.inserted) == 2
    assert {r.asset_id for r in llm_repo.inserted} == {"a1", "a2"}


def test_service_cost_split_evenly_across_batch_items():
    assets = [_asset("BTC", "Bitcoin", "a1"), _asset("ETH", "Ethereum", "a2")]
    provider = FakeProvider("claude", _provider_result("claude", "model-x", ["BTC", "ETH"], cost=Decimal("0.10")))
    llm_repo = FakeLLMAnalysisRepo()

    _llm_service(assets, [provider], llm_repo=llm_repo).run("RUN-1")

    assert all(r.estimated_cost == Decimal("0.05") for r in llm_repo.inserted)


def test_service_one_provider_failure_does_not_block_others():
    assets = [_asset("BTC", "Bitcoin", "a1")]
    failing = FakeProvider("claude", _provider_result("claude", "model-x", [], error="boom"))
    working = FakeProvider("openai", _provider_result("openai", "model-y", ["BTC"]))
    llm_repo = FakeLLMAnalysisRepo()

    result = _llm_service(assets, [failing, working], llm_repo=llm_repo).run("RUN-1")

    assert result.failed == [("claude", "boom")]
    assert result.stored_by_provider == {"openai": 1}


def test_service_skips_provider_when_cost_cap_exceeded():
    assets = [_asset("BTC", "Bitcoin", "a1")]
    provider = FakeProvider("claude", _provider_result("claude", "model-x", ["BTC"]))

    result = _llm_service(
        assets, [provider], cost_guard=FakeCostGuard(allowed=False, reason="cap reached")
    ).run("RUN-1")

    assert result.skipped_cost_cap == ["claude"]
    assert result.stored_by_provider == {}
    assert provider.called_with is None


def test_service_skips_unknown_asset_symbol_from_provider():
    assets = [_asset("BTC", "Bitcoin", "a1")]
    provider = FakeProvider("claude", _provider_result("claude", "model-x", ["BTC", "DOGE"]))
    llm_repo = FakeLLMAnalysisRepo()

    result = _llm_service(assets, [provider], llm_repo=llm_repo).run("RUN-1")

    assert result.stored_by_provider == {"claude": 1}
    assert len(llm_repo.inserted) == 1


def test_service_no_active_assets_returns_empty_result():
    provider = FakeProvider("claude", _provider_result("claude", "model-x", ["BTC"]))
    result = _llm_service([], [provider]).run("RUN-1")
    assert result.stored_by_provider == {}
    assert provider.called_with is None


# --- OpenRouterProvider (HTTP + retry-once behavior) ---------------------------

class FakeHttpResponse:
    def __init__(self, payload, status_ok=True):
        self._payload = payload
        self._status_ok = status_ok

    def raise_for_status(self):
        if not self._status_ok:
            raise httpx.HTTPStatusError("error", request=None, response=None)

    def json(self):
        return self._payload


def _chat_payload(content: str, prompt_tokens=100, completion_tokens=50):
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


def _provider():
    return OpenRouterProvider(
        name="claude", model="anthropic/claude-sonnet-4.5", api_key="key",
        base_url="https://openrouter.ai/api/v1", timeout_seconds=10,
    )


def test_openrouter_provider_valid_response_no_retry(monkeypatch):
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs)
        return FakeHttpResponse(_chat_payload(json.dumps({"analyses": [VALID_ANALYSIS]})))

    monkeypatch.setattr("app.llm.openrouter_client.httpx.post", fake_post)

    result = _provider().analyze("system", "user")

    assert len(calls) == 1
    assert result.error is None
    assert result.batch is not None
    assert result.token_usage.prompt_tokens == 100


def test_openrouter_provider_retries_once_then_succeeds(monkeypatch):
    responses = [
        FakeHttpResponse(_chat_payload("not json")),
        FakeHttpResponse(_chat_payload('{"analyses": []}')),
    ]
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs)
        return responses.pop(0)

    monkeypatch.setattr("app.llm.openrouter_client.httpx.post", fake_post)

    result = _provider().analyze("system", "user")

    assert len(calls) == 2
    assert result.error is None
    assert result.batch.analyses == []
    # token usage accumulated across both attempts
    assert result.token_usage.prompt_tokens == 200


def test_openrouter_provider_fails_after_two_invalid_attempts(monkeypatch):
    def fake_post(*args, **kwargs):
        return FakeHttpResponse(_chat_payload("still not json"))

    monkeypatch.setattr("app.llm.openrouter_client.httpx.post", fake_post)

    result = _provider().analyze("system", "user")

    assert result.error is not None
    assert result.batch is None
    assert result.token_usage.prompt_tokens == 200  # both attempts counted


def test_openrouter_provider_handles_http_error_gracefully(monkeypatch):
    def fake_post(*args, **kwargs):
        return FakeHttpResponse({}, status_ok=False)

    monkeypatch.setattr("app.llm.openrouter_client.httpx.post", fake_post)

    result = _provider().analyze("system", "user")

    assert result.error is not None
    assert result.batch is None
