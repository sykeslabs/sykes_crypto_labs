"""One-time real-holdings import (Phase 5o, 2026-09-26) -- replaces the
mockup My Portfolio (BTC 0.01, SOL 5.0, ADA 130, JASMY 20, CASH $1000) with
the full, real transaction history reconciled live in conversation from two
real exports: `data/cb_20260926.csv` (Coinbase, full history 2019-10-06 ->
today) and `data/lw_20260926.csv` (Ledger Wallet, 35 rows, all one
2025-08-25 custody transfer FROM Coinbase).

Three real data-shape bugs were found and fixed during reconciliation, all
reproduced here:
  1. Coinbase's "Advanced Trade Buy/Sell" settles against USDC or EUR but
     never emits a row for that leg -- it's only visible in the Notes text
     ("...for 280.39 USDC on BTC-USDC..."). Reconstructed here; EUR legs
     are dropped (this system's CASH line is USD-only, never asked for
     EUR tracking).
  2. A Coinbase -> Ledger Wallet transfer is cost-basis-NEUTRAL, never a
     disposal-then-repurchase at transfer-day price -- the wallet side's
     `cost_basis_usd` is the exact dollar amount proportionally moved out
     of Coinbase's own running cost pool at that point, computed here via
     a same-UTC-day aggregate (not per-row -- XRP's destination-tag
     mechanic produces 2 wallet-side rows per 1 real send, so per-row
     matching is fragile).
  3. Perpetual-futures rows (Buy/Sell/Deposit/Withdrawal, Funding Fees,
     Settlements) are margin/derivatives bookkeeping, not spot custody --
     excluded entirely; this system has no concept of leverage.

Requires migrations/0022_holdings_platform.sql to already be applied
(holdings_ledger.platform/source_type columns must exist).

Makes real, deliberate, irreversible changes: deletes every existing
holdings_ledger row, creates real `assets` rows for every new symbol the
history touches (CoinGecko-verified, never guessed), and inserts one row
per real historical transaction. Prints a full plan and asks for
confirmation before writing anything (skippable with --yes). Zero LLM
cost -- CoinGecko's free /search endpoint only.

Usage:
    python -m scripts.import_real_holdings
    python -m scripts.import_real_holdings --yes
"""

import argparse
import csv
import re
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import httpx

from app.config import get_settings
from app.database.client import get_supabase_client
from app.database.repository import AssetRepository, HoldingsLedgerRepository
from app.market_data.coingecko import CoinGeckoClient
from app.portfolio.schemas import HoldingsLedgerEntry


def _search_coin_with_retry(coingecko_client: CoinGeckoClient, symbol: str, max_retries: int = 5) -> dict | None:
    """CoinGecko's free /search endpoint has a real, tight rate limit --
    confirmed live (429 after ~8 calls in quick succession). Retries with
    exponential backoff on 429 specifically; any other error propagates
    (never silently swallowed)."""
    delay = 10.0
    for attempt in range(max_retries):
        try:
            return coingecko_client.search_coin_by_symbol(symbol)
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 429 or attempt == max_retries - 1:
                raise
            print(f"    ({symbol}: CoinGecko rate limit, waiting {delay:.0f}s before retry {attempt + 1}/{max_retries})")
            time.sleep(delay)
            delay *= 1.5
    return None

DATA_DIR = "data"
CB_FILE = "cb_20260926.csv"
LW_FILE = "lw_20260926.csv"

DUST = Decimal("0.000001")
QUOTE_PATTERN = re.compile(r"for ([\d.]+) (\w+) on")

EXCLUDED_TYPES = {
    "Perpetual Futures Buy", "Perpetual Futures Sell",
    "Perpetual Futures Deposit", "Perpetual Futures Withdrawal",
    "Debit", "Credit",
}


