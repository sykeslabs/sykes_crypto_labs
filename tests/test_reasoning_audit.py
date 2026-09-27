import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from pydantic import ValidationError

import scripts.run_reasoning_audit as run_reasoning_audit_module
from app.benchmarks.reasoning_audit import (
    AuditCandidate,
    render_audit_prompt,
    select_audit_sample,
)
from app.benchmarks.schemas import DecisionOutcome, JudgeReasoningAuditRecord, ReasoningAuditResult
from app.config.settings import Settings
from app.database import repository as repository_module
from app.judge.schemas import JudgeDecisionRecord
from app.llm.cost import CostGuard, CostLedgerRepository
from app.llm.structured_provider import OpenRouterStructuredProvider
from scripts.run_reasoning_audit import fetch_candidates


def _candidate(
    decision_id="d1", requires_review=False, model_agreement=0.9, source_agreement=0.9,
    outcome_contradicted_decision=False,
):
    return AuditCandidate(
        decision_id=decision_id, thesis="t", key_evidence=["e1"], contradictory_evidence=[],
        requires_review=requires_review, model_agreement=model_agreement, source_agreement=source_agreement,
        outcome_contradicted_decision=outcome_contradicted_decision,
    )


# --- select_audit_sample ------------------------------------------------------

def test_select_audit_sample_prioritizes_contradicted_outcomes_first():
    contradicted = _candidate("d1", outcome_contradicted_decision=True)
    plain = _candidate("d2")
    sample = select_audit_sample([plain, contradicted], sample_size=1)
    assert sample == [contradicted]


def test_select_audit_sample_prioritizes_requires_review_over_plain():
    review = _candidate("d1", requires_review=True)
    plain = _candidate("d2")
    sample = select_audit_sample([plain, review], sample_size=1)
    assert sample == [review]


def test_select_audit_sample_includes_low_agreement_before_plain():
    low_agreement = _candidate("d1", model_agreement=0.3, source_agreement=0.3)
    plain = _candidate("d2")
    sample = select_audit_sample([plain, low_agreement], sample_size=1)
    assert sample == [low_agreement]


def test_select_audit_sample_never_exceeds_requested_size():
    candidates = [_candidate(f"d{i}") for i in range(20)]
    sample = select_audit_sample(candidates, sample_size=5)
    assert len(sample) == 5


def test_select_audit_sample_deduplicates_candidates_matching_multiple_criteria():
    both = _candidate("d1", requires_review=True, outcome_contradicted_decision=True)
    plain = _candidate("d2")
    sample = select_audit_sample([both, plain], sample_size=10)
    # "both" must appear exactly once, not twice, even though it qualifies
    # under two priority groups.
    assert [c.decision_id for c in sample].count("d1") == 1
    assert len(sample) == 2


def test_select_audit_sample_returns_fewer_than_requested_if_pool_is_smaller():
    sample = select_audit_sample([_candidate("d1")], sample_size=10)
    assert len(sample) == 1


# --- fetch_candidates: pagination-safe repository retrieval (2026-09-27) -----

def _decision_record(id_, decision="BUY", requires_review=False):
    record = JudgeDecisionRecord(
        run_id="RUN-TEST", asset_id="asset-1", created_at=datetime(2026, 9, 1, tzinfo=UTC),
        decision=decision, confidence=0.6, target_allocation=0.1, expected_return=0.1,
        expected_alpha=0.05, risk_score=0.4, uncertainty=0.3, model_agreement=0.8, source_agreement=0.7,
        investment_horizon_days=30, key_evidence=["e1"], contradictory_evidence=[], key_risks=[],
        invalidation_conditions=[], requires_review=requires_review, thesis="t", macro_sensitivity="n/a",
        regime_id=None, prompt_template_id="p1", estimated_cost=Decimal("0.01"), is_backfilled=True,
    )
    record.id = id_
    return record


