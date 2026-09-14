from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.config.settings import Settings
from app.database.models import Asset
from app.llm.assessment_agreement import compute_model_agreement, compute_return_dispersion
from app.llm.assessment_context import (
    AssetContext,
    AssessmentContext,
    _run_sanity_check,
    render_prompt,
)
from app.llm.assessment_provider import OpenRouterAssessmentProvider
from app.llm.assessment_schemas import AssessmentBatch, AssetAssessment
from app.llm.assessment_service import AssessmentService
from app.llm.cost import CostGuard, CostLedgerRepository
from app.market_data.schemas import MarketSnapshot
from app.market_data.screening_schemas import MarketRegimeSnapshot, ScreenedAsset

VALID_ASSESSMENT = dict(
    asset="BTC",
    assessment_timestamp="2026-09-05T00:00:00Z",
    horizon={"short_term_days": 7, "medium_term_days": 30, "long_term_days": 90},
    direction={"short_term": "BULLISH", "medium_term": "NEUTRAL", "long_term": "NEUTRAL"},
    confidence={"short_term": 0.6, "medium_term": 0.5, "long_term": 0.45},
    expected_return={"7d": 0.03, "30d": 0.05, "90d": 0.08},
    risk={"score": 0.5, "level": "MEDIUM"},
    market_regime="RISK_ON",
    key_drivers=[{"factor": "ETF inflows", "direction": "BULLISH", "importance": 0.7, "reason": "steady demand"}],
    key_risks=[{"factor": "macro", "direction": "BEARISH", "importance": 0.4, "reason": "rate risk"}],
    source_assessment=[{"source": "binance_funding_rate", "direction": "NEUTRAL", "importance": 0.3, "reason": "flat funding"}],
    thesis="Consolidating within an uptrend.",
    invalidation_conditions=["Break below $70k"],
    overall_assessment="BULLISH",
)


# --- schemas -----------------------------------------------------------------

def test_asset_assessment_accepts_valid_payload():
    a = AssetAssessment(**VALID_ASSESSMENT)
    assert a.overall_assessment == "BULLISH"
    assert a.expected_return.return_7d == 0.03


def test_asset_assessment_rejects_invalid_direction():
    bad = dict(VALID_ASSESSMENT, overall_assessment="MAYBE")
    with pytest.raises(ValidationError):
        AssetAssessment(**bad)


def test_asset_assessment_rejects_confidence_out_of_range():
    bad = dict(VALID_ASSESSMENT)
    bad["confidence"] = {"short_term": 1.5, "medium_term": 0.5, "long_term": 0.5}
    with pytest.raises(ValidationError):
        AssetAssessment(**bad)


def test_assessment_batch_parses_list():
    batch = AssessmentBatch(assessments=[VALID_ASSESSMENT, dict(VALID_ASSESSMENT, asset="ETH")])
    assert len(batch.assessments) == 2


# --- model agreement -----------------------------------------------------

def test_agreement_unanimous_is_one():
    assert compute_model_agreement(["BULLISH", "BULLISH", "BULLISH"]) == 1.0


def test_agreement_split_is_fractional():
    assert compute_model_agreement(["BULLISH", "BULLISH", "BEARISH"]) == pytest.approx(2 / 3)


def test_agreement_single_model_is_one():
    assert compute_model_agreement(["BULLISH"]) == 1.0


def test_agreement_empty_is_zero():
    assert compute_model_agreement([]) == 0.0


def test_agreement_even_split():
    assert compute_model_agreement(["BULLISH", "BEARISH"]) == pytest.approx(0.5)


# --- return dispersion (continuous complement to model_agreement) ----------

def test_dispersion_identical_returns_is_zero():
    assert compute_return_dispersion([0.05, 0.05, 0.05]) == pytest.approx(0.0)


def test_dispersion_reflects_real_spread():
    # Real population stdev of [0.05, 0.05, -0.35]: mean=-0.0833..,
    # differences squared summed/3, sqrt -- computed independently here
    # rather than re-deriving the implementation's own formula.
    import statistics
    values = [0.05, 0.05, -0.35]
    expected = statistics.pstdev(values)
    assert compute_return_dispersion(values) == pytest.approx(expected)


