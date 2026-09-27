from datetime import UTC, datetime
from decimal import Decimal

import pytest

import scripts.run_evidence_value_ranking as run_evidence_value_ranking_module
from app.benchmarks.evidence_value import (
    MIN_SAMPLE_SIZE,
    TrainingExample,
    rank_evidence_value,
    regime_sliced_ranking,
    rolling_window_drift,
    train_logistic_regression,
)
from app.benchmarks.schemas import DecisionOutcome, EvidenceValueReportRecord
from app.database import repository as repository_module
from app.judge.schemas import JudgeDecisionRecord
from scripts.run_evidence_value_ranking import (
    FEATURE_FIELDS,
    fetch_backfilled_decisions_chronological,
    fetch_directional_examples,
)


def _perfect_vs_noise_examples(n: int) -> list[TrainingExample]:
    """Engineered fixture: `perfect_predictor` perfectly determines the
    label (+1 when label=1, -1 when label=0) — the model should learn a
    large-magnitude coefficient for it. `pure_noise` is constructed, in
    blocks of 4, so that within every block exactly half the label=1 rows
    and half the label=0 rows share each noise value — an EXACT zero
    sample correlation with the label by construction (not merely
    low-probability random noise), so the model should learn a
    near-zero coefficient for it."""
    examples = []
    for i in range(n):
        label = i % 2  # alternating 1,0,1,0,...
        block_pos = i % 4
        noise = 0.0 if block_pos in (0, 1) else 1.0
        perfect = 1.0 if label == 1 else -1.0
        examples.append(TrainingExample(features={"perfect_predictor": perfect, "pure_noise": noise}, label=label))
    return examples


def test_train_logistic_regression_recovers_known_perfect_vs_noise_relationship():
    examples = _perfect_vs_noise_examples(60)
    coefficients = train_logistic_regression(examples)
    assert abs(coefficients["perfect_predictor"]) > 2.0
    assert abs(coefficients["pure_noise"]) < 0.3
    assert abs(coefficients["perfect_predictor"]) > abs(coefficients["pure_noise"])


def test_rank_evidence_value_reports_insufficient_data_below_threshold():
    examples = _perfect_vs_noise_examples(10)
    report = rank_evidence_value(examples, min_sample_size=MIN_SAMPLE_SIZE)
    assert report.sufficient_sample is False
    assert report.feature_importances == {}
    assert "insufficient" in report.notes.lower()
    assert str(MIN_SAMPLE_SIZE) in report.notes


def test_rank_evidence_value_computes_ranking_at_or_above_threshold():
    examples = _perfect_vs_noise_examples(60)
    report = rank_evidence_value(examples, min_sample_size=50)
    assert report.sufficient_sample is True
    assert report.sample_size == 60
    assert abs(report.feature_importances["perfect_predictor"]) > abs(report.feature_importances["pure_noise"])


def test_rank_evidence_value_custom_min_sample_size_gating():
    examples = _perfect_vs_noise_examples(20)
    below = rank_evidence_value(examples, min_sample_size=25)
    at_threshold = rank_evidence_value(examples, min_sample_size=20)
    assert below.sufficient_sample is False
    assert at_threshold.sufficient_sample is True


# --- rolling-window drift -----------------------------------------------------

def test_rolling_window_drift_splits_into_non_overlapping_windows():
    examples = _perfect_vs_noise_examples(40)
    reports = rolling_window_drift(examples, window_size=20, min_sample_size=20)
    assert len(reports) == 2
    assert all(r.sufficient_sample for r in reports)
    assert all(r.sample_size == 20 for r in reports)


def test_rolling_window_drift_reports_insufficient_for_small_final_window():
    examples = _perfect_vs_noise_examples(45)  # 20 + 20 + 5 remainder
    reports = rolling_window_drift(examples, window_size=20, min_sample_size=20)
    assert len(reports) == 3
    assert reports[0].sufficient_sample and reports[1].sufficient_sample
    assert reports[2].sufficient_sample is False  # only 5 examples in the last window
    assert reports[2].sample_size == 5


# --- regime-sliced ranking / engineered regime-dependent fixture -------------

