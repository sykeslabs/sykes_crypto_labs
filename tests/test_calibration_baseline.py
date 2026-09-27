from datetime import UTC, datetime
from decimal import Decimal

from app.benchmarks.schemas import DecisionOutcome
from app.database import repository as repository_module
from app.judge.schemas import JudgeDecisionRecord
from scripts.calibration_baseline import run_backfill_baseline, run_live_baseline


class _FakeQuery:
    """Minimal fake mimicking supabase-py's chained query builder, extended
    with `.insert()` since run_live_baseline persists a CalibrationRunRecord
    -- same convention as tests/test_run_composite_weights_validation.py's
    `_FakeQuery`. `.order()`/`.range()` added 2026-09-19: run_live_baseline/
    run_backfill_baseline now go through `JudgeDecisionRepository.get_recent
    (limit=None, ...)`, which pages via `_fetch_all_paginated`'s `.range()`
    calls. `.order()` is a no-op since these tests' own assertions don't
    depend on row order (same as test_run_composite_weights_validation.py's
    identical fake).

    Crucially, `.execute()` WITHOUT a preceding `.range()` call is also
    capped at `_SUPABASE_MAX_ROWS_PER_REQUEST` rows for `judge_decisions`
    specifically -- reproducing the real Supabase/PostgREST behavior this
    fix closes (a plain, unpaginated `.execute()` is silently capped
    server-side too, not just an explicit `.limit()`). Without this, a
    test using the OLD, unpaginated `client.table(...).execute()` code
    path would incorrectly still see every row via this fake and never
    catch the real regression. Scoped to `judge_decisions` only (not
    every table) so a monkeypatched tiny page size, chosen to force
    judge_decisions pagination in a test, doesn't also spuriously
    truncate an unrelated `decision_outcomes` fetch in the same test."""

    def __init__(self, rows, sink=None, capped=False):
        self._rows = rows
        self._sink = sink  # list to append inserted rows to, if this is an insert
        self._ranged = False
        self._capped = capped

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

    def insert(self, row):
        if self._sink is not None:
            self._sink.append(row)
        return self

    def execute(self):
        rows = self._rows
        if self._capped and not self._ranged:
            rows = rows[:repository_module._SUPABASE_MAX_ROWS_PER_REQUEST]
        return _FakeResult(rows)


class _FakeResult:
    def __init__(self, data):
        self.data = data


class FakeSupabaseClient:
    def __init__(self, tables: dict[str, list[dict]]):
        self._tables = tables
        self.inserted_calibration_runs: list[dict] = []

    def table(self, name):
        if name == "calibration_runs":
            return _FakeQuery([], sink=self.inserted_calibration_runs)
        # capped for judge_decisions AND decision_outcomes (2026-09-27,
        # batch 2): both tables are subject to the same real Supabase
        # per-request row cap when fetched without `.range()` -- this
        # fake must reproduce that for whichever table a regression test
        # needs to catch, not just the one Phase 5n originally fixed.
        return _FakeQuery(list(self._tables.get(name, [])), capped=(name in ("judge_decisions", "decision_outcomes")))


def _decision(
    id_, asset_id, created_at, decision="BUY", confidence=0.6, macro_sensitivity="n/a",
    is_backfilled=False, prompt_template_id="p1",
):
    # Real fields required for JudgeDecisionRecord.model_validate() to
    # succeed -- run_live_baseline/run_backfill_baseline now fetch through
    # JudgeDecisionRepository.get_recent(), which validates every raw row
    # into a full JudgeDecisionRecord, not just the handful of fields the
    # old raw-dict-based code happened to select.
    record = JudgeDecisionRecord(
        run_id="RUN-TEST", asset_id=asset_id, created_at=created_at, decision=decision,
        confidence=confidence, target_allocation=0.05, expected_return=0.1, expected_alpha=0.05,
        risk_score=0.4, uncertainty=0.3, model_agreement=0.8, source_agreement=0.7,
        investment_horizon_days=30, key_evidence=[], contradictory_evidence=[], key_risks=[],
        invalidation_conditions=[], requires_review=False, thesis="t",
        macro_sensitivity=macro_sensitivity, regime_id=None, prompt_template_id=prompt_template_id,
        estimated_cost=Decimal("0.01"), is_backfilled=is_backfilled,
    )
    row = record.to_row()
    row["id"] = id_
    return row