def test_dispersion_distinguishes_tight_from_wide_majority_splits():
    # Two 2-1 majority splits that compute_model_agreement scores IDENTICALLY
    # (both 0.667) but that clearly differ in real disagreement magnitude --
    # the whole point of this continuous complement.
    tight = compute_return_dispersion([0.05, 0.06, -0.02])
    wide = compute_return_dispersion([0.05, 0.06, -0.45])
    assert tight < wide


def test_dispersion_single_value_is_none():
    assert compute_return_dispersion([0.05]) is None


def test_dispersion_empty_is_none():
    assert compute_return_dispersion([]) is None


# --- sanity check (reuses 3b's anomaly detection) ---------------------------

class FakeSnapshotRepoForSanity:
    def __init__(self, snapshots):
        self._snapshots = snapshots  # newest-first, matching real repo's contract

    def get_recent_snapshots(self, asset_id, limit=10):
        return self._snapshots[:limit]

    def get_latest_snapshot(self, asset_id):
        return self._snapshots[0] if self._snapshots else None


def _snapshot(price, volume, ts):
    return MarketSnapshot(
        asset_id="a1", timestamp=ts, price=Decimal(str(price)), market_cap=Decimal("1000"),
        volume_24h=Decimal(str(volume)), price_change_24h=Decimal("1"),
        price_change_7d=Decimal("2"), price_change_30d=Decimal("3"),
    )


def test_sanity_check_flags_price_spike():
    now = datetime.now(UTC)
    # newest-first: big jump on the latest (first) entry
    snapshots = [_snapshot(300, 1000, now)] + [_snapshot(100, 1000, now) for _ in range(9)]
    flagged, reason = _run_sanity_check("a1", FakeSnapshotRepoForSanity(snapshots))
    assert flagged is True
    assert reason is not None


def test_sanity_check_passes_ordinary_data():
    now = datetime.now(UTC)
    snapshots = [_snapshot(100 + i, 1000, now) for i in range(10)]
    flagged, reason = _run_sanity_check("a1", FakeSnapshotRepoForSanity(snapshots))
    assert flagged is False


def test_sanity_check_insufficient_history_never_flags():
    now = datetime.now(UTC)
    snapshots = [_snapshot(100, 1000, now), _snapshot(300, 1000, now)]
    flagged, reason = _run_sanity_check("a1", FakeSnapshotRepoForSanity(snapshots))
    assert flagged is False


# --- prompt rendering ------------------------------------------------------

def _asset(symbol="BTC", asset_id="a1"):
    return Asset(
        id=asset_id, symbol=symbol, name=symbol, coingecko_id=symbol.lower(),
        active=True, in_asset=True, created_at=datetime.now(UTC),
    )


def _screened(symbol="BTC", asset_id="a1", score=0.7):
    return ScreenedAsset(
        run_id="RUN-1", computed_at=datetime.now(UTC), symbol=symbol, coingecko_id=symbol.lower(),
        asset_id=asset_id, composite_factor_score=score, is_top_candidate=True,
    )


def test_render_prompt_includes_shared_regime_and_sanity_warning():
    regime = MarketRegimeSnapshot(
        run_id="RUN-1", computed_at=datetime.now(UTC), regime="RISK_ON", inputs={"breadth_pct": 0.6},
    )
    context = AssessmentContext(
        run_id="RUN-1", as_of=datetime.now(UTC), regime=regime,
        assets=[AssetContext(
            asset=_asset(), screened=_screened(), snapshot=None,
            sanity_flagged=True, sanity_reason="test spike",
        )],
    )
    system_prompt, user_prompt = render_prompt(context, "v1")
    assert "RISK_ON" in user_prompt
    assert "DATA QUALITY WARNING" in user_prompt
    assert "test spike" in user_prompt
    assert "asset" in system_prompt.lower()


