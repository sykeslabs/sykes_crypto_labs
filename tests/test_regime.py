from datetime import date

import pytest

from app.market_data.regime import (
    compute_altcoin_season_index,
    compute_breadth_pct,
    compute_btc_dominance,
    compute_halving_cycle_days,
    classify_risk_regime,
    moving_average,
)


def test_compute_breadth_pct():
    assert compute_breadth_pct([0.1, 0.2, -0.05, 0.3]) == pytest.approx(0.75)


def test_compute_breadth_pct_ignores_none():
    assert compute_breadth_pct([0.1, None, -0.05]) == pytest.approx(0.5)


def test_compute_breadth_pct_empty_is_none():
    assert compute_breadth_pct([None, None]) is None


def test_classify_risk_on():
    regime = classify_risk_regime(btc_price=110, btc_ma_short=105, btc_ma_long=100, breadth_pct=0.7)
    assert regime == "RISK_ON"


def test_classify_risk_off():
    regime = classify_risk_regime(btc_price=90, btc_ma_short=95, btc_ma_long=100, breadth_pct=0.3)
    assert regime == "RISK_OFF"


def test_classify_neutral_on_mixed_signals():
    # Above short MA but below long MA -> mixed, not a clean trend either way
    regime = classify_risk_regime(btc_price=102, btc_ma_short=100, btc_ma_long=105, breadth_pct=0.5)
    assert regime == "NEUTRAL"


def test_classify_missing_breadth_defers_to_price_trend():
    regime = classify_risk_regime(btc_price=110, btc_ma_short=105, btc_ma_long=100, breadth_pct=None)
    assert regime == "RISK_ON"


def test_compute_btc_dominance():
    assert compute_btc_dominance(600_000, 1_000_000) == pytest.approx(0.6)


def test_compute_btc_dominance_zero_universe_is_none():
    assert compute_btc_dominance(600_000, 0) is None


def test_compute_altcoin_season_index():
    # 3 of 4 altcoins outperformed BTC's 90d momentum of 0.10
    idx = compute_altcoin_season_index([0.20, 0.15, 0.05, 0.30], btc_momentum_90d=0.10)
    assert idx == pytest.approx(0.75)


def test_compute_altcoin_season_index_none_without_btc_momentum():
    assert compute_altcoin_season_index([0.20, 0.15], btc_momentum_90d=None) is None


def test_moving_average():
    assert moving_average([1.0, 2.0, 3.0, 4.0], window=2) == pytest.approx(3.5)


def test_moving_average_insufficient_data_is_none():
    assert moving_average([1.0, 2.0], window=5) is None


def test_halving_cycle_days_shortly_after_known_halving():
    days_since, days_until = compute_halving_cycle_days(date(2024, 4, 27))  # 7 days after 2024-04-20
    assert days_since == 7
    assert days_until == 1458 - 7


def test_halving_cycle_days_far_future_rolls_over_interval():
    # 2024-04-20 + 1458 days ~= 2028-04-16; a date after that should roll to
    # the *next* estimated cycle rather than going negative.
    far_future = date(2029, 1, 1)
    days_since, days_until = compute_halving_cycle_days(far_future)
    assert days_since > 0
    assert days_until > 0


def test_halving_cycle_days_before_any_known_halving_does_not_crash():
    # A date before Bitcoin's first halving (2012) can't occur in practice —
    # `as_of` is always "now" — but the function shouldn't raise for it.
    days_since, days_until = compute_halving_cycle_days(date(2010, 1, 1))
    assert isinstance(days_since, int)
    assert isinstance(days_until, int)