def _outcome(decision_id, realized_return=0.05, outcome_label="HIT_TARGET", is_backfilled=False):
    # Real fields required for DecisionOutcome.model_validate() to succeed
    # -- run_live_baseline/run_backfill_baseline now fetch through
    # DecisionOutcomeRepository.get_resolved_by_decision_ids() (2026-09-27,
    # batch 2), which validates every raw row into a full DecisionOutcome,
    # not just the 3 fields the old raw-dict-based code happened to select
    # (same convention as _decision()'s own comment above).
    record = DecisionOutcome(
        decision_id=decision_id, asset_id="asset-1", decision_timestamp=datetime(2026, 9, 1, tzinfo=UTC),
        horizon_days=30, target_return=0.1, stop_return=-0.1, realized_return=realized_return,
        outcome_label=outcome_label, judge_confidence=0.6, is_backfilled=is_backfilled,
    )
    return record.to_row()


def test_run_live_baseline_excludes_a_same_day_duplicate_group():
    day = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
    tables = {
        "judge_decisions": [
            _decision("btc-1", "btc-id", day),
            _decision("btc-2", "btc-id", day.replace(hour=11)),
            _decision("eth-1", "eth-id", day),
        ],
        "decision_outcomes": [
            _outcome("btc-1"), _outcome("btc-2"), _outcome("eth-1"),
        ],
    }
    client = FakeSupabaseClient(tables)

    run_live_baseline(client)

    # Two persisted records (pre-3f/post-3f eras) -- macro_sensitivity="n/a"
    # for all three decisions here means every one is "post-3f" (truthy),
    # so only the post-3f record should carry a real sample; BTC's
    # duplicate group must be entirely excluded, leaving only ETH.
    post_3f_records = [r for r in client.inserted_calibration_runs if r["method"] == "LIVE_POST_3F_BASELINE"]
    assert len(post_3f_records) == 1
    assert post_3f_records[0]["sample_size"] == 1  # ETH only -- both BTC rows excluded


def test_run_live_baseline_unaffected_when_no_duplicates_exist():
    day = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
    tables = {
        "judge_decisions": [_decision("btc-1", "btc-id", day), _decision("eth-1", "eth-id", day)],
        "decision_outcomes": [_outcome("btc-1"), _outcome("eth-1")],
    }
    client = FakeSupabaseClient(tables)

    run_live_baseline(client)

    post_3f_records = [r for r in client.inserted_calibration_runs if r["method"] == "LIVE_POST_3F_BASELINE"]
    assert len(post_3f_records) == 1
    assert post_3f_records[0]["sample_size"] == 2