def _regime_dependent_examples(n_per_regime: int) -> dict[str, list[TrainingExample]]:
    """Engineered fixture for task 1a: `regime_dependent_feature` perfectly
    predicts the label in REGIME_A, but is pure noise (same exact-zero-
    correlation block construction as above) in REGIME_B. The drift check
    must recover a large importance in REGIME_A and a near-zero importance
    in REGIME_B for the SAME feature."""
    regime_a = []
    for i in range(n_per_regime):
        label = i % 2
        value = 1.0 if label == 1 else -1.0
        regime_a.append(TrainingExample(features={"regime_dependent_feature": value}, label=label))

    regime_b = []
    for i in range(n_per_regime):
        label = i % 2
        block_pos = i % 4
        value = 0.0 if block_pos in (0, 1) else 1.0  # zero-correlation construction
        regime_b.append(TrainingExample(features={"regime_dependent_feature": value}, label=label))

    return {"REGIME_A": regime_a, "REGIME_B": regime_b}


def test_regime_sliced_ranking_recovers_engineered_regime_dependence():
    examples_by_regime = _regime_dependent_examples(40)
    reports = regime_sliced_ranking(examples_by_regime, min_sample_size=40)

    assert reports["REGIME_A"].sufficient_sample is True
    assert reports["REGIME_B"].sufficient_sample is True

    importance_a = abs(reports["REGIME_A"].feature_importances["regime_dependent_feature"])
    importance_b = abs(reports["REGIME_B"].feature_importances["regime_dependent_feature"])
    assert importance_a > 2.0
    assert importance_b < 0.3
    assert importance_a > importance_b


def test_regime_sliced_ranking_reports_insufficient_data_per_slice_independently():
    examples_by_regime = {
        "REGIME_A": _regime_dependent_examples(40)["REGIME_A"],
        "REGIME_B": _regime_dependent_examples(5)["REGIME_B"],  # too small
    }
    reports = regime_sliced_ranking(examples_by_regime, min_sample_size=40)
    assert reports["REGIME_A"].sufficient_sample is True
    assert reports["REGIME_B"].sufficient_sample is False


# --- EvidenceValueReportRecord schema -----------------------------------------

def test_evidence_value_report_record_to_row_serializes_datetime():
    record = EvidenceValueReportRecord(
        run_at=datetime(2026, 1, 1, tzinfo=UTC), method="full_history_logistic_regression",
        sample_size=36, feature_importances={"model_agreement": 0.4}, sufficient_sample=False,
        notes="insufficient data",
    )
    row = record.to_row()
    assert isinstance(row["run_at"], str)
    assert row["feature_importances"] == {"model_agreement": 0.4}


# --- fetch_backfilled_decisions_chronological / fetch_directional_examples:
# pagination-safe repository retrieval (2026-09-27) ---------------------------

def _decision_record(id_, created_at, decision="BUY", investment_horizon_days=30):
    record = JudgeDecisionRecord(
        run_id="RUN-TEST", asset_id="asset-1", created_at=created_at, decision=decision,
        confidence=0.6, target_allocation=0.1, expected_return=0.1, expected_alpha=0.05,
        risk_score=0.4, uncertainty=0.3, model_agreement=0.8, source_agreement=0.7,
        investment_horizon_days=investment_horizon_days, key_evidence=[], contradictory_evidence=[],
        key_risks=[], invalidation_conditions=[], requires_review=False, thesis="t",
        macro_sensitivity="n/a", regime_id=None, prompt_template_id="p1",
        estimated_cost=Decimal("0.01"), is_backfilled=True,
    )
    record.id = id_
    return record


