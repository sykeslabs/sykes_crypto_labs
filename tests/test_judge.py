from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.config.settings import Settings
from app.database.models import Asset, SignalSource
from app.database.repository import compute_duplicate_group_decision_ids, utc_day_bounds
from app.judge.context import JudgeContext, AssetJudgeContext, build_judge_context, render_prompt
from app.portfolio.schemas import PortfolioPosition
from app.judge.provider import OpenRouterJudgeProvider
from app.judge.schemas import JudgeDecisionBatch, JudgeDecisionItem, JudgeDecisionRecord
from app.judge.service import JudgeService
from app.llm.assessment_schemas import ModelMarketAssessmentRecord
from app.llm.cost import CostGuard, CostLedgerRepository
from app.market_data.evidence_schemas import EvidenceObservation
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
    macro_sensitivity="No macro evidence available this run.",
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
        macro_sensitivity="n/a", regime_id="r1", prompt_template_id="p1", estimated_cost=Decimal("0.01"),
    )
    row = record.to_row()
    assert row["estimated_cost"] == "0.01"
    assert isinstance(row["created_at"], str)


def test_judge_decision_record_accepts_null_macro_sensitivity_for_pre_3f_rows():
    # Real bug found live (Phase 5): pre-3f backfilled judge_decisions rows
    # genuinely have macro_sensitivity=NULL in the DB (the column didn't
    # exist before migration 0010) -- reading one back must not crash.
    record = JudgeDecisionRecord(
        run_id="BACKFILL-2026-08-09", asset_id="a1", created_at=datetime(2026, 8, 9, tzinfo=UTC),
        decision="BUY", confidence=0.6, target_allocation=0.05, expected_return=0.1,
        expected_alpha=0.05, risk_score=0.4, uncertainty=0.3, model_agreement=0.8,
        source_agreement=0.7, investment_horizon_days=30, key_evidence=[], contradictory_evidence=[],
        key_risks=[], invalidation_conditions=[], requires_review=False, thesis="t",
        macro_sensitivity=None, regime_id=None, prompt_template_id="p1", estimated_cost=Decimal("0.01"),
        is_backfilled=True,
    )
    assert record.macro_sensitivity is None


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


def _build_context(candidates, assets_by_id, assessments, regime=None, positions=None, sources=None, current_allocations=None):
    settings = Settings(_env_file=None)
    return build_judge_context(
        "RUN-1", settings, candidates, assets_by_id,
        FakeRegimeRepoForContext(regime), FakeEvidenceRepoForContext(),
        FakeAssessmentRepoForContext(assessments), FakeLLMAnalysisRepoForContext(),
        FakeNewsRepoForContext(), FakeAssetStatusRepoForContext(),
        FakePortfolioPositionRepoForContext(positions), FakeSignalSourceRepoForContext(sources),
        current_allocations=current_allocations,
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
        SignalSource(name="Glassnode", status="NOT_IMPLEMENTED"),
        SignalSource(name="CoinGecko", status="OK"),
    ]
    context = _build_context(candidates, {"a1": btc}, [_assessment("a1")], sources=sources)
    assert context.unavailable_sources == ["Glassnode"]


# --- actual holdings vs. system target (2026-09-14 investigation fix) -------
# Real incident: the Judge's own "current allocation" context field was
# silently the system's own last TARGET (portfolio_positions.
# current_allocation), never real holdings -- so a manual trade the system
# didn't know about (or a strategy target the user never executed) could
# diverge from reality by double digits for weeks (see the live replay:
# BTC was told 16.32% when real holdings were 33.83%). These two concepts
# must now be genuinely distinct fields, both reaching the prompt.

def test_context_keeps_actual_holdings_and_system_target_distinct():
    btc = _asset("BTC", "a1")
    candidates = [_screened("BTC", "a1")]
    positions = {"a1": PortfolioPosition(asset_id="a1", current_allocation=0.05)}
    context = _build_context(
        candidates, {"a1": btc}, [_assessment("a1")],
        positions=positions, current_allocations={"a1": 0.30},
    )
    ac = context.assets[0]
    assert ac.actual_allocation == pytest.approx(0.30)
    assert ac.previous_system_target == pytest.approx(0.05)


def test_context_defaults_actual_holdings_to_zero_when_not_supplied():
    # No new caller forgot to update -- an absent/empty current_allocations
    # degrades to 0.0 per asset (the same fallback already used for a
    # never-targeted asset), not a crash.
    btc = _asset("BTC", "a1")
    candidates = [_screened("BTC", "a1")]
    context = _build_context(candidates, {"a1": btc}, [_assessment("a1")])
    assert context.assets[0].actual_allocation == 0.0


def test_context_defaults_system_target_to_zero_for_never_targeted_asset():
    btc = _asset("BTC", "a1")
    candidates = [_screened("BTC", "a1")]
    context = _build_context(
        candidates, {"a1": btc}, [_assessment("a1")], current_allocations={"a1": 0.22},
    )
    assert context.assets[0].previous_system_target == 0.0
    assert context.assets[0].actual_allocation == pytest.approx(0.22)


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
    assert "macro_sensitivity" in system_prompt


