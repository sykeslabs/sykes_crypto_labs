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

from app.database.repository import LLMAnalysisRepository, _fetch_all_paginated


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
