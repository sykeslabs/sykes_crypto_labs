"""Phase 5a: converts real, ground-truth `holdings_ledger` entries (real
asset quantities + an explicit cash line) into the fractional
`current_allocation` values the Risk Engine/Portfolio Construction pipeline
has always operated on — a pure, mechanical, non-editorializing
computation (quantity * real current price), never a place a decision or
target_allocation could sneak in (see PHASE5A_PROMPT.md's own
non-negotiable).
"""

from app.portfolio.schemas import HoldingsLedgerEntry


def compute_current_allocations(
    latest_holdings: list[HoldingsLedgerEntry],
    price_by_asset_id: dict[str, float],
) -> dict[str, float]:
    """`latest_holdings` is the most recent `holdings_ledger` row per
    asset (including at most one cash row, `asset_id=None`) — never the
    full append-only history. `price_by_asset_id` should cover every
    non-cash asset in `latest_holdings` plus every asset the caller cares
    about (assets with no entered holding correctly get 0.0 below).

    Two real edge cases handled explicitly, never a crash or a silent
    fall-back to any other source:
    - True cold start (`latest_holdings` is empty — nothing has ever been
      entered, not even a cash line): every asset in `price_by_asset_id`
      gets 0.0. This is a legitimate, expected state (100% cash by
      omission), not an error.
    - A computed total portfolio value that is zero or negative (e.g. a
      cash row of $0 and no other holdings): same all-zero result, rather
      than dividing by zero.
    """
    asset_ids = list(price_by_asset_id.keys())
    if not latest_holdings:
        return {aid: 0.0 for aid in asset_ids}

    total_value = 0.0
    value_by_asset: dict[str, float] = {}
    for entry in latest_holdings:
        if entry.asset_id is None:
            total_value += entry.quantity  # cash: quantity IS the USD amount
            continue
        price = price_by_asset_id.get(entry.asset_id)
        if price is None:
            continue  # no real current price available -- can't value this holding
        value = entry.quantity * price
        value_by_asset[entry.asset_id] = value
        total_value += value

    if total_value <= 0:
        return {aid: 0.0 for aid in asset_ids}

    return {aid: value_by_asset.get(aid, 0.0) / total_value for aid in asset_ids}