def _outcome_row(decision_id, realized_return=0.05, outcome_label="HIT_TARGET"):
    # Real fields required for DecisionOutcome.model_validate() to succeed
    # -- fetch_candidates now retrieves outcomes through
    # DecisionOutcomeRepository.get_resolved_by_decision_ids() (2026-09-27,
    # batch 3), which validates every raw row into a full DecisionOutcome,
    # not just the 3 fields the old raw-dict-based code happened to select
    # (same convention as _decision_record's own comment above).
    record = DecisionOutcome(
        decision_id=decision_id, asset_id="asset-1", decision_timestamp=datetime(2026, 9, 1, tzinfo=UTC),
        horizon_days=30, target_return=0.1, stop_return=-0.1, realized_return=realized_return,
        outcome_label=outcome_label, judge_confidence=0.6, is_backfilled=True,
    )
    return record.to_row()


class _FakeJudgeDecisionRepository:
    last_calls: list[dict] = []
    records: list = []

    def __init__(self, client):
        self._client = client

    def get_recent(self, limit=None, is_backfilled=None):
        _FakeJudgeDecisionRepository.last_calls.append({"limit": limit, "is_backfilled": is_backfilled})
        return _FakeJudgeDecisionRepository.records


class _FakeAuditTableQuery:
    def __init__(self, rows, capped=False):
        self._rows = rows
        self._capped = capped
        self._ranged = False

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, column, value):
        self._rows = [r for r in self._rows if r.get(column) == value]
        return self

    def neq(self, column, value):
        self._rows = [r for r in self._rows if r.get(column) != value]
        return self

    def in_(self, column, values):
        values = set(values)
        self._rows = [r for r in self._rows if r.get(column) in values]
        return self

    def order(self, *_args, **_kwargs):
        return self

    def range(self, start, end):
        self._rows = self._rows[start:end + 1]
        self._ranged = True
        return self

    def execute(self):
        rows = self._rows
        if self._capped and not self._ranged:
            rows = rows[:repository_module._SUPABASE_MAX_ROWS_PER_REQUEST]
        return _FakeAuditResult(rows)


class _FakeAuditResult:
    def __init__(self, data):
        self.data = data


class _FakeAuditClient:
    def __init__(self, tables: dict):
        self._tables = tables

    def table(self, name):
        # capped for decision_outcomes (2026-09-27, batch 3): reproduces
        # the real Supabase per-request row cap for a query issued
        # without `.range()` -- the exact regression
        # get_resolved_by_decision_ids's pagination closes (same
        # convention as tests/test_calibration_baseline.py's fake).
        return _FakeAuditTableQuery(list(self._tables.get(name, [])), capped=(name == "decision_outcomes"))


def _setup_fake_repository(monkeypatch, records):
    _FakeJudgeDecisionRepository.last_calls = []
    _FakeJudgeDecisionRepository.records = records
    monkeypatch.setattr(run_reasoning_audit_module, "JudgeDecisionRepository", _FakeJudgeDecisionRepository)


def test_fetch_candidates_calls_repository_with_limit_none_and_backfilled_true(monkeypatch):
    _setup_fake_repository(monkeypatch, [])
    client = _FakeAuditClient({})

    fetch_candidates(client)

    assert _FakeJudgeDecisionRepository.last_calls == [{"limit": None, "is_backfilled": True}]


def test_fetch_candidates_reaches_sampler_with_deterministic_repository_order(monkeypatch):
    # get_recent() supplies a defined `created_at DESC` order (unlike the
    # old raw query, which had no `.order()` at all and no ordering
    # guarantee). This proves that order reaches fetch_candidates's own
    # returned list unchanged -- select_audit_sample's within-group
    # tie-breaking now has something deterministic to depend on.
    d1, d2, d3 = _decision_record("d1"), _decision_record("d2"), _decision_record("d3")
    _setup_fake_repository(monkeypatch, [d1, d2, d3])
    client = _FakeAuditClient({
        "decision_outcomes": [_outcome_row("d1"), _outcome_row("d2"), _outcome_row("d3")],
        "judge_reasoning_audits": [],
    })

    candidates = fetch_candidates(client)

    assert [c.decision_id for c in candidates] == ["d1", "d2", "d3"]


def test_fetch_candidates_excludes_already_audited_decisions(monkeypatch):
    d1, d2 = _decision_record("d1"), _decision_record("d2")
    _setup_fake_repository(monkeypatch, [d1, d2])
    client = _FakeAuditClient({
        "decision_outcomes": [_outcome_row("d1"), _outcome_row("d2")],
        "judge_reasoning_audits": [{"decision_id": "d1"}],
    })

    candidates = fetch_candidates(client)

    assert [c.decision_id for c in candidates] == ["d2"]


