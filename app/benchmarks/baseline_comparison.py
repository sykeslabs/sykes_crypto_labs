"""Phase 4 task 3: benchmark tracking against naive baselines (equal-weight
-across-universe, BTC buy-and-hold), costed with the SAME fee/slippage
treatment as the system's own simulated fills — an uncosted baseline vs. a
costed system would silently favor the baseline.

Real, disclosed methodological point: a one-time round-trip fee doesn't
change how an asset's PRICE moves day to day (the daily return series and
max-drawdown are scale-invariant ratios, unaffected by a flat cost applied
once at entry/exit) — so this module reports Sharpe/max-drawdown on the raw
(uncosted) daily price path, and reports the round-trip cost's effect only
on the TOTAL return over the period, as a distinct, separately-labeled
figure. This mirrors exactly how the system's own `realized_return` vs.
`realized_return_net_of_costs` are two clearly separate numbers, never
conflated into one.
"""

from dataclasses import dataclass

from app.benchmarks.statistical_validation import sample_sharpe_stats
from app.market_data.factors import compute_max_drawdown


@dataclass
class BaselineStats:
    label: str
    n_days: int
    sharpe_daily: float | None
    max_drawdown: float | None
    total_return_raw: float
    total_return_net_of_costs: float
    round_trip_cost_pct: float


def build_equal_weight_basket_path(price_paths: dict[str, list[float]]) -> list[float]:
    """Each symbol's real close series over the SAME real calendar dates,
    oldest-first, equal length across symbols. Normalizes each asset to
    start at 1.0 (an equal dollar amount invested in each asset at day 0,
    never rebalanced afterward — the standard buy-and-hold interpretation,
    not a daily-rebalanced index) and averages across assets each day."""
    if not price_paths:
        raise ValueError("no price paths given")
    lengths = {len(p) for p in price_paths.values()}
    if len(lengths) != 1:
        raise ValueError("all price paths must share the same length (same real calendar dates)")
    n_days = lengths.pop()
    if n_days < 2:
        raise ValueError("need at least 2 days of history")

    normalized = {symbol: [p / prices[0] for p in prices] for symbol, prices in price_paths.items()}
    return [
        sum(normalized[symbol][day] for symbol in normalized) / len(normalized)
        for day in range(n_days)
    ]


def compute_baseline_stats(label: str, price_path: list[float], round_trip_cost_pct_value: float) -> BaselineStats:
    if len(price_path) < 2:
        raise ValueError("need at least 2 price points")
    daily_returns = [(price_path[i] / price_path[i - 1]) - 1 for i in range(1, len(price_path))]

    sharpe_daily = None
    if len(daily_returns) >= 2:
        try:
            sharpe_daily, _, _, _ = sample_sharpe_stats(daily_returns)
        except ValueError:
            sharpe_daily = None

    total_return_raw = (price_path[-1] / price_path[0]) - 1
    return BaselineStats(
        label=label,
        n_days=len(price_path),
        sharpe_daily=sharpe_daily,
        max_drawdown=compute_max_drawdown(price_path),
        total_return_raw=total_return_raw,
        total_return_net_of_costs=total_return_raw - round_trip_cost_pct_value,
        round_trip_cost_pct=round_trip_cost_pct_value,
    )
