from datetime import UTC, datetime, timedelta

import pytest

from app.portfolio.holdings import aggregate_current_holdings, collapse_platforms, compute_current_allocations, filter_materially_held
from app.portfolio.schemas import HoldingsLedgerEntry


def _entry(asset_id, quantity, cost_basis=None, platform="coinbase"):
    return HoldingsLedgerEntry(
        asset_id=asset_id, quantity=quantity, cost_basis_usd=cost_basis,
        recorded_at=datetime.now(UTC), platform=platform,
    )


def _tx(asset_id, quantity, cost_basis=None, transaction_type="BUY", minutes_ago=0, platform="coinbase"):
    return HoldingsLedgerEntry(
        asset_id=asset_id, quantity=quantity, cost_basis_usd=cost_basis,
        recorded_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
        transaction_type=transaction_type, platform=platform,
    )


def test_cold_start_with_no_entries_returns_all_zero_never_crashes():
    # Real requirement: before any real holdings are ever entered, every
    # asset must read as 0.0 (100% cash by omission), not a crash and not
    # a silent fall-back to any other source.
    result = compute_current_allocations([], price_by_asset_id={"a1": 100.0, "a2": 50.0})
    assert result == {"a1": 0.0, "a2": 0.0}


def test_known_hand_computation_with_cash_and_one_asset():
    # Known: 2 BTC @ $100 = $200 value; cash = $800. Total = $1000.
    # BTC fraction = 200/1000 = 0.2 exactly; a2 (no holding) = 0.0.
    holdings = [_entry("btc", 2.0), _entry(None, 800.0)]
    result = compute_current_allocations(holdings, price_by_asset_id={"btc": 100.0, "eth": 50.0})
    assert result["btc"] == pytest.approx(0.2)
    assert result["eth"] == pytest.approx(0.0)


def test_known_hand_computation_multiple_assets_and_cash():
    # Known: 1 BTC @ $100 = $100; 4 ETH @ $50 = $200; cash = $700. Total = $1000.
    # BTC = 0.1, ETH = 0.2 exactly.
    holdings = [_entry("btc", 1.0), _entry("eth", 4.0), _entry(None, 700.0)]
    result = compute_current_allocations(holdings, price_by_asset_id={"btc": 100.0, "eth": 50.0})
    assert result["btc"] == pytest.approx(0.1)
    assert result["eth"] == pytest.approx(0.2)


def test_no_cash_line_entered_implies_zero_cash_not_undefined():
    # Real holdings with no cash row at all: total value is just the
    # summed real holdings -- fully allocated (fraction sums to 1.0), an
    # honest reflection of what was actually entered, not an error.
    holdings = [_entry("btc", 1.0), _entry("eth", 1.0)]
    result = compute_current_allocations(holdings, price_by_asset_id={"btc": 100.0, "eth": 100.0})
    assert result["btc"] == pytest.approx(0.5)
    assert result["eth"] == pytest.approx(0.5)


def test_zero_total_value_returns_all_zero_never_divides_by_zero():
    # A cash row of exactly $0 and nothing else -- total value is 0, must
    # not raise a ZeroDivisionError.
    holdings = [_entry(None, 0.0)]
    result = compute_current_allocations(holdings, price_by_asset_id={"btc": 100.0})
    assert result == {"btc": 0.0}


def test_removed_holding_represented_as_zero_quantity_not_absence():
    # Append-only "remove" is a new row with quantity=0 -- the latest row
    # per asset already reflects this correctly once dedup has happened
    # upstream (this function just trusts "latest_holdings" is already the
    # latest-per-asset view); confirm a zero-quantity entry contributes
    # zero value, not an error.
    holdings = [_entry("btc", 0.0), _entry(None, 1000.0)]
    result = compute_current_allocations(holdings, price_by_asset_id={"btc": 100.0})
    assert result["btc"] == pytest.approx(0.0)


def test_asset_with_no_real_price_available_is_skipped_not_crashed():
    # A held asset with no current price fetchable (e.g. a delisted/stale
    # asset) must not crash the whole computation -- it's simply excluded
    # from the value sum (can't be valued), while other real holdings and
    # cash still compute correctly.
    holdings = [_entry("btc", 1.0), _entry("obscure", 5.0), _entry(None, 900.0)]
    result = compute_current_allocations(holdings, price_by_asset_id={"btc": 100.0})
    # total_value = 100 (btc) + 900 (cash) = 1000; obscure has no price, excluded.
    assert result["btc"] == pytest.approx(0.1)


def test_asset_with_no_entered_holding_defaults_to_zero():
    holdings = [_entry("btc", 1.0), _entry(None, 900.0)]
    result = compute_current_allocations(holdings, price_by_asset_id={"btc": 100.0, "sol": 20.0})
    assert result["sol"] == pytest.approx(0.0)