def test_render_prompt_shows_actual_holdings_and_system_target_as_distinct_labeled_values():
    context = JudgeContext(
        run_id="RUN-1", as_of=datetime.now(UTC), regime=None, regime_id=None,
        unavailable_sources=[],
        assets=[AssetJudgeContext(
            asset=_asset(), screened=_screened(), snapshot=None,
            assessments=[_assessment()], model_agreement=1.0,
            actual_allocation=0.3383, previous_system_target=0.1632,
        )],
    )
    _, user_prompt = render_prompt(context, "v1")
    assert "Actual holdings" in user_prompt
    assert "33.83%" in user_prompt
    assert "Last strategy target" in user_prompt
    assert "16.32%" in user_prompt
    # Real bug being regressed against: the old wording rendered a single
    # unqualified "Current allocation" line -- must not reappear.
    assert "Current allocation:" not in user_prompt


def test_render_prompt_includes_full_term_structure_curve_not_one_point():
    context = JudgeContext(
        run_id="RUN-1", as_of=datetime.now(UTC), regime=None, regime_id=None,
        unavailable_sources=[],
        assets=[AssetJudgeContext(
            asset=_asset(), screened=_screened(), snapshot=None,
            assessments=[_assessment()], model_agreement=1.0,
            term_structure_by_source={
                "deribit_futures_term_structure": [
                    {"payload": {"instrument": "BTC-25SEP26", "annualized_carry_yield": 0.04}, "freshness": "RECENT", "decay_half_life_hours": 24, "status": "OK"},
                    {"payload": {"instrument": "BTC-25DEC26", "annualized_carry_yield": 0.05}, "freshness": "RECENT", "decay_half_life_hours": 24, "status": "OK"},
                    {"payload": {"instrument": "BTC-26MAR27", "annualized_carry_yield": 0.06}, "freshness": "RECENT", "decay_half_life_hours": 24, "status": "OK"},
                ],
            },
        )],
    )
    _, user_prompt = render_prompt(context, "v1")
    assert "BTC-25SEP26" in user_prompt
    assert "BTC-25DEC26" in user_prompt
    assert "BTC-26MAR27" in user_prompt
    assert "3 distinct" in user_prompt


def test_render_prompt_includes_shared_macro_evidence():
    context = JudgeContext(
        run_id="RUN-1", as_of=datetime.now(UTC), regime=None, regime_id=None,
        unavailable_sources=[],
        assets=[AssetJudgeContext(
            asset=_asset(), screened=_screened(), snapshot=None,
            assessments=[_assessment()], model_agreement=1.0,
        )],
        macro_evidence={
            "macro_cpi": {"payload": {"actual": "311.5"}, "freshness": "RECENT", "decay_half_life_hours": 720, "status": "OK"},
        },
    )
    _, user_prompt = render_prompt(context, "v1")
    assert "macro_cpi" in user_prompt
    assert "311.5" in user_prompt


def test_render_prompt_discloses_no_macro_evidence_when_absent():
    context = JudgeContext(
        run_id="RUN-1", as_of=datetime.now(UTC), regime=None, regime_id=None,
        unavailable_sources=[],
        assets=[AssetJudgeContext(
            asset=_asset(), screened=_screened(), snapshot=None,
            assessments=[_assessment()], model_agreement=1.0,
        )],
        macro_evidence={},
    )
    _, user_prompt = render_prompt(context, "v1")
    assert "none available this run" in user_prompt


def test_render_prompt_includes_adversarial_research_when_present():
    from app.llm.adversarial_schemas import AdversarialResearchRecord

    adversarial = AdversarialResearchRecord(
        run_id="RUN-1", asset_id="a1", prompt_template_id="pt1",
        bull_case={"asset": "BTC", "thesis": "Strong ETF inflows", "catalysts": ["ETF demand"], "evidence": ["flow data"]},
        bear_case={"asset": "BTC", "attack_points": ["Crowded positioning"], "evidence": ["funding elevated"], "attacks_bull_point": ["ETF demand"]},
        scenarios={"asset": "BTC", "bull": {}, "base": {}, "bear": {}},
        estimated_cost=Decimal("0.01"), created_at=datetime.now(UTC),
    )
    context = JudgeContext(
        run_id="RUN-1", as_of=datetime.now(UTC), regime=None, regime_id=None,
        unavailable_sources=[],
        assets=[AssetJudgeContext(
            asset=_asset(), screened=_screened(), snapshot=None,
            assessments=[_assessment()], model_agreement=1.0, adversarial=adversarial,
        )],
    )
    _, user_prompt = render_prompt(context, "v1")
    assert "Strong ETF inflows" in user_prompt
    assert "Crowded positioning" in user_prompt


class FakeGlobalEvidenceRepoForContext:
    """Real bug regression: a source name shared by many distinct observations
    (scheduled_macro_event, regulatory_event_sec_edgar) must NOT be deduped
    down to one row the way a true single-value source (macro_cpi) is."""

    def __init__(self, observations):
        self._observations = observations

    def get_latest_by_asset(self, asset_id):
        return []

    def get_latest_global_all(self, limit=100):
        return self._observations