def _outcome_row(decision_id, decision_timestamp, realized_return=0.05, outcome_label="HIT_TARGET", is_backfilled=True):
    # Real fields required for DecisionOutcome.model_validate() to succeed
    # -- fetch_directional_examples now retrieves outcomes through
    # DecisionOutcomeRepository.get_recent() (2026-09-27, batch 3), which
    # validates every raw row into a full DecisionOutcome, not just the 4
    # fields the old raw-dict-based code happened to select (same
    # convention as _decision_record's own comment above).
    record = DecisionOutcome(
        decision_id=decision_id, asset_id="asset-1", decision_timestamp=decision_timestamp,
        horizon_days=30, target_return=0.1, stop_return=-0.1, realized_return=realized_return,
        outcome_label=outcome_label, judge_confidence=0.6, is_backfilled=is_backfilled,
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


class _FakeOutcomesQuery:
    def __init__(self, rows, capped=False):
        self._rows = rows
        self._capped = capped
        self._ranged = False
        self._order_keys = []

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, column, value):
        self._rows = [r for r in self._rows if r.get(column) == value]
        return self

    def neq(self, column, value):
        self._rows = [r for r in self._rows if r.get(column) != value]
        return self

    def order(self, column, desc=False):
        self._order_keys.append((column, desc))
        return self

    def range(self, start, end):
        for column, desc in reversed(self._order_keys):
            self._rows = sorted(self._rows, key=lambda r: r.get(column, ""), reverse=desc)
        self._rows = self._rows[start:end + 1]
        self._ranged = True
        return self

    def execute(self):
        rows = self._rows
        if self._capped and not self._ranged:
            rows = rows[:repository_module._SUPABASE_MAX_ROWS_PER_REQUEST]
        return _FakeResult(rows)


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeOutcomesClient:
    def __init__(self, outcome_rows):
        self._outcome_rows = outcome_rows

    def table(self, name):
        assert name == "decision_outcomes"
        # capped (2026-09-27, batch 3): reproduces the real Supabase
        # per-request row cap for a query issued without `.range()` -- the
        # exact regression migrating this consumer to get_recent() closes.
        return _FakeOutcomesQuery(list(self._outcome_rows), capped=True)


def _setup_fake_repository(monkeypatch, records):
    _FakeJudgeDecisionRepository.last_calls = []
    _FakeJudgeDecisionRepository.records = records
    monkeypatch.setattr(run_evidence_value_ranking_module, "JudgeDecisionRepository", _FakeJudgeDecisionRepository)


def test_fetch_backfilled_decisions_chronological_calls_repository_with_limit_none_and_backfilled_true(monkeypatch):
    _setup_fake_repository(monkeypatch, [])

    fetch_backfilled_decisions_chronological(client=object())

    assert _FakeJudgeDecisionRepository.last_calls == [{"limit": None, "is_backfilled": True}]


def test_fetch_backfilled_decisions_chronological_reverses_descending_repository_order(monkeypatch):
    # get_recent() returns DESCENDING by created_at (newest first) -- this
    # proves the reversal genuinely restores ascending chronological order,
    # not merely that some value comes back.
    old = _decision_record("old", datetime(2026, 1, 1, tzinfo=UTC))
    mid = _decision_record("mid", datetime(2026, 6, 1, tzinfo=UTC))
    new = _decision_record("new", datetime(2026, 9, 1, tzinfo=UTC))
    _setup_fake_repository(monkeypatch, [new, mid, old])  # descending, as get_recent() returns

    decisions = fetch_backfilled_decisions_chronological(client=object())

    assert [d.id for d in decisions] == ["old", "mid", "new"]  # ascending


def test_fetch_backfilled_decisions_chronological_does_not_truncate_a_population_crossing_the_old_1000_row_boundary(monkeypatch):
    records = [_decision_record(f"d-{i}", datetime(2026, 1, 1, tzinfo=UTC)) for i in range(1001)]
    _setup_fake_repository(monkeypatch, records)

    decisions = fetch_backfilled_decisions_chronological(client=object())

    assert len(decisions) == 1001


def test_fetch_directional_examples_uses_record_attributes_not_dict_keys(monkeypatch):
    # Proves the dict-access -> JudgeDecisionRecord-attribute migration is
    # real for fetch_directional_examples's own downstream logic (decision/
    # feature-field lookups), independent of the ordering question above.
    buy = _decision_record("buy-1", datetime(2026, 1, 1, tzinfo=UTC), decision="BUY", investment_horizon_days=45)
    _setup_fake_repository(monkeypatch, [buy])
    client = _FakeOutcomesClient([_outcome_row("buy-1", datetime(2026, 1, 1, tzinfo=UTC))])

    examples = fetch_directional_examples(client)

    assert len(examples) == 1
    assert examples[0].label == 1  # BUY with positive realized_return -> correct
    assert examples[0].features["investment_horizon_days"] == 45
    assert set(examples[0].features) == set(FEATURE_FIELDS)