def load_coinbase() -> dict[str, list[tuple]]:
    """Returns {asset_symbol: [(datetime, source_type, qty, subtotal), ...]},
    already including the reconstructed USDC quote-leg rows for Advanced
    Trade Buy/Sell (EUR legs dropped)."""
    with open(f"{DATA_DIR}/{CB_FILE}", encoding="utf-8") as f:
        lines = f.readlines()
    reader = csv.DictReader(lines[2:])  # real export shape: 2 header lines, then the real header row
    by_symbol: dict[str, list[tuple]] = defaultdict(list)
    for row in reader:
        ttype = row["Transaction Type"]
        if ttype in EXCLUDED_TYPES or ttype.startswith("Settlements Of Unrealized P/L") or ttype.startswith("Funding Fee"):
            continue
        symbol = row["Asset"]
        if symbol == "EUR":
            continue
        try:
            qty = Decimal(row["Quantity Transacted"])
        except InvalidOperation:
            continue
        subtotal_raw = row["Subtotal"].replace("$", "").replace(",", "")
        try:
            subtotal = Decimal(subtotal_raw)
        except InvalidOperation:
            subtotal = Decimal("0")
        ts = datetime.strptime(row["Timestamp"], "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=UTC)
        by_symbol[symbol].append((ts, ttype, qty, subtotal))

        if ttype in ("Advanced Trade Buy", "Advanced Trade Sell"):
            m = QUOTE_PATTERN.search(row["Notes"])
            if m:
                quote_amount, quote_currency = Decimal(m.group(1)), m.group(2)
                if quote_currency == "USDC":
                    signed = -quote_amount if ttype == "Advanced Trade Buy" else quote_amount
                    by_symbol["USDC"].append((ts, f"{ttype} (quote leg)", signed, signed))
    return dict(by_symbol)


def load_ledger_wallet_daily() -> dict[tuple[str, object], Decimal]:
    """Returns {(asset_symbol, date): total_quantity_received_that_day} --
    day-aggregated (not per-row) since XRP's destination-tag mechanic
    produces 2 wallet-side rows per 1 real send."""
    with open(f"{DATA_DIR}/{LW_FILE}", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        daily: dict[tuple[str, object], Decimal] = defaultdict(Decimal)
        for row in reader:
            symbol = row["Currency Ticker"]
            qty = Decimal(row["Operation Amount"])
            ts = datetime.strptime(row["Operation Date"], "%Y-%m-%dT%H:%M:%S.%fZ")
            daily[(symbol, ts.date())] += qty
    return dict(daily)


def build_ledger_rows(cb_txns: dict[str, list[tuple]], lw_daily: dict[tuple, Decimal]) -> list[dict]:
    """Row-construction rule (see this file's own docstring): every
    Coinbase-side transaction is inserted as-is (platform=coinbase); a
    Coinbase Send on a day matching a Ledger Wallet arrival ALSO gets one
    extra platform=ledger_wallet BUY row, with cost_basis_usd equal to the
    exact dollar amount proportionally moved out of Coinbase's own running
    cost pool at that point -- never the wallet's own transfer-day value.
    This mirrors this session's already-validated
    full_portfolio_v4_transfer_aware.py exactly."""
    rows: list[dict] = []
    for symbol, txns in cb_txns.items():
        txns = sorted(txns, key=lambda t: t[0])
        running_qty = Decimal("0")
        running_cost = Decimal("0")
        i = 0
        while i < len(txns):
            ts, source_type, qty, subtotal = txns[i]
            day = ts.date()

            if source_type == "Send" and (symbol, day) in lw_daily:
                day_sends = Decimal("0")
                j = i
                while j < len(txns) and txns[j][1] == "Send" and txns[j][0].date() == day:
                    day_sends += txns[j][2]  # negative
                    j += 1
                lw_qty_received = lw_daily[(symbol, day)]
                if running_qty > 0:
                    fraction = min(Decimal("1"), abs(day_sends) / running_qty)
                    moved_cost = running_cost * fraction
                else:
                    moved_cost = Decimal("0")
                running_cost -= moved_cost
                running_qty += day_sends  # negative
                if running_qty < 0:
                    running_qty = Decimal("0")
                rows.append({
                    "symbol": symbol, "platform": "coinbase", "transaction_type": "SELL",
                    "quantity": float(abs(day_sends)), "cost_basis_usd": None,
                    "purchased_at": ts, "source_type": "Internal Transfer",
                })
                rows.append({
                    "symbol": symbol, "platform": "ledger_wallet", "transaction_type": "BUY",
                    "quantity": float(lw_qty_received), "cost_basis_usd": float(moved_cost),
                    "purchased_at": ts, "source_type": "Internal Transfer",
                })
                i = j
                continue

            if qty >= 0:
                running_qty += qty
                running_cost += subtotal
                rows.append({
                    "symbol": symbol, "platform": "coinbase", "transaction_type": "BUY",
                    "quantity": float(qty), "cost_basis_usd": float(subtotal),
                    "purchased_at": ts, "source_type": source_type,
                })
            else:
                if running_qty > 0:
                    fraction = min(Decimal("1"), abs(qty) / running_qty)
                    running_cost -= running_cost * fraction
                running_qty += qty
                rows.append({
                    "symbol": symbol, "platform": "coinbase", "transaction_type": "SELL",
                    "quantity": float(abs(qty)), "cost_basis_usd": None,
                    "purchased_at": ts, "source_type": source_type,
                })
            if running_qty < 0:
                running_qty = Decimal("0")
            i += 1
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="One-time real-holdings import from Coinbase + Ledger Wallet exports")
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    args = parser.parse_args()

    client = get_supabase_client()
    asset_repo = AssetRepository(client)
    ledger_repo = HoldingsLedgerRepository(client)
    coingecko_client = CoinGeckoClient(get_settings())

    print("Parsing real export files...")
    cb_txns = load_coinbase()
    lw_daily = load_ledger_wallet_daily()
    rows = build_ledger_rows(cb_txns, lw_daily)
    print(f"  {sum(len(v) for v in cb_txns.values())} Coinbase-derived transaction legs across {len(cb_txns)} symbols")
    print(f"  {len(rows)} holdings_ledger rows to insert")

    symbols_needed = sorted(cb_txns.keys())
    # A plain table read, not get_active_assets() -- that only returns
    # active=true rows, and a symbol tracked-but-inactive must not be
    # re-created as a duplicate.
    all_assets_resp = client.table("assets").select("id,symbol").execute()
    existing_by_symbol = {r["symbol"]: r["id"] for r in all_assets_resp.data}

    symbols_to_create = [s for s in symbols_needed if s not in existing_by_symbol]
    print(f"\n{len(symbols_to_create)} new asset(s) need onboarding (CoinGecko-verified, real symbols only):")

    # Computed from the FINAL constructed rows (both platforms), not just
    # Coinbase's own net quantity -- an asset fully transferred to the
    # Ledger Wallet (e.g. ETC) nets to ~0 on the Coinbase side alone, which
    # would wrongly look unheld if only cb_txns were summed here.
    net_qty_by_symbol: dict[str, Decimal] = defaultdict(Decimal)
    for row in rows:
        signed = Decimal(str(row["quantity"])) * (1 if row["transaction_type"] == "BUY" else -1)
        net_qty_by_symbol[row["symbol"]] += signed
    held_symbols = {s for s, q in net_qty_by_symbol.items() if abs(q) >= DUST}

    resolved: dict[str, dict] = {}
    unresolved: list[str] = []
    for n, symbol in enumerate(symbols_to_create):
        if n > 0:
            time.sleep(2.0)  # stay well under CoinGecko's free-tier rate limit
        match = _search_coin_with_retry(coingecko_client, symbol)
        if match is None:
            unresolved.append(symbol)
            print(f"  {symbol}: NOT FOUND on CoinGecko -- will be skipped entirely (no assets row, no holdings_ledger rows)")
            continue
        resolved[symbol] = match
        in_asset = symbol in held_symbols
        print(f"  {symbol}: -> {match['name']} ({match['id']}), active=False, in_asset={in_asset}")

    if unresolved:
        rows = [r for r in rows if r["symbol"] not in unresolved]
        print(f"\n{len(unresolved)} unresolved symbol(s) excluded from the import: {unresolved}")

    print(f"\nThis will DELETE every existing holdings_ledger row (the mockup portfolio) and INSERT {len(rows)} real rows.")
    if not args.yes:
        confirm = input("Proceed? [y/N] ")
        if confirm.strip().lower() != "y":
            print("Aborted -- nothing changed.")
            return 1

    for symbol, match in resolved.items():
        asset = asset_repo.create_asset(
            symbol=match["symbol"].upper(), name=match["name"], coingecko_id=match["id"],
            active=False, in_asset=symbol in held_symbols,
        )
        existing_by_symbol[symbol] = asset.id
        print(f"  Created asset: {symbol} -> {asset.id}")

    print("\nDeleting existing holdings_ledger rows...")
    client.table("holdings_ledger").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()

    print(f"Inserting {len(rows)} real holdings_ledger rows...")
    inserted = 0
    for row in rows:
        asset_id = existing_by_symbol.get(row["symbol"])
        if asset_id is None:
            continue  # unresolved symbol, already filtered above -- defensive
        entry = HoldingsLedgerEntry(
            asset_id=asset_id, quantity=row["quantity"], cost_basis_usd=row["cost_basis_usd"],
            recorded_at=datetime.now(UTC), purchased_at=row["purchased_at"],
            transaction_type=row["transaction_type"], platform=row["platform"],
            source_type=row["source_type"],
        )
        ledger_repo.insert(entry)
        inserted += 1

    print(f"\nDone. {inserted} real transaction(s) imported across {len(existing_by_symbol)} tracked assets.")
    print("Run `python -m scripts.reconcile_in_asset` if any in_asset flags need a final pass.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
