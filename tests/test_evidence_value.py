from datetime import UTC, datetime

import pytest

from app.benchmarks.evidence_value import (
    MIN_SAMPLE_SIZE,
    TrainingExample,
    rank_evidence_value,
    regime_sliced_ranking,
    rolling_window_drift,
    train_logistic_regression,
)
from app.benchmarks.schemas import EvidenceValueReportRecord


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
