"""Phase 5a: converts real, ground-truth `holdings_ledger` entries (real
asset quantities + an explicit cash line) into the fractional
`current_allocation` values the Risk Engine/Portfolio Construction pipeline
has always operated on — a pure, mechanical, non-editorializing
computation (quantity * real current price), never a place a decision or
target_allocation could sneak in (see PHASE5A_PROMPT.md's own
non-negotiable).
"""

from app.portfolio.schemas import HoldingsLedgerEntry


def aggregate_current_holdings(all_entries: list[HoldingsLedgerEntry]) -> list[HoldingsLedgerEntry]:
    """Phase 5b: a genuinely transactional view, not a snapshot-per-asset
    one. `all_entries` is the FULL append-only history (every BUY/SELL
    transaction ever recorded, every asset) — this sums BUY quantities and
    subtracts SELL quantities per asset to produce one synthetic "current
    position" entry per asset, which is what `compute_current_allocations`
    should be called with (that function itself is unchanged: it still
    just treats its input as "one row per asset," now genuinely true by
    construction rather than by "latest wins").

    Cost basis for the synthesized entry uses the weighted-average-cost
    method: each BUY adds its own cost_basis_usd to a running total; each
    SELL reduces that running total by the same fraction of cost basis as
    the fraction of quantity it sold. This is a real, stated accounting
    policy choice — not FIFO/LIFO, which would require tracking individual
    lot ages — and this project doesn't claim it's the only correct one.

    The cash line keeps its original Phase 5a semantic completely
    unchanged: the single LATEST cash row is an absolute stated USD total,
    never summed with prior cash rows (a deposit/withdrawal ledger is a
    different, not-yet-built feature) — `transaction_type` is ignored for
    the cash line entirely.

    A SELL that (due to a data-entry error) exceeds the running position
    is clamped at zero rather than going negative, which would corrupt
    every downstream allocation fraction — but this is a defensive
    backstop, not real validation; the API layer rejects an over-sized
    SELL outright before it ever reaches this function (see
    `app/api/routers/holdings.py`)."""
    cash_entries = [e for e in all_entries if e.asset_id is None]
    latest_cash = max(cash_entries, key=lambda e: e.recorded_at, default=None)

    by_asset: dict[str, list[HoldingsLedgerEntry]] = {}
    for entry in all_entries:
        if entry.asset_id is not None:
            by_asset.setdefault(entry.asset_id, []).append(entry)

    aggregated: list[HoldingsLedgerEntry] = []
    for asset_id, entries in by_asset.items():
        ordered = sorted(entries, key=lambda e: e.recorded_at)
        quantity = 0.0
        cost_basis = 0.0
        for entry in ordered:
            if entry.transaction_type == "SELL":
                if quantity > 0:
                    fraction_sold = min(entry.quantity, quantity) / quantity
                    cost_basis -= cost_basis * fraction_sold
                quantity = max(0.0, quantity - entry.quantity)
            else:  # BUY
                quantity += entry.quantity
                cost_basis += entry.cost_basis_usd or 0.0
        if quantity > 0:
            aggregated.append(HoldingsLedgerEntry(
                asset_id=asset_id, quantity=quantity,
                cost_basis_usd=cost_basis if cost_basis > 0 else None,
                recorded_at=ordered[-1].recorded_at,
            ))

    if latest_cash is not None:
        aggregated.append(latest_cash)
    return aggregated


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
