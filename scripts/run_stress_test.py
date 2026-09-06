"""Phase 3h task 2: portfolio tail-risk stress testing, run against the
current live portfolio (or, with --historical-note, conceptually any
allocation snapshot — this script demonstrates the ad hoc/current path;
`app.risk.stress_test`'s functions accept any allocation dict, so a caller
with a historical snapshot source can reuse them directly).

Fetches each asset's real historical OHLCV (Binance primary, Coinbase
fallback — same clients 3e.1's replay already verified live) to compute
HISTORICAL_WORST_DRAWDOWN inputs; ALTCOIN_CONTAGION_LUNA_FTX_STYLE needs no
fetch (a stated assumption). Zero LLM cost — purely deterministic market-data
fetches and arithmetic.

Usage:
    python scripts/run_stress_test.py
"""

import sys
from datetime import UTC, datetime

from app.config import get_settings
from app.database.client import get_supabase_client
from app.database.repository import AssetRepository, PortfolioPositionRepository
from app.market_data.binance import BinanceClient
from app.market_data.coinbase import CoinbaseClient
from app.risk.stress_test import AssetDrawdownInput, run_all_scenarios

MAX_DAYS = 1000  # Binance kline endpoint's real per-call candle cap
STALE_THRESHOLD_DAYS = 30


def compute_max_drawdown(closes: list[float]) -> float:
    peak = closes[0]
    worst = 0.0
    for c in closes:
        peak = max(peak, c)
        worst = min(worst, (c - peak) / peak)
    return worst


def fetch_drawdown_input(binance: BinanceClient, coinbase: CoinbaseClient, symbol: str) -> AssetDrawdownInput:
    rows = binance.fetch_daily_ohlcv_with_timestamps(symbol, MAX_DAYS)
    if rows is None:
        rows = coinbase.fetch_daily_ohlcv_with_timestamps(symbol, MAX_DAYS)
    if not rows:
        return AssetDrawdownInput(symbol=symbol, max_drawdown=None)

    dates = [r[0] for r in rows]
    closes = [r[1] for r in rows]
    end_date = dates[-1]
    is_stale = (datetime.now(UTC) - end_date).days > STALE_THRESHOLD_DAYS
    return AssetDrawdownInput(
        symbol=symbol, max_drawdown=compute_max_drawdown(closes), is_stale=is_stale,
        data_points=len(rows), start_date=dates[0].date().isoformat(), end_date=end_date.date().isoformat(),
    )


def main() -> int:
    settings = get_settings()
    client = get_supabase_client()
    binance = BinanceClient(settings)
    coinbase = CoinbaseClient(settings)

    asset_repo = AssetRepository(client)
    position_repo = PortfolioPositionRepository(client)
    assets_by_id = {a.id: a for a in asset_repo.get_active_assets()}
    positions = position_repo.get_all()

    allocations = {
        assets_by_id[asset_id].symbol: p.current_allocation
        for asset_id, p in positions.items()
        if asset_id in assets_by_id and p.current_allocation > 0
    }
    print(f"Current live portfolio ({len(allocations)} positions, {sum(allocations.values()):.4f} total allocated):")
    for symbol, weight in allocations.items():
        print(f"  {symbol}: {weight:.4%}")

    print("\nFetching real historical OHLCV for drawdown inputs...")
    drawdown_inputs: dict[str, AssetDrawdownInput] = {}
    symbols_needed = set(allocations) | {"BTC"}  # BTC always needed as the fallback proxy
    for symbol in sorted(symbols_needed):
        entry = fetch_drawdown_input(binance, coinbase, symbol)
        drawdown_inputs[symbol] = entry
        if entry.max_drawdown is None:
            print(f"  {symbol}: NO REAL DATA")
        else:
            stale_note = " (STALE)" if entry.is_stale else ""
            print(f"  {symbol}: max_drawdown={entry.max_drawdown:.1%} ({entry.data_points}d, {entry.start_date} to {entry.end_date}){stale_note}")

    results = run_all_scenarios(allocations, drawdown_inputs, settings.max_stress_scenario_drawdown)
    print(f"\n=== Stress test results (MAX_STRESS_SCENARIO_DRAWDOWN={settings.max_stress_scenario_drawdown:.0%}) ===")
    for result in results:
        print(f"\n{result.scenario_name}")
        print(f"  {result.description}")
        print(f"  Portfolio drawdown: {result.portfolio_drawdown_pct:.2%}")
        print(f"  CVaR-style estimate: {result.cvar_style_estimate_pct:.2%}")
        print(f"  FLAGGED: {result.flagged}")
        for ar in result.asset_results:
            proxy_note = f" [{ar.proxy_reason}]" if ar.proxy_reason else ""
            print(f"    {ar.symbol}: {ar.drawdown_pct:.1%}{proxy_note}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
