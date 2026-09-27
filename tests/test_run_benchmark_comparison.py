from datetime import UTC, datetime

from app.benchmarks.schemas import DecisionOutcome
from scripts.run_benchmark_comparison import fetch_backfilled_decision_timestamps


def _outcome(decision_id, decision_timestamp, outcome_label="HIT_TARGET", is_backfilled=True):
    return DecisionOutcome(
        decision_id=decision_id, asset_id="asset-1", decision_timestamp=decision_timestamp,
        horizon_days=30, target_return=0.1, stop_return=-0.1, realized_return=0.05,
        outcome_label=outcome_label, judge_confidence=0.6, is_backfilled=is_backfilled,
    )


class _FakeDecisionOutcomeRepo:
    def __init__(self, rows):
        self._rows = rows
        self.calls = []

    def get_recent(self, limit=200, is_backfilled=None):
        self.calls.append({"limit": limit, "is_backfilled": is_backfilled})
        return self._rows


def test_fetch_backfilled_decision_timestamps_calls_repository_with_limit_none_and_backfilled_true():
    repo = _FakeDecisionOutcomeRepo([])

    fetch_backfilled_decision_timestamps(repo)

    assert repo.calls == [{"limit": None, "is_backfilled": True}]


def test_fetch_backfilled_decision_timestamps_includes_unresolved_rows():
    # Real, preserved behavior: the old raw query had no outcome_label
    # filter at all -- every backfilled decision's own timestamp counts
    # toward the comparison window regardless of resolution status.
    ts_unresolved = datetime(2026, 9, 1, tzinfo=UTC)
    ts_resolved = datetime(2026, 9, 15, tzinfo=UTC)
    rows = [
        _outcome("unresolved-1", ts_unresolved, outcome_label="UNRESOLVED"),
        _outcome("resolved-1", ts_resolved, outcome_label="HIT_TARGET"),
    ]
    repo = _FakeDecisionOutcomeRepo(rows)

    timestamps = fetch_backfilled_decision_timestamps(repo)

    assert sorted(timestamps) == [ts_unresolved, ts_resolved]


def test_fetch_backfilled_decision_timestamps_does_not_truncate_past_the_old_unbounded_query_risk():
    # The old raw query had no .range()/.limit() at all -- subject to
    # Supabase's own implicit per-request row cap. This proves the
    # consumer now consumes the complete repository result, not just
    # whatever a single unbounded request would have silently returned.
    now = datetime(2026, 9, 27, tzinfo=UTC)
    rows = [_outcome(f"d-{i}", now) for i in range(1200)]
    repo = _FakeDecisionOutcomeRepo(rows)

    timestamps = fetch_backfilled_decision_timestamps(repo)

    assert len(timestamps) == 1200


def test_fetch_backfilled_decision_timestamps_min_max_window_reflects_the_true_earliest_and_latest():
    earliest = datetime(2022, 11, 8, tzinfo=UTC)  # the real FTX-window ablation date
    latest = datetime(2026, 9, 27, tzinfo=UTC)
    rows = [_outcome("mid", datetime(2026, 1, 1, tzinfo=UTC)), _outcome("earliest", earliest), _outcome("latest", latest)]
    repo = _FakeDecisionOutcomeRepo(rows)

    timestamps = sorted(fetch_backfilled_decision_timestamps(repo))

    assert timestamps[0] == earliest
    assert timestamps[-1] == latest
