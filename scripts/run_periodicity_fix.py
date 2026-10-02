"""Fixes the `[HIGH][Backtest] The system-vs-BTC/equal-weight Sharpe
comparison mixes two different return periodicities` TODO: Phase 4's
system-vs-baseline Sharpe comparison computed the system's Sharpe over
individual decision-level returns (each spanning a whole multi-week horizon)
while the baselines' Sharpe was computed over continuous daily returns of a
buy-and-hold position — different amounts of information per "observation",
so the system's structurally larger Sharpe was never real evidence of skill
vs. the baselines by itself.

Real fix, not just a caveat: for every resolved, directional (BUY/SELL)
BACKFILLED decision, fetch the real daily OHLCV for that asset over exactly
its own [decision_timestamp, evaluated_at] holding window (SELL inverts the
sign, mirroring a short position's daily PnL), then pool every decision's
own daily return observations into one series and compute Sharpe over THAT
-- now genuinely the same periodicity (per-day) as the baselines' Sharpe.

Real, disclosed methodological choice: this pools per-position daily returns
across decisions rather than building one single blended multi-asset equity
curve (positions can overlap in calendar time across different assets) --
still a same-periodicity, real fix for the specific bug (decision-level vs.
daily), not a claim of a fully continuous single portfolio index.

Zero LLM cost -- purely deterministic OHLCV fetches (Binance primary,
Coinbase fallback) and arithmetic, same as scripts/run_stress_test.py and
scripts/run_benchmark_comparison.py.

Usage:
    python -m scripts.run_periodicity_fix
"""

import sys
from datetime import UTC, datetime

from app.benchmarks.baseline_comparison import build_equal_weight_basket_path, compute_baseline_stats
from app.benchmarks.schemas import CalibrationRunRecord
from app.benchmarks.statistical_validation import sample_sharpe_stats
from app.config import get_settings
from app.database.client import get_supabase_client
from app.database.repository import (
    AssetRepository,
    CalibrationRunRepository,
    DecisionOutcomeRepository,
    JudgeDecisionRepository,
)
from app.market_data.binance import BinanceClient
from app.market_data.coinbase import CoinbaseClient

# Comfortably covers this project's entire real decision history (oldest
# backfilled decisions are well under a year old) in one unpaginated call,
# same convention as scripts/run_benchmark_comparison.py's own fetch.
HISTORICAL_FETCH_DAYS = 1000


def fetch_full_close_series(binance: BinanceClient, coinbase: CoinbaseClient, symbol: str):
    rows = binance.fetch_daily_ohlcv_with_timestamps(symbol, HISTORICAL_FETCH_DAYS)
    if rows is None:
        rows = coinbase.fetch_daily_ohlcv_with_timestamps(symbol, HISTORICAL_FETCH_DAYS)
    return rows  # list[(datetime, close, volume)] oldest-first, or None


def pooled_daily_returns_for_decision(
    full_series: list[tuple[datetime, float, float]], start: datetime, end: datetime, direction: str,
) -> list[float]:
    windowed_closes = [c for d, c, _ in full_series if start <= d <= end]
    if len(windowed_closes) < 2:
        return []
    daily_returns = [(windowed_closes[i] / windowed_closes[i - 1]) - 1 for i in range(1, len(windowed_closes))]
    if direction == "SELL":
        daily_returns = [-r for r in daily_returns]
    return daily_returns


def fetch_resolved_backfilled_outcomes(outcome_repo: DecisionOutcomeRepository):
    """Pagination-safe repository retrieval (2026-09-27 follow-up to the
    DecisionOutcome pagination work, consumer migration batch 2): every
    backfilled outcome, not just the first 2000 -- see doc/decisions.md's
    2026-09-27 entry. No ordering dependency here: window_start/window_end
    downstream are derived via an explicit Python sorted() over
    `directional`'s own timestamps, not database order, so the new
    deterministic tiebreaker this migration relies on for pagination
    correctness has no other effect on this script."""
    all_outcomes = outcome_repo.get_recent(limit=None, is_backfilled=True)
    return [o for o in all_outcomes if o.outcome_label != "UNRESOLVED"]


