import math
from statistics import NormalDist

import pytest

from app.benchmarks.statistical_validation import (
    brier_decomposition,
    brier_score,
    deflated_sharpe_ratio,
    expected_max_sharpe_under_null,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
    reliability_table,
    sample_sharpe_stats,
    sharpe_ratio_standard_error,
)

# --- Probabilistic Sharpe Ratio -----------------------------------------------

def test_psr_at_benchmark_sharpe_is_exactly_half():
    # Known-correct by construction: when sharpe_ratio == benchmark_sharpe,
    # the z-score numerator is exactly 0, so PSR = Phi(0) = 0.5 for ANY n,
    # skew, or kurtosis — this is an exact mathematical identity, not an
    # approximation.
    for n in (5, 30, 1000):
        for skew, kurt in ((0.0, 3.0), (-1.2, 6.5), (0.8, 4.1)):
            psr = probabilistic_sharpe_ratio(1.25, 1.25, n, skew, kurt)
            assert psr == pytest.approx(0.5, abs=1e-9)


def test_psr_matches_independent_z_score_computation():
    # Cross-check against Lo (2002)'s closed-form standard error, computed
    # here via a second, independently-written expression (not calling the
    # module's own helper), and Phi via the stdlib's own NormalDist —
    # confirms no transcription error in the module's implementation.
    sr, sr_star, n, skew, kurt = 1.8, 0.0, 40, -0.5, 5.0
    se_expected = math.sqrt((1 - skew * sr + (kurt - 1) / 4 * sr**2) / (n - 1))
    z_expected = (sr - sr_star) / se_expected
    expected = NormalDist().cdf(z_expected)
    assert probabilistic_sharpe_ratio(sr, sr_star, n, skew, kurt) == pytest.approx(expected, rel=1e-12)


def test_psr_increases_with_more_observations_when_sharpe_exceeds_benchmark():
    low_n = probabilistic_sharpe_ratio(1.0, 0.0, 10)
    high_n = probabilistic_sharpe_ratio(1.0, 0.0, 500)
    assert high_n > low_n


def test_sharpe_ratio_standard_error_rejects_too_few_observations():
    with pytest.raises(ValueError):
        sharpe_ratio_standard_error(1.0, 1)


# --- Deflated Sharpe Ratio ----------------------------------------------------

def test_expected_max_sharpe_is_zero_at_one_trial_the_real_project_case():
    # This project's honest trial count is 1 (see README's Phase 3g section)
    # — with no genuine selection among alternatives, no deflation applies.
    assert expected_max_sharpe_under_null(1, sharpe_std_across_trials=0.4) == 0.0


def test_expected_max_sharpe_rejects_zero_trials():
    with pytest.raises(ValueError):
        expected_max_sharpe_under_null(0, 0.4)


def test_expected_max_sharpe_increases_with_more_trials():
    small = expected_max_sharpe_under_null(5, sharpe_std_across_trials=0.3)
    large = expected_max_sharpe_under_null(500, sharpe_std_across_trials=0.3)
    assert large > small > 0


def test_dsr_at_one_trial_reduces_exactly_to_psr_of_zero():
    sr, n = 0.9, 60
    dsr = deflated_sharpe_ratio(sr, n_observations=n, n_trials=1)
    psr_zero = probabilistic_sharpe_ratio(sr, 0.0, n)
    assert dsr == pytest.approx(psr_zero, rel=1e-12)


def test_dsr_is_lower_than_undeflated_psr_when_multiple_trials_occurred():
    # With a real multi-trial count, the deflation must make DSR strictly
    # harder to clear than the naive (non-deflated) PSR(0) — otherwise the
    # correction isn't doing anything.
    sr, n = 0.9, 60
    dsr_many_trials = deflated_sharpe_ratio(sr, n_observations=n, n_trials=50, sharpe_std_across_trials=0.3)
    psr_zero = probabilistic_sharpe_ratio(sr, 0.0, n)
    assert dsr_many_trials < psr_zero


# --- sample_sharpe_stats ------------------------------------------------------

def test_sample_sharpe_stats_matches_hand_computed_values():
    # returns = [1, 2, 3]: mean=2, population variance=2/3, stdev=sqrt(2/3).
    # Symmetric around the mean -> skewness=0 exactly. Kurtosis computed by
    # hand: sum((r-mean)^4)/n = (1+0+1)/3 = 2/3; kurtosis = (2/3)/stdev^4
    # = (2/3)/(4/9) = 1.5.
    sharpe, skew, kurt, n = sample_sharpe_stats([1.0, 2.0, 3.0])
    stdev = math.sqrt(2 / 3)
    assert n == 3
    assert sharpe == pytest.approx(2 / stdev)
    assert skew == pytest.approx(0.0, abs=1e-9)
    assert kurt == pytest.approx(1.5, rel=1e-9)


def test_sample_sharpe_stats_rejects_too_few_returns():
    with pytest.raises(ValueError):
        sample_sharpe_stats([0.01])