def test_fetch_directional_examples_does_not_truncate_past_the_old_real_1000_row_cap(monkeypatch):
    # The old raw decision_outcomes query had no `.range()`/`.limit()` at
    # all -- a genuine unbounded table scan, subject to Supabase's real
    # implicit per-request row cap (reproduced here via the fake's own
    # `capped` simulation). Proves the migration to get_recent() actually
    # retrieves the complete population, not just the first page.
    now = datetime(2026, 9, 27, tzinfo=UTC)
    decisions = [_decision_record(f"d-{i}", now, investment_horizon_days=i % 90 + 1) for i in range(1200)]
    _setup_fake_repository(monkeypatch, decisions)
    client = _FakeOutcomesClient([_outcome_row(f"d-{i}", now) for i in range(1200)])

    examples = fetch_directional_examples(client)

    assert len(examples) == 1200


def test_fetch_directional_examples_orders_by_ascending_decision_timestamp_for_rolling_windows(monkeypatch):
    # The critical ordering fix this batch introduces: rolling_window_drift
    # requires chronological order, but the old raw query had no `.order()`
    # at all. This proves fetch_directional_examples now genuinely sorts
    # by the outcome's own real decision_timestamp, ascending -- using
    # investment_horizon_days as a per-decision identity marker (each
    # decision here has a distinct value) to verify the ACTUAL sequence
    # examples come out in, not just that some value comes back.
    d_newest = _decision_record("newest", datetime(2026, 1, 1, tzinfo=UTC), investment_horizon_days=90)
    d_oldest = _decision_record("oldest", datetime(2026, 1, 1, tzinfo=UTC), investment_horizon_days=10)
    d_middle = _decision_record("middle", datetime(2026, 1, 1, tzinfo=UTC), investment_horizon_days=45)
    _setup_fake_repository(monkeypatch, [d_newest, d_oldest, d_middle])  # deliberately NOT chronological

    # Outcomes supplied in an arbitrary, non-chronological order too --
    # proves the final order is driven by each row's own real
    # decision_timestamp, never by whatever order either query happened to
    # return rows in.
    client = _FakeOutcomesClient([
        _outcome_row("newest", datetime(2026, 9, 1, tzinfo=UTC)),
        _outcome_row("oldest", datetime(2026, 1, 1, tzinfo=UTC)),
        _outcome_row("middle", datetime(2026, 5, 1, tzinfo=UTC)),
    ])
    examples = fetch_directional_examples(client)

    # investment_horizon_days uniquely identifies each decision here --
    # ascending order must be oldest (10) -> middle (45) -> newest (90).
    assert [e.features["investment_horizon_days"] for e in examples] == [10, 45, 90]


def test_fetch_directional_examples_ordering_is_independent_of_input_order(monkeypatch):
    # No lookahead / no accidental order-dependence: feeding the SAME
    # observations in a different input order must still produce the
    # identical chronological output order -- the sort key is each row's
    # own real timestamp, not position in the input list.
    d_a = _decision_record("a", datetime(2026, 1, 1, tzinfo=UTC), investment_horizon_days=1)
    d_b = _decision_record("b", datetime(2026, 1, 1, tzinfo=UTC), investment_horizon_days=2)
    d_c = _decision_record("c", datetime(2026, 1, 1, tzinfo=UTC), investment_horizon_days=3)
    _setup_fake_repository(monkeypatch, [d_a, d_b, d_c])

    rows_forward = [
        _outcome_row("a", datetime(2026, 1, 1, tzinfo=UTC)),
        _outcome_row("b", datetime(2026, 6, 1, tzinfo=UTC)),
        _outcome_row("c", datetime(2026, 9, 1, tzinfo=UTC)),
    ]
    examples_forward = fetch_directional_examples(_FakeOutcomesClient(rows_forward))
    examples_reversed = fetch_directional_examples(_FakeOutcomesClient(list(reversed(rows_forward))))

    forward_order = [e.features["investment_horizon_days"] for e in examples_forward]
    reversed_input_order = [e.features["investment_horizon_days"] for e in examples_reversed]
    assert forward_order == [1, 2, 3]
    assert reversed_input_order == [1, 2, 3]  # identical, regardless of input order