def test_render_prompt_includes_full_term_structure_curve_not_one_point():
    context = AssessmentContext(
        run_id="RUN-1", as_of=datetime.now(UTC), regime=None,
        assets=[AssetContext(
            asset=_asset(), screened=_screened(), snapshot=None,
            term_structure_by_source={
                "deribit_futures_term_structure": [
                    {"instrument": "BTC-25SEP26", "annualized_carry_yield": 0.04},
                    {"instrument": "BTC-25DEC26", "annualized_carry_yield": 0.05},
                    {"instrument": "BTC-26MAR27", "annualized_carry_yield": 0.06},
                ],
            },
        )],
    )
    _, user_prompt = render_prompt(context, "v1")
    assert "BTC-25SEP26" in user_prompt
    assert "BTC-25DEC26" in user_prompt
    assert "BTC-26MAR27" in user_prompt
    assert "3 distinct" in user_prompt


def test_render_prompt_deterministic_for_same_context():
    regime = MarketRegimeSnapshot(run_id="RUN-1", computed_at=datetime(2026, 1, 1, tzinfo=UTC), regime="NEUTRAL", inputs={})
    context = AssessmentContext(
        run_id="RUN-1", as_of=datetime(2026, 1, 1, tzinfo=UTC), regime=regime,
        assets=[AssetContext(asset=_asset(), screened=_screened(), snapshot=None)],
    )
    r1 = render_prompt(context, "v1")
    r2 = render_prompt(context, "v1")
    assert r1 == r2


# --- CostGuard registration (locked-decision requirement) -------------------

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


def test_cost_guard_reflects_model_market_assessments_row():
    client = FakeSupabaseClient({
        "model_market_assessments": [
            {"assessment_timestamp": datetime.now(UTC).isoformat(), "estimated_cost": "0.03"},
        ],
    })
    settings = Settings(_env_file=None, max_daily_llm_cost=Decimal("0.02"), max_monthly_llm_cost=Decimal("50"))
    guard = CostGuard(settings, CostLedgerRepository(client))
    allowed, reason = guard.check()
    assert allowed is False
    assert "Daily" in reason


# --- AssessmentService orchestration ----------------------------------------

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


class FakeRegimeRepo:
    def __init__(self, regime=None):
        self._regime = regime

    def get_latest(self):
        return self._regime


class FakeEvidenceRepoForService:
    def get_latest_by_asset(self, asset_id):
        return []


class FakeNewsRepoForService:
    def get_recent_relevant_news(self, symbols, since, until, limit_per_asset):
        return {}


class FakeAssetStatusRepoForService:
    def get_latest_status(self, asset_id):
        return None


class FakeSnapshotRepoForService:
    def get_latest_snapshot(self, asset_id):
        return None

    def get_recent_snapshots(self, asset_id, limit=10):
        return []


class FakePromptTemplateRepo:
    def __init__(self):
        self.calls = []
        self._next_id = 0

    def get_or_create(self, name, stage, version, template_hash):
        self.calls.append((name, stage, version))
        self._next_id += 1
        return f"template-{self._next_id}"


class FakeAssessmentRepo:
    def __init__(self):
        self.inserted = []

    def insert(self, record):
        self.inserted.append(record)


class FakeCostGuardForService:
    def __init__(self, allowed=True, reason=None):
        self._allowed = allowed
        self._reason = reason

    def check(self):
        return self._allowed, self._reason


class FakeAssessmentProvider:
    def __init__(self, name, result):
        self.name = name
        self.model = result.model
        self._result = result
        self.called = False

    def analyze(self, system_prompt, user_prompt):
        self.called = True
        return self._result


def _provider_result(provider, model, symbols, cost=Decimal("0.02"), error=None):
    from app.llm.assessment_provider import AssessmentProviderResult
    from app.llm.schemas import TokenUsage

    if error:
        return AssessmentProviderResult(
            provider=provider, model=model, batch=None, token_usage=None,
            estimated_cost=Decimal("0"), raw_response=None, error=error,
        )
    assessments = [dict(VALID_ASSESSMENT, asset=s) for s in symbols]
    return AssessmentProviderResult(
        provider=provider, model=model, batch=AssessmentBatch(assessments=assessments),
        token_usage=TokenUsage(prompt_tokens=100, completion_tokens=100),
        estimated_cost=cost, raw_response={"choices": [{"message": {"content": "{}"}}]}, error=None,
    )