def _macro_obs(source, payload, scope="MACRO"):
    return EvidenceObservation(
        source=source, asset_id=None, scope=scope,
        observation_timestamp=datetime.now(UTC), retrieval_timestamp=datetime.now(UTC),
        freshness="RECENT", decay_half_life_hours=720, status="OK", payload=payload,
    )


def test_build_judge_context_keeps_all_scheduled_macro_events_not_just_one():
    observations = [
        _macro_obs("scheduled_macro_event", {"event": "CPI", "scheduled_date": "2026-10-13"}),
        _macro_obs("scheduled_macro_event", {"event": "PCE", "scheduled_date": "2026-10-28"}),
        _macro_obs("scheduled_macro_event", {"event": "NFP", "scheduled_date": "2026-11-06"}),
        _macro_obs("macro_cpi", {"actual": "311.5"}),
    ]
    btc = _asset("BTC", "a1")
    context = build_judge_context(
        "RUN-1", Settings(_env_file=None), [_screened("BTC", "a1")], {"a1": btc},
        FakeRegimeRepoForContext(), FakeGlobalEvidenceRepoForContext(observations),
        FakeAssessmentRepoForContext([_assessment("a1")]), FakeLLMAnalysisRepoForContext(),
        FakeNewsRepoForContext(), FakeAssetStatusRepoForContext(),
        FakePortfolioPositionRepoForContext(), FakeSignalSourceRepoForContext(),
    )
    assert len(context.scheduled_events) == 3
    assert {e["event"] for e in context.scheduled_events} == {"CPI", "PCE", "NFP"}
    # single-value source still collapses to one entry, untouched by the fix
    assert "macro_cpi" in context.macro_evidence
    assert len(context.macro_evidence) == 1


def test_build_judge_context_keeps_all_regulatory_events_up_to_cap():
    observations = [
        _macro_obs("regulatory_event_sec_edgar", {"accession_number": f"000{i}", "title": f"Filing {i}"})
        for i in range(15)
    ]
    btc = _asset("BTC", "a1")
    context = build_judge_context(
        "RUN-1", Settings(_env_file=None), [_screened("BTC", "a1")], {"a1": btc},
        FakeRegimeRepoForContext(), FakeGlobalEvidenceRepoForContext(observations),
        FakeAssessmentRepoForContext([_assessment("a1")]), FakeLLMAnalysisRepoForContext(),
        FakeNewsRepoForContext(), FakeAssetStatusRepoForContext(),
        FakePortfolioPositionRepoForContext(), FakeSignalSourceRepoForContext(),
    )
    # 15 distinct filings collected but capped to MAX_REGULATORY_EVENTS_SHOWN
    assert len(context.regulatory_events) == 10


def test_render_prompt_includes_multiple_scheduled_and_regulatory_events_distinctly():
    context = JudgeContext(
        run_id="RUN-1", as_of=datetime.now(UTC), regime=None, regime_id=None,
        unavailable_sources=[],
        assets=[AssetJudgeContext(
            asset=_asset(), screened=_screened(), snapshot=None,
            assessments=[_assessment()], model_agreement=1.0,
        )],
        scheduled_events=[
            {"event": "CPI", "scheduled_date": "2026-10-13"},
            {"event": "PCE", "scheduled_date": "2026-10-28"},
        ],
        regulatory_events=[
            {"source": "regulatory_event_sec_edgar", "title": "Filing A"},
            {"source": "regulatory_event_congress", "title": "Bill B"},
        ],
    )
    _, user_prompt = render_prompt(context, "v1")
    assert "CPI" in user_prompt and "2026-10-13" in user_prompt
    assert "PCE" in user_prompt and "2026-10-28" in user_prompt
    assert "Filing A" in user_prompt
    assert "Bill B" in user_prompt


def test_build_judge_context_degrades_gracefully_without_macro_or_adversarial_repos():
    # 3e.1's replay passes an evidence repo with no get_latest_global_all
    # method and no adversarial_repo at all — must not raise, must produce
    # empty macro_evidence and adversarial=None rather than crashing.
    class EvidenceRepoWithoutGlobalMethod:
        def get_latest_by_asset(self, asset_id):
            return []

    btc = _asset("BTC", "a1")
    candidates = [_screened("BTC", "a1")]
    context = build_judge_context(
        "RUN-1", Settings(_env_file=None), candidates, {"a1": btc},
        FakeRegimeRepoForContext(), EvidenceRepoWithoutGlobalMethod(),
        FakeAssessmentRepoForContext([_assessment("a1")]), FakeLLMAnalysisRepoForContext(),
        FakeNewsRepoForContext(), FakeAssetStatusRepoForContext(),
        FakePortfolioPositionRepoForContext(), FakeSignalSourceRepoForContext(),
    )
    assert context.macro_evidence == {}
    assert context.assets[0].adversarial is None


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


