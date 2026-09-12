"""Phase 4 task 2: computes a fee/slippage-adjusted `realized_return_net_of_
costs` for every resolved `decision_outcomes` row still missing one,
stored ALONGSIDE the existing mark-to-mid `realized_return`, never instead
of it.

Real, disclosed constraint: order books are not stored historically
anywhere in this project, and exchanges don't serve historical depth via
free APIs — so every currently-resolved decision (all backfilled, plus any
live ones once they resolve) uses the VOLATILITY_SCALED_ESTIMATE fill
method, computed from real historical volatility/volume as of each
decision's own entry and exit dates (point-in-time-safe via
`HistoricalSeries.as_of`, same convention as 3e.1's replay) — never the
DEPTH_WALKED method, which is built, tested, and live-verified
(see app/trading/fill_simulator.py) but only point-in-time-valid for a
decision being made in real time, not retroactively.

Usage:
    python -m scripts.apply_execution_costs
"""

import sys
from datetime import UTC, datetime

from app.benchmarks.historical_factors import HistoricalSeries
from app.config import get_settings
from app.database.client import get_supabase_client
from app.database.repository import AssetRepository, DecisionOutcomeRepository
from app.market_data.binance import BinanceClient
from app.market_data.coinbase import CoinbaseClient
from app.market_data.factors import compute_volatility
from app.trading.fill_simulator import TAKER_FEE_RATE_BY_EXCHANGE, round_trip_cost_pct

# A documented sizing assumption: this project's decision_outcomes/
# judge_decisions have no tracked total-portfolio dollar value (only
# fractional `current_allocation`/`target_allocation`) -- a $10,000 paper
# bankroll is a common, simple reference size for a per-decision USD order,
# used only to scale the participation-rate term in the volatility-scaled
# slippage estimate, not treated as this project's real capital.
ASSUMED_PORTFOLIO_NOTIONAL_USD = 10_000.0
TRAILING_WINDOW_DAYS = 30
HISTORICAL_FETCH_DAYS = 1000  # Binance's real per-call candle cap


def fetch_historical_series(binance: BinanceClient, coinbase: CoinbaseClient, symbol: str, asset_id: str) -> HistoricalSeries | None:
    rows = binance.fetch_daily_ohlcv_with_timestamps(symbol, HISTORICAL_FETCH_DAYS)
    source = "BINANCE"
    if rows is None:
        rows = coinbase.fetch_daily_ohlcv_with_timestamps(symbol, HISTORICAL_FETCH_DAYS)
        source = "COINBASE"
    if not rows:
        return None
    dates = [r[0] for r in rows]
    closes = [r[1] for r in rows]
    volumes = [r[2] for r in rows]
    return HistoricalSeries(symbol=symbol, asset_id=asset_id, source=source, dates=dates, closes=closes, volumes=volumes)


def volatility_and_volume_as_of(series: HistoricalSeries, as_of: datetime) -> tuple[float | None, float | None]:
    _, closes, volumes = series.as_of(as_of)
    if len(closes) < 2:
        return None, None
    trailing_closes = closes[-TRAILING_WINDOW_DAYS:]
    volatility = compute_volatility(trailing_closes)
    volume_24h_proxy = closes[-1] * volumes[-1] if volumes else None
    return volatility, volume_24h_proxy


def main() -> int:
    settings = get_settings()
    client = get_supabase_client()
    outcome_repo = DecisionOutcomeRepository(client)
    asset_repo = AssetRepository(client)
    binance = BinanceClient(settings)
    coinbase = CoinbaseClient(settings)

    assets_by_id = {a.id: a for a in asset_repo.get_active_assets()}
    decisions = {
        d["id"]: d for d in client.table("judge_decisions").select("id,decision,target_allocation").execute().data
    }

    resolved = outcome_repo.get_resolved_without_net_of_costs(limit=1000)
    print(f"Resolved decision_outcomes missing net_of_costs: {len(resolved)}")

    series_cache: dict[str, HistoricalSeries | None] = {}
    updated = 0
    skipped_no_series = 0
    skipped_no_volatility = 0

    for outcome in resolved:
        asset = assets_by_id.get(outcome.asset_id)
        decision_row = decisions.get(outcome.decision_id)
        if asset is None or decision_row is None or outcome.realized_return is None:
            continue

        if asset.symbol not in series_cache:
            series_cache[asset.symbol] = fetch_historical_series(binance, coinbase, asset.symbol, asset.id)
        series = series_cache[asset.symbol]
        if series is None:
            skipped_no_series += 1
            continue

        entry_vol, entry_vol_usd = volatility_and_volume_as_of(series, outcome.decision_timestamp)
        exit_vol, exit_vol_usd = volatility_and_volume_as_of(series, outcome.evaluated_at or outcome.decision_timestamp)
        if not all([entry_vol, entry_vol_usd, exit_vol, exit_vol_usd]):
            skipped_no_volatility += 1
            continue

        exchange = "BINANCE" if series.source == "BINANCE" else "COINBASE"
        fee_rate = TAKER_FEE_RATE_BY_EXCHANGE[exchange]
        order_size_usd = abs(decision_row["target_allocation"] or 0.0) * ASSUMED_PORTFOLIO_NOTIONAL_USD
        if order_size_usd <= 0:
            order_size_usd = 0.01 * ASSUMED_PORTFOLIO_NOTIONAL_USD  # a minimal nonzero reference size

        cost_pct = round_trip_cost_pct(
            entry_volatility=entry_vol, entry_typical_daily_volume_usd=entry_vol_usd,
            exit_volatility=exit_vol, exit_typical_daily_volume_usd=exit_vol_usd,
            order_size_usd=order_size_usd, fee_rate=fee_rate,
        )
        net_of_costs = outcome.realized_return - cost_pct
        outcome_repo.update_net_of_costs(outcome.decision_id, net_of_costs, "VOLATILITY_SCALED_ESTIMATE")
        updated += 1

    print(f"Updated: {updated}")
    print(f"Skipped (no historical series available): {skipped_no_series}")
    print(f"Skipped (insufficient history for volatility/volume): {skipped_no_volatility}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