def test_run_live_baseline_uses_repository_pagination_not_a_single_page(monkeypatch):
    # Real regression for the 2026-09-19 fix: run_live_baseline used to
    # issue one raw, unpaginated query -- silently subject to the same
    # server-side row cap already found for llm_analyses. This proves the
    # baseline now consumes the COMPLETE repository result across several
    # pages, not just whatever a single page/request would return, using a
    # monkeypatched small page size (not a real 1000+ row fixture) --
    # mirrors tests/test_repository_pagination.py's own convention.
    #
    # Deliberately chosen so the OLD and NEW behavior produce DIFFERENT
    # sample_size values, not a coincidental tie -- a same-day BTC
    # duplicate group is split across the page-1/page-2 boundary, AND a
    # 3rd, later page holds an additional unique decision (ADA) that the
    # old single-request code would never see at all:
    #   OLD (page 1 only, 2 rows): sees ETH-1, BTC-1 only. BTC-1 appears
    #     alone in its group (its duplicate sibling is invisible) and is
    #     WRONGLY treated as non-duplicate -> directional sample = {ETH-1,
    #     BTC-1} = 2. BTC-2, SOL-1, ADA-1 never seen at all.
    #   NEW (all 3 pages, 5 rows): BTC-1 and BTC-2 are correctly grouped
    #     and BOTH excluded -> directional sample = {ETH-1, SOL-1, ADA-1}
    #     = 3.
    # If this test still reported sample_size == 2 after the fix, that
    # would mean pagination silently stopped short again.
    monkeypatch.setattr("app.database.repository._SUPABASE_MAX_ROWS_PER_REQUEST", 2)
    day = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
    tables = {
        "judge_decisions": [
            _decision("eth-1", "eth-id", day),                    # page 1
            _decision("btc-1", "btc-id", day),                    # page 1
            _decision("btc-2", "btc-id", day.replace(hour=11)),   # page 2 -- same group as btc-1
            _decision("sol-1", "sol-id", day),                    # page 2
            _decision("ada-1", "ada-id", day),                    # page 3 (partial)
        ],
        "decision_outcomes": [
            _outcome("eth-1"), _outcome("btc-1"), _outcome("btc-2"), _outcome("sol-1"), _outcome("ada-1"),
        ],
    }
    client = FakeSupabaseClient(tables)

    run_live_baseline(client)

    post_3f_records = [r for r in client.inserted_calibration_runs if r["method"] == "LIVE_POST_3F_BASELINE"]
    assert len(post_3f_records) == 1
    # 5 real decisions across 3 pages; both BTC rows excluded as a
    # same-day duplicate group (only detectable because pagination
    # actually retrieved page 2); ETH/SOL/ADA remain -- proves the full
    # population was retrieved, not just page 1.
    assert post_3f_records[0]["sample_size"] == 3


def test_run_backfill_baseline_uses_repository_pagination():
    # No prior test coverage existed for run_backfill_baseline at all.
    # Confirms it now goes through JudgeDecisionRepository.get_recent
    # (limit=None, is_backfilled=True) too, and correctly scores backfilled
    # decisions end to end.
    day = datetime(2026, 9, 10, tzinfo=UTC)
    tables = {
        "judge_decisions": [
            _decision("bf-1", "btc-id", day, is_backfilled=True),
            _decision("bf-2", "eth-id", day, decision="SELL", is_backfilled=True),
        ],
        "decision_outcomes": [
            _outcome("bf-1", realized_return=0.03, outcome_label="HIT_TARGET"),
            _outcome("bf-2", realized_return=-0.02, outcome_label="HIT_STOP"),
        ],
    }
    client = FakeSupabaseClient(tables)

    run_backfill_baseline(client)

    records = [r for r in client.inserted_calibration_runs if r["method"] == "BACKFILL_BASELINE"]
    assert len(records) == 1
    assert records[0]["sample_size"] == 2  # both directional (BUY/SELL), both resolved


