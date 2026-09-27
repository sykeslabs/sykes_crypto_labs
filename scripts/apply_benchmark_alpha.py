"""Phase 5b addendum: computes a real "effective" (realized) alpha for
every resolved `decision_outcomes` row still missing one -- stored
ALONGSIDE the existing mark-to-mid `realized_return`/
`realized_return_net_of_costs`, never instead of them.

`benchmark_return` is BTC's own realized_return over this SAME decision's
exact [decision_timestamp, evaluated_at] window -- a straight two-point
buy-and-hold return (BTC has no target/stop of its own here; it's a
passive benchmark, not a triple-barrier-resolved position).

Real, disclosed constraint (discovered while first running this script):
`market_snapshots` (what app/benchmarks/evaluation_service.py itself reads
to resolve a decision's OWN realized_return) only holds the LIVE
collector's own history -- a handful of days, not the months a backfilled
(3e.1 replay) decision can span. So, like `apply_execution_costs.py`
before it, this fetches BTC's real historical daily OHLCV directly from
Binance/Coinbase (paginated back far enough to cover the oldest resolved
decision still missing a benchmark -- see `_required_fetch_days`) and
reads a point-in-time price via `HistoricalSeries.as_of` -- the same real
data source backfilled decisions' own realized_return was originally
computed from, so this covers both backfilled and live decisions in one
path.

`effective_alpha` = realized_return - benchmark_return.

Usage:
    python -m scripts.apply_benchmark_alpha
"""

import sys
from datetime import UTC, datetime

from app.benchmarks.historical_factors import HistoricalSeries
from app.config import get_settings
from app.database.client import get_supabase_client
from app.database.repository import AssetRepository, DecisionOutcomeRepository
from app.market_data.binance import BinanceClient
from app.market_data.coinbase import CoinbaseClient

HISTORICAL_FETCH_DAYS = 1000  # Binance's real per-call candle cap -- a floor, not a ceiling; see _required_fetch_days
FETCH_BUFFER_DAYS = 5  # slack beyond the exact oldest-decision boundary


def _required_fetch_days(oldest_needed: datetime, now: datetime) -> int:
    """How many days of history to request so the series reaches back past
    the oldest decision still needing a benchmark price -- never less than
    HISTORICAL_FETCH_DAYS. Fixes a real bug: the old fixed
    HISTORICAL_FETCH_DAYS=1000 was anchored to today, so any decision older
    than ~2.7 years before the real current date silently fell out of
    reach (same bug class already fixed for replay/stress-test -- see
    BinanceClient.fetch_daily_ohlcv_paginated's own docstring)."""
    days_since_oldest = (now - oldest_needed).days
    return max(HISTORICAL_FETCH_DAYS, days_since_oldest + FETCH_BUFFER_DAYS)


def fetch_historical_series(
    binance: BinanceClient, coinbase: CoinbaseClient, symbol: str, asset_id: str, total_days: int,
) -> HistoricalSeries | None:
    rows = binance.fetch_daily_ohlcv_paginated(symbol, total_days)
    source = "BINANCE"
    if rows is None:
        # Coinbase's fetch isn't paginated -- same disclosed residual gap,
        # same precedent as scripts/run_stress_test.py's identical fallback.
        rows = coinbase.fetch_daily_ohlcv_with_timestamps(symbol, HISTORICAL_FETCH_DAYS)
        source = "COINBASE"
    if not rows:
        return None
    dates = [r[0] for r in rows]
    closes = [r[1] for r in rows]
    volumes = [r[2] for r in rows]
    return HistoricalSeries(symbol=symbol, asset_id=asset_id, source=source, dates=dates, closes=closes, volumes=volumes)


def _price_as_of(series: HistoricalSeries, at: datetime) -> float | None:
    _, closes, _ = series.as_of(at)
    return closes[-1] if closes else None


def compute_benchmark_alpha(entry_price: float, exit_price: float, realized_return: float) -> tuple[float, float]:
    """BTC's own two-point buy-and-hold return over the window
    (`benchmark_return`), and the decision's own `realized_return` minus
    that -- the real effective alpha. A pure function, kept separate from
    the DB/data-fetch plumbing above so it's directly testable."""
    benchmark_return = (exit_price / entry_price) - 1
    effective_alpha = realized_return - benchmark_return
    return benchmark_return, effective_alpha


def fetch_resolved_outcomes_without_benchmark_alpha(outcome_repo: DecisionOutcomeRepository):
    """Pagination-safe repository retrieval (2026-09-27 follow-up to the
    DecisionOutcome pagination work, Phase 2/consumer batch 1): every
    resolved row still missing effective_alpha, not just the first 1000 --
    see doc/decisions.md's 2026-09-27 entry."""
    return outcome_repo.get_resolved_without_benchmark_alpha(limit=None)


def main() -> int:
    settings = get_settings()
    client = get_supabase_client()
    outcome_repo = DecisionOutcomeRepository(client)
    asset_repo = AssetRepository(client)
    binance = BinanceClient(settings)
    coinbase = CoinbaseClient(settings)

    btc = asset_repo.get_by_symbol("BTC")
    if btc is None:
        print("BTC is not a tracked asset -- cannot compute a BTC benchmark.")
        return 1

    resolved = fetch_resolved_outcomes_without_benchmark_alpha(outcome_repo)
    print(f"Resolved decision_outcomes missing effective_alpha: {len(resolved)}")

    now = datetime.now(UTC)
    oldest_needed = min(
        (o.decision_timestamp for o in resolved if o.realized_return is not None), default=now,
    )
    total_days = _required_fetch_days(oldest_needed, now)

    btc_series = fetch_historical_series(binance, coinbase, "BTC", btc.id, total_days)
    if btc_series is None:
        print("Could not fetch BTC's historical price series from Binance or Coinbase.")
        return 1
    print(f"BTC historical series: {len(btc_series.closes)} daily points from {btc_series.source}, "
          f"{btc_series.dates[0].date()} to {btc_series.dates[-1].date()}")

    updated = 0
    skipped_no_realized_return = 0
    skipped_no_btc_price = 0

    for outcome in resolved:
        if outcome.realized_return is None:
            skipped_no_realized_return += 1
            continue

        entry_price = _price_as_of(btc_series, outcome.decision_timestamp)
        exit_price = _price_as_of(btc_series, outcome.evaluated_at or outcome.decision_timestamp)
        if entry_price is None or exit_price is None or entry_price == 0:
            skipped_no_btc_price += 1
            continue

        benchmark_return, effective_alpha = compute_benchmark_alpha(entry_price, exit_price, outcome.realized_return)
        outcome_repo.update_benchmark_alpha(outcome.decision_id, benchmark_return, effective_alpha)
        updated += 1

    print(f"Updated: {updated}")
    print(f"Skipped (no realized_return yet): {skipped_no_realized_return}")
    print(f"Skipped (no BTC price available for this window -- before the fetched history's own start date): {skipped_no_btc_price}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
