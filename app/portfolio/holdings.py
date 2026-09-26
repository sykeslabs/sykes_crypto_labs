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
    """Phase 5b (extended Phase 5o, 2026-09-26): a genuinely transactional
    view, not a snapshot-per-asset one. `all_entries` is the FULL
    append-only history (every BUY/SELL transaction ever recorded, every
    asset, every platform) — this sums BUY quantities and subtracts SELL
    quantities per **(asset_id, platform)** pair to produce one synthetic
    "current position" entry per asset PER PLATFORM (the same asset held
    on two platforms is two independent positions, each with its own cost
    basis) — not one per asset. Callers that only ever want a single
    cross-custody number per asset (Risk Engine, Judge context, screening
    coverage) should pass this function's output through
    `collapse_platforms()` before calling `compute_current_allocations`
    (which is itself unchanged: it still just treats its input as "one row
    per key," genuinely true by construction either way).

    Cost basis for the synthesized entry uses the weighted-average-cost
    method: each BUY adds its own cost_basis_usd to a running total; each
    SELL reduces that running total by the same fraction of cost basis as
    the fraction of quantity it sold. This is a real, stated accounting
    policy choice — not FIFO/LIFO, which would require tracking individual
    lot ages — and this project doesn't claim it's the only correct one.

    The cash line keeps its original Phase 5a semantic per platform: the
    single LATEST cash row *for that platform* is an absolute stated USD
    total, never summed with prior cash rows on the same platform (a
    deposit/withdrawal ledger is a different, not-yet-built feature) —
    `transaction_type` is ignored for cash entirely. Multiple platforms can
    each carry their own cash line (e.g. USD sitting on Coinbase); combine
    them with `collapse_platforms()`.

    A SELL that (due to a data-entry error) exceeds the running position
    is clamped at zero rather than going negative, which would corrupt
    every downstream allocation fraction — but this is a defensive
    backstop, not real validation; the API layer rejects an over-sized
    SELL outright before it ever reaches this function (see
    `app/api/routers/holdings.py`)."""
    by_cash_platform: dict[str, list[HoldingsLedgerEntry]] = {}
    by_asset_platform: dict[tuple[str, str], list[HoldingsLedgerEntry]] = {}
    for entry in all_entries:
        if entry.asset_id is None:
            by_cash_platform.setdefault(entry.platform, []).append(entry)
        else:
            by_asset_platform.setdefault((entry.asset_id, entry.platform), []).append(entry)

    aggregated: list[HoldingsLedgerEntry] = []
    for (asset_id, platform), entries in by_asset_platform.items():
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
                platform=platform,
            ))

    for platform, cash_entries in by_cash_platform.items():
        latest_cash = max(cash_entries, key=lambda e: e.recorded_at)
        aggregated.append(latest_cash)
    return aggregated


def collapse_platforms(per_platform_holdings: list[HoldingsLedgerEntry]) -> list[HoldingsLedgerEntry]:
    """Sums `aggregate_current_holdings`'s per-(asset, platform) rows back
    down to one row per asset (and one combined cash row), for every
    consumer that only ever wants a single cross-custody number — Risk
    Engine sizing, Judge context, screening coverage, `in_asset`
    bookkeeping. `total_cost = sum(cost_basis_usd)` is valid here because
    each input row's `cost_basis_usd` is already an absolute dollar total
    for that platform's position, not a per-unit price — summing two
    absolute totals is correct; no re-weighting needed."""
    by_asset: dict[str, list[HoldingsLedgerEntry]] = {}
    cash_entries: list[HoldingsLedgerEntry] = []
    for entry in per_platform_holdings:
        if entry.asset_id is None:
            cash_entries.append(entry)
        else:
            by_asset.setdefault(entry.asset_id, []).append(entry)

    collapsed: list[HoldingsLedgerEntry] = []
    for asset_id, entries in by_asset.items():
        total_quantity = sum(e.quantity for e in entries)
        total_cost = sum(e.cost_basis_usd or 0.0 for e in entries)
        collapsed.append(HoldingsLedgerEntry(
            asset_id=asset_id, quantity=total_quantity,
            cost_basis_usd=total_cost if total_cost > 0 else None,
            recorded_at=max(e.recorded_at for e in entries),
            platform=entries[0].platform,  # informational only once collapsed; not meaningful across platforms
        ))

    if cash_entries:
        total_cash = sum(e.quantity for e in cash_entries)
        collapsed.append(HoldingsLedgerEntry(
            asset_id=None, quantity=total_cash,
            recorded_at=max(e.recorded_at for e in cash_entries),
            platform=cash_entries[0].platform,
        ))
    return collapsed


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
