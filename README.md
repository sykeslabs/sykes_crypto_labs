# Crypto AI Portfolio (Phase 1)

Modular, auditable AI-driven crypto portfolio management system. **Paper trading only** —
no exchange credentials or live orders exist yet.

Phase 1 implements the foundation only: project structure, configuration, the Supabase
schema for `assets` and `market_snapshots`, and a CoinGecko market-data collector.

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
     `market_snapshots` tables, indexes, and seeds the initial 6-asset universe
     (BTC, ETH, SOL, XRP, BNB, HYPE).
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

## Development phases

This project is built incrementally. Phase 1 (this state) covers market data
collection only. Later phases (see the original spec) add multi-model LLM research,
a Judge, a deterministic Risk Engine, paper trading execution, benchmarking, a
dashboard, and — only after extensive paper-trading validation — sandboxed exchange
integration. Each phase is implemented and reviewed before the next begins.
