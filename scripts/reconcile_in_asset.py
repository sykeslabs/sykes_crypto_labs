"""One-time reconciliation for the `[Open] Reconcile assets.in_asset with
real holdings data at the source` TODO -- `assets.in_asset` was previously
only ever set once, at asset-creation time, and never updated again as real
holdings changed (e.g. an asset with `in_asset=true` and zero real
transactions ever recorded, confirmed live via "S"/Sonic). `POST /holdings`
now keeps this in sync going forward (see app/api/routers/holdings.py); this
script performs the one-time retroactive correction, computing every asset's
REAL current aggregated position from the full holdings_ledger history and
correcting any mismatch. Zero cost -- pure deterministic aggregation and a
plain UPDATE, no LLM/API calls at all.

Usage:
    python -m scripts.reconcile_in_asset
"""

import sys

from app.config import get_settings
from app.database.client import get_supabase_client
from app.database.repository import AssetRepository, HoldingsLedgerRepository, MarketSnapshotRepository
from app.portfolio.holdings import aggregate_current_holdings, collapse_platforms, filter_materially_held


def main() -> int:
    settings = get_settings()
    client = get_supabase_client()
    asset_repo = AssetRepository(client)
    ledger_repo = HoldingsLedgerRepository(client)
    snapshot_repo = MarketSnapshotRepository(client)

    aggregated = collapse_platforms(aggregate_current_holdings(ledger_repo.get_all_history()))
    price_by_asset_id = {}
    for entry in aggregated:
        if entry.asset_id is None:
            continue
        snapshot = snapshot_repo.get_latest_snapshot(entry.asset_id)
        if snapshot is not None:
            price_by_asset_id[entry.asset_id] = float(snapshot.price)
    # Phase 5o (2026-09-27): a dust position (real qty > 0, real value
    # below MIN_MATERIAL_HOLDING_USD) is not "held" for in_asset purposes.
    material = filter_materially_held(aggregated, price_by_asset_id, settings.min_material_holding_usd)
    held_asset_ids = {h.asset_id for h in material if h.asset_id is not None and h.quantity > 0}

    all_assets_resp = client.table("assets").select("id,symbol,in_asset").execute()
    corrected = 0
    for row in all_assets_resp.data:
        real_in_asset = row["id"] in held_asset_ids
        if row["in_asset"] != real_in_asset:
            asset_repo.update_in_asset(row["id"], real_in_asset)
            print(f"  {row['symbol']}: in_asset {row['in_asset']} -> {real_in_asset} (real current position: {'held' if real_in_asset else 'none'})")
            corrected += 1

    print(f"\nChecked {len(all_assets_resp.data)} assets, corrected {corrected} stale in_asset value(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
