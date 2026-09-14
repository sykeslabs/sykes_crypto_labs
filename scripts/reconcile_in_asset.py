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

from app.database.client import get_supabase_client
from app.database.repository import AssetRepository, HoldingsLedgerRepository
from app.portfolio.holdings import aggregate_current_holdings


def main() -> int:
    client = get_supabase_client()
    asset_repo = AssetRepository(client)
    ledger_repo = HoldingsLedgerRepository(client)

    aggregated = aggregate_current_holdings(ledger_repo.get_all_history())
    held_asset_ids = {h.asset_id for h in aggregated if h.asset_id is not None and h.quantity > 0}

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
