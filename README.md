# Crypto AI Portfolio

Modular, auditable AI-driven crypto portfolio management system. **Paper trading only** —
no exchange credentials or live orders exist yet.

## Status

- ✅ **Phase 1 — Foundation**: project structure, configuration, Supabase schema
  (`assets`, `market_snapshots`), CoinGecko market-data collector. Complete and
  verified against a live Supabase project.
- ⬜ Phase 2 — Multi-model AI (OpenRouter: Claude, OpenAI, Gemini)
- ⬜ Phase 3 — Judge, Portfolio Manager, Risk Engine
- ⬜ Phase 4 — Paper trading execution, benchmarks
- ⬜ Phase 5 — Dashboard, scheduling
- ⬜ Phase 6 — Exchange integration (testnet only)

## Setup

1. Create a virtual environment and install dependencies:

   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and fill in:
   - `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` — from your Supabase project's
     Settings -> API page. **Required.**
   - `COINGECKO_API_KEY` — optional; leave blank to use CoinGecko's public
     (rate-limited) endpoint.
   - `DATABASE_URL` — optional, only needed if you want to apply migrations via
     `scripts/apply_migration.py` instead of the Supabase SQL Editor.

3. Apply the database schema. Either:
   - **Recommended**: open the Supabase SQL Editor and paste the contents of
     `migrations/0001_init.sql`, then run it. This creates the `assets` and
     `market_snapshots` tables, indexes, and seeds the asset universe (see below).
     The migration is idempotent — safe to re-run any time it changes.
   - Or, with `DATABASE_URL` set: `python scripts/apply_migration.py migrations/0001_init.sql`

4. Run the collector:

   ```
   python -m app.main
   ```

   This fetches current market data for all active assets from CoinGecko and stores
   one normalized snapshot per asset in `market_snapshots`, skipping any asset whose
   most recent snapshot is younger than `MIN_SNAPSHOT_INTERVAL_MINUTES` (default 5)
   to avoid redundant writes.

## Verifying it worked

- Console output logs a `run_id` (e.g. `RUN-2026-09-03-001`) and a per-run summary:
  `inserted=N skipped_duplicate=N failed=N`, plus which symbols were stored.
- In the Supabase Table Editor, check `market_snapshots` — you should see one row
  per active asset with a recent `timestamp`, `price`, `market_cap`, etc.
- Run `python -m app.main` again immediately — assets should show up in
  `skipped_duplicate` rather than being re-inserted (dedup working).
- Run `pytest` — all tests should pass without needing any credentials (they use
  fakes/mocks, no live network or database calls).

## Asset universe

The asset universe is **not hard-coded** in the application. It lives in the `assets`
table (seeded by the migration) and is read fresh on every run. To add or disable an
asset, edit the `assets` table directly (e.g. set `active = false`, or insert a new
row with its CoinGecko id) — no code changes required.

Two independent flags per asset:
- `active` — whether the market-data collector tracks this asset at all.
- `in_asset` — whether it's currently held in the live portfolio, vs. tracked for
  research/watchlist purposes only. Purely informational in Phase 1; later phases
  (Portfolio Manager, Risk Engine) will read it.

Seeded assets:

| symbol | name | coingecko_id | in_asset |
|---|---|---|---|
| BTC | Bitcoin | `bitcoin` | true |
| ETH | Ethereum | `ethereum` | true |
| SOL | Solana | `solana` | false |
| XRP | XRP | `ripple` | false |
| BNB | BNB | `binancecoin` | false |
| HYPE | Hyperliquid | `hyperliquid` | false |
| LINK | Chainlink | `chainlink` | true |
| ONDO | Ondo | `ondo-finance` | true |
| JASMY | JasmyCoin | `jasmycoin` | true |
| ENA | Ethena | `ethena` | true |
| S | Sonic | `sonic-3` | true |
| STORJ | Storj | `storj` | true |
| ZRX | 0x Protocol | `0x` | true |
| XTZ | Tezos | `tezos` | true |
| BONK | Bonk | `bonk` | true |
| JTO | Jito | `jito-governance-token` | true |

All 16 are `active`, so the collector currently tracks all of them regardless of
`in_asset`.

## Project layout

```
app/
  config/        Settings (env-driven)
  database/      Supabase client + repositories (assets, market_snapshots)
  market_data/   CoinGecko client, normalization, collection service
  news/          Phase 2
  llm/           Phase 2
  judge/         Phase 3
  portfolio/     Phase 3
  risk/          Phase 3
  trading/       Phase 4
  benchmarks/    Phase 4
  main.py        Entrypoint (python -m app.main)
tests/
migrations/      SQL schema, applied manually or via scripts/apply_migration.py
scripts/
```

## Development methodology

This project is built and verified one phase at a time (see Status above) — each
phase is implemented, tested against a live Supabase project, and reviewed before
the next begins. Live trading is only ever activated after a separate, explicit
safety review; the default and current mode is PAPER.
