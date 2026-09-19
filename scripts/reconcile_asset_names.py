"""One-time reconciliation for a real bug found live 2026-09-16: newly
promoted assets (`ScreeningService._promote_new_candidates`) had their
`name` fall back to the bare symbol (e.g. "ZEC") instead of CoinGecko's
real display name (e.g. "Zcash") -- CoinGecko's real name was already
fetched into `_build_universe`'s own in-memory dict but never threaded
through `ScreenedAsset` to reach asset creation. Fixed going forward (see
`ScreenedAsset.name` / `ScreeningService._promote_new_candidates`); this
script performs the one-time retroactive correction for assets already
created under the bug.

Scope: every asset whose stored `name` exactly equals its `symbol` -- the
bug's own unambiguous signature (no other code path in this project ever
sets `name` that way; every manually-seeded asset has a real name). A
handful of real coins genuinely have a display name identical to their
symbol (e.g. XRP, BNB) -- these are correctly left unchanged, since the
live-fetched CoinGecko name will match what's already stored and no update
occurs.

Zero LLM cost -- one batched CoinGecko call (already-integrated client, no
new dependency) plus plain UPDATEs.

Usage:
    python -m scripts.reconcile_asset_names
"""

import sys

from app.config import get_settings
from app.database.client import get_supabase_client
from app.market_data.coingecko import CoinGeckoClient

# Same window _build_universe uses (screening_universe_size + 15, capped
# generously here since this is a one-time backfill, not a per-run budget) --
# covers every real asset this project has ever tracked, live-verified.
MARKETS_FETCH_LIMIT = 250


def main() -> int:
    client = get_supabase_client()
    settings = get_settings()
    coingecko = CoinGeckoClient(settings)

    all_assets = client.table("assets").select("id,symbol,name,coingecko_id").execute().data
    suspicious = [a for a in all_assets if a["name"] == a["symbol"] and a["coingecko_id"]]
    if not suspicious:
        print("No assets with name == symbol found -- nothing to reconcile.")
        return 0

    markets = coingecko.fetch_top_markets(MARKETS_FETCH_LIMIT)
    real_name_by_coingecko_id = {m["id"]: m["name"] for m in markets}

    corrected = 0
    for asset in suspicious:
        real_name = real_name_by_coingecko_id.get(asset["coingecko_id"])
        if real_name is None:
            print(f"  {asset['symbol']}: not found in top {MARKETS_FETCH_LIMIT} CoinGecko markets -- skipped, not guessed.")
            continue
        if real_name == asset["name"]:
            continue  # genuinely correct already (e.g. XRP, BNB) -- no-op
        client.table("assets").update({"name": real_name}).eq("id", asset["id"]).execute()
        print(f"  {asset['symbol']}: \"{asset['name']}\" -> \"{real_name}\"")
        corrected += 1

    print(f"\nChecked {len(suspicious)} suspicious asset(s), corrected {corrected}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
