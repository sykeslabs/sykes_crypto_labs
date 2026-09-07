"""Phase 5a: the ground-truth "what do I actually own" write endpoint —
the ONE narrow exception to Phase 5's otherwise strictly read-only API.
Ground truth only, never a decision override (see PHASE5A_PROMPT.md's own
non-negotiable): the request schema below has no `decision`,
`target_allocation`, or any other Judge/Risk Engine/Portfolio Construction
output field, by construction, not by convention alone.
"""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.auth import verify_api_key
from app.api.dependencies import (
    get_asset_repo,
    get_asset_status_repo,
    get_binance_client,
    get_coinbase_client,
    get_coingecko_client,
    get_holdings_ledger_repo,
    get_market_snapshot_repo,
)
from app.api.schemas import HoldingsEntryView
from app.database.repository import AssetRepository, AssetStatusRepository, HoldingsLedgerRepository, MarketSnapshotRepository
from app.market_data.binance import BinanceClient
from app.market_data.coinbase import CoinbaseClient
from app.market_data.coingecko import CoinGeckoClient
from app.market_data.live_price import fetch_live_price
from app.portfolio.holdings import aggregate_current_holdings, compute_current_allocations
from app.portfolio.schemas import HoldingsLedgerEntry

router = APIRouter(prefix="/holdings", tags=["holdings"], dependencies=[Depends(verify_api_key)])


@router.get("/valid-symbols", response_model=list[str])
def get_valid_symbols(asset_repo: AssetRepository = Depends(get_asset_repo)) -> list[str]:
    """Phase 5b: every real, currently-active tracked symbol — feeds the
    dashboard's entry-form autocomplete so a symbol can be looked up
    rather than typed blind. Narrower than what `POST /holdings` itself
    accepts (any tracked status, not just active, per Phase 5a's own
    rule) — a deliberately real UX choice, not a validation rule: an
    inactive/delisted asset is a real but unhelpful autocomplete
    suggestion, though still POST-able directly by symbol if needed."""
    return sorted(a.symbol for a in asset_repo.get_active_assets())


def _with_symbols(entries: list[HoldingsLedgerEntry], asset_repo: AssetRepository) -> list[HoldingsEntryView]:
    """Joins each entry's `asset_id` against `AssetRepository` for a
    human-readable `symbol` — `"CASH"` for the reserved cash line — rather
    than making a dashboard/API caller resolve a raw UUID by hand."""
    views = []
    for entry in entries:
        if entry.asset_id is None:
            symbol = "CASH"
        else:
            asset = asset_repo.get_by_id(entry.asset_id)
            symbol = asset.symbol if asset is not None else entry.asset_id
        views.append(HoldingsEntryView(
            id=entry.id, asset_id=entry.asset_id, symbol=symbol,
            quantity=entry.quantity, cost_basis_usd=entry.cost_basis_usd,
            recorded_at=entry.recorded_at, purchased_at=entry.purchased_at,
            transaction_type=entry.transaction_type,
        ))
    return views


class HoldingsEntryRequest(BaseModel):
    """Phase 5b: entered by real token symbol (e.g. `"SOL"`, case-
    insensitive), never a raw asset UUID — resolved and validated
    server-side against the real `assets` table (`asset_symbol="CASH"` or
    blank is the reserved cash line, `quantity` then a stated USD amount
    directly, not asset units). No decision/allocation field exists here
    or anywhere in this request; adding one would be a non-negotiable
    violation, not a feature.

    `transaction_type="SELL"` is validated against the real current
    aggregated position for that asset — it's rejected (422) if it would
    sell more than is actually held, rather than silently clamping to zero
    the way the underlying pure aggregation function defensively does."""

    asset_symbol: str = Field(default="CASH", description='A real tracked token symbol (e.g. "SOL"), or "CASH" for the cash line.')
    quantity: float = Field(ge=0, description="Asset units, or USD amount when asset_symbol is CASH.")
    cost_basis_usd: float | None = Field(default=None, ge=0, description="Total cost basis for THIS transaction, not a per-unit price.")
    purchased_at: datetime | None = Field(default=None, description="The real date this was bought/sold — distinct from when it's entered.")
    transaction_type: Literal["BUY", "SELL"] = "BUY"


