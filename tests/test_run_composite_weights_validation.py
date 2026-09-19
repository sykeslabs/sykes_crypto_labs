from datetime import UTC, datetime
from decimal import Decimal

from app.benchmarks.schemas import DecisionOutcome
from app.judge.schemas import JudgeDecisionRecord
from scripts.run_composite_weights_validation import FACTOR_FIELDS, fetch_joinable_directional_examples


class _FakeQuery:
    """Minimal fake mimicking supabase-py's chained query builder across
    arbitrary tables -- same convention as tests/test_phase3a.py's
    `_FakeTableQuery`/tests/test_judge.py's `_FakeJudgeDecisionsTableQuery`,
    generalized to the handful of extra operators this script's real
    queries (screened_universe lookups) also use."""

    def __init__(self, rows):
        self._rows = rows

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, column, value):
        self._rows = [r for r in self._rows if r.get(column) == value]
        return self

    def in_(self, column, values):
        values = set(values)
        self._rows = [r for r in self._rows if r.get(column) in values]
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def range(self, start, end):
        # Real incident 2026-09-18: JudgeDecisionRepository.get_recent's
        # limit=None path now paginates via .range() (Supabase/PostgREST's
        # own ~1000-row-per-request cap) instead of issuing a single
        # unbounded request -- see app/database/repository.py's
        # _fetch_all_paginated. This fake's real row counts are always
        # small, so a single .range() call already covers everything.
        self._rows = self._rows[start:end + 1]
        return self

    def execute(self):
        return _FakeResult(self._rows)


class _FakeResult:
    def __init__(self, data):
        self.data = data


class FakeSupabaseClient:
    def __init__(self, tables: dict[str, list[dict]]):
        self._tables = tables

    def table(self, name):
        return _FakeQuery(list(self._tables.get(name, [])))


def _outcome_row(decision_id, asset_id, realized_return=0.05, is_backfilled=False):
    return DecisionOutcome(
        decision_id=decision_id, asset_id=asset_id, decision_timestamp=datetime.now(UTC),
        horizon_days=30, target_return=0.1, stop_return=-0.1, realized_return=realized_return,
        outcome_label="HIT_TARGET", judge_confidence=0.6, is_backfilled=is_backfilled,
    ).to_row()


def _decision_row(decision_id, asset_id, run_id, created_at, is_backfilled=False):
    row = JudgeDecisionRecord(
        id=decision_id, run_id=run_id, asset_id=asset_id, created_at=created_at,
        decision="BUY", confidence=0.6, target_allocation=0.05, expected_return=0.1,
        expected_alpha=0.05, risk_score=0.4, uncertainty=0.3, model_agreement=0.8,
        source_agreement=0.7, investment_horizon_days=30, key_evidence=[], contradictory_evidence=[],
        key_risks=[], invalidation_conditions=[], requires_review=False, thesis="t",
        macro_sensitivity="n/a", regime_id=None, prompt_template_id=None,
        estimated_cost=Decimal("0.01"), is_backfilled=is_backfilled,
    ).to_row()
    row["id"] = decision_id
    return row


def _screened_row(run_id, asset_id, momentum=0.1):
    row = {f: momentum for f in FACTOR_FIELDS}
    row["run_id"] = run_id
    row["asset_id"] = asset_id
    return row


def test_fetch_joinable_directional_examples_excludes_a_live_duplicate_group():
    # BTC has 2 same-day live decisions (a duplicate group); ETH has 1.
    # Only ETH's real, resolved, joinable decision should survive.
    day = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
    tables = {
        "decision_outcomes": [
            _outcome_row("btc-1", "btc-id"),
            _outcome_row("btc-2", "btc-id"),
            _outcome_row("eth-1", "eth-id"),
        ],
        "judge_decisions": [
            _decision_row("btc-1", "btc-id", "RUN-1", day),
            _decision_row("btc-2", "btc-id", "RUN-2", day.replace(hour=11)),
            _decision_row("eth-1", "eth-id", "RUN-1", day),
        ],
        "screened_universe": [
            _screened_row("RUN-1", "btc-id", momentum=0.20),
            _screened_row("RUN-1", "eth-id", momentum=0.05),
            _screened_row("RUN-2", "btc-id", momentum=0.20),
            _screened_row("RUN-2", "eth-id", momentum=0.05),
        ],
    }
    client = FakeSupabaseClient(tables)

    examples, skipped_no_screening_row, skipped_duplicate_group = fetch_joinable_directional_examples(client)

    assert skipped_duplicate_group == 2  # both BTC rows, the entire group
    assert len(examples) == 1
    assert skipped_no_screening_row == 0


def test_fetch_joinable_directional_examples_unaffected_when_no_duplicates_exist():
    day = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
    tables = {
        "decision_outcomes": [_outcome_row("btc-1", "btc-id"), _outcome_row("eth-1", "eth-id")],
        "judge_decisions": [
            _decision_row("btc-1", "btc-id", "RUN-1", day),
            _decision_row("eth-1", "eth-id", "RUN-1", day),
        ],
        "screened_universe": [
            _screened_row("RUN-1", "btc-id", momentum=0.20),
            _screened_row("RUN-1", "eth-id", momentum=0.05),
        ],
    }
    client = FakeSupabaseClient(tables)

    examples, skipped_no_screening_row, skipped_duplicate_group = fetch_joinable_directional_examples(client)

    assert skipped_duplicate_group == 0
    assert len(examples) == 2


def test_fetch_joinable_directional_examples_ignores_backfilled_rows_for_grouping():
    # A backfilled decision sharing BTC's asset/day must never be treated
    # as part of a live duplicate group, and must never itself be excluded.
    day = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
    tables = {
        "decision_outcomes": [
            _outcome_row("btc-live", "btc-id"),
            _outcome_row("btc-backfilled", "btc-id", is_backfilled=True),
        ],
        "judge_decisions": [
            _decision_row("btc-live", "btc-id", "RUN-1", day),
            _decision_row("btc-backfilled", "btc-id", "BACKFILL-1", day, is_backfilled=True),
        ],
        "screened_universe": [
            _screened_row("RUN-1", "btc-id", momentum=0.20),
            _screened_row("BACKFILL-1", "btc-id", momentum=0.20),
        ],
    }
    client = FakeSupabaseClient(tables)

    examples, skipped_no_screening_row, skipped_duplicate_group = fetch_joinable_directional_examples(client)

    assert skipped_duplicate_group == 0
    assert len(examples) == 2
    assert {e["is_backfilled"] for e in examples} == {False, True}
