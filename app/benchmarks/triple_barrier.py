"""A lightweight triple-barrier labeling scheme (task 4) — deliberately not a
full research-grade implementation (no path-dependent path counting, no
multiple concurrent barriers per PHASE3E_PROMPT.md's own scoping note).
"""

from datetime import datetime

OutcomeLabel = str  # "HIT_TARGET" | "HIT_STOP" | "TIMED_OUT" | "UNRESOLVED"

# A floor on the target/stop magnitude so a near-zero expected_return
# decision (e.g. NO_TRADE/WATCH-adjacent) still gets a workable, non-trivial
# barrier rather than one that's hit on the very next tick.
MIN_BARRIER_MAGNITUDE = 0.05


def compute_target_stop_thresholds(expected_return: float, risk_score: float) -> tuple[float, float]:
    """Simple, inspectable, symmetric-ish barrier derived from the Judge's
    own `expected_return` and `risk_score` (one of the two options
    PHASE3E_PROMPT.md task 4 explicitly allows). Higher risk_score widens
    the downside stop relative to the upside target — a riskier thesis is
    given more room before being called wrong, not less."""
    magnitude = max(abs(expected_return), MIN_BARRIER_MAGNITUDE)
    target_return = magnitude
    stop_return = -magnitude * (1 + risk_score)
    return target_return, stop_return


def evaluate_triple_barrier(
    entry_price: float,
    price_series: list[tuple[datetime, float]],
    target_return: float,
    stop_return: float,
    horizon_end: datetime,
) -> tuple[OutcomeLabel, float | None, datetime | None]:
    """`price_series` is oldest-first (timestamp, price) points from at/after
    the decision through at most `horizon_end`. Walks forward and returns
    the first barrier hit; if none is hit but the series already reaches
    `horizon_end`, returns TIMED_OUT at that point's return. Returns
    ("UNRESOLVED", None, None) if neither barrier fired and we haven't
    reached the horizon yet (not enough data to conclude anything)."""
    if entry_price == 0:
        return "UNRESOLVED", None, None

    for ts, price in price_series:
        running_return = (price / entry_price) - 1
        if running_return >= target_return:
            return "HIT_TARGET", running_return, ts
        if running_return <= stop_return:
            return "HIT_STOP", running_return, ts
        if ts >= horizon_end:
            return "TIMED_OUT", running_return, ts

    return "UNRESOLVED", None, None