@router.post("", response_model=HoldingsEntryView, status_code=201)
def record_holding(
    entry: HoldingsEntryRequest,
    asset_repo: AssetRepository = Depends(get_asset_repo),
    asset_status_repo: AssetStatusRepository = Depends(get_asset_status_repo),
    ledger_repo: HoldingsLedgerRepository = Depends(get_holdings_ledger_repo),
    coingecko_client: CoinGeckoClient = Depends(get_coingecko_client),
) -> HoldingsEntryView:
    """Append-only: this always INSERTS a new row, never updates or
    deletes a prior one — editing a position is a new BUY (or SELL)
    transaction, summed with every prior one for that asset (Phase 5b's
    transactional model — see `aggregate_current_holdings`); removing a
    position entirely is a SELL for its full remaining quantity. "What did
    I hold as of date T" stays answerable via `/holdings/history`.

    Phase 5b (addendum): a symbol not yet in our tracked universe (e.g.
    "ADA", "LTC") is no longer rejected outright — it's verified against
    the real CoinGecko `/search` endpoint first (never trusting the typed
    symbol blindly), and only turned into a newly tracked asset if a real,
    unambiguous CoinGecko-listed coin has that exact ticker. This is a
    genuinely new tracked asset, `in_asset=True` (this call is recording a
    real position in it right now) and `active=True`, with a real
    `asset_status_history` "HELD" entry recording why it was added —
    exactly the audit trail 3b's own screening-driven promotions get, not
    a special-cased shortcut."""
    symbol_input = entry.asset_symbol.strip()
    if symbol_input.upper() == "CASH" or symbol_input == "":
        asset_id = None
        symbol = "CASH"
    else:
        asset = asset_repo.get_by_symbol(symbol_input)
        if asset is None:
            match = coingecko_client.search_coin_by_symbol(symbol_input)
            if match is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"'{symbol_input}' is not a tracked asset symbol, and no real CoinGecko-listed token with that exact ticker was found either.",
                )
            # Same duplicate-guard 3b's screening promotion uses (`_promote_new_candidates`)
            # -- this CoinGecko coin could already be tracked under a
            # different symbol casing/history, in which case reuse it
            # rather than inserting a second row for the same real coin.
            asset = asset_repo.get_by_coingecko_id(match["id"])
            if asset is None:
                asset = asset_repo.create_asset(
                    symbol=match["symbol"].upper(), name=match["name"], coingecko_id=match["id"],
                    active=True, in_asset=True,
                )
                asset_status_repo.record_status_change(
                    asset.id, "HELD", reason=f"Manually added via holdings entry ('{symbol_input}' -> real CoinGecko coin '{match['id']}')",
                )
        asset_id = asset.id
        symbol = asset.symbol

    if asset_id is not None and entry.transaction_type == "SELL":
        aggregated = aggregate_current_holdings(ledger_repo.get_all_history())
        currently_held = next((h.quantity for h in aggregated if h.asset_id == asset_id), 0.0)
        if entry.quantity > currently_held:
            raise HTTPException(
                status_code=422,
                detail=f"Cannot sell {entry.quantity} {symbol} — only {currently_held} currently held.",
            )

    record = HoldingsLedgerEntry(
        asset_id=asset_id, quantity=entry.quantity, cost_basis_usd=entry.cost_basis_usd,
        recorded_at=datetime.now(UTC), purchased_at=entry.purchased_at,
        transaction_type=entry.transaction_type,
    )
    ledger_repo.insert(record)
    return HoldingsEntryView(
        id=record.id, asset_id=record.asset_id, symbol=symbol, quantity=record.quantity,
        cost_basis_usd=record.cost_basis_usd, recorded_at=record.recorded_at,
        purchased_at=record.purchased_at, transaction_type=record.transaction_type,
    )