# --- Phase 5b: aggregate_current_holdings (transactional, not snapshot) -------

def test_aggregate_sums_multiple_buys_for_the_same_asset():
    # 5 SOL @ $100 total, then 3 more SOL @ $120 total, in two separate
    # transactions -- a transactional view means these ADD to 8 SOL, not
    # the second transaction silently replacing the first.
    entries = [_tx("sol", 5.0, cost_basis=100.0, minutes_ago=60), _tx("sol", 3.0, cost_basis=120.0, minutes_ago=10)]
    result = aggregate_current_holdings(entries)
    assert len(result) == 1
    assert result[0].asset_id == "sol"
    assert result[0].quantity == pytest.approx(8.0)
    assert result[0].cost_basis_usd == pytest.approx(220.0)  # 100 + 120, weighted-average-cost


def test_aggregate_partial_sell_reduces_quantity_and_cost_basis_proportionally():
    # Bought 10 @ total cost basis $1000 ($100/unit average). Sell 4 units
    # -- 40% of the position -- should remove 40% of the cost basis too
    # (weighted-average-cost method), leaving 6 units @ $600 cost basis.
    entries = [_tx("sol", 10.0, cost_basis=1000.0, minutes_ago=60), _tx("sol", 4.0, transaction_type="SELL", minutes_ago=10)]
    result = aggregate_current_holdings(entries)
    assert len(result) == 1
    assert result[0].quantity == pytest.approx(6.0)
    assert result[0].cost_basis_usd == pytest.approx(600.0)


def test_aggregate_sell_that_exactly_zeroes_position_removes_it_from_result():
    entries = [_tx("sol", 5.0, cost_basis=500.0, minutes_ago=60), _tx("sol", 5.0, transaction_type="SELL", minutes_ago=10)]
    result = aggregate_current_holdings(entries)
    assert result == []  # a fully-sold asset shouldn't appear at all, not as a 0-quantity row


def test_aggregate_sell_exceeding_held_quantity_clamps_at_zero_not_negative():
    # Defensive backstop only (real validation lives at the API layer) --
    # must never produce a negative quantity that would corrupt allocation math.
    entries = [_tx("sol", 5.0, cost_basis=500.0, minutes_ago=60), _tx("sol", 9.0, transaction_type="SELL", minutes_ago=10)]
    result = aggregate_current_holdings(entries)
    assert result == []  # clamped to 0, same as the exact-zero case above


def test_aggregate_cash_line_uses_latest_row_only_never_summed():
    # Cash keeps its original Phase 5a semantic: an absolute stated total,
    # not a transaction ledger -- entering $2000 then later $500 means you
    # NOW have $500 cash, not $2500.
    entries = [_tx(None, 2000.0, minutes_ago=60), _tx(None, 500.0, minutes_ago=10)]
    result = aggregate_current_holdings(entries)
    assert len(result) == 1
    assert result[0].asset_id is None
    assert result[0].quantity == pytest.approx(500.0)


def test_aggregate_feeds_correctly_into_compute_current_allocations():
    # Integration check: two BUYs of SOL (8 total) + one cash row, fed
    # through the real two-step pipeline (aggregate, then allocate).
    entries = [
        _tx("sol", 5.0, cost_basis=500.0, minutes_ago=60),
        _tx("sol", 3.0, cost_basis=360.0, minutes_ago=10),
        _tx(None, 140.0, minutes_ago=60),
    ]
    aggregated = aggregate_current_holdings(entries)
    result = compute_current_allocations(aggregated, price_by_asset_id={"sol": 100.0})
    # 8 SOL @ $100 = $800; cash = $140; total = $940 -> SOL fraction = 800/940
    assert result["sol"] == pytest.approx(800.0 / 940.0)


# --- Phase 5o: platform-aware bucketing + collapse_platforms -----------------

def test_aggregate_buckets_the_same_asset_by_platform_independently():
    # The same asset held on two platforms is two independent positions,
    # each with its own weighted-average cost basis -- not one merged row.
    entries = [
        _tx("btc", 1.0, cost_basis=1000.0, platform="coinbase"),
        _tx("btc", 2.0, cost_basis=4000.0, platform="ledger_wallet"),
    ]
    result = aggregate_current_holdings(entries)
    by_platform = {r.platform: r for r in result}
    assert set(by_platform) == {"coinbase", "ledger_wallet"}
    assert by_platform["coinbase"].quantity == pytest.approx(1.0)
    assert by_platform["coinbase"].cost_basis_usd == pytest.approx(1000.0)
    assert by_platform["ledger_wallet"].quantity == pytest.approx(2.0)
    assert by_platform["ledger_wallet"].cost_basis_usd == pytest.approx(4000.0)


