import pytest

from app.benchmarks.baseline_comparison import (
    build_equal_weight_basket_path,
    compute_baseline_stats,
)


def test_build_equal_weight_basket_path_known_hand_computation():
    # A: [100, 110, 121] -> normalized [1.0, 1.1, 1.21]
    # B: [50, 45, 45] -> normalized [1.0, 0.9, 0.9]
    # Basket average per day: [1.0, 1.0, 1.055] exactly.
    paths = {"A": [100.0, 110.0, 121.0], "B": [50.0, 45.0, 45.0]}
    basket = build_equal_weight_basket_path(paths)
    assert basket == pytest.approx([1.0, 1.0, 1.055])


def test_build_equal_weight_basket_path_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        build_equal_weight_basket_path({"A": [100.0, 110.0], "B": [50.0, 45.0, 45.0]})


def test_build_equal_weight_basket_path_rejects_empty_input():
    with pytest.raises(ValueError):
        build_equal_weight_basket_path({})


def test_compute_baseline_stats_known_hand_computation():
    # path: [100, 110, 121] -> total_return_raw = 121/100 - 1 = 0.21 exactly.
    # max_drawdown: monotonically increasing -> 0.0 exactly (never below peak).
    stats = compute_baseline_stats("TEST", [100.0, 110.0, 121.0], round_trip_cost_pct_value=0.02)
    assert stats.total_return_raw == pytest.approx(0.21)
    assert stats.total_return_net_of_costs == pytest.approx(0.19)
    assert stats.max_drawdown == pytest.approx(0.0)
    assert stats.n_days == 3


def test_compute_baseline_stats_known_drawdown():
    # path: [100, 50, 100] -> peak=100, trough=50 -> drawdown = (50-100)/100 = -0.5 exactly.
    stats = compute_baseline_stats("TEST", [100.0, 50.0, 100.0], round_trip_cost_pct_value=0.0)
    assert stats.max_drawdown == pytest.approx(-0.5)
    assert stats.total_return_raw == pytest.approx(0.0)


def test_compute_baseline_stats_rejects_too_short_path():
    with pytest.raises(ValueError):
        compute_baseline_stats("TEST", [100.0], round_trip_cost_pct_value=0.0)
