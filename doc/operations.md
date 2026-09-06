# Operations

How to install, configure, run, and verify this system day-to-day.

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
   - (From Phase 3d onward, optional) `OPENROUTER_ASSESSMENT_MODELS` — the
     model set for the current-market-assessment stage; may include Grok if
     you choose to enable it.
   - (Optional, Phase 3d onward) `LANGFUSE_*` credentials — only needed if you
     choose to enable call tracing; the pipeline runs identically without
     them.
   - (Optional, Phase 3c onward) `GLASSNODE_API_KEY` / `CRYPTOQUANT_API_KEY`
     — only needed to enable on-chain valuation-cycle metrics
     (MVRV/SOPR/NUPL/LTH-STH cohorts); a paid tier may be required for full
     coverage. Leave blank to have that source recorded as
     `NOT_IMPLEMENTED`/`UNAVAILABLE` in `signal_sources` rather than
     approximated.
   - (Optional, Phase 3c onward) `TOKEN_UNLOCK_SOURCE_API_KEY` (Messari or
     TokenUnlocks) — only needed to enable token unlock/vesting schedule
     data for the altcoin tier of the universe.
   - (Optional, Phase 3c onward) `CME_COT_SOURCE` config — the CFTC
     publishes Commitment of Traders data for free with no key required;
     this setting only exists if you choose to point at a documented
     aggregator instead of the CFTC's own published data directly. Leave
     unset to have `CME_COT_POSITIONING` recorded as `NOT_IMPLEMENTED`
     rather than approximated.
   - (Optional, Phase 3f onward) `FRED_API_KEY` — free, required by FRED for
     the global-liquidity/cross-asset-correlation macro extension (M2, Fed
     balance sheet, S&P 500/dollar-index series). Leave blank to have
     `GLOBAL_LIQUIDITY_MACRO` recorded as `NOT_IMPLEMENTED`.
   - (Optional, Phase 3f onward) `SEC_EDGAR_USER_AGENT` /
     `CONGRESS_GOV_API_KEY` — only needed to enable the regulatory/policy
     event calendar. Both underlying APIs are free; leave blank to have
     `REGULATORY_EVENT_CALENDAR` recorded as `NOT_IMPLEMENTED`.
   - (Optional, Phase 3f onward) `REGIONAL_EXCHANGE_API_KEY` / endpoint
     config (e.g. Upbit/Bithumb) — only needed to enable the regional
     exchange price-premium source. Leave unset to have
     `REGIONAL_EXCHANGE_PREMIUM` recorded as `NOT_IMPLEMENTED`.
   - (Optional, Phase 3i onward) `NANSEN_API_KEY` / `ARKHAM_API_KEY` — only
     needed to enable wallet-entity-clustering/"smart money" flow
     intelligence; a paid tier is required. Leave blank to have
     `ENTITY_FLOW_INTELLIGENCE` recorded as `NOT_IMPLEMENTED`.
   - (Optional, Phase 3i onward) `DEV_ACTIVITY_SOURCE_API_KEY` (e.g. an
     Electric Capital Developer Report-style aggregator, or a direct
     GitHub API token) — only needed to enable the developer-activity half
     of `NETWORK_FUNDAMENTALS_DEV_ACTIVITY`; the network-usage half (active
     addresses, fees) reuses the on-chain explorer credentials already
     configured for 3c. Leave blank to have the developer-activity field
     recorded as `NOT_IMPLEMENTED`.
   - (Optional, Phase 3i onward) `CUSTODY_WATCH_ADDRESSES` config — a
     documented list of known custody-provider addresses to track balance
     deltas for; no paid API required if using publicly known addresses via
     the existing on-chain explorer. Leave unset to have `CUSTODY_OTC_FLOW`
     recorded as `NOT_IMPLEMENTED`.

