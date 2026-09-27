from datetime import UTC, datetime, timedelta

import pytest

from app.benchmarks.evaluation_service import OutcomeEvaluationService
from app.benchmarks.schemas import CalibrationRunRecord, DecisionOutcome
from app.benchmarks.triple_barrier import compute_target_stop_thresholds, evaluate_triple_barrier
from app.market_data.schemas import MarketSnapshot
from decimal import Decimal


# --- triple barrier ------------------------------------------------------------

def test_compute_target_stop_thresholds_uses_expected_return_magnitude():
    target, stop = compute_target_stop_thresholds(expected_return=0.20, risk_score=0.5)
    assert target == pytest.approx(0.20)
    assert stop == pytest.approx(-0.30)  # -0.20 * (1 + 0.5)


def test_compute_target_stop_thresholds_floors_small_expected_return():
    target, _ = compute_target_stop_thresholds(expected_return=0.001, risk_score=0.2)
    assert target == 0.05  # MIN_BARRIER_MAGNITUDE floor


def test_evaluate_triple_barrier_hits_target():
    now = datetime.now(UTC)
    series = [(now + timedelta(days=1), 105.0), (now + timedelta(days=2), 120.0)]
    label, realized, evaluated_at = evaluate_triple_barrier(
        entry_price=100.0, price_series=series, target_return=0.15, stop_return=-0.15,
        horizon_end=now + timedelta(days=30),
    )
    assert label == "HIT_TARGET"
    assert realized == pytest.approx(0.20)
    assert evaluated_at == series[1][0]


def test_evaluate_triple_barrier_hits_stop():
    now = datetime.now(UTC)
    series = [(now + timedelta(days=1), 90.0), (now + timedelta(days=2), 80.0)]
    label, realized, _ = evaluate_triple_barrier(
        entry_price=100.0, price_series=series, target_return=0.15, stop_return=-0.15,
        horizon_end=now + timedelta(days=30),
    )
    assert label == "HIT_STOP"
    assert realized == pytest.approx(-0.20)


def test_evaluate_triple_barrier_times_out_at_horizon():
    now = datetime.now(UTC)
    horizon_end = now + timedelta(days=10)
    series = [(now + timedelta(days=5), 102.0), (horizon_end, 103.0)]
    label, realized, evaluated_at = evaluate_triple_barrier(
        entry_price=100.0, price_series=series, target_return=0.15, stop_return=-0.15,
        horizon_end=horizon_end,
    )
    assert label == "TIMED_OUT"
    assert realized == pytest.approx(0.03)
    assert evaluated_at == horizon_end


def test_evaluate_triple_barrier_unresolved_when_neither_hit_and_before_horizon():
    now = datetime.now(UTC)
    series = [(now + timedelta(days=1), 102.0)]
    label, realized, evaluated_at = evaluate_triple_barrier(
        entry_price=100.0, price_series=series, target_return=0.15, stop_return=-0.15,
        horizon_end=now + timedelta(days=30),
    )
    assert label == "UNRESOLVED"
    assert realized is None
    assert evaluated_at is None


def test_evaluate_triple_barrier_zero_entry_price_is_unresolved():
    label, realized, evaluated_at = evaluate_triple_barrier(
        entry_price=0.0, price_series=[(datetime.now(UTC), 10.0)],
        target_return=0.1, stop_return=-0.1, horizon_end=datetime.now(UTC),
    )
    assert label == "UNRESOLVED"


# --- schemas ---------------------------------------------------------------

def test_decision_outcome_to_row_serializes_optional_fields():
    outcome = DecisionOutcome(
        decision_id="d1", asset_id="a1", decision_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        horizon_days=30, target_return=0.1, stop_return=-0.1, judge_confidence=0.6,
    )
    row = outcome.to_row()
    assert row["outcome_label"] == "UNRESOLVED"
    assert row["evaluated_at"] is None
    assert row["in_holdout_window"] is False


def test_calibration_run_record_to_row():
    record = CalibrationRunRecord(
        run_at=datetime(2026, 1, 1, tzinfo=UTC), method="baseline", sample_size=10,
        prompt_template_ids=["v1"], hit_rate=0.55, brier_score=0.2,
    )
    row = record.to_row()
    assert row["sample_size"] == 10
    assert isinstance(row["run_at"], str)


# --- OutcomeEvaluationService orchestration ---------------------------------