def test_fetch_candidates_does_not_truncate_a_population_crossing_the_old_1000_row_boundary(monkeypatch):
    records = [_decision_record(f"d-{i}") for i in range(1001)]
    _setup_fake_repository(monkeypatch, records)
    client = _FakeAuditClient({
        "decision_outcomes": [_outcome_row(f"d-{i}") for i in range(1001)],
        "judge_reasoning_audits": [],
    })

    candidates = fetch_candidates(client)

    assert len(candidates) == 1001


# --- render_audit_prompt ------------------------------------------------------

def test_render_audit_prompt_includes_thesis_and_evidence():
    candidate = AuditCandidate(
        decision_id="d1", thesis="Strong bullish setup",
        key_evidence=["3/3 models bullish"], contradictory_evidence=["funding negative"],
        requires_review=True, model_agreement=0.5, source_agreement=0.5,
        outcome_contradicted_decision=False,
    )
    system_prompt, user_prompt = render_audit_prompt(candidate, "v1")
    assert "Strong bullish setup" in user_prompt
    assert "3/3 models bullish" in user_prompt
    assert "funding negative" in user_prompt
    assert "supported" in system_prompt


# --- ReasoningAuditResult / JudgeReasoningAuditRecord schemas -----------------

def test_reasoning_audit_result_accepts_valid_payload():
    result = ReasoningAuditResult(supported=False, unsupported_claims=["claim X not backed"], notes="n")
    assert result.supported is False


def test_reasoning_audit_result_defaults_unsupported_claims_to_empty():
    result = ReasoningAuditResult(supported=True, notes="fine")
    assert result.unsupported_claims == []


def test_reasoning_audit_result_rejects_missing_supported():
    with pytest.raises(ValidationError):
        ReasoningAuditResult(notes="n")


def test_judge_reasoning_audit_record_to_row_serializes_decimal_and_datetime():
    record = JudgeReasoningAuditRecord(
        run_at=datetime(2026, 1, 1, tzinfo=UTC), decision_id="d1", audit_model="m",
        supported=True, unsupported_claims=[], notes="ok",
        estimated_cost=Decimal("0.01"), created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    row = record.to_row()
    assert row["estimated_cost"] == "0.01"
    assert isinstance(row["created_at"], str)


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
    def __init__(self, tables: dict):
        self._tables = tables

    def table(self, name):
        return _FakeTableQuery(list(self._tables.get(name, [])))


def test_cost_guard_reflects_judge_reasoning_audits_row():
    client = FakeSupabaseClient({
        "judge_reasoning_audits": [{"created_at": datetime.now(UTC).isoformat(), "estimated_cost": "0.04"}],
    })
    settings = Settings(_env_file=None, max_daily_llm_cost=Decimal("0.03"), max_monthly_llm_cost=Decimal("50"))
    guard = CostGuard(settings, CostLedgerRepository(client))
    allowed, reason = guard.check()
    assert allowed is False
    assert "Daily" in reason


# --- mocked-LLM test for the audit call --------------------------------------

class FakeHttpResponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)


def test_reasoning_audit_call_parses_structured_response(monkeypatch):
    payload = {
        "choices": [{"message": {"content": json.dumps({
            "supported": False,
            "unsupported_claims": ["thesis claims X but key_evidence never mentions X"],
            "notes": "The thesis makes an unsupported leap.",
        })}}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 40},
    }
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeHttpResponse(payload))

    provider = OpenRouterStructuredProvider(
        name="reasoning_audit", model="anthropic/claude-sonnet-5", api_key="k",
        base_url="https://openrouter.ai/api/v1", timeout_seconds=30.0,
    )
    candidate = AuditCandidate(
        decision_id="d1", thesis="t", key_evidence=["e1"], contradictory_evidence=[],
        requires_review=True, model_agreement=0.4, source_agreement=0.4,
        outcome_contradicted_decision=True,
    )
    system_prompt, user_prompt = render_audit_prompt(candidate, "v1")
    result = provider.call(system_prompt, user_prompt, ReasoningAuditResult)

    assert result.error is None
    assert result.parsed.supported is False
    assert result.parsed.unsupported_claims == ["thesis claims X but key_evidence never mentions X"]
    assert result.estimated_cost > 0