def _make_service(top_candidates, assets, providers, prompt_repo=None, assessment_repo=None, cost_guard=None, regime=None):
    settings = Settings(_env_file=None)
    return AssessmentService(
        settings=settings,
        asset_repo=FakeAssetRepo(assets),
        screened_universe_repo=FakeScreenedUniverseRepoForService(top_candidates),
        regime_repo=FakeRegimeRepo(regime),
        evidence_repo=FakeEvidenceRepoForService(),
        news_repo=FakeNewsRepoForService(),
        asset_status_repo=FakeAssetStatusRepoForService(),
        snapshot_repo=FakeSnapshotRepoForService(),
        prompt_template_repo=prompt_repo or FakePromptTemplateRepo(),
        assessment_repo=assessment_repo or FakeAssessmentRepo(),
        cost_guard=cost_guard or FakeCostGuardForService(allowed=True),
        providers=providers,
    )


def test_service_returns_empty_when_no_top_candidates():
    service = _make_service(top_candidates=[], assets=[], providers=[])
    result = service.run("RUN-1")
    assert result.stored_by_provider == {}
    assert result.assessed_assets == []


def test_service_stores_one_row_per_asset_per_provider():
    btc = _asset("BTC", "a1")
    top = [_screened("BTC", "a1")]
    provider = FakeAssessmentProvider("claude", _provider_result("claude", "model-x", ["BTC"]))
    assessment_repo = FakeAssessmentRepo()

    service = _make_service(top, [btc], [provider], assessment_repo=assessment_repo)
    result = service.run("RUN-1")

    assert result.stored_by_provider == {"claude": 1}
    assert len(assessment_repo.inserted) == 1
    assert assessment_repo.inserted[0].asset_id == "a1"


def test_service_computes_agreement_across_providers():
    btc = _asset("BTC", "a1")
    top = [_screened("BTC", "a1")]
    bullish = dict(VALID_ASSESSMENT, asset="BTC", overall_assessment="BULLISH")
    bearish = dict(VALID_ASSESSMENT, asset="BTC", overall_assessment="BEARISH")

    from app.llm.assessment_provider import AssessmentProviderResult
    from app.llm.schemas import TokenUsage

    p1 = FakeAssessmentProvider("claude", AssessmentProviderResult(
        provider="claude", model="m1", batch=AssessmentBatch(assessments=[bullish]),
        token_usage=TokenUsage(prompt_tokens=10, completion_tokens=10),
        estimated_cost=Decimal("0.01"), raw_response={}, error=None,
    ))
    p2 = FakeAssessmentProvider("openai", AssessmentProviderResult(
        provider="openai", model="m2", batch=AssessmentBatch(assessments=[bearish]),
        token_usage=TokenUsage(prompt_tokens=10, completion_tokens=10),
        estimated_cost=Decimal("0.01"), raw_response={}, error=None,
    ))
    assessment_repo = FakeAssessmentRepo()

    service = _make_service(top, [btc], [p1, p2], assessment_repo=assessment_repo)
    service.run("RUN-1")

    assert all(r.model_agreement == pytest.approx(0.5) for r in assessment_repo.inserted)


def test_service_computes_return_dispersion_across_providers():
    btc = _asset("BTC", "a1")
    top = [_screened("BTC", "a1")]
    low_return = dict(VALID_ASSESSMENT, asset="BTC", expected_return={"7d": 0.03, "30d": 0.05, "90d": 0.08})
    high_return = dict(VALID_ASSESSMENT, asset="BTC", expected_return={"7d": 0.03, "30d": -0.15, "90d": 0.08})

    from app.llm.assessment_provider import AssessmentProviderResult
    from app.llm.schemas import TokenUsage

    p1 = FakeAssessmentProvider("claude", AssessmentProviderResult(
        provider="claude", model="m1", batch=AssessmentBatch(assessments=[low_return]),
        token_usage=TokenUsage(prompt_tokens=10, completion_tokens=10),
        estimated_cost=Decimal("0.01"), raw_response={}, error=None,
    ))
    p2 = FakeAssessmentProvider("openai", AssessmentProviderResult(
        provider="openai", model="m2", batch=AssessmentBatch(assessments=[high_return]),
        token_usage=TokenUsage(prompt_tokens=10, completion_tokens=10),
        estimated_cost=Decimal("0.01"), raw_response={}, error=None,
    ))
    assessment_repo = FakeAssessmentRepo()

    service = _make_service(top, [btc], [p1, p2], assessment_repo=assessment_repo)
    service.run("RUN-1")

    import statistics
    expected = statistics.pstdev([0.05, -0.15])
    assert all(r.expected_return_dispersion_30d == pytest.approx(expected) for r in assessment_repo.inserted)