def _snapshot(price, ts, asset_id="a1"):
    return MarketSnapshot(
        asset_id=asset_id, timestamp=ts, price=Decimal(str(price)), market_cap=Decimal("1000"),
        volume_24h=Decimal("100"), price_change_24h=Decimal("1"),
        price_change_7d=Decimal("2"), price_change_30d=Decimal("3"),
    )


class FakeDecisionOutcomeRepo:
    def __init__(self, unresolved):
        self._unresolved = unresolved
        self.updated = []
        self.get_unresolved_calls = []

    def get_unresolved(self, limit=500):
        self.get_unresolved_calls.append(limit)
        return self._unresolved

    def update_outcome(self, decision_id, realized_return, outcome_label, evaluated_at):
        self.updated.append((decision_id, realized_return, outcome_label, evaluated_at))


class FakeSnapshotRepoForEvaluation:
    def __init__(self, snapshots_by_asset):
        self._snapshots_by_asset = snapshots_by_asset

    def get_snapshots_in_range(self, asset_id, start, end):
        rows = self._snapshots_by_asset.get(asset_id, [])
        return [s for s in rows if start <= s.timestamp <= end]


def test_evaluation_service_resolves_past_horizon_decision():
    decision_ts = datetime(2026, 1, 1, tzinfo=UTC)
    outcome = DecisionOutcome(
        decision_id="d1", asset_id="a1", decision_timestamp=decision_ts, horizon_days=7,
        target_return=0.15, stop_return=-0.15, judge_confidence=0.6,
    )
    snapshots = [
        _snapshot(100, decision_ts),
        _snapshot(96, decision_ts + timedelta(days=3)),
        _snapshot(80, decision_ts + timedelta(days=6)),  # hits stop
    ]
    service = OutcomeEvaluationService(
        FakeDecisionOutcomeRepo([outcome]), FakeSnapshotRepoForEvaluation({"a1": snapshots})
    )
    result = service.run(now=decision_ts + timedelta(days=10))

    assert result.evaluated == 1
    assert service._decision_outcome_repo.updated[0][2] == "HIT_STOP"


def test_evaluation_service_leaves_recent_decision_unresolved():
    decision_ts = datetime(2026, 1, 1, tzinfo=UTC)
    outcome = DecisionOutcome(
        decision_id="d1", asset_id="a1", decision_timestamp=decision_ts, horizon_days=30,
        target_return=0.15, stop_return=-0.15, judge_confidence=0.6,
    )
    snapshots = [_snapshot(100, decision_ts), _snapshot(101, decision_ts + timedelta(days=2))]
    service = OutcomeEvaluationService(
        FakeDecisionOutcomeRepo([outcome]), FakeSnapshotRepoForEvaluation({"a1": snapshots})
    )
    result = service.run(now=decision_ts + timedelta(days=3))  # well before the 30d horizon

    assert result.evaluated == 0
    assert result.still_unresolved == 1


def test_evaluation_service_skips_when_no_entry_price_available():
    decision_ts = datetime(2026, 1, 1, tzinfo=UTC)
    outcome = DecisionOutcome(
        decision_id="d1", asset_id="a1", decision_timestamp=decision_ts, horizon_days=7,
        target_return=0.15, stop_return=-0.15, judge_confidence=0.6,
    )
    service = OutcomeEvaluationService(
        FakeDecisionOutcomeRepo([outcome]), FakeSnapshotRepoForEvaluation({})  # no snapshots at all
    )
    result = service.run(now=decision_ts + timedelta(days=10))

    assert result.evaluated == 0
    assert result.skipped_no_entry_price == 1


def test_evaluation_service_requests_the_complete_unresolved_population():
    # 2026-09-27 follow-up: run() must request limit=None (every genuinely
    # unresolved row, via DecisionOutcomeRepository's own pagination), not
    # the old hardcoded 500-row default -- proves the retrieval-completeness
    # fix without asserting anything about processing order (no FIFO/
    # priority policy was introduced).
    decision_ts = datetime(2026, 1, 1, tzinfo=UTC)
    outcome = DecisionOutcome(
        decision_id="d1", asset_id="a1", decision_timestamp=decision_ts, horizon_days=7,
        target_return=0.15, stop_return=-0.15, judge_confidence=0.6,
    )
    repo = FakeDecisionOutcomeRepo([outcome])
    service = OutcomeEvaluationService(repo, FakeSnapshotRepoForEvaluation({}))

    service.run(now=decision_ts + timedelta(days=10))

    assert repo.get_unresolved_calls == [None]