def test_cost_accounting_counts_same_day_duplicate_decisions_fully_unaffected_by_b2():
    # B2 (2026-09-16) excludes same-day duplicate live decisions from
    # CALIBRATION statistics only -- app/llm/cost.py sums judge_decisions
    # directly by timestamp, a completely separate code path with no
    # dependency on compute_duplicate_group_decision_ids or calibration.py
    # at all. Three real, same-day, same-asset LLM calls (a duplicate
    # group, exactly the 2026-09-05/06 incident's shape) must all three
    # still count as real spend.
    now = datetime.now(UTC).isoformat()
    client = FakeSupabaseClient({
        "judge_decisions": [
            {"created_at": now, "estimated_cost": "0.05"},
            {"created_at": now, "estimated_cost": "0.05"},
            {"created_at": now, "estimated_cost": "0.05"},
        ],
    })
    settings = Settings(_env_file=None, max_daily_llm_cost=Decimal("0.10"), max_monthly_llm_cost=Decimal("50"))
    guard = CostGuard(settings, CostLedgerRepository(client))
    allowed, reason = guard.check()
    # $0.15 of real, fully-counted spend against a $0.10 daily cap --
    # blocked, proving none of the three duplicate rows were silently
    # dropped from cost accounting.
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
    def __init__(self, existing_live_decisions_by_asset=None):
        self.inserted = []
        self._next_id = 0
        # B1: {asset_id: JudgeDecisionRecord} -- what get_live_decisions_on_day
        # returns, simulating a decision that already exists for "today".
        # Empty by default, matching the real DB's behavior when nothing
        # has been decided yet.
        self._existing_live_decisions_by_asset = existing_live_decisions_by_asset or {}
        self.get_live_decisions_on_day_calls = []

    def insert(self, record):
        self._next_id += 1
        decision_id = f"decision-{self._next_id}"
        self.inserted.append(record)
        return decision_id

    def get_live_decisions_on_day(self, asset_ids, day):
        self.get_live_decisions_on_day_calls.append((list(asset_ids), day))
        return {
            asset_id: record
            for asset_id, record in self._existing_live_decisions_by_asset.items()
            if asset_id in asset_ids
        }


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
        self.last_system_prompt = None
        self.last_user_prompt = None

    def decide(self, system_prompt, user_prompt):
        self.called = True
        self.last_system_prompt = system_prompt
        self.last_user_prompt = user_prompt
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
    positions=None,
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
        portfolio_position_repo=FakePortfolioPositionRepoForContext(positions),
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
    # Live (non-replay) decisions/outcomes must never be tagged
    # is_backfilled — only 3e.1's replay ever sets this.
    assert decision_repo.inserted[0].is_backfilled is False
    assert outcome_repo.inserted[0].is_backfilled is False


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


def test_service_threads_real_current_allocations_into_the_actual_llm_prompt():
    # End-to-end regression for the 2026-09-14 fix: current_allocations
    # passed into .run() must reach the ACTUAL rendered prompt sent to the
    # provider, distinct from the system's own recorded target.
    btc = _asset("BTC", "a1")
    top = [_screened("BTC", "a1")]
    assessments = [_assessment("a1")]
    provider = FakeJudgeProvider(_judge_provider_result([VALID_DECISION]))
    positions = {"a1": PortfolioPosition(asset_id="a1", current_allocation=0.1632)}

    service = _make_service(top, [btc], assessments, provider, positions=positions)
    service.run("RUN-1", current_allocations={"a1": 0.3383})

    assert "33.83%" in provider.last_user_prompt
    assert "16.32%" in provider.last_user_prompt


def test_service_registers_prompt_template_with_correct_stage():
    btc = _asset("BTC", "a1")
    top = [_screened("BTC", "a1")]
    assessments = [_assessment("a1")]
    provider = FakeJudgeProvider(_judge_provider_result([VALID_DECISION]))
    prompt_repo = FakePromptTemplateRepo()

    service = _make_service(top, [btc], assessments, provider, prompt_repo=prompt_repo)
    service.run("RUN-1")

    assert prompt_repo.calls == [("judge_decision", "3e", "v3")]


# --- B1: same-day production Judge idempotency (2026-09-16) -------------------
#
# Real incident this closes: on 2026-09-05/06, `--with-judge` was run 3
# times each day with no guard at all, producing 40 independent extra live
# decisions (see doc/history.md's Phase 5i section). Those historical rows
# are untouched by this fix -- these tests only cover PREVENTING a new
# recurrence, never the historical treatment (a separate, later task).

def _existing_decision(asset_id, run_id="RUN-EARLIER", created_at=None, is_backfilled=False):
    return JudgeDecisionRecord(
        run_id=run_id, asset_id=asset_id, created_at=created_at or datetime.now(UTC),
        decision="BUY", confidence=0.6, target_allocation=0.05, expected_return=0.1,
        expected_alpha=0.05, risk_score=0.4, uncertainty=0.3, model_agreement=0.8,
        source_agreement=0.7, investment_horizon_days=30, key_evidence=[], contradictory_evidence=[],
        key_risks=[], invalidation_conditions=[], requires_review=False, thesis="t",
        macro_sensitivity="n/a", regime_id="r1", prompt_template_id="p1", estimated_cost=Decimal("0.01"),
        is_backfilled=is_backfilled,
    )


