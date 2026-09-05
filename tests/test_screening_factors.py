import pytest

from app.market_data.factors import (
    compute_composite_factor_scores,
    compute_max_drawdown,
    compute_relative_strength,
    compute_volatility,
    percentile_ranks,
)


def test_compute_volatility_known_series():
    # Constant series -> zero volatility
    assert compute_volatility([100.0, 100.0, 100.0]) == pytest.approx(0.0)


def test_compute_volatility_nontrivial_series():
    closes = [100.0, 110.0, 99.0, 108.9]
    vol = compute_volatility(closes)
    assert vol is not None
    assert vol > 0


def test_compute_volatility_insufficient_data():
    assert compute_volatility([]) is None
    assert compute_volatility([100.0]) is None


def test_compute_max_drawdown_known_series():
    # Peaks at 100, drops to 50 -> -50% drawdown
    closes = [80.0, 100.0, 90.0, 50.0, 70.0]
    assert compute_max_drawdown(closes) == pytest.approx(-0.5)


def test_compute_max_drawdown_monotonic_up_is_zero():
    closes = [10.0, 20.0, 30.0]
    assert compute_max_drawdown(closes) == pytest.approx(0.0)


def test_compute_max_drawdown_empty_is_none():
    assert compute_max_drawdown([]) is None


def test_compute_relative_strength():
    assert compute_relative_strength(0.30, 0.10) == pytest.approx(0.20)
    assert compute_relative_strength(None, 0.10) is None
    assert compute_relative_strength(0.30, None) is None


def test_percentile_ranks_orders_correctly():
    ranks = percentile_ranks([10.0, 30.0, 20.0])
    assert ranks[0] == 0.0  # worst
    assert ranks[2] == 0.5  # middle
    assert ranks[1] == 1.0  # best


def test_percentile_ranks_preserves_none():
    ranks = percentile_ranks([10.0, None, 30.0])
    assert ranks[1] is None
    assert ranks[0] == 0.0
    assert ranks[2] == 1.0


def test_percentile_ranks_all_none():
    assert percentile_ranks([None, None]) == [None, None]


def test_percentile_ranks_single_value_is_neutral():
    assert percentile_ranks([42.0]) == [0.5]


def test_percentile_ranks_ties_get_averaged_rank():
    ranks = percentile_ranks([10.0, 10.0, 30.0])
    assert ranks[0] == pytest.approx(ranks[1])
    assert ranks[2] > ranks[0]


def test_composite_score_higher_momentum_scores_higher():
    rows = [
        {
            "momentum_30d": 0.50, "momentum_7d": 0.10, "relative_strength_30d": 0.20,
            "volatility_30d": 0.05, "drawdown_30d": -0.10, "volume_24h": 1_000_000,
        },
        {
            "momentum_30d": 0.05, "momentum_7d": 0.01, "relative_strength_30d": -0.10,
            "volatility_30d": 0.05, "drawdown_30d": -0.10, "volume_24h": 1_000_000,
        },
    ]
    scores = compute_composite_factor_scores(rows)
    assert scores[0] > scores[1]


def test_composite_score_lower_volatility_scores_higher_when_other_factors_equal():
    rows = [
        {
            "momentum_30d": 0.20, "momentum_7d": 0.05, "relative_strength_30d": 0.0,
            "volatility_30d": 0.02, "drawdown_30d": -0.10, "volume_24h": 1_000_000,
        },
        {
            "momentum_30d": 0.20, "momentum_7d": 0.05, "relative_strength_30d": 0.0,
            "volatility_30d": 0.20, "drawdown_30d": -0.10, "volume_24h": 1_000_000,
        },
    ]
    scores = compute_composite_factor_scores(rows)
    assert scores[0] > scores[1]


def test_composite_score_missing_factor_does_not_crash_and_still_ranks_on_other_factors():
    # An asset missing volatility_30d entirely should still be scored (not
    # excluded/None) based on its other real factors, with the missing
    # factor's weight redistributed rather than treated as a zero/failure.
    rows = [
        {
            "momentum_30d": 0.50, "momentum_7d": 0.20, "relative_strength_30d": 0.30,
            "volatility_30d": None, "drawdown_30d": -0.05, "volume_24h": 1_000_000,
        },
        {
            "momentum_30d": 0.05, "momentum_7d": 0.01, "relative_strength_30d": -0.10,
            "volatility_30d": 0.02, "drawdown_30d": -0.05, "volume_24h": 1_000_000,
        },
    ]
    scores = compute_composite_factor_scores(rows)
    assert scores[0] is not None
    # Row 0's strong momentum/relative-strength should dominate despite the
    # missing volatility factor.
    assert scores[0] > scores[1]


def test_composite_score_ties_split_evenly_not_by_input_order():
    # Two assets identical on every factor should score identically —
    # ranking ties must not be arbitrarily broken by list position.
    row = {
        "momentum_30d": 0.20, "momentum_7d": 0.05, "relative_strength_30d": 0.0,
        "volatility_30d": 0.10, "drawdown_30d": -0.10, "volume_24h": 1_000_000,
    }
    scores = compute_composite_factor_scores([dict(row), dict(row)])
    assert scores[0] == pytest.approx(scores[1])


def test_composite_score_all_factors_missing_is_none():
    rows = [{k: None for k in ("momentum_30d", "momentum_7d", "relative_strength_30d", "volatility_30d", "drawdown_30d", "volume_24h")}]
    assert compute_composite_factor_scores(rows) == [None]