def test_service_one_provider_failure_does_not_block_others():
    btc = _asset("BTC", "a1")
    top = [_screened("BTC", "a1")]
    failing = FakeAssessmentProvider("claude", _provider_result("claude", "m1", [], error="boom"))
    working = FakeAssessmentProvider("openai", _provider_result("openai", "m2", ["BTC"]))
    assessment_repo = FakeAssessmentRepo()

    service = _make_service(top, [btc], [failing, working], assessment_repo=assessment_repo)
    result = service.run("RUN-1")

    assert result.failed == [("claude", "boom")]
    assert result.stored_by_provider == {"openai": 1}


def test_service_skips_provider_when_cost_cap_exceeded():
    btc = _asset("BTC", "a1")
    top = [_screened("BTC", "a1")]
    provider = FakeAssessmentProvider("claude", _provider_result("claude", "m1", ["BTC"]))

    service = _make_service(
        top, [btc], [provider], cost_guard=FakeCostGuardForService(allowed=False, reason="cap reached"),
    )
    result = service.run("RUN-1")

    assert result.skipped_cost_cap == ["claude"]
    assert provider.called is False


def test_service_registers_prompt_template_with_correct_stage():
    btc = _asset("BTC", "a1")
    top = [_screened("BTC", "a1")]
    provider = FakeAssessmentProvider("claude", _provider_result("claude", "m1", ["BTC"]))
    prompt_repo = FakePromptTemplateRepo()

    service = _make_service(top, [btc], [provider], prompt_repo=prompt_repo)
    service.run("RUN-1")

    assert prompt_repo.calls == [("market_assessment", "3d", "v2")]


def test_service_unknown_asset_symbol_skipped_gracefully():
    btc = _asset("BTC", "a1")
    top = [_screened("BTC", "a1")]
    provider = FakeAssessmentProvider("claude", _provider_result("claude", "m1", ["BTC", "DOGE"]))
    assessment_repo = FakeAssessmentRepo()

    service = _make_service(top, [btc], [provider], assessment_repo=assessment_repo)
    result = service.run("RUN-1")

    assert result.stored_by_provider == {"claude": 1}
    assert len(assessment_repo.inserted) == 1


# --- OpenRouterAssessmentProvider (HTTP + retry, mirrors Phase 2's tested pattern) --

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


def test_assessment_provider_valid_response_no_retry(monkeypatch):
    import json

    calls = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs)
        return FakeHttpResponse(_chat_payload(json.dumps({"assessments": [VALID_ASSESSMENT]})))

    monkeypatch.setattr("app.llm.assessment_provider.httpx.post", fake_post)

    provider = OpenRouterAssessmentProvider(
        name="claude", model="anthropic/claude-sonnet-5", api_key="key",
        base_url="https://openrouter.ai/api/v1", timeout_seconds=10,
    )
    result = provider.analyze("system", "user")

    assert len(calls) == 1
    assert result.error is None
    assert result.batch.assessments[0].asset == "BTC"


def test_assessment_provider_retries_once_then_succeeds(monkeypatch):
    responses = [
        FakeHttpResponse(_chat_payload("not json")),
        FakeHttpResponse(_chat_payload('{"assessments": []}')),
    ]
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs)
        return responses.pop(0)

    monkeypatch.setattr("app.llm.assessment_provider.httpx.post", fake_post)

    provider = OpenRouterAssessmentProvider(
        name="claude", model="anthropic/claude-sonnet-5", api_key="key",
        base_url="https://openrouter.ai/api/v1", timeout_seconds=10,
    )
    result = provider.analyze("system", "user")

    assert len(calls) == 2
    assert result.error is None
    assert result.batch.assessments == []
    assert result.token_usage.prompt_tokens == 200
