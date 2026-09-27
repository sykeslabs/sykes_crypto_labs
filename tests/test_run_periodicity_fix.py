from datetime import UTC, datetime

import pytest

from app.benchmarks.schemas import DecisionOutcome
from scripts.run_periodicity_fix import fetch_resolved_backfilled_outcomes, pooled_daily_returns_for_decision


def _outcome(decision_id, outcome_label="HIT_TARGET", is_backfilled=True):
    return DecisionOutcome(
        decision_id=decision_id, asset_id="asset-1", decision_timestamp=datetime(2026, 9, 1, tzinfo=UTC),
        horizon_days=30, target_return=0.1, stop_return=-0.1, realized_return=0.05,
        outcome_label=outcome_label, judge_confidence=0.6, is_backfilled=is_backfilled,
        evaluated_at=datetime(2026, 9, 15, tzinfo=UTC),
    )


class _FakeDecisionOutcomeRepo:
    def __init__(self, rows):
        self._rows = rows
        self.calls = []

    def get_recent(self, limit=200, is_backfilled=None):
        self.calls.append({"limit": limit, "is_backfilled": is_backfilled})
        return self._rows


def test_fetch_resolved_backfilled_outcomes_calls_repository_with_limit_none_and_backfilled_true():
    repo = _FakeDecisionOutcomeRepo([])

    fetch_resolved_backfilled_outcomes(repo)

    assert repo.calls == [{"limit": None, "is_backfilled": True}]


def test_fetch_resolved_backfilled_outcomes_excludes_unresolved():
    rows = [_outcome("resolved-1", outcome_label="HIT_TARGET"), _outcome("unresolved-1", outcome_label="UNRESOLVED")]
    repo = _FakeDecisionOutcomeRepo(rows)

    resolved = fetch_resolved_backfilled_outcomes(repo)

    assert [o.decision_id for o in resolved] == ["resolved-1"]


def test_fetch_resolved_backfilled_outcomes_does_not_truncate_past_the_old_2000_row_boundary():
    # The repository's own pagination is already covered by
    # tests/test_repository_pagination.py -- this proves the CONSUMER
    # doesn't reintroduce a truncation on top of whatever it returns.
    rows = [_outcome(f"d-{i}") for i in range(2500)]
    repo = _FakeDecisionOutcomeRepo(rows)

    resolved = fetch_resolved_backfilled_outcomes(repo)

    assert len(resolved) == 2500


# --- pooled_daily_returns_for_decision: unchanged calculation, sanity check
# that this migration didn't touch it ----------------------------------------

def test_pooled_daily_returns_for_decision_computes_simple_daily_returns():
    series = [
        (datetime(2026, 1, 1, tzinfo=UTC), 100.0, 10.0),
        (datetime(2026, 1, 2, tzinfo=UTC), 110.0, 10.0),
        (datetime(2026, 1, 3, tzinfo=UTC), 99.0, 10.0),
    ]
    returns = pooled_daily_returns_for_decision(
        series, datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 3, tzinfo=UTC), "BUY",
    )
    assert returns == pytest.approx([0.10, -0.10])


def test_pooled_daily_returns_for_decision_inverts_sign_for_sell():
    series = [
        (datetime(2026, 1, 1, tzinfo=UTC), 100.0, 10.0),
        (datetime(2026, 1, 2, tzinfo=UTC), 110.0, 10.0),
    ]
    returns = pooled_daily_returns_for_decision(
        series, datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC), "SELL",
    )
    assert returns == pytest.approx([-0.10])
