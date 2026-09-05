"""Derived computations for 3c's derivatives evidence — pure functions, no
network calls. Both are transformations of data already captured elsewhere
in this sub-phase, not new external sources.
"""

from datetime import datetime


def compute_annualized_carry_yield(
    spot_price: float, futures_price: float, delivery_timestamp_ms: int, as_of: datetime
) -> float | None:
    """The basis between a dated future and spot, annualized — the same way
    a bond desk annualizes a cash-and-carry trade, making the curve
    comparable across expiries/assets. None if the contract has already
    expired relative to `as_of` (can't annualize a negative/zero horizon)."""
    delivery = datetime.fromtimestamp(delivery_timestamp_ms / 1000, tz=as_of.tzinfo)
    days_to_expiry = (delivery - as_of).total_seconds() / 86400
    if days_to_expiry <= 0 or spot_price <= 0:
        return None
    raw_basis = (futures_price / spot_price) - 1
    return raw_basis * (365 / days_to_expiry)


def compute_volatility_risk_premium(implied_vol: float | None, realized_vol: float | None) -> float | None:
    """VRP = implied - realized, over a matched window. None unless both
    inputs are genuinely available for the same asset/window — never
    approximated from one side alone.

    Note on units: `implied_vol` from Deribit is annualized (e.g. 15.77 =
    15.77%); `realized_vol` from 3b's factors.compute_volatility is a raw
    period (30d) stdev of daily returns, not annualized. Callers must
    annualize the realized-vol input before calling this (multiply by
    sqrt(365)) so both sides are on the same scale — this function only
    subtracts, it doesn't rescale.
    """
    if implied_vol is None or realized_vol is None:
        return None
    return implied_vol - realized_vol


def annualize_daily_volatility(period_stdev: float) -> float:
    """Converts a raw daily-return stdev (e.g. 3b's compute_volatility
    output) into an annualized volatility percentage, for comparison against
    Deribit's annualized implied volatility."""
    return period_stdev * (365 ** 0.5) * 100