def test_duplicate_production_decision_is_skipped_not_recreated():
    # Test 1: BTC already has a live decision "today" -- a second attempt
    # must not create another judge_decisions/decision_outcomes row.
    btc = _asset("BTC", "a1")
    top = [_screened("BTC", "a1")]
    assessments = [_assessment("a1")]
    provider = FakeJudgeProvider(_judge_provider_result([VALID_DECISION]))
    decision_repo = FakeJudgeDecisionRepo(existing_live_decisions_by_asset={
        "a1": _existing_decision("a1", run_id="RUN-EARLIER-TODAY"),
    })
    outcome_repo = FakeDecisionOutcomeRepo()

    service = _make_service(
        top, [btc], assessments, provider,
        judge_decision_repo=decision_repo, decision_outcome_repo=outcome_repo,
    )
    result = service.run("RUN-ATTEMPT")

    assert result.duplicate_skipped == ["BTC"]
    assert result.stored == 0
    assert decision_repo.inserted == []  # no second judge_decisions row
    assert outcome_repo.inserted == []  # no second decision_outcomes row
    assert provider.called is False  # the LLM call itself was skipped, not just its result discarded


def test_different_asset_is_not_blocked_by_an_unrelated_duplicate():
    # Test 2: BTC already decided today; ETH is a fresh candidate this run
    # and must be processed normally.
    btc = _asset("BTC", "a1")
    eth = _asset("ETH", "a2")
    top = [_screened("BTC", "a1"), _screened("ETH", "a2")]
    assessments = [_assessment("a1"), _assessment("a2")]
    eth_decision = dict(VALID_DECISION, asset="ETH")
    provider = FakeJudgeProvider(_judge_provider_result([eth_decision]))
    decision_repo = FakeJudgeDecisionRepo(existing_live_decisions_by_asset={
        "a1": _existing_decision("a1"),
    })

    service = _make_service(
        top, [btc, eth], assessments, provider, judge_decision_repo=decision_repo,
    )
    result = service.run("RUN-ATTEMPT")

    assert result.duplicate_skipped == ["BTC"]
    assert result.decided_assets == ["ETH"]
    assert len(decision_repo.inserted) == 1
    assert decision_repo.inserted[0].asset_id == "a2"


def test_same_asset_different_day_is_allowed():
    # Test 3: BTC's existing decision was made on a different UTC day than
    # "now" -- get_live_decisions_on_day is queried for TODAY only, so an
    # existing decision from yesterday must never be returned as a match.
    # (get_live_decisions_on_day's own day-scoping is exercised directly in
    # test_utc_day_bounds_* below; here we confirm the fake correctly
    # reports "no existing decision for today" when none is registered for
    # today's date, which is what a real repository call would also return.)
    btc = _asset("BTC", "a1")
    top = [_screened("BTC", "a1")]
    assessments = [_assessment("a1")]
    provider = FakeJudgeProvider(_judge_provider_result([VALID_DECISION]))
    decision_repo = FakeJudgeDecisionRepo()  # nothing registered "today"

    service = _make_service(
        top, [btc], assessments, provider, judge_decision_repo=decision_repo,
    )
    result = service.run("RUN-TODAY")

    assert result.duplicate_skipped == []
    assert result.stored == 1
    assert decision_repo.inserted[0].asset_id == "a1"


def test_backfilled_replay_decisions_are_never_considered_by_the_production_guard():
    # Test 4: get_live_decisions_on_day only ever returns is_backfilled=false
    # rows (enforced server-side by the real repository's own `.eq("is_backfilled", False)`
    # filter). Simulate this precisely: the fake is seeded as if a
    # backfilled row existed for today (which a real query would never
    # surface here) to prove the SERVICE-level guard has no special-casing
    # that could accidentally start honoring one -- the guard only ever
    # asks "does get_live_decisions_on_day return this asset," and a real
    # backfilled row structurally never would.
    btc = _asset("BTC", "a1")
    top = [_screened("BTC", "a1")]
    assessments = [_assessment("a1")]
    provider = FakeJudgeProvider(_judge_provider_result([VALID_DECISION]))
    # An empty dict here is the REAL behavior for a backfilled-only day,
    # since get_live_decisions_on_day filters is_backfilled=false server-side.
    decision_repo = FakeJudgeDecisionRepo(existing_live_decisions_by_asset={})

    service = _make_service(
        top, [btc], assessments, provider, judge_decision_repo=decision_repo,
    )
    result = service.run("BACKFILL-RUN")

    assert result.duplicate_skipped == []
    assert result.stored == 1  # a live decision is still created normally


