"""Real bug fixed 2026-09-17: `portfolio_allocation_changes` carried no
record of WHY a target changed, so `get_turnover_since` (the query
MAX_WEEKLY_TURNOVER is checked against) summed every persisted target delta
uniformly -- including WATCH/NO_TRADE risk-control corrections that
`RiskEngine._strategy_turnover_delta` already treats as zero strategy
turnover at decision time. These tests cover the persisted `change_reason`
filter added to close that gap -- see migrations/0021 and
app/portfolio/schemas.py's `PortfolioAllocationChange.change_reason`
docstring for the full incident.
"""

from datetime import UTC, datetime, timedelta

from app.database.repository import PortfolioAllocationChangeRepository
from app.portfolio.schemas import PortfolioAllocationChange


class _FakeQuery:
    """Minimal fake mimicking supabase-py's chained query builder -- same
    convention as tests/test_run_composite_weights_validation.py's
    `_FakeQuery`, extended with `.gte()` since `get_turnover_since` filters
    on `changed_at` before its two `.eq()` filters."""

    def __init__(self, rows):
        self._rows = rows

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, column, value):
        self._rows = [r for r in self._rows if r.get(column) == value]
        return self

    def gte(self, column, value):
        self._rows = [r for r in self._rows if r.get(column) >= value]
        return self

    def execute(self):
        return _FakeResult(self._rows)


class _FakeResult:
    def __init__(self, data):
        self.data = data


class FakeSupabaseClient:
    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        assert name == "portfolio_allocation_changes"
        return _FakeQuery(list(self._rows))


def _row(previous, new, changed_at, change_reason="strategy", baseline_semantics="system_target"):
    return {
        "previous_allocation": previous,
        "new_allocation": new,
        "changed_at": changed_at.isoformat(),
        "change_reason": change_reason,
        "baseline_semantics": baseline_semantics,
    }


def test_get_turnover_since_only_sums_strategy_change_reason_rows():
    now = datetime(2026, 9, 17, tzinfo=UTC)
    rows = [
        _row(0.10, 0.20, now, change_reason="strategy"),
        _row(0.30, 0.15, now, change_reason="risk_control"),
    ]
    repo = PortfolioAllocationChangeRepository(FakeSupabaseClient(rows))

    turnover = repo.get_turnover_since(now - timedelta(days=7))

    assert turnover == 0.10  # only the strategy row's |0.20 - 0.10|


def test_get_turnover_since_excludes_risk_control_rows_even_within_window():
    now = datetime(2026, 9, 17, tzinfo=UTC)
    rows = [_row(0.0, 0.15, now, change_reason="risk_control")]
    repo = PortfolioAllocationChangeRepository(FakeSupabaseClient(rows))

    turnover = repo.get_turnover_since(now - timedelta(days=7))

    assert turnover == 0.0


def test_get_turnover_since_combines_change_reason_with_existing_baseline_and_window_filters():
    now = datetime(2026, 9, 17, tzinfo=UTC)
    rows = [
        _row(0.10, 0.20, now, change_reason="strategy", baseline_semantics="system_target"),
        _row(0.0, 0.50, now, change_reason="strategy", baseline_semantics="actual_holdings"),  # pre-2026-09-14 row
        _row(0.05, 0.25, now - timedelta(days=10), change_reason="strategy"),  # outside 7d window
        _row(0.40, 0.10, now, change_reason="risk_control", baseline_semantics="system_target"),
    ]
    repo = PortfolioAllocationChangeRepository(FakeSupabaseClient(rows))

    turnover = repo.get_turnover_since(now - timedelta(days=7))

    assert turnover == 0.10  # only the first row survives all three filters


def test_insert_persists_change_reason_and_get_recent_round_trips_it():
    inserted = {}

    class _RecordingQuery(_FakeQuery):
        def insert(self, row):
            inserted.update(row)
            return self

    class _RecordingClient(FakeSupabaseClient):
        def table(self, name):
            return _RecordingQuery(list(self._rows))

    repo = PortfolioAllocationChangeRepository(_RecordingClient([]))
    change = PortfolioAllocationChange(
        asset_id="a1", run_id="RUN-1", decision_id="d1",
        previous_allocation=0.30, new_allocation=0.15,
        actual_allocation_before=0.30, change_reason="risk_control",
        changed_at=datetime.now(UTC),
    )

    repo.insert(change)

    assert inserted["change_reason"] == "risk_control"
