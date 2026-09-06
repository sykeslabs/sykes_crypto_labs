import pytest

from app.trading.fill_simulator import (
    OrderBookLevel,
    OrderBookSnapshot,
    estimate_fill_volatility_scaled,
    round_trip_cost_pct,
    walk_order_book,
)


def _book() -> OrderBookSnapshot:
    return OrderBookSnapshot(
        bids=[OrderBookLevel(99, 1), OrderBookLevel(98, 2), OrderBookLevel(97, 5)],
        asks=[OrderBookLevel(100, 1), OrderBookLevel(101, 2), OrderBookLevel(102, 5)],
        source="BINANCE",
    )


def test_walk_order_book_buy_within_top_level_has_zero_slippage():
    result = walk_order_book("BUY", order_size_usd=100.0, book=_book(), fee_rate=0.001)
    assert result.average_price == pytest.approx(100.0)
    assert result.top_of_book_price == pytest.approx(100.0)
    assert result.slippage_pct == pytest.approx(0.0)
    assert result.fully_filled is True
    assert result.levels_consumed == 1
    assert result.fee_usd == pytest.approx(100.0 * 0.001)


def test_walk_order_book_buy_spans_two_levels_known_vwap():
    # Known hand computation: level 1 fills $100 (qty 1); remaining $50 fills
    # at level 2 (price 101), qty = 50/101. VWAP = 150 / (1 + 50/101)
    # = 150*101/151 = 15150/151 = 100.33112582781457 exactly.
    result = walk_order_book("BUY", order_size_usd=150.0, book=_book(), fee_rate=0.001)
    expected_vwap = 15150 / 151
    assert result.average_price == pytest.approx(expected_vwap, rel=1e-12)
    assert result.slippage_pct == pytest.approx((expected_vwap - 100.0) / 100.0, rel=1e-12)
    assert result.levels_consumed == 2
    assert result.fully_filled is True
    assert result.filled_usd == pytest.approx(150.0)


def test_walk_order_book_buy_partial_fill_when_order_exceeds_available_depth():
    # Known hand computation: total available depth = 100 + 202 + 510 = 812.
    # An $1000 order can only fill $812 -- a genuine partial fill, not
    # unlimited liquidity beyond the fetched levels.
    result = walk_order_book("BUY", order_size_usd=1000.0, book=_book(), fee_rate=0.001)
    assert result.fully_filled is False
    assert result.filled_usd == pytest.approx(812.0)
    assert result.requested_usd == pytest.approx(1000.0)
    assert result.levels_consumed == 3
    # VWAP over fully-consumed levels: (100+202+510) / (1+2+5) = 812/8 = 101.5 exactly.
    assert result.average_price == pytest.approx(101.5)
    assert result.slippage_pct == pytest.approx(0.015)


def test_walk_order_book_sell_within_top_level_has_zero_slippage():
    result = walk_order_book("SELL", order_size_usd=99.0, book=_book(), fee_rate=0.001)
    assert result.average_price == pytest.approx(99.0)
    assert result.top_of_book_price == pytest.approx(99.0)
    assert result.slippage_pct == pytest.approx(0.0)
    assert result.fully_filled is True
    assert result.levels_consumed == 1


def test_walk_order_book_rejects_empty_side():
    empty_book = OrderBookSnapshot(bids=[], asks=[], source="BINANCE")
    with pytest.raises(ValueError):
        walk_order_book("BUY", 100.0, empty_book, fee_rate=0.001)


def test_walk_order_book_slippage_is_worse_for_larger_orders():
    small = walk_order_book("BUY", 100.0, _book(), fee_rate=0.001)
    large = walk_order_book("BUY", 812.0, _book(), fee_rate=0.001)
    assert large.slippage_pct > small.slippage_pct


# --- volatility-scaled fallback path ------------------------------------------

def test_estimate_fill_volatility_scaled_known_hand_computation():
    # Known hand computation: participation_rate = 1000/10000 = 0.1;
    # slippage = 0.5 * 0.04 * sqrt(0.1) = 0.02 * 0.31622776601683794
    # = 0.006324555320336759 exactly. BUY -> average_price = 100*(1+slippage).
    result = estimate_fill_volatility_scaled(
        "BUY", order_size_usd=1000.0, mid_price=100.0, recent_volatility=0.04,
        typical_daily_volume_usd=10000.0, fee_rate=0.001, slippage_multiplier=0.5,
    )
    expected_slippage = 0.5 * 0.04 * (0.1 ** 0.5)
    assert result.slippage_pct == pytest.approx(expected_slippage, rel=1e-12)
    assert result.average_price == pytest.approx(100.0 * (1 + expected_slippage), rel=1e-12)
    assert result.fill_method == "VOLATILITY_SCALED_ESTIMATE"
    assert result.fully_filled is True
    assert result.fee_usd == pytest.approx(1.0)


def test_estimate_fill_volatility_scaled_sell_moves_price_down():
    result = estimate_fill_volatility_scaled(
        "SELL", order_size_usd=1000.0, mid_price=100.0, recent_volatility=0.04,
        typical_daily_volume_usd=10000.0, fee_rate=0.001,
    )
    assert result.average_price < 100.0


def test_estimate_fill_volatility_scaled_rejects_nonpositive_volume():
    with pytest.raises(ValueError):
        estimate_fill_volatility_scaled("BUY", 100.0, 100.0, 0.04, 0.0, 0.001)


def test_estimate_fill_volatility_scaled_larger_order_has_more_slippage():
    small = estimate_fill_volatility_scaled("BUY", 100.0, 100.0, 0.04, 10000.0, 0.001)
    large = estimate_fill_volatility_scaled("BUY", 5000.0, 100.0, 0.04, 10000.0, 0.001)
    assert large.slippage_pct > small.slippage_pct


# --- round_trip_cost_pct -------------------------------------------------------

def test_round_trip_cost_pct_known_hand_computation():
    # Known hand computation, identical entry/exit conditions:
    # per-leg slippage = 0.5 * 0.04 * sqrt(1000/10000) = 0.02 * sqrt(0.1)
    # = 0.006324555320336759. Round trip = 2 * fee_rate + 2 * slippage
    # = 2*0.001 + 2*0.006324555320336759 = 0.014649110640673518 exactly.
    cost = round_trip_cost_pct(
        entry_volatility=0.04, entry_typical_daily_volume_usd=10000.0,
        exit_volatility=0.04, exit_typical_daily_volume_usd=10000.0,
        order_size_usd=1000.0, fee_rate=0.001,
    )
    per_leg_slippage = 0.5 * 0.04 * (0.1 ** 0.5)
    expected = 2 * 0.001 + 2 * per_leg_slippage
    assert cost == pytest.approx(expected, rel=1e-12)


def test_round_trip_cost_pct_increases_with_higher_volatility():
    low_vol = round_trip_cost_pct(0.01, 10000.0, 0.01, 10000.0, 1000.0, 0.001)
    high_vol = round_trip_cost_pct(0.10, 10000.0, 0.10, 10000.0, 1000.0, 0.001)
    assert high_vol > low_vol


def test_round_trip_cost_pct_is_always_positive():
    cost = round_trip_cost_pct(0.02, 5000.0, 0.03, 5000.0, 200.0, 0.001)
    assert cost > 0