def test_run_backfill_baseline_uses_repository_pagination_for_decision_outcomes_too(monkeypatch):
    # 2026-09-27 follow-up (DecisionOutcome consumer migration batch 2):
    # the judge_decisions side of this function was already pagination-safe
    # (test above); the decision_outcomes side used a raw, unpaginated
    # `.in_(decision_ids)` query until this batch. Same monkeypatched-tiny-
    # page-size technique, but this time forcing the DECISION_OUTCOMES
    # fetch across multiple pages -- proves get_resolved_by_decision_ids
    # doesn't silently drop rows past the first page.
    monkeypatch.setattr("app.database.repository._SUPABASE_MAX_ROWS_PER_REQUEST", 2)
    day = datetime(2026, 9, 10, tzinfo=UTC)
    tables = {
        "judge_decisions": [
            _decision("bf-1", "btc-id", day, is_backfilled=True),
            _decision("bf-2", "eth-id", day, decision="SELL", is_backfilled=True),
            _decision("bf-3", "sol-id", day, is_backfilled=True),
            _decision("bf-4", "ada-id", day, decision="SELL", is_backfilled=True),
            _decision("bf-5", "link-id", day, is_backfilled=True),
        ],
        "decision_outcomes": [
            _outcome("bf-1", realized_return=0.03, is_backfilled=True),
            _outcome("bf-2", realized_return=-0.02, is_backfilled=True),
            _outcome("bf-3", realized_return=0.05, is_backfilled=True),
            _outcome("bf-4", realized_return=-0.01, is_backfilled=True),
            _outcome("bf-5", realized_return=0.02, is_backfilled=True),
        ],
    }
    client = FakeSupabaseClient(tables)

    run_backfill_baseline(client)

    records = [r for r in client.inserted_calibration_runs if r["method"] == "BACKFILL_BASELINE"]
    assert len(records) == 1
    # All 5 directional/resolved outcomes must be found, not just the
    # first _SUPABASE_MAX_ROWS_PER_REQUEST=2 rows a single unpaginated
    # request would have silently returned.
    assert records[0]["sample_size"] == 5


def test_run_backfill_baseline_ignores_decision_outcomes_rows_outside_the_relevant_decision_ids():
    # The .in_(decision_ids) join must stay correctly scoped: a
    # decision_outcomes row for a LIVE decision (noise, not part of this
    # backfilled run's own decision_ids) must never be picked up merely
    # because it happens to sit in the same table.
    day = datetime(2026, 9, 10, tzinfo=UTC)
    tables = {
        "judge_decisions": [
            _decision("bf-1", "btc-id", day, is_backfilled=True),
            _decision("live-1", "eth-id", day, is_backfilled=False),
        ],
        "decision_outcomes": [
            _outcome("bf-1", realized_return=0.03, is_backfilled=True),
            _outcome("live-1", realized_return=0.10, is_backfilled=False),  # noise -- must be excluded
        ],
    }
    client = FakeSupabaseClient(tables)

    run_backfill_baseline(client)

    records = [r for r in client.inserted_calibration_runs if r["method"] == "BACKFILL_BASELINE"]
    assert len(records) == 1
    assert records[0]["sample_size"] == 1  # only bf-1 -- live-1 was never in this run's decision_ids


def test_run_live_baseline_decision_outcomes_pagination_preserves_b2_duplicate_exclusion(monkeypatch):
    # Combines both concerns the audit flagged for this file: decision_
    # outcomes pagination AND B2 duplicate-group exclusion must both hold
    # at the same time, not just in isolation.
    monkeypatch.setattr("app.database.repository._SUPABASE_MAX_ROWS_PER_REQUEST", 2)
    day = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
    tables = {
        "judge_decisions": [
            _decision("btc-1", "btc-id", day),
            _decision("btc-2", "btc-id", day.replace(hour=11)),  # same-day duplicate group with btc-1
            _decision("eth-1", "eth-id", day),
            _decision("sol-1", "sol-id", day),
        ],
        "decision_outcomes": [
            _outcome("btc-1"), _outcome("btc-2"), _outcome("eth-1"), _outcome("sol-1"),
        ],
    }
    client = FakeSupabaseClient(tables)

    run_live_baseline(client)

    post_3f_records = [r for r in client.inserted_calibration_runs if r["method"] == "LIVE_POST_3F_BASELINE"]
    assert len(post_3f_records) == 1
    # BTC's duplicate group (2 rows) excluded entirely; ETH and SOL remain
    # -- proves decision_outcomes pagination retrieved every row (both
    # BTC rows, not just whichever page happened to include one of them)
    # while B2 exclusion still applies correctly on top of that.
    assert post_3f_records[0]["sample_size"] == 2