def test_aggregate_sell_on_one_platform_never_affects_the_other_platforms_cost_basis():
    # A disposal on Coinbase must not touch the Ledger Wallet's own
    # independently-tracked cost basis for the same asset.
    entries = [
        _tx("btc", 1.0, cost_basis=1000.0, platform="coinbase"),
        _tx("btc", 0.5, transaction_type="SELL", platform="coinbase"),
        _tx("btc", 2.0, cost_basis=4000.0, platform="ledger_wallet"),
    ]
    result = aggregate_current_holdings(entries)
    by_platform = {r.platform: r for r in result}
    assert by_platform["coinbase"].quantity == pytest.approx(0.5)
    assert by_platform["coinbase"].cost_basis_usd == pytest.approx(500.0)  # 50% sold -> 50% of cost basis removed
    assert by_platform["ledger_wallet"].quantity == pytest.approx(2.0)
    assert by_platform["ledger_wallet"].cost_basis_usd == pytest.approx(4000.0)  # untouched


def test_aggregate_cash_line_is_latest_per_platform_not_one_global_latest():
    entries = [
        _tx(None, 100.0, minutes_ago=60, platform="coinbase"),
        _tx(None, 50.0, minutes_ago=10, platform="coinbase"),
        _tx(None, 25.0, minutes_ago=30, platform="ledger_wallet"),
    ]
    result = aggregate_current_holdings(entries)
    cash_rows = {r.platform: r.quantity for r in result if r.asset_id is None}
    assert cash_rows == {"coinbase": 50.0, "ledger_wallet": 25.0}


def test_collapse_platforms_sums_quantity_and_cost_basis_across_platforms():
    per_platform = [
        _entry("btc", 1.0, cost_basis=1000.0, platform="coinbase"),
        _entry("btc", 2.0, cost_basis=4000.0, platform="ledger_wallet"),
    ]
    collapsed = collapse_platforms(per_platform)
    assert len(collapsed) == 1
    assert collapsed[0].asset_id == "btc"
    assert collapsed[0].quantity == pytest.approx(3.0)
    assert collapsed[0].cost_basis_usd == pytest.approx(5000.0)


def test_collapse_platforms_sums_cash_across_platforms_too():
    per_platform = [
        _entry(None, 100.0, platform="coinbase"),
        _entry(None, 25.0, platform="ledger_wallet"),
    ]
    collapsed = collapse_platforms(per_platform)
    cash_rows = [r for r in collapsed if r.asset_id is None]
    assert len(cash_rows) == 1
    assert cash_rows[0].quantity == pytest.approx(125.0)


def test_collapse_platforms_then_allocate_matches_pipeline_consumers_expectations():
    # Integration check mirroring how app/main.py etc. actually call this:
    # collapse_platforms(aggregate_current_holdings(...)) feeding straight
    # into compute_current_allocations, same as a single-platform position
    # would -- platform detail must be invisible to this pipeline.
    entries = [
        _tx("btc", 1.0, cost_basis=1000.0, platform="coinbase"),
        _tx("btc", 1.0, cost_basis=1000.0, platform="ledger_wallet"),
        _tx(None, 800.0, platform="coinbase"),
    ]
    collapsed = collapse_platforms(aggregate_current_holdings(entries))
    result = compute_current_allocations(collapsed, price_by_asset_id={"btc": 100.0})
    # 2 BTC @ $100 = $200; cash = $800; total = $1000 -> BTC fraction = 0.2
    assert result["btc"] == pytest.approx(0.2)


# --- Phase 5o (2026-09-27): filter_materially_held ---------------------------

def test_filter_materially_held_excludes_a_priced_dust_position():
    holdings = [_entry("ren", 0.0000002), _entry("btc", 1.0)]
    result = filter_materially_held(holdings, {"ren": 3.0, "btc": 100.0}, min_value_usd=1.0)
    assert [h.asset_id for h in result] == ["btc"]


def test_filter_materially_held_keeps_a_position_with_no_price_available():
    # "No price yet" and "priced below the threshold" are different --
    # silently hiding a real, unpriced position would be worse than
    # showing it.
    holdings = [_entry("newasset", 5.0)]
    result = filter_materially_held(holdings, {}, min_value_usd=1.0)
    assert [h.asset_id for h in result] == ["newasset"]


def test_filter_materially_held_keeps_a_value_exactly_at_the_threshold():
    holdings = [_entry("btc", 0.01)]
    result = filter_materially_held(holdings, {"btc": 100.0}, min_value_usd=1.0)  # exactly $1.00
    assert [h.asset_id for h in result] == ["btc"]


def test_filter_materially_held_filters_the_cash_line_by_its_own_quantity():
    holdings = [_entry(None, 0.50), _entry(None, 5.0, platform="ledger_wallet")]
    result = filter_materially_held(holdings, {}, min_value_usd=1.0)
    assert len(result) == 1
    assert result[0].quantity == pytest.approx(5.0)