@router.get("", response_model=list[HoldingsEntryView])
def get_current_holdings(
    repo: HoldingsLedgerRepository = Depends(get_holdings_ledger_repo),
    asset_repo: AssetRepository = Depends(get_asset_repo),
    snapshot_repo: MarketSnapshotRepository = Depends(get_market_snapshot_repo),
    binance_client: BinanceClient = Depends(get_binance_client),
    coinbase_client: CoinbaseClient = Depends(get_coinbase_client),
) -> list[HoldingsEntryView]:
    """The current AGGREGATED position per asset (including the cash
    line) — every BUY/SELL transaction ever recorded for that asset summed
    together (Phase 5b's transactional model, see
    `aggregate_current_holdings`), not just the latest row. This is the
    real ground-truth holdings state Portfolio Construction actually
    reasons against. Each row's `allocation` is computed via the exact
    same `compute_current_allocations` (Phase 5a) the live pipeline itself
    calls — the real fraction-of-total-portfolio-value comparable against
    "Portfolio state"'s recommended allocation, not a separate estimate.
    `value_usd` (Phase 5b) is this entry's real dollar value right now —
    summing every row's `value_usd` gives the real total portfolio value,
    which cannot be derived from `allocation` (a fraction) alone.
    `price_usd` is the real current price behind that math, exposed
    directly rather than making a caller re-derive it from value/quantity.
    `live_price_usd` (Phase 5b, by explicit user choice) is a separate,
    genuinely live spot price fetched from Binance/Coinbase at request
    time — deliberately not used for `value_usd`/`allocation` above, so
    those stay consistent with the real pipeline's own stored-snapshot
    basis (see `app/market_data/live_price.py`). `cost_per_unit`/
    `unrealized_pnl_usd`/`unrealized_pnl_pct` are computed from the
    aggregated position's own weighted-average cost basis against
    `value_usd` — `None` whenever no cost basis was ever entered."""
    latest_holdings = aggregate_current_holdings(repo.get_all_history())
    price_by_asset_id = {}
    price_as_of_by_asset_id = {}
    for entry in latest_holdings:
        if entry.asset_id is None:
            continue
        snapshot = snapshot_repo.get_latest_snapshot(entry.asset_id)
        if snapshot is not None:
            price_by_asset_id[entry.asset_id] = float(snapshot.price)
            price_as_of_by_asset_id[entry.asset_id] = snapshot.timestamp

    allocations = compute_current_allocations(latest_holdings, price_by_asset_id)
    cash_allocation = 1.0 - sum(allocations.values())
    value_by_asset_id = {}
    cash_value = 0.0
    for entry in latest_holdings:
        if entry.asset_id is None:
            cash_value += entry.quantity
            continue
        price = price_by_asset_id.get(entry.asset_id)
        if price is not None:
            value_by_asset_id[entry.asset_id] = entry.quantity * price

    views = _with_symbols(latest_holdings, asset_repo)
    for view in views:
        if view.asset_id is None:
            view.allocation = cash_allocation
            view.value_usd = cash_value
        else:
            view.allocation = allocations.get(view.asset_id)
            view.value_usd = value_by_asset_id.get(view.asset_id)
            view.price_usd = price_by_asset_id.get(view.asset_id)
            view.price_as_of = price_as_of_by_asset_id.get(view.asset_id)
            live = fetch_live_price(view.symbol, binance_client, coinbase_client)
            if live is not None:
                view.live_price_usd, view.live_price_as_of, view.live_price_source = live
            if view.cost_basis_usd is not None and view.quantity > 0:
                view.cost_per_unit = view.cost_basis_usd / view.quantity
                if view.value_usd is not None:
                    view.unrealized_pnl_usd = view.value_usd - view.cost_basis_usd
                    view.unrealized_pnl_pct = (view.unrealized_pnl_usd / view.cost_basis_usd) * 100 if view.cost_basis_usd > 0 else None
    return views


@router.get("/history", response_model=list[HoldingsEntryView])
def get_holdings_history(
    asset_id: str | None = None, cash: bool = False,
    repo: HoldingsLedgerRepository = Depends(get_holdings_ledger_repo),
    asset_repo: AssetRepository = Depends(get_asset_repo),
) -> list[HoldingsEntryView]:
    """Full append-only history, newest first — proves "what did I hold as
    of date T" is genuinely answerable, not just the latest snapshot.
    `cash=true` returns just the cash line's history; `asset_id=<id>`
    returns just that asset's; omitting both returns every entry ever
    recorded (cash and every asset)."""
    if cash:
        entries = repo.get_history(None)
    elif asset_id is not None:
        entries = repo.get_history(asset_id)
    else:
        entries = repo.get_all_history()
    return _with_symbols(entries, asset_repo)
