"""Deterministic screening-factor computation — pure functions over input
data, no network calls, so they're backtestable without hitting live APIs.
Momentum (7d/30d) comes directly from already-fetched point-in-time percent
changes (CoinGecko/CoinMarketCap); volatility/drawdown need a real daily
close-price series (Binance primary, Coinbase fallback — see
app/market_data/screening_service.py for the source-selection logic).
"""

import statistics


def compute_volatility(daily_closes: list[float]) -> float | None:
    """Stdev of day-over-day returns across the given close series (oldest
    first). Reported as the raw period stdev, not annualized. None if fewer
    than 2 closes are available (no return can be computed)."""
    if len(daily_closes) < 2:
        return None
    returns = [
        (daily_closes[i] / daily_closes[i - 1]) - 1
        for i in range(1, len(daily_closes))
        if daily_closes[i - 1] != 0
    ]
    if len(returns) < 2:
        return None
    return statistics.pstdev(returns)


def compute_max_drawdown(daily_closes: list[float]) -> float | None:
    """Max peak-to-trough decline (negative fraction, e.g. -0.35 = -35%)
    across the given close series (oldest first). None if empty."""
    if not daily_closes:
        return None
    peak = daily_closes[0]
    max_dd = 0.0
    for price in daily_closes:
        peak = max(peak, price)
        if peak > 0:
            max_dd = min(max_dd, (price - peak) / peak)
    return max_dd


def compute_relative_strength(asset_momentum_30d: float | None, btc_momentum_30d: float | None) -> float | None:
    """Asset's 30d momentum minus BTC's 30d momentum over the same window —
    positive means the asset outperformed BTC. None if either input is
    missing (never silently treated as zero)."""
    if asset_momentum_30d is None or btc_momentum_30d is None:
        return None
    return asset_momentum_30d - btc_momentum_30d


def percentile_ranks(values: list[float | None]) -> list[float | None]:
    """Returns each value's percentile rank (0.0 worst .. 1.0 best) among the
    non-None values in the list, preserving position and None-ness. Tied
    values get the same (averaged) rank rather than being arbitrarily split
    by their position in the input list. A single non-None value ranks 0.5
    (neutral — there's no real distribution to call it "best" against)."""
    present = [(i, v) for i, v in enumerate(values) if v is not None]
    result: list[float | None] = [None] * len(values)
    n = len(present)
    if n == 0:
        return result
    if n == 1:
        result[present[0][0]] = 0.5
        return result

    sorted_present = sorted(present, key=lambda pair: pair[1])
    i = 0
    while i < n:
        j = i
        while j + 1 < n and sorted_present[j + 1][1] == sorted_present[i][1]:
            j += 1
        average_rank_position = (i + j) / 2
        for k in range(i, j + 1):
            original_index = sorted_present[k][0]
            result[original_index] = average_rank_position / (n - 1)
        i = j + 1
    return result


# Composite factor score weights — a rank-based (not raw-value) combination,
# so factors with very different natural scales (momentum in %, volume in
# dollars) combine safely without needing careful normalization. Chosen
# convention, documented rather than tuned by feel (see README "Known
# limitations / decisions"): momentum-weighted with a quality tilt toward
# lower volatility and shallower drawdown. Weights sum to 1.0.
COMPOSITE_FACTOR_WEIGHTS: dict[str, float] = {
    "momentum_30d": 0.30,
    "momentum_7d": 0.15,
    "relative_strength_30d": 0.20,
    "volatility_30d": 0.15,  # inverted: lower volatility ranks higher
    "drawdown_30d": 0.10,  # inverted: shallower (less negative) drawdown ranks higher
    "volume_24h": 0.10,  # liquidity
}

_INVERTED_FACTORS = {"volatility_30d", "drawdown_30d"}


def compute_composite_factor_scores(
    factor_rows: list[dict[str, float | None]],
) -> list[float | None]:
    """Given one dict of raw factor values per screened asset (same keys as
    COMPOSITE_FACTOR_WEIGHTS), returns each asset's composite score.

    Missing factors for a given asset are excluded from its own weighted sum
    and the remaining weights are renormalized for that asset — a missing
    value is never treated as neutral/zero (per the "never silently default
    missing data" non-negotiable), it just doesn't contribute, and the other
    factors' weights proportionally cover the gap.
    """
    ranked: dict[str, list[float | None]] = {}
    for factor_name in COMPOSITE_FACTOR_WEIGHTS:
        raw_values = [row.get(factor_name) for row in factor_rows]
        if factor_name in _INVERTED_FACTORS:
            raw_values = [(-v if v is not None else None) for v in raw_values]
        ranked[factor_name] = percentile_ranks(raw_values)

    scores: list[float | None] = []
    for i in range(len(factor_rows)):
        weighted_sum = 0.0
        total_weight = 0.0
        for factor_name, weight in COMPOSITE_FACTOR_WEIGHTS.items():
            rank = ranked[factor_name][i]
            if rank is None:
                continue
            weighted_sum += rank * weight
            total_weight += weight
        scores.append(weighted_sum / total_weight if total_weight > 0 else None)
    return scores
