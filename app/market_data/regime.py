"""Deterministic market-regime classification — computed once per run, not
guessed per-asset by later stages, so every downstream consumer (3d's model
assessments, 3e's Judge) sees the same label. Pure functions over already-
collected data; no new external source.
"""

import statistics
from datetime import date, timedelta

Regime = str  # "RISK_ON" | "RISK_OFF" | "NEUTRAL"


def compute_breadth_pct(momentum_30d_values: list[float | None]) -> float | None:
    """% of the screened universe with positive 30d momentum. None if no
    asset has usable momentum data."""
    present = [v for v in momentum_30d_values if v is not None]
    if not present:
        return None
    positive = sum(1 for v in present if v > 0)
    return positive / len(present)


def classify_risk_regime(
    btc_price: float, btc_ma_short: float, btc_ma_long: float, breadth_pct: float | None
) -> Regime:
    """RISK_ON/RISK_OFF require BTC's price to agree with both moving
    averages AND breadth to agree with that direction; anything mixed is
    NEUTRAL rather than forced into one side."""
    above_short = btc_price > btc_ma_short
    above_long = btc_price > btc_ma_long
    breadth_bullish = breadth_pct is None or breadth_pct >= 0.5
    breadth_bearish = breadth_pct is None or breadth_pct < 0.5

    if above_short and above_long and breadth_bullish:
        return "RISK_ON"
    if not above_short and not above_long and breadth_bearish:
        return "RISK_OFF"
    return "NEUTRAL"


def compute_btc_dominance(btc_market_cap: float, total_universe_market_cap: float) -> float | None:
    """BTC's share of total screened-universe market cap. None if the
    universe total is non-positive (shouldn't happen with real data, but
    never divide by an untrusted zero)."""
    if total_universe_market_cap <= 0:
        return None
    return btc_market_cap / total_universe_market_cap


def compute_altcoin_season_index(
    altcoin_momentum_90d: list[float | None], btc_momentum_90d: float | None
) -> float | None:
    """% of non-stablecoin altcoins in the universe that outperformed BTC
    over a trailing 90d window — the standard altcoin-season formulation.
    None if BTC's own 90d momentum is unavailable (e.g. CoinMarketCap not
    configured, since 90d percent-change comes from CMC's quote fields) or
    no altcoin has usable 90d data."""
    if btc_momentum_90d is None:
        return None
    present = [v for v in altcoin_momentum_90d if v is not None]
    if not present:
        return None
    outperforming = sum(1 for v in present if v > btc_momentum_90d)
    return outperforming / len(present)


def moving_average(daily_closes: list[float], window: int) -> float | None:
    if len(daily_closes) < window:
        return None
    return statistics.mean(daily_closes[-window:])


# Public, historical facts — not something requiring live verification, and
# unaffected by not having a live block-height source (see README).
KNOWN_HALVING_DATES: list[date] = [
    date(2012, 11, 28),
    date(2016, 7, 9),
    date(2020, 5, 11),
    date(2024, 4, 20),
]

# ~210,000 blocks at Bitcoin's ~10-minute target block time — used only to
# estimate the *next* halving date. The *past* halving date is always a known
# historical fact (the latest entry above), never an estimate.
ESTIMATED_HALVING_INTERVAL_DAYS = 1458


def compute_halving_cycle_days(as_of: date) -> tuple[int, int]:
    """Returns (days_since_most_recent_halving, days_until_next_estimated_halving).

    Calendar-based approximation, not live block height — none of
    CoinGecko/CoinMarketCap/Coinbase/Binance expose current BTC block height
    (verified live; they're trading/aggregation APIs, not block explorers).
    Deliberately raw day-counts only, no cycle-phase interpretation (e.g. no
    "N days post-halving = bullish" label) — that belongs to the Judge (3e)
    or later scenario research (3f), not the collector.
    """
    past_halvings = [d for d in KNOWN_HALVING_DATES if d <= as_of]
    most_recent = max(past_halvings) if past_halvings else KNOWN_HALVING_DATES[-1]
    days_since = (as_of - most_recent).days

    next_estimated = most_recent + timedelta(days=ESTIMATED_HALVING_INTERVAL_DAYS)
    while next_estimated <= as_of:
        next_estimated += timedelta(days=ESTIMATED_HALVING_INTERVAL_DAYS)
    days_until = (next_estimated - as_of).days

    return days_since, days_until