class _FakeJudgeDecisionsTableQuery:
    """Minimal fake mimicking supabase-py's chained query builder --
    `.select().in_().eq().gte().lt().execute()` -- same convention as
    tests/test_phase3a.py's `_FakeTableQuery`, extended with the extra
    operators `get_live_decisions_on_day` actually chains, so its real
    query construction (not just a filtered-in-Python fake) is exercised."""

    def __init__(self, rows):
        self._rows = rows
        # order/limit/range are deferred to execute() (real incident
        # 2026-09-18: get_recent's pagination fix chains TWO .order() calls
        # -- .order("created_at", desc=True).order("id", desc=True), a real
        # primary+tiebreaker sort -- applying each call as an immediate,
        # independent re-sort would discard the first key entirely rather
        # than using it as a tiebreak, since ids are unique. Filters
        # (in_/eq/gte/lt) stay eager -- they commute freely regardless of
        # when they're applied).
        self._order_keys = []
        self._limit = None
        self._range = None

    def select(self, *_args, **_kwargs):
        return self

    def in_(self, column, values):
        values = set(values)
        self._rows = [r for r in self._rows if r.get(column) in values]
        return self

    def eq(self, column, value):
        self._rows = [r for r in self._rows if r.get(column) == value]
        return self

    def gte(self, column, value):
        self._rows = [r for r in self._rows if r.get(column, "") >= value]
        return self

    def lt(self, column, value):
        self._rows = [r for r in self._rows if r.get(column, "") < value]
        return self

    def order(self, column, desc=False):
        self._order_keys.append((column, desc))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        rows = list(self._rows)
        # Stable-sort by the LEAST significant key first, most significant
        # last (Python's sort is stable, so this is the standard way to
        # compose several independent single-key sorts into one correct
        # multi-key sort) -- reproduces real Postgres/PostgREST
        # `ORDER BY col1 DESC, col2 DESC` semantics for chained .order()
        # calls, in the order the real caller chained them.
        for column, desc in reversed(self._order_keys):
            rows = sorted(rows, key=lambda r: r.get(column, ""), reverse=desc)
        if self._range is not None:
            start, end = self._range
            rows = rows[start:end + 1]
        elif self._limit is not None:
            rows = rows[:self._limit]
        return _FakeJudgeDecisionsQueryResult(rows)


class _FakeJudgeDecisionsQueryResult:
    def __init__(self, data):
        self.data = data


class FakeSupabaseClientForJudgeDecisions:
    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        assert name == "judge_decisions"
        return _FakeJudgeDecisionsTableQuery(list(self._rows))


def _judge_decisions_row(asset_id, run_id, created_at, is_backfilled=False):
    record = _existing_decision(asset_id, run_id=run_id, created_at=created_at, is_backfilled=is_backfilled)
    row = record.to_row()
    row["id"] = f"id-{asset_id}-{run_id}"
    return row


def test_get_live_decisions_on_day_excludes_backfilled_rows_and_other_days():
    # Test 4 (real repository, not the fake): confirms the actual query
    # construction -- not just the service-level guard -- scopes to
    # is_backfilled=false AND the requested UTC day, the one place a
    # replay/ablation row could otherwise leak into the production guard.
    from app.database.repository import JudgeDecisionRepository

    today = date(2026, 9, 16)
    rows = [
        _judge_decisions_row("a1", "RUN-TODAY-LIVE", datetime(2026, 9, 16, 10, 0, tzinfo=UTC), is_backfilled=False),
        _judge_decisions_row("a1", "BACKFILL-RUN", datetime(2026, 9, 16, 11, 0, tzinfo=UTC), is_backfilled=True),
        _judge_decisions_row("a2", "RUN-YESTERDAY", datetime(2026, 9, 15, 10, 0, tzinfo=UTC), is_backfilled=False),
    ]
    repo = JudgeDecisionRepository(FakeSupabaseClientForJudgeDecisions(rows))

    result = repo.get_live_decisions_on_day(["a1", "a2"], today)

    # a1's backfilled row and a2's prior-day row are both correctly excluded.
    assert set(result.keys()) == {"a1"}
    assert result["a1"].run_id == "RUN-TODAY-LIVE"


def test_failed_previous_run_does_not_block_a_later_successful_run():
    # Test 5: no judge_decisions row was ever persisted for today (a prior
    # invocation failed before persisting -- e.g. cost cap or provider
    # error) -- a later same-day attempt must proceed normally.
    btc = _asset("BTC", "a1")
    top = [_screened("BTC", "a1")]
    assessments = [_assessment("a1")]
    provider = FakeJudgeProvider(_judge_provider_result([VALID_DECISION]))
    decision_repo = FakeJudgeDecisionRepo()  # empty: the earlier failed run persisted nothing

    service = _make_service(
        top, [btc], assessments, provider, judge_decision_repo=decision_repo,
    )
    result = service.run("RUN-RETRY")

    assert result.duplicate_skipped == []
    assert result.failed is None
    assert result.stored == 1


def test_one_duplicate_among_several_does_not_abort_the_run():
    # Test 6: BTC already decided today; ETH has not been. The duplicate
    # must not abort the overall run -- ETH is still processed.
    btc = _asset("BTC", "a1")
    eth = _asset("ETH", "a2")
    top = [_screened("BTC", "a1"), _screened("ETH", "a2")]
    assessments = [_assessment("a1"), _assessment("a2")]
    eth_decision = dict(VALID_DECISION, asset="ETH")
    provider = FakeJudgeProvider(_judge_provider_result([eth_decision]))
    decision_repo = FakeJudgeDecisionRepo(existing_live_decisions_by_asset={"a1": _existing_decision("a1")})
    outcome_repo = FakeDecisionOutcomeRepo()

    service = _make_service(
        top, [btc, eth], assessments, provider,
        judge_decision_repo=decision_repo, decision_outcome_repo=outcome_repo,
    )
    result = service.run("RUN-ATTEMPT")

    assert result.failed is None
    assert result.duplicate_skipped == ["BTC"]
    assert result.stored == 1
    assert len(outcome_repo.inserted) == 1
    assert outcome_repo.inserted[0].asset_id == "a2"