3. Apply the database schema — all five migrations, in order. Either:
   - **Recommended**: open the Supabase SQL Editor and paste the contents of
     `migrations/0001_init.sql`, run it, then do the same for
     `migrations/0002_llm_and_news.sql`,
     `migrations/0003_phase3a_universe_provenance.sql`,
     `migrations/0004_phase3b_screening_regime.sql`, and
     `migrations/0005_phase3c_derivatives_onchain.sql`. All are idempotent —
     safe to re-run any time they change.
   - Or, with `DATABASE_URL` set:
     ```
     python scripts/apply_migration.py migrations/0001_init.sql
     python scripts/apply_migration.py migrations/0002_llm_and_news.sql
     python scripts/apply_migration.py migrations/0003_phase3a_universe_provenance.sql
     python scripts/apply_migration.py migrations/0004_phase3b_screening_regime.sql
     python scripts/apply_migration.py migrations/0005_phase3c_derivatives_onchain.sql
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

6. Optionally, also run 3b's screening + market-regime classification (zero
   LLM cost — CoinGecko/CoinMarketCap/Coinbase/Binance market data only):

   ```
   python -m app.main --with-screening
   ```

   Combine with `--with-llm` if you want both in one run. See the Phase 3b
   section below for what this does.

7. Optionally, also run 3c's derivatives/on-chain collection (zero LLM cost —
   Binance Futures/Deribit/CFTC/DefiLlama market data, no key required for
   any of those four):

   ```
   python -m app.main --with-derivatives
   ```

   Combine with `--with-llm`/`--with-screening` as needed. See the Phase 3c
   section below for what this does.


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


## Daily operation

Scheduling was explicitly considered and deferred in Phase 5 (see
[`open-work.md`](open-work.md) for the reasoning and revisit trigger) — this
remains a **manually-triggered system**. This section documents the current
manual command sequence for running the full advisory pipeline day-to-day.
It describes today's operating reality, not an eventual scheduled/automated
system.

### What each flag does, its real per-run cost, and ordering

Every invocation of `python -m app.main` unconditionally collects base
market data first (CoinGecko, one batched call, zero LLM cost, all active
assets), regardless of which flags are passed. Everything below is
additive on top of that.

| Flag | What it does | Real per-run cost | Ordering dependency |
|---|---|---|---|
| `--with-screening` | 3b's screening + market-regime classification (CoinMarketCap/Coinbase/Binance) — computes that run's `TOP_CANDIDATES`. | Zero LLM cost. | None upstream. Everything below that reads `TOP_CANDIDATES` (asset-intelligence, assessment) needs this to have run at some point — either earlier the same day or in the same command — since those steps read the *latest stored* screened universe, not necessarily this exact invocation's. |
| `--with-derivatives` | 3c's derivatives/on-chain collection (Binance Futures funding/OI, Deribit options IV/skew, CFTC COT, DefiLlama TVL; optional Etherscan/Glassnode). | Zero LLM cost. | None — writes `evidence_observations` directly per asset, independent of screening. Run before `--with-judge`/`--with-assessment` if you want this evidence fresh for that run's reasoning (the Judge/assessment read whatever is latest in the database, not scoped to "this run only"). |
| `--with-macro` | 3f's macro matrix (CPI/PCE/claims/payrolls/yields/fed funds), macro-event calendar, FRED global-liquidity/cross-asset-correlation, Upbit regional premium, SEC EDGAR/congress.gov regulatory calendar. | Zero LLM cost. | Same as `--with-derivatives` — independent, no hard ordering requirement, but its output feeds Judge context so run it before `--with-judge` for freshness. |
| `--with-asset-intelligence` | 3i's entity-flow intelligence (Nansen smart-money netflow, `TOP_CANDIDATES` only) + network usage/developer-activity (Etherscan `tokentx` proxy + GitHub). | Zero LLM cost. **Nansen's free tier is genuinely credit-constrained** (100 one-time credits + 10/day refill — see the dashboard's `signal_sources` panel), a real operational limit independent of LLM cost. | Its own `--help` text states it explicitly: **requires a prior `--with-screening` run** (reads `TOP_CANDIDATES`) and `NANSEN_API_KEY`. |
| `--with-assessment` | 3d's multi-model current-market assessment (Claude/OpenAI/Gemini, one call per model per candidate) over the latest `TOP_CANDIDATES`. | **$0.4115 for 10 candidates**, live-verified (claude $0.1313, openai $0.1292, gemini $0.1510) — see `phases.md`'s Phase 3d section. Scales with candidate count. | Reads 3b's latest `TOP_CANDIDATES` — a `--with-screening` run must have happened at some point before this (same command or earlier). |
| `--with-adversarial` | 3f's bull → bear → scenario adversarial research cycle over the latest `TOP_CANDIDATES`. | **$0.2366 for 10 candidates**, live-verified (bull $0.0515, bear $0.0911, scenario $0.0940) — see `phases.md`'s Phase 3f section. | Its own `--help` text: **requires a prior `--with-assessment` run** (reads `model_market_assessments`). |
| `--with-judge` | 3e's Judge (synthesizes 3b/3c/3d/3f/3i/Phase-2 evidence into one decision per candidate) → Risk Engine (deterministic sizing/gating) → Portfolio Construction, sized against real `holdings_ledger` ground truth (Phase 5a). | **$0.2133–$0.2407 for 10 decisions**, two independent live-measured figures from real runs today (`RUN-20260906-080647` and `RUN-20260906-114219`) — see `phases.md`'s Phase 3e and Phase 5a sections. Full pipeline (assessment + adversarial + Judge combined) ≈ **$0.80/run**, comfortably inside `MAX_DAILY_LLM_COST=12`/`MAX_MONTHLY_LLM_COST=30` even at several runs/day. | Its own `--help` text: **requires a prior `--with-assessment` run**. Also reads `adversarial_research` and `llm_analyses` if present — both degrade gracefully to empty/`None` when absent, so it works without them, just with a narrower evidence base. |
| `--evaluate-outcomes` | Backfills `realized_return`/outcome label on past-horizon `decision_outcomes` rows against actual subsequent `market_snapshots`. | Zero LLM cost, deterministic. | **Independent of every other flag** per its own `--help` text — safe to run any time, alone or combined. |
| `--with-llm` | Phase 2's original path: RSS news collection + one batched multi-model (Claude/OpenAI/Gemini) call per provider over all active assets, stored to `llm_analyses`. | **Never aggregated as a per-run figure anywhere in this project's docs** — flagging that honestly rather than estimating fresh. Real measured figures do exist in Supabase, pulled directly rather than invented for this section: **$0.5695** across 96 rows (32 candidates × 3 providers, `RUN-2026-09-04-001`) and **$0.3092** across 48 rows (16 assets × 3 providers, `RUN-20260905-064042`). Cost scales with active-asset count, which has grown over the project's life, so neither figure is "the" current per-run cost — treat both as real historical data points, not a current estimate. | **Real ordering quirk, not fixed (out of this pass's scope): `--with-llm`'s actual news+LLM-research code runs LAST in `app/main.py`** — after Judge/Portfolio Construction and after `--evaluate-outcomes`, not right after market data collection as you might expect. Combining `--with-llm --with-judge` in **one command** means the Judge step in that same run sees only *previously stored* `llm_analyses` (if any), never the fresh rows `--with-llm` collects later in that same invocation. If you want Judge to reason over this run's own fresh `llm_analyses`, run `--with-llm` in its own separate, earlier invocation. |

### Recommended daily sequence

One combined command covers the full pipeline in the correct dependency
order (flags execute in this fixed order inside `app/main.py` regardless of
which subset you pass):

```
python -m app.main --with-llm
python -m app.main --with-screening --with-derivatives --with-macro --with-asset-intelligence --with-assessment --with-adversarial --with-judge --evaluate-outcomes
```

Run `--with-llm` in its own earlier invocation (per the ordering quirk
above) if you want the Judge to see this cycle's fresh news-driven
analysis; otherwise it's optional and can be skipped or run independently
on its own cadence. `--evaluate-outcomes` is safe to run standalone at any
point, including multiple times a day, with zero additional cost.

## Running the API & dashboard

Confirmed from `app/api/main.py`'s own module docstring — not guessed:

```
uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/` in a browser for the dashboard. The page
itself loads with no key required, but every data-bearing panel and the
`POST /holdings` form go through the same `X-API-Key`-gated JSON endpoints
as any other caller (Phase 5's access-control non-negotiable) — paste the
value of `API_ACCESS_KEY` from your `.env` into the dashboard's key field
and click "Save key" (stored in that browser's `localStorage` only, per
the documented localhost/personal-machine deployment scope). The same
header is required for direct API calls, e.g.
`curl -H "X-API-Key: $API_ACCESS_KEY" http://127.0.0.1:8000/holdings`.