def main() -> int:
    settings = get_settings()
    client = get_supabase_client()
    binance = BinanceClient(settings)
    coinbase = CoinbaseClient(settings)
    asset_repo = AssetRepository(client)
    judge_repo = JudgeDecisionRepository(client)
    outcome_repo = DecisionOutcomeRepository(client)
    calibration_run_repo = CalibrationRunRepository(client)

    resolved_backfilled = fetch_resolved_backfilled_outcomes(outcome_repo)
    print(f"Resolved backfilled outcomes: {len(resolved_backfilled)}")

    directional = []
    decision_level_returns = []
    for o in resolved_backfilled:
        decision = judge_repo.get_by_id(o.decision_id)
        if decision is None or decision.decision not in ("BUY", "SELL"):
            continue
        asset = asset_repo.get_by_id(o.asset_id)
        if asset is None:
            continue
        if o.evaluated_at is None:
            continue
        directional.append((o, decision, asset))
        if o.realized_return is not None:
            decision_level_returns.append(o.realized_return)

    print(f"Directional (BUY/SELL) resolved backfilled decisions: {len(directional)}")

    # OLD (buggy) metric, recomputed here for direct side-by-side comparison.
    old_decision_level_sharpe = None
    if len(decision_level_returns) >= 2:
        try:
            old_decision_level_sharpe, _, _, n_old = sample_sharpe_stats(decision_level_returns)
        except ValueError:
            pass

    # NEW: pool real per-day returns across each decision's own real holding window.
    close_series_by_symbol: dict[str, list[tuple[datetime, float, float]] | None] = {}
    pooled_daily_returns: list[float] = []
    decisions_with_daily_data = 0
    decisions_skipped_no_data = 0
    for o, decision, asset in directional:
        symbol = asset.symbol
        if symbol not in close_series_by_symbol:
            close_series_by_symbol[symbol] = fetch_full_close_series(binance, coinbase, symbol)
        full_series = close_series_by_symbol[symbol]
        if not full_series:
            decisions_skipped_no_data += 1
            continue
        daily_returns = pooled_daily_returns_for_decision(full_series, o.decision_timestamp, o.evaluated_at, decision.decision)
        if not daily_returns:
            decisions_skipped_no_data += 1
            continue
        decisions_with_daily_data += 1
        pooled_daily_returns.extend(daily_returns)

    print(f"\nDecisions with real daily data pooled: {decisions_with_daily_data} (skipped, no real data: {decisions_skipped_no_data})")
    print(f"Pooled daily return observations: {len(pooled_daily_returns)}")

    new_pooled_daily_sharpe = None
    if len(pooled_daily_returns) >= 2:
        try:
            new_pooled_daily_sharpe, _, _, n_new = sample_sharpe_stats(pooled_daily_returns)
        except ValueError:
            pass

    # Baseline (BTC buy-and-hold), same real calendar window, for a genuinely
    # apples-to-apples reference point (reuses the exact Phase 4 methodology).
    timestamps = sorted(o.decision_timestamp for o, _, _ in directional)
    window_start, window_end = timestamps[0], timestamps[-1]
    btc_series = fetch_full_close_series(binance, coinbase, "BTC")
    btc_stats = None
    if btc_series:
        btc_window = [c for d, c, _ in btc_series if window_start <= d <= window_end]
        if len(btc_window) >= 2:
            btc_stats = compute_baseline_stats("BTC_BUY_AND_HOLD", btc_window, round_trip_cost_pct_value=0.0)

    print(f"\n=== OLD (buggy) metric: decision-level Sharpe over {len(decision_level_returns)} multi-week-horizon returns ===")
    print(f"  sharpe_decision_level = {old_decision_level_sharpe}")
    print(f"\n=== NEW (fixed) metric: pooled daily Sharpe over {len(pooled_daily_returns)} real daily returns ===")
    print(f"  sharpe_pooled_daily = {new_pooled_daily_sharpe}")
    print(
        "  NOTE: this system-level Sharpe is not computed from the one genuinely embargoed "
        "holdout cohort (EMBARGO_HOLDOUT_COHORT_PROMPT.md, see /calibration/summary's "
        "holdout_cohort_* fields) -- treat as directional evidence only, not confirmatory."
    )
    if btc_stats:
        print(f"\n=== Reference: BTC buy-and-hold daily Sharpe over the same real window ({window_start.date()} to {window_end.date()}) ===")
        print(f"  sharpe_daily = {btc_stats.sharpe_daily}  (n_days={btc_stats.n_days})")

    notes = (
        f"Periodicity fix (2026-09-12): OLD sharpe_decision_level={old_decision_level_sharpe} "
        f"computed over {len(decision_level_returns)} individual multi-week-horizon decision "
        f"returns (not comparable in periodicity to any daily baseline). NEW "
        f"sharpe_pooled_daily={new_pooled_daily_sharpe} computed over {len(pooled_daily_returns)} "
        f"real daily return observations, pooled across each decision's own real "
        f"[decision_timestamp, evaluated_at] holding window (SELL decisions inverted to reflect "
        f"short PnL) -- now genuinely the same per-day periodicity as "
        f"BTC_BUY_AND_HOLD's own daily Sharpe"
        + (f"={btc_stats.sharpe_daily} over the same real {window_start.date()}-{window_end.date()} window" if btc_stats else " (BTC reference unavailable this run)")
        + f". {decisions_with_daily_data} of {len(directional)} directional decisions contributed real daily data "
        f"({decisions_skipped_no_data} skipped, no real OHLCV reachable for their window). Real, disclosed "
        "simplification: this pools per-position daily returns across decisions (positions can overlap in "
        "calendar time across different assets) rather than building one single blended multi-asset equity "
        "curve -- still a genuine periodicity fix for the specific decision-level-vs-daily bug, not a claim "
        "of one continuous portfolio index."
    )
    calibration_run_repo.insert(CalibrationRunRecord(
        run_at=datetime.now(UTC), method="pooled_daily_sharpe_periodicity_fix",
        sample_size=len(pooled_daily_returns), hit_rate=None, brier_score=None, notes=notes,
    ))
    print("\nReal CalibrationRunRecord persisted (method=pooled_daily_sharpe_periodicity_fix).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
