"""Phase 4 task 3: benchmark tracking — system vs. equal-weight-across-
universe buy-and-hold vs. BTC buy-and-hold, all under the same fee/slippage
cost treatment (task 2's `round_trip_cost_pct`), over the same real
calendar window the system's own resolved decisions span.

Usage:
    python scripts/run_benchmark_comparison.py
"""

import sys

from app.benchmarks.baseline_comparison import build_equal_weight_basket_path, compute_baseline_stats
from app.config import get_settings
from app.database.client import get_supabase_client
from app.database.repository import AssetRepository, DecisionOutcomeRepository
from app.market_data.binance import BinanceClient
from app.market_data.coinbase import CoinbaseClient
from app.market_data.factors import compute_volatility
from app.trading.fill_simulator import TAKER_FEE_RATE_BY_EXCHANGE, round_trip_cost_pct

ASSUMED_PORTFOLIO_NOTIONAL_USD = 10_000.0
HISTORICAL_FETCH_DAYS = 1000


def fetch_window_closes(binance, coinbase, symbol, window_start, window_end):
    rows = binance.fetch_daily_ohlcv_with_timestamps(symbol, HISTORICAL_FETCH_DAYS)
    source = "BINANCE"
    if rows is None:
        rows = coinbase.fetch_daily_ohlcv_with_timestamps(symbol, HISTORICAL_FETCH_DAYS)
        source = "COINBASE"
    if not rows:
        return None, None
    windowed = [(d, c, v) for d, c, v in rows if window_start <= d <= window_end]
    if len(windowed) < 2:
        return None, None
    return windowed, source


def fetch_backfilled_decision_timestamps(outcome_repo: DecisionOutcomeRepository):
    """Pagination-safe repository retrieval (2026-09-27 follow-up,
    DecisionOutcome consumer migration batch 2): the old raw, unbounded
    query had no `.range()`/`.limit()` at all -- feeding directly into a
    min/max comparison window, a truncation would have silently shrunk
    the real window, not just undercounted rows. No resolution filter
    here, preserved exactly as before -- every backfilled decision's own
    timestamp counts toward the window regardless of whether it has
    resolved yet. Ordering doesn't matter for this min/max computation
    (the caller's own sorted() is authoritative, not database order), so
    the new pagination tiebreaker has no other effect on this script."""
    outcomes = outcome_repo.get_recent(limit=None, is_backfilled=True)
    return [o.decision_timestamp for o in outcomes]


def main() -> int:
    settings = get_settings()
    client = get_supabase_client()
    binance = BinanceClient(settings)
    coinbase = CoinbaseClient(settings)
    asset_repo = AssetRepository(client)

    timestamps = sorted(fetch_backfilled_decision_timestamps(DecisionOutcomeRepository(client)))
    window_start, window_end = timestamps[0], timestamps[-1]
    print(f"Real comparison window: {window_start.date()} to {window_end.date()} ({(window_end - window_start).days} days)")

    active_assets = asset_repo.get_active_assets()
    price_paths: dict[str, list[float]] = {}
    exchange_by_symbol: dict[str, str] = {}
    vol_volume_by_symbol: dict[str, tuple[float, float]] = {}

    for asset in active_assets:
        windowed, source = fetch_window_closes(binance, coinbase, asset.symbol, window_start, window_end)
        if windowed is None:
            continue
        closes = [c for _, c, _ in windowed]
        volumes = [v for _, _, v in windowed]
        price_paths[asset.symbol] = closes
        exchange_by_symbol[asset.symbol] = source
        vol = compute_volatility(closes)
        volume_usd = closes[-1] * volumes[-1] if volumes else None
        if vol is not None and volume_usd:
            vol_volume_by_symbol[asset.symbol] = (vol, volume_usd)

    print(f"Real per-asset closes fetched for {len(price_paths)} of {len(active_assets)} active assets over this window")

    # BTC buy-and-hold
    btc_path = price_paths.get("BTC")
    if btc_path is None:
        print("BTC data unavailable for this window -- cannot compute BTC baseline.")
        return 1
    btc_vol, btc_volume_usd = vol_volume_by_symbol["BTC"]
    btc_cost = round_trip_cost_pct(
        entry_volatility=btc_vol, entry_typical_daily_volume_usd=btc_volume_usd,
        exit_volatility=btc_vol, exit_typical_daily_volume_usd=btc_volume_usd,
        order_size_usd=ASSUMED_PORTFOLIO_NOTIONAL_USD, fee_rate=TAKER_FEE_RATE_BY_EXCHANGE[exchange_by_symbol["BTC"]],
    )
    btc_stats = compute_baseline_stats("BTC_BUY_AND_HOLD", btc_path, btc_cost)

    # Equal-weight-across-universe buy-and-hold. Needs equal-length paths --
    # restrict to assets with a full window's worth of real data (same
    # length as BTC's, the deepest-history reference asset in this universe).
    equal_length_paths = {s: p for s, p in price_paths.items() if len(p) == len(btc_path)}
    print(f"Assets with a full matching window (used in equal-weight basket): {sorted(equal_length_paths)}")
    basket_path = build_equal_weight_basket_path(equal_length_paths)
    # Cost: average round-trip cost across the basket's real constituents.
    basket_costs = []
    for symbol in equal_length_paths:
        vol, volume_usd = vol_volume_by_symbol[symbol]
        basket_costs.append(round_trip_cost_pct(
            entry_volatility=vol, entry_typical_daily_volume_usd=volume_usd,
            exit_volatility=vol, exit_typical_daily_volume_usd=volume_usd,
            order_size_usd=ASSUMED_PORTFOLIO_NOTIONAL_USD / len(equal_length_paths),
            fee_rate=TAKER_FEE_RATE_BY_EXCHANGE[exchange_by_symbol[symbol]],
        ))
    basket_cost = sum(basket_costs) / len(basket_costs)
    basket_stats = compute_baseline_stats("EQUAL_WEIGHT_UNIVERSE_BUY_AND_HOLD", basket_path, basket_cost)

    print(f"\n=== {btc_stats.label} ===")
    print(f"n_days={btc_stats.n_days} sharpe_daily={btc_stats.sharpe_daily} max_drawdown={btc_stats.max_drawdown:.4f}")
    print(f"total_return_raw={btc_stats.total_return_raw:.4f} total_return_net_of_costs={btc_stats.total_return_net_of_costs:.4f}")

    print(f"\n=== {basket_stats.label} ===")
    print(f"n_days={basket_stats.n_days} sharpe_daily={basket_stats.sharpe_daily} max_drawdown={basket_stats.max_drawdown:.4f}")
    print(f"total_return_raw={basket_stats.total_return_raw:.4f} total_return_net_of_costs={basket_stats.total_return_net_of_costs:.4f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
