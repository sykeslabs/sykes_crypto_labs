from datetime import UTC, datetime

import pytest

from app.market_data.derivatives_factors import (
    annualize_daily_volatility,
    compute_annualized_carry_yield,
    compute_volatility_risk_premium,
)


def test_annualized_carry_yield_contango():
    # Future priced 1% above spot, 36.5 days to expiry -> ~10% annualized
    as_of = datetime(2026, 1, 1, tzinfo=UTC)
    delivery_ms = int(datetime(2026, 2, 6, tzinfo=UTC).timestamp() * 1000)  # 36 days out
    yield_ = compute_annualized_carry_yield(100.0, 101.0, delivery_ms, as_of)
    assert yield_ == pytest.approx(0.01 * (365 / 36), rel=0.05)


def test_annualized_carry_yield_backwardation_is_negative():
    as_of = datetime(2026, 1, 1, tzinfo=UTC)
    delivery_ms = int(datetime(2026, 2, 6, tzinfo=UTC).timestamp() * 1000)
    yield_ = compute_annualized_carry_yield(100.0, 99.0, delivery_ms, as_of)
    assert yield_ < 0


def test_annualized_carry_yield_expired_contract_is_none():
    as_of = datetime(2026, 3, 1, tzinfo=UTC)
    delivery_ms = int(datetime(2026, 2, 6, tzinfo=UTC).timestamp() * 1000)  # already past
    assert compute_annualized_carry_yield(100.0, 101.0, delivery_ms, as_of) is None


def test_annualized_carry_yield_zero_spot_is_none():
    as_of = datetime(2026, 1, 1, tzinfo=UTC)
    delivery_ms = int(datetime(2026, 2, 6, tzinfo=UTC).timestamp() * 1000)
    assert compute_annualized_carry_yield(0.0, 101.0, delivery_ms, as_of) is None


def test_vrp_positive_when_implied_exceeds_realized():
    assert compute_volatility_risk_premium(60.0, 45.0) == pytest.approx(15.0)


def test_vrp_negative_when_realized_exceeds_implied():
    assert compute_volatility_risk_premium(30.0, 45.0) == pytest.approx(-15.0)


def test_vrp_none_when_either_input_missing():
    assert compute_volatility_risk_premium(None, 45.0) is None
    assert compute_volatility_risk_premium(60.0, None) is None


def test_annualize_daily_volatility():
    # A 2% daily stdev annualizes to roughly 38%
    result = annualize_daily_volatility(0.02)
    assert result == pytest.approx(0.02 * (365 ** 0.5) * 100)
    assert 30 < result < 45