def test_sample_sharpe_stats_rejects_zero_variance():
    with pytest.raises(ValueError):
        sample_sharpe_stats([0.05, 0.05, 0.05])


# --- Probability of Backtest Overfitting (CSCV) ------------------------------

def test_pbo_is_zero_for_a_strictly_dominant_configuration():
    # A is B shifted up by a constant (+4) in every period -> identical
    # variance in every possible subset, strictly higher mean in every
    # subset -> A has the higher Sharpe ratio in EVERY in-sample AND
    # out-of-sample split, so the in-sample-best config never ranks below
    # median OOS. PBO must be exactly 0.0 (verified by hand for this
    # construction, not merely asserted).
    b = [1.0, 2.0, 3.0, 4.0, 1.0, 2.0, 3.0, 4.0]
    a = [v + 4.0 for v in b]
    pbo = probability_of_backtest_overfitting([a, b], n_subsamples=4)
    assert pbo == pytest.approx(0.0)


def test_pbo_is_exactly_half_for_two_identical_configurations():
    # Two configurations with LITERALLY identical return series tie on
    # every in-sample and out-of-sample comparison. By this function's
    # documented tie convention (a median tie scores 0.5), and since ties
    # occur on every single split, PBO must be exactly 0.5 — provable by
    # hand for this construction (see docstring derivation in the module),
    # not merely asserted from running the code.
    returns = [0.02, -0.01, 0.03, 0.01, -0.02, 0.015, 0.005, -0.005]
    pbo = probability_of_backtest_overfitting([returns, returns], n_subsamples=4)
    assert pbo == pytest.approx(0.5)


def test_pbo_rejects_fewer_than_two_configurations():
    with pytest.raises(ValueError):
        probability_of_backtest_overfitting([[0.01, 0.02, 0.03, 0.04]], n_subsamples=2)


def test_pbo_rejects_odd_or_non_dividing_subsample_count():
    with pytest.raises(ValueError):
        probability_of_backtest_overfitting([[0.01] * 8, [0.02] * 8], n_subsamples=3)


# --- Brier score decomposition ------------------------------------------------

def test_brier_decomposition_reconstructs_plain_brier_score_exactly():
    # reliability - resolution + uncertainty + within_bucket_dispersion is
    # an exact algebraic identity for ANY predictions/outcomes/bucketing —
    # checked across several distinct synthetic datasets (including
    # continuous confidence values that don't share an exact bucket mean),
    # which is a real, checkable known-correct property (not a memorized
    # literature number). The classical 3-term Murphy decomposition alone
    # (without within_bucket_dispersion) is only exact when every point's
    # forecast equals its bucket mean — see the module docstring.
    datasets = [
        ([0.9, 0.8, 0.3, 0.2, 0.6], [1, 1, 0, 0, 1]),
        ([0.5, 0.5, 0.5, 0.5], [1, 0, 1, 0]),
        ([0.1, 0.95, 0.4, 0.6, 0.7, 0.2], [0, 1, 1, 0, 1, 0]),
    ]
    for predictions, outcomes in datasets:
        result = brier_decomposition(predictions, outcomes)
        assert result["reconstructed"] == pytest.approx(result["brier_score"], abs=1e-9)
        assert result["brier_score"] == pytest.approx(brier_score(predictions, outcomes))


def test_brier_decomposition_within_bucket_dispersion_is_zero_for_singleton_buckets():
    # Fine enough bucketing that every bucket holds forecasts equal to its
    # own mean trivially (each bucket ends up with identical raw values) —
    # the classical 3-term decomposition alone must already be exact here,
    # i.e. within_bucket_dispersion is exactly 0.
    predictions = [1.0, 0.0, 1.0, 0.0]
    outcomes = [1, 0, 1, 0]
    result = brier_decomposition(predictions, outcomes)
    assert result["brier_score"] == pytest.approx(0.0, abs=1e-12)
    assert result["reliability"] == pytest.approx(0.0, abs=1e-12)
    assert result["within_bucket_dispersion"] == pytest.approx(0.0, abs=1e-12)


def test_brier_decomposition_bucket_boundary_not_misclassified_by_float_error():
    # 0.3 / 0.1 == 2.9999999999999996 in float arithmetic — a naive
    # int(f / bucket_size) truncates this into bucket 2 ("0.2-0.3") instead
    # of bucket 3 ("0.3-0.4"). Confirms the fix via reliability_table.
    table = reliability_table([0.3], [1], bucket_size=0.1)
    assert "0.3-0.4" in table
    assert "0.2-0.3" not in table


def test_reliability_table_reports_bucket_sample_sizes():
    predictions = [0.55, 0.58, 0.91, 0.95, 0.2]
    outcomes = [1, 0, 1, 1, 0]
    table = reliability_table(predictions, outcomes, bucket_size=0.1)
    assert sum(b["n"] for b in table.values()) == 5
    assert "0.5-0.6" in table
    assert table["0.5-0.6"]["n"] == 2
