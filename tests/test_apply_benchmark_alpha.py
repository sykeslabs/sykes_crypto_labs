import pytest

from scripts.apply_benchmark_alpha import compute_benchmark_alpha


def test_compute_benchmark_alpha_known_hand_computation():
    # BTC (benchmark) went 100 -> 110: benchmark_return = 0.10 exactly.
    # The decision's own realized_return was 0.25 -> effective_alpha = 0.15 exactly.
    benchmark_return, effective_alpha = compute_benchmark_alpha(entry_price=100.0, exit_price=110.0, realized_return=0.25)
    assert benchmark_return == pytest.approx(0.10)
    assert effective_alpha == pytest.approx(0.15)


def test_compute_benchmark_alpha_negative_alpha_when_benchmark_outperforms():
    # BTC went 100 -> 130 (0.30) while the decision only realized 0.05 --
    # a real negative alpha: the decision underperformed passively holding BTC.
    benchmark_return, effective_alpha = compute_benchmark_alpha(entry_price=100.0, exit_price=130.0, realized_return=0.05)
    assert benchmark_return == pytest.approx(0.30)
    assert effective_alpha == pytest.approx(-0.25)


def test_compute_benchmark_alpha_when_benchmark_fell():
    # BTC fell 100 -> 90 (-0.10) while the decision realized +0.05 -- alpha is
    # larger than the raw realized_return, since it beat a falling benchmark too.
    benchmark_return, effective_alpha = compute_benchmark_alpha(entry_price=100.0, exit_price=90.0, realized_return=0.05)
    assert benchmark_return == pytest.approx(-0.10)
    assert effective_alpha == pytest.approx(0.15)
