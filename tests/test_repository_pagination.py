"""Real bug fixed 2026-09-18: this project's Supabase/PostgREST instance
silently caps any single request at ~1000 rows (its own server-side
db-max-rows/max-rows default) -- confirmed live against `llm_analyses`
(1379 real rows, both a no-`.limit()` query and an explicit `.limit(5000)`
both returned exactly 1000). `_fetch_all_paginated` (app/database/
repository.py) is the shared fix: pages through `.range()` until a page
returns fewer rows than requested, so a genuine "get everything" method
actually gets everything instead of a silent, undocumented truncation.
These tests cover the pagination helper directly, and `LLMAnalysisRepository
.get_recent()` as its first real, currently-affected consumer.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.database.repository import DecisionOutcomeRepository, LLMAnalysisRepository, _fetch_all_paginated


class _FakeRangeQuery:
    """Minimal fake mimicking supabase-py's chained query builder, scoped
    to exactly what _fetch_all_paginated needs: `.range(start, end)` then
    `.execute()`. `page_cap` simulates Supabase's own real server-side
    max-rows behavior -- even a `.range()` spanning more rows than that is
    silently truncated to it, the exact real incident this fix closes."""

    def __init__(self, rows, page_cap=None):
        self._rows = rows
        self._page_cap = page_cap
        self._range = None

    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        start, end = self._range
        page = self._rows[start:end + 1]
        if self._page_cap is not None:
            page = page[:self._page_cap]
        return _FakeRangeResult(page)


class _FakeRangeResult:
    def __init__(self, data):
        self.data = data


def test_fetch_all_paginated_single_page_under_the_cap():
    rows = [{"id": i} for i in range(5)]
    result = _fetch_all_paginated(lambda: _FakeRangeQuery(rows))
    assert result == rows


def test_fetch_all_paginated_empty_result():
    result = _fetch_all_paginated(lambda: _FakeRangeQuery([]))
    assert result == []


def test_fetch_all_paginated_exactly_one_full_page():
    # A real page boundary: exactly `_SUPABASE_MAX_ROWS_PER_REQUEST` rows
    # available. Must still terminate after that one page (never issue a
    # spurious extra request expecting more).
    from app.database.repository import _SUPABASE_MAX_ROWS_PER_REQUEST

    rows = [{"id": i} for i in range(_SUPABASE_MAX_ROWS_PER_REQUEST)]
    calls = []

    def build_query():
        calls.append(1)
        return _FakeRangeQuery(rows)

    result = _fetch_all_paginated(build_query)
    assert result == rows
    assert len(calls) == 2  # one full page, then one empty page confirms the end


def test_fetch_all_paginated_multiple_pages(monkeypatch):
    # Real end-to-end pagination across several pages, using a small
    # monkeypatched page size (not a real 1000-item list) to keep the test
    # fast while still exercising the actual multi-page loop logic.
    monkeypatch.setattr("app.database.repository._SUPABASE_MAX_ROWS_PER_REQUEST", 3)
    rows = [{"id": i} for i in range(7)]  # 3 + 3 + 1

    result = _fetch_all_paginated(lambda: _FakeRangeQuery(rows))

    assert result == rows
    assert len(result) == 7


def test_fetch_all_paginated_respects_the_real_server_side_cap_per_page(monkeypatch):
    # Even if the caller's own range() spans more rows than the server
    # will actually return in one response (the real incident: an
    # explicit .limit(5000) still only got 1000 back), pagination must
    # still recover every row across enough pages.
    monkeypatch.setattr("app.database.repository._SUPABASE_MAX_ROWS_PER_REQUEST", 3)
    rows = [{"id": i} for i in range(10)]

    result = _fetch_all_paginated(lambda: _FakeRangeQuery(rows, page_cap=3))

    assert result == rows


class _FakeLlmAnalysesQuery:
    def __init__(self, rows):
        self._rows = rows
        self._order_keys = []
        self._range = None
        self._limit = None

    def select(self, *_args, **_kwargs):
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
        for column, desc in reversed(self._order_keys):
            rows = sorted(rows, key=lambda r: r.get(column, ""), reverse=desc)
        if self._range is not None:
            start, end = self._range
            rows = rows[start:end + 1][:1000]  # real Supabase per-request cap
        elif self._limit is not None:
            rows = rows[:self._limit]
        return _FakeRangeResult(rows)


class _FakeLlmAnalysesClient:
    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        assert name == "llm_analyses"
        return _FakeLlmAnalysesQuery(list(self._rows))


def _llm_analysis_row(i, timestamp):
    return {
        "id": f"id-{i}",
        "run_id": "RUN-1",
        "asset_id": "asset-1",
        "provider": "claude",
        "model": "anthropic/claude-sonnet-5",
        "prompt_version": "v1",
        "timestamp": timestamp.isoformat(),
        "input_hash": "hash",
        "response": {},
        "action": "HOLD",
        "confidence": 0.5,
        "target_allocation": 0.1,
        "investment_horizon": "30d",
        "bull_case": "b",
        "bear_case": "b",
        "catalysts": [],
        "risks": [],
        "invalidation_conditions": [],
        "token_usage": None,
        "estimated_cost": "0.01",
    }


def test_get_recent_with_no_limit_returns_every_row_past_the_real_1000_cap():
    # Reproduces the real 2026-09-18 incident precisely: 1379 real rows,
    # a single unbounded request silently truncated to 1000. Uses 1200
    # here (not 1379) -- enough to force 2 real pages against the fake's
    # own 1000-row-per-request cap, without the test needing to match the
    # exact live figure.
    now = datetime(2026, 9, 18, tzinfo=UTC)
    rows = [_llm_analysis_row(i, now - timedelta(minutes=i)) for i in range(1200)]
    repo = LLMAnalysisRepository(_FakeLlmAnalysesClient(rows))

    result = repo.get_recent(limit=None)

    assert len(result) == 1200  # not silently truncated to 1000
    # Newest-first: row 0 (timestamp = now) must be first.
    assert result[0].id == "id-0"
    assert result[-1].id == "id-1199"


def test_get_recent_with_explicit_limit_is_unaffected_by_pagination():
    now = datetime(2026, 9, 18, tzinfo=UTC)
    rows = [_llm_analysis_row(i, now - timedelta(minutes=i)) for i in range(50)]
    repo = LLMAnalysisRepository(_FakeLlmAnalysesClient(rows))

    result = repo.get_recent(limit=10)

    assert len(result) == 10
    assert result[0].id == "id-0"


# --- DecisionOutcomeRepository: 2026-09-27 follow-up (Phase 1 of the
# DecisionOutcome migration) -- get_recent/get_unresolved/
# get_resolved_without_net_of_costs/get_resolved_without_benchmark_alpha
# all gained the identical limit=None -> _fetch_all_paginated convention
# already proven above for LLMAnalysisRepository. Same fake-query shape,
# extended with eq/neq/is_ since these methods filter on more than one
# column. ------------------------------------------------------------------

class _FakeDecisionOutcomesQuery:
    def __init__(self, rows):
        self._rows = list(rows)
        self._order_keys = []
        self._range = None
        self._limit = None

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

    def is_(self, column, value):
        assert value == "null"
        self._rows = [r for r in self._rows if r.get(column) is None]
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
        for column, desc in reversed(self._order_keys):
            rows = sorted(rows, key=lambda r: r.get(column, ""), reverse=desc)
        if self._range is not None:
            start, end = self._range
            rows = rows[start:end + 1][:1000]  # real Supabase per-request cap
        elif self._limit is not None:
            rows = rows[:self._limit]
        return _FakeRangeResult(rows)


class _FakeDecisionOutcomesClient:
    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        assert name == "decision_outcomes"
        return _FakeDecisionOutcomesQuery(list(self._rows))


def _outcome_row(
    decision_id, decision_timestamp, outcome_label="HIT_TARGET", is_backfilled=False,
    realized_return_net_of_costs=None, effective_alpha=None,
):
    return {
        "decision_id": decision_id, "asset_id": "asset-1", "decision_timestamp": decision_timestamp.isoformat(),
        "horizon_days": 30, "target_return": 0.1, "stop_return": -0.1, "judge_confidence": 0.6,
        "outcome_label": outcome_label, "is_backfilled": is_backfilled,
        "realized_return_net_of_costs": realized_return_net_of_costs, "effective_alpha": effective_alpha,
    }


def test_decision_outcome_get_recent_with_no_limit_returns_every_row_past_the_real_1000_cap():
    now = datetime(2026, 9, 27, tzinfo=UTC)
    rows = [_outcome_row(f"d-{i}", now - timedelta(minutes=i)) for i in range(1200)]
    repo = DecisionOutcomeRepository(_FakeDecisionOutcomesClient(rows))

    result = repo.get_recent(limit=None)

    assert len(result) == 1200  # not silently truncated to 1000
    assert result[0].decision_id == "d-0"  # newest-first
    assert result[-1].decision_id == "d-1199"


def test_decision_outcome_get_recent_deterministic_tiebreaker_on_a_shared_timestamp():
    # Two rows sharing the exact same decision_timestamp (real: multiple
    # decisions persisted in the same batched run) -- decision_id DESC must
    # deterministically resolve the tie, regardless of insertion order.
    ts = datetime(2026, 9, 27, tzinfo=UTC)
    rows = [_outcome_row("b-decision", ts), _outcome_row("a-decision", ts)]
    repo = DecisionOutcomeRepository(_FakeDecisionOutcomesClient(rows))

    result = repo.get_recent(limit=None)

    assert [r.decision_id for r in result] == ["b-decision", "a-decision"]


def test_decision_outcome_get_recent_explicit_limit_is_unaffected_by_pagination():
    now = datetime(2026, 9, 27, tzinfo=UTC)
    rows = [_outcome_row(f"d-{i}", now - timedelta(minutes=i)) for i in range(50)]
    repo = DecisionOutcomeRepository(_FakeDecisionOutcomesClient(rows))

    result = repo.get_recent(limit=10)

    assert len(result) == 10
    assert result[0].decision_id == "d-0"


def test_decision_outcome_get_recent_is_backfilled_filter_applies_with_limit_none():
    now = datetime(2026, 9, 27, tzinfo=UTC)
    rows = (
        [_outcome_row(f"live-{i}", now - timedelta(minutes=i), is_backfilled=False) for i in range(3)]
        + [_outcome_row(f"bf-{i}", now - timedelta(minutes=i), is_backfilled=True) for i in range(3)]
    )
    repo = DecisionOutcomeRepository(_FakeDecisionOutcomesClient(rows))

    result = repo.get_recent(limit=None, is_backfilled=True)

    assert len(result) == 3
    assert all(r.is_backfilled for r in result)


def test_get_unresolved_default_limit_500_remains_bounded():
    now = datetime(2026, 9, 27, tzinfo=UTC)
    rows = [_outcome_row(f"d-{i}", now, outcome_label="UNRESOLVED") for i in range(700)]
    repo = DecisionOutcomeRepository(_FakeDecisionOutcomesClient(rows))

    result = repo.get_unresolved()

    assert len(result) == 500


def test_get_unresolved_with_limit_none_returns_all_past_the_real_1000_cap():
    now = datetime(2026, 9, 27, tzinfo=UTC)
    rows = (
        [_outcome_row(f"unresolved-{i}", now, outcome_label="UNRESOLVED") for i in range(1200)]
        + [_outcome_row("resolved-1", now, outcome_label="HIT_TARGET")]
    )
    repo = DecisionOutcomeRepository(_FakeDecisionOutcomesClient(rows))

    result = repo.get_unresolved(limit=None)

    assert len(result) == 1200  # not silently truncated to 1000, and the resolved row stays excluded
    assert all(r.outcome_label == "UNRESOLVED" for r in result)


def test_get_resolved_without_net_of_costs_default_limit_remains_bounded():
    now = datetime(2026, 9, 27, tzinfo=UTC)
    rows = [_outcome_row(f"d-{i}", now, realized_return_net_of_costs=None) for i in range(700)]
    repo = DecisionOutcomeRepository(_FakeDecisionOutcomesClient(rows))

    result = repo.get_resolved_without_net_of_costs()

    assert len(result) == 500


def test_get_resolved_without_net_of_costs_with_limit_none_past_the_real_1000_cap():
    now = datetime(2026, 9, 27, tzinfo=UTC)
    rows = (
        [_outcome_row(f"missing-{i}", now, realized_return_net_of_costs=None) for i in range(1200)]
        + [_outcome_row("already-done", now, realized_return_net_of_costs=0.01)]
        + [_outcome_row("still-unresolved", now, outcome_label="UNRESOLVED", realized_return_net_of_costs=None)]
    )
    repo = DecisionOutcomeRepository(_FakeDecisionOutcomesClient(rows))

    result = repo.get_resolved_without_net_of_costs(limit=None)

    assert len(result) == 1200  # not truncated; already-processed and still-unresolved rows correctly excluded
    assert all(r.realized_return_net_of_costs is None for r in result)
    assert all(r.outcome_label != "UNRESOLVED" for r in result)


def test_get_resolved_without_benchmark_alpha_default_limit_remains_bounded():
    now = datetime(2026, 9, 27, tzinfo=UTC)
    rows = [_outcome_row(f"d-{i}", now, effective_alpha=None) for i in range(700)]
    repo = DecisionOutcomeRepository(_FakeDecisionOutcomesClient(rows))

    result = repo.get_resolved_without_benchmark_alpha()

    assert len(result) == 500


def test_get_resolved_without_benchmark_alpha_with_limit_none_past_the_real_1000_cap():
    now = datetime(2026, 9, 27, tzinfo=UTC)
    rows = (
        [_outcome_row(f"missing-{i}", now, effective_alpha=None) for i in range(1200)]
        + [_outcome_row("already-done", now, effective_alpha=0.02)]
        + [_outcome_row("still-unresolved", now, outcome_label="UNRESOLVED", effective_alpha=None)]
    )
    repo = DecisionOutcomeRepository(_FakeDecisionOutcomesClient(rows))

    result = repo.get_resolved_without_benchmark_alpha(limit=None)

    assert len(result) == 1200
    assert all(r.effective_alpha is None for r in result)
    assert all(r.outcome_label != "UNRESOLVED" for r in result)


# --- get_resolved_by_decision_ids: new method added for the
# calibration_baseline.py `.in_(decision_ids)` migration, batch 2
# (2026-09-27) ---------------------------------------------------------------

def test_get_resolved_by_decision_ids_returns_empty_for_an_empty_list():
    repo = DecisionOutcomeRepository(_FakeDecisionOutcomesClient([]))

    assert repo.get_resolved_by_decision_ids([]) == []


def test_get_resolved_by_decision_ids_filters_to_the_given_ids_and_resolved_only():
    now = datetime(2026, 9, 27, tzinfo=UTC)
    rows = [
        _outcome_row("wanted-resolved", now, outcome_label="HIT_TARGET"),
        _outcome_row("wanted-unresolved", now, outcome_label="UNRESOLVED"),
        _outcome_row("not-wanted", now, outcome_label="HIT_TARGET"),
    ]
    repo = DecisionOutcomeRepository(_FakeDecisionOutcomesClient(rows))

    result = repo.get_resolved_by_decision_ids(["wanted-resolved", "wanted-unresolved"])

    assert [r.decision_id for r in result] == ["wanted-resolved"]


def test_get_resolved_by_decision_ids_does_not_truncate_past_the_real_1000_cap():
    now = datetime(2026, 9, 27, tzinfo=UTC)
    decision_ids = [f"d-{i}" for i in range(1200)]
    rows = [_outcome_row(d, now) for d in decision_ids]
    repo = DecisionOutcomeRepository(_FakeDecisionOutcomesClient(rows))

    result = repo.get_resolved_by_decision_ids(decision_ids)

    assert len(result) == 1200  # not silently capped at 1000