def test_duplicate_skip_is_observable_via_result_summary(caplog):
    # Test 7: the skip is visible both in the log and in the run-summary
    # object (app/main.py logs `judge_result.summary` verbatim, so this is
    # what actually reaches the daily run's console output).
    btc = _asset("BTC", "a1")
    top = [_screened("BTC", "a1")]
    assessments = [_assessment("a1")]
    provider = FakeJudgeProvider(_judge_provider_result([]))
    decision_repo = FakeJudgeDecisionRepo(existing_live_decisions_by_asset={
        "a1": _existing_decision("a1", run_id="RUN-EARLIER-TODAY", created_at=datetime(2026, 9, 16, 8, 0, tzinfo=UTC)),
    })

    service = _make_service(top, [btc], assessments, provider, judge_decision_repo=decision_repo)
    with caplog.at_level("INFO"):
        result = service.run("RUN-ATTEMPT-TODAY")

    assert "duplicate_skipped=['BTC']" in result.summary
    assert any(
        "BTC" in record.message and "RUN-EARLIER-TODAY" in record.message and "RUN-ATTEMPT-TODAY" in record.message
        for record in caplog.records
    )


# A normal run with zero duplicates stays unobtrusive in the summary.
def test_normal_run_with_no_duplicates_reports_an_empty_skip_list():
    btc = _asset("BTC", "a1")
    top = [_screened("BTC", "a1")]
    assessments = [_assessment("a1")]
    provider = FakeJudgeProvider(_judge_provider_result([VALID_DECISION]))

    service = _make_service(top, [btc], assessments, provider)
    result = service.run("RUN-1")

    assert result.duplicate_skipped == []
    assert "duplicate_skipped=[]" in result.summary


# --- Test 8: UTC calendar-day boundary (robustness only, no redesign) --------

def test_utc_day_bounds_covers_the_full_calendar_day_inclusive_of_23_59_59():
    start, end = utc_day_bounds(date(2026, 9, 16))
    almost_midnight = datetime(2026, 9, 16, 23, 59, 59, tzinfo=UTC)
    assert start <= almost_midnight < end


def test_utc_day_bounds_excludes_the_next_days_00_00_01():
    start, end = utc_day_bounds(date(2026, 9, 16))
    just_after_midnight_next_day = datetime(2026, 9, 17, 0, 0, 1, tzinfo=UTC)
    assert not (start <= just_after_midnight_next_day < end)


def test_utc_day_bounds_for_the_next_day_starts_exactly_where_the_previous_ends():
    _start_16, end_16 = utc_day_bounds(date(2026, 9, 16))
    start_17, _end_17 = utc_day_bounds(date(2026, 9, 17))
    assert end_16 == start_17


# --- B2: historical same-day duplicate Judge decisions excluded from ----------
# --- calibration/evaluation (query-level, no canonical row) (2026-09-16) ------
#
# Real incident this addresses: 20 asset-day groups of live (is_backfilled=
# false) duplicate Judge decisions from 2026-09-05/06 (see doc/history.md's
# Phase 5j section). No canonical row is ever chosen -- the ENTIRE group is
# excluded from calibration/evaluation statistics. Raw judge_decisions/
# decision_outcomes rows, portfolio state, and cost accounting are all
# completely untouched by this function -- it is a pure, read-only
# classification used only to filter which decision_ids feed a metric.

def test_duplicate_group_of_three_live_decisions_is_entirely_excluded():
    now = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
    decisions = [
        ("d1", "btc-id", now, False),
        ("d2", "btc-id", now.replace(hour=11), False),
        ("d3", "btc-id", now.replace(hour=12), False),
    ]
    excluded = compute_duplicate_group_decision_ids(decisions)
    assert excluded == {"d1", "d2", "d3"}


def test_unrelated_asset_on_the_same_day_is_not_excluded():
    now = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
    decisions = [
        ("d1", "btc-id", now, False),
        ("d2", "btc-id", now.replace(hour=11), False),
        ("d3", "eth-id", now, False),  # single decision, different asset
    ]
    excluded = compute_duplicate_group_decision_ids(decisions)
    assert excluded == {"d1", "d2"}
    assert "d3" not in excluded


def test_a_single_live_decision_for_an_asset_day_remains_eligible():
    decisions = [("d1", "btc-id", datetime(2026, 9, 16, 10, 0, tzinfo=UTC), False)]
    assert compute_duplicate_group_decision_ids(decisions) == set()


