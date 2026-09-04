# Crypto AI Portfolio

Modular, auditable AI-driven crypto portfolio management system. **Paper trading only** —
no exchange credentials or live orders exist yet.

## Status

- ✅ **Phase 1 — Foundation**: project structure, configuration, Supabase schema
  (`assets`, `market_snapshots`), CoinGecko market-data collector. Complete and
  verified against a live Supabase project.
- ✅ **Phase 2 — Multi-model AI**: RSS news collection + relevance matching,
  OpenRouter integration (Claude, OpenAI, Gemini), structured/validated LLM
  output, cost tracking with daily/monthly caps. Complete and verified with
  live LLM calls against a real Supabase project.
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
   - `OPENROUTER_API_KEY`, `CLAUDE_MODEL`, `OPENAI_MODEL`, `GEMINI_MODEL` — only
     required if you want to run `--with-llm` (see Phase 2 below). Not needed
     for plain market-data collection.

3. Apply the database schema — both migrations, in order. Either:
   - **Recommended**: open the Supabase SQL Editor and paste the contents of
     `migrations/0001_init.sql`, run it, then do the same for
     `migrations/0002_llm_and_news.sql`. Both are idempotent — safe to re-run
     any time they change.
   - Or, with `DATABASE_URL` set:
     ```
     python scripts/apply_migration.py migrations/0001_init.sql
     python scripts/apply_migration.py migrations/0002_llm_and_news.sql
     ```

4. Run the collector:

   ```
   python -m app.main
   ```

   This fetches current market data for all active assets from CoinGecko and stores
   one normalized snapshot per asset in `market_snapshots`, skipping any asset whose
   most recent snapshot is younger than `MIN_SNAPSHOT_INTERVAL_MINUTES` (default 5)
   to avoid redundant writes.

5. Optionally, also run news collection + multi-model LLM research:

   ```
   python -m app.main --with-llm
   ```

   **This makes real, billed calls to Claude/OpenAI/Gemini via OpenRouter** — see
   the Phase 2 section below before running it.

## Verifying it worked

- Console output logs a `run_id` (e.g. `RUN-20260903-141623`, unique to the second) and a per-run summary:
  `inserted=N skipped_duplicate=N failed=N`, plus which symbols were stored.
- In the Supabase Table Editor, check `market_snapshots` — you should see one row
  per active asset with a recent `timestamp`, `price`, `market_cap`, etc.
- Run `python -m app.main` again immediately — assets should show up in
  `skipped_duplicate` rather than being re-inserted (dedup working).
- Run `pytest` — all tests should pass without needing any credentials (they use
  fakes/mocks, no live network or database calls).

For `--with-llm`: check `news` and `llm_analyses` in the Supabase Table Editor.
`llm_analyses` should have up to one row per (provider, asset) — 3 providers ×
however many `active` assets. Console output logs `stored_by_provider`,
`failed`, and `skipped_cost_cap` per provider so failures are visible without
digging through the database.

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

## Phase 2 — Multi-model AI research (`--with-llm`)

Running `python -m app.main --with-llm` adds two steps after market data
collection:

1. **News collection** (`app/news/`): pulls RSS from CoinDesk, CoinTelegraph,
   and Decrypt (free, no API key), matches each article against the asset
   universe by name/ticker (word-bounded; ticker matching is case-sensitive
   to avoid e.g. "LINK" matching the ordinary word "link"), dedupes on
   `content_hash`, and stores only articles relevant to at least one asset.
2. **LLM research** (`app/llm/`): builds one shared market-data-plus-news
   context, sends it to Claude, OpenAI, and Gemini via OpenRouter (one
   batched call per provider covering every asset, not one call per asset,
   to keep cost down), validates each response against a strict Pydantic
   schema (retrying once in-conversation if the model returns invalid JSON),
   and persists one row per (provider, asset) to `llm_analyses`. One provider
   failing never blocks the other two.

**Cost control**: `CostGuard` checks cumulative spend (summed from
`llm_analyses.estimated_cost`) against `MAX_DAILY_LLM_COST` /
`MAX_MONTHLY_LLM_COST` before every provider call, skipping (not crashing)
once a cap is hit. The pricing table in `app/llm/cost.py` is a point-in-time
snapshot of OpenRouter pricing — re-check https://openrouter.ai/models
periodically, especially after changing `CLAUDE_MODEL`/`OPENAI_MODEL`/`GEMINI_MODEL`.

**Known limitations** (accepted tradeoffs, not bugs):
- `sentiment` on `news` rows is always `NULL` — computing it reliably needs
  either an extra LLM call (cost) or a real sentiment model; deferred.
- News relevance matching is a keyword heuristic, not NLP — it will
  occasionally miss context or produce a coincidental match. It's a cheap
  pre-filter feeding models that can apply their own judgment, not a source
  of ground truth.
- Coverage is uneven across the asset universe: general crypto news outlets
  cover BTC/ETH/SOL/XRP/BNB/HYPE far more than smaller caps like STORJ or
  JTO. When no news is found, the LLMs correctly fall back to price-momentum
  reasoning rather than inventing a catalyst.

`run_id` is time-based to the second (`RUN-YYYYMMDD-HHMMSS`), generated fresh
per process — each `python -m app.main` invocation gets its own unique id.

## Project layout

```
app/
  config/        Settings (env-driven)
  database/      Supabase client + repositories (assets, market_snapshots, news, llm_analyses)
  market_data/   CoinGecko client, normalization, collection service
  news/          RSS collection, relevance matching, dedup (Phase 2)
  llm/           OpenRouter integration, structured output, cost guard (Phase 2)
  judge/         Phase 3
  portfolio/     Phase 3
  risk/          Phase 3
  trading/       Phase 4
  benchmarks/    Phase 4
  main.py        Entrypoint (python -m app.main [--with-llm])
tests/
migrations/      SQL schema, applied manually or via scripts/apply_migration.py
scripts/
```

## Development methodology

This project is built and verified one phase at a time (see Status above) — each
phase is implemented, tested against a live Supabase project, and reviewed before
the next begins. Live trading is only ever activated after a separate, explicit
safety review; the default and current mode is PAPER.