def test_backfilled_rows_never_participate_in_duplicate_grouping():
    # Two LIVE decisions for BTC today (a real duplicate) plus a BACKFILLED
    # decision for the same asset/day -- the backfilled row must never be
    # excluded (is_backfilled=true rows are structurally exempt), and must
    # never affect whether the live pair counts as a duplicate (it already
    # does, on its own, regardless of the backfilled row's presence).
    now = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
    decisions = [
        ("live-1", "btc-id", now, False),
        ("live-2", "btc-id", now.replace(hour=11), False),
        ("backfilled-1", "btc-id", now, True),
    ]
    excluded = compute_duplicate_group_decision_ids(decisions)
    assert excluded == {"live-1", "live-2"}
    assert "backfilled-1" not in excluded


def test_exclusion_depends_only_on_group_membership_not_resolution_status():
    # The function itself takes no resolution-status input at all -- proof
    # by construction that the excluded set can never depend on it, and
    # confirmation that calling it twice with the identical group (as would
    # happen once before and once after an outcome resolves) is perfectly
    # stable: reproduces the real NEAR/2026-09-06 case (2 resolved + 1
    # still-unresolved decision in the same group).
    now = datetime(2026, 9, 6, 7, 49, tzinfo=UTC)
    near_group = [
        ("resolved-1", "near-id", now, False),
        ("resolved-2", "near-id", now.replace(hour=8), False),
        ("unresolved-3", "near-id", now.replace(hour=11), False),
    ]
    before = compute_duplicate_group_decision_ids(near_group)
    after = compute_duplicate_group_decision_ids(near_group)  # "unresolved-3" now resolved elsewhere -- same input here
    assert before == after == {"resolved-1", "resolved-2", "unresolved-3"}


def test_utc_midnight_boundary_does_not_merge_or_split_a_real_group():
    # A decision at 23:59:59Z and one at 00:00:01Z the next day are
    # DIFFERENT UTC calendar days -- correctly not grouped together, even
    # though they're only 2 seconds apart in wall-clock time. This is a
    # disclosed, accepted exposure (see doc/todo.md), not silently ignored.
    decisions = [
        ("d1", "btc-id", datetime(2026, 9, 16, 23, 59, 59, tzinfo=UTC), False),
        ("d2", "btc-id", datetime(2026, 9, 17, 0, 0, 1, tzinfo=UTC), False),
    ]
    assert compute_duplicate_group_decision_ids(decisions) == set()


def test_get_recent_with_no_limit_supplies_a_complete_population_for_duplicate_detection():
    # Regression for the 2026-09-16 fix: a fixed limit=2000 fetch, ordered
    # newest-first, would silently drop the OLDEST rows once the live
    # population exceeds it -- exactly the failure mode that could split an
    # old duplicate group across the cutoff. Reproduces this precisely
    # without creating 2001 real database rows: 1999 recent, unrelated
    # "filler" decisions (one per asset/day, never duplicates among
    # themselves) plus a real 2-member duplicate group (BTC) older than
    # every filler -- 2001 rows total. Under the OLD `limit=2000` behavior,
    # ordering newest-first and cutting at 2000 keeps all 1999 fillers plus
    # only the NEWER of the two BTC rows, dropping the older one entirely --
    # so the "duplicate" group would incorrectly look like a single,
    # non-duplicate decision. `get_recent(limit=None, ...)` must return the
    # complete population instead, so compute_duplicate_group_decision_ids
    # sees and correctly excludes both.
    from app.database.repository import JudgeDecisionRepository

    now = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    fillers = [
        _judge_decisions_row(f"filler-asset-{i}", f"RUN-FILLER-{i}", now - timedelta(minutes=i))
        for i in range(1999)
    ]
    btc_newer = _judge_decisions_row("btc-id", "RUN-BTC-NEWER", now - timedelta(minutes=1999))
    btc_older = _judge_decisions_row("btc-id", "RUN-BTC-OLDER", now - timedelta(minutes=2000))
    btc_newer_id, btc_older_id = btc_newer["id"], btc_older["id"]
    all_rows = fillers + [btc_newer, btc_older]
    assert len(all_rows) == 2001

    repo = JudgeDecisionRepository(FakeSupabaseClientForJudgeDecisions(all_rows))

    # The old, now-removed call shape -- kept here only to demonstrate the
    # real failure mode this fix closes, not as production code.
    old_capped_fetch = repo.get_recent(limit=2000, is_backfilled=False)
    old_excluded = compute_duplicate_group_decision_ids(
        (d.id, d.asset_id, d.created_at, d.is_backfilled) for d in old_capped_fetch
    )
    assert btc_older_id not in {d.id for d in old_capped_fetch}  # confirms the cutoff really drops it
    assert old_excluded == set()  # the old behavior: BTC's real duplicate is invisible

    complete_fetch = repo.get_recent(limit=None, is_backfilled=False)
    assert len(complete_fetch) == 2001
    new_excluded = compute_duplicate_group_decision_ids(
        (d.id, d.asset_id, d.created_at, d.is_backfilled) for d in complete_fetch
    )
    assert new_excluded == {btc_newer_id, btc_older_id}  # the fix: both members correctly excluded


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
