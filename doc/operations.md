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
   - (Optional, Phase 3b onward) `COINMARKETCAP_API_KEY` — free-tier key,
     enables a CoinGecko cross-check and 90d-momentum data (feeds the
     altcoin-season index). Leave blank to have `CoinMarketCap` recorded
     `NOT_IMPLEMENTED` rather than approximated.
   - (Optional, Phase 3c onward) `ETHERSCAN_API_KEY` — free-tier key,
     enables the large-ETH-transfer proxy and per-token network-usage
     proxy. Leave blank to have `Etherscan` recorded `NOT_IMPLEMENTED`.
   - (Optional, Phase 3c onward) `GLASSNODE_API_KEY` — on-chain
     valuation-cycle metrics (MVRV/SOPR/NUPL/LTH-STH cohorts) and BTC
     miner metrics; client is built and ready but a paid tier is very
     likely required — **deliberately not subscribed to** (see
     [`decisions.md`](decisions.md)). Leave blank to have `ON_CHAIN_MINER_METRICS`/
     `ON_CHAIN_VALUATION_METRICS` recorded `NOT_IMPLEMENTED`.
   - (Optional, Phase 3f onward) `FRED_API_KEY` — free, required by FRED for
     the global-liquidity/cross-asset-correlation macro extension (M2, Fed
     balance sheet, S&P 500/dollar-index series) and the macro
     CPI/PCE/claims/payrolls/yields/fed-funds matrix. Leave blank to have
     `GLOBAL_LIQUIDITY_MACRO`/`Macro` recorded `NOT_IMPLEMENTED`.
   - (Optional, Phase 3f onward) `CONGRESS_GOV_API_KEY` — a quick free
     signup, enables the legislative half of the regulatory event calendar
     (SEC EDGAR's half needs no key, only `SEC_EDGAR_USER_AGENT` below).
     Leave blank to have that half of `REGULATORY_EVENT_CALENDAR` recorded
     `NOT_IMPLEMENTED`.
   - `SEC_EDGAR_USER_AGENT` — a descriptive identification string SEC's
     fair-access policy requires (not a secret); defaults to a real,
     working value already set in this project. An empty string is
     treated the same as unset (falls back to the default), not sent
     as-is — SEC rejects an empty/generic User-Agent with a 403.
   - (Optional, Phase 3i onward) `NANSEN_API_KEY` — free tier (100
     one-time + 10/day credits, genuinely credit-constrained), enables
     entity-flow/"smart money" netflow intelligence for `TOP_CANDIDATES`
     on Nansen-supported (EVM/Solana) chains. Leave blank to have
     `ENTITY_FLOW_INTELLIGENCE` recorded `NOT_IMPLEMENTED`.
   - (Optional, Phase 3i onward) `GITHUB_TOKEN` — a free personal access
     token; raises the developer-activity collector's GitHub rate limit
     from 60/hr to 5000/hr. Not required for this project's small,
     curated primary-repo map (10 assets) — leave blank and it still
     works, just closer to the unauthenticated limit.
   - (Added 2026-09-15, deferred — not yet wired into any client)
     `LUNARCRUSH_API_KEY` — a real user key was tested live against every
     plausible endpoint (coins list, single coin, topic); all return HTTP
     402, requiring an "Individual" tier or higher. Setting this
     currently has **no effect** — no Settings field or client reads it
     yet. See [`decisions.md`](decisions.md) and
     [`history.md`](history.md)'s Phase 5e section.
   - Everything else named in earlier planning docs as a possible env var
     for CME COT positioning, the regional exchange premium, custody/OTC
     address tracking, or token-unlock schedules was **never actually
     built as a configurable source** — CME COT uses the CFTC's free
     public API directly (no key), the regional premium uses Upbit
     directly (no key), and custody/OTC flow and token unlocks are
     recorded `NOT_IMPLEMENTED` (no viable/reachable source found — see
     [`todo.md`](todo.md)). If you see a reference to
     `CME_COT_SOURCE`/`REGIONAL_EXCHANGE_API_KEY`/`DEV_ACTIVITY_SOURCE_API_KEY`/
     `CUSTODY_WATCH_ADDRESSES`/`TOKEN_UNLOCK_SOURCE_API_KEY` anywhere, it's
     stale planning-time documentation, not a real setting — none of
     these exist in `app/config/settings.py`.

3. Apply the database schema — all migrations in `migrations/`, **in numeric
   order** (each depends on tables/columns the previous ones created):

   | # | File | Adds |
   |---|---|---|
   | 0001 | `0001_init.sql` | Core schema: `assets`, `market_snapshots`. |
   | 0002 | `0002_llm_and_news.sql` | `news`, `llm_analyses` (Phase 2). |
   | 0003 | `0003_phase3a_universe_provenance.sql` | Universe-provenance tracking (3a). |
   | 0004 | `0004_phase3b_screening_regime.sql` | `screened_universe`, market-regime fields (3b). |
   | 0005 | `0005_phase3c_derivatives_onchain.sql` | `evidence_observations` + derivatives/on-chain sources (3c). |
   | 0006 | `0006_phase3d_model_assessments.sql` | `model_market_assessments` (3d multi-model current assessment). |
   | 0007 | `0007_phase3e_portfolio_state.sql` | `portfolio_positions`, `decisions`, `decision_outcomes` (3e Judge/Risk/Portfolio). |
   | 0008 | `0008_phase3e1_backfill_flag.sql` | Backfilled-vs-live flag on decisions. |
   | 0009 | `0009_phase3f_adversarial_research.sql` | `adversarial_research` (3f bull/bear/scenario cycle). |
   | 0010 | `0010_phase3f_judge_macro_sensitivity.sql` | Macro-sensitivity fields feeding the Judge. |
   | 0011 | `0011_phase3g_judge_reasoning_audits.sql` | `judge_reasoning_audits` (3g). |
   | 0012 | `0012_phase3h_evidence_value_reports.sql` | `evidence_value_reports` (3h evidence-value ranking). |
   | 0013 | `0013_phase4_execution_costs.sql` | Execution-cost fields on `decision_outcomes` (Phase 4). |
   | 0014 | `0014_phase5a_holdings_ledger.sql` | `holdings_ledger` — real holdings ground truth (Phase 5a). |
   | 0015 | `0015_phase5b_holdings_transactions.sql` | `holdings_transactions` (Phase 5b transaction history). |
   | 0016 | `0016_drop_signal_sources_enabled.sql` | Drops a stale `signal_sources.enabled` column. |
   | 0017 | `0017_effective_alpha.sql` | `benchmark_return`/`effective_alpha` on `decision_outcomes`. |
   | 0018 | `0018_return_dispersion.sql` | Return-dispersion fields, continuous `model_agreement` alternative. |
   | 0019 | `0019_turnover_cap_events.sql` | `turnover_cap_events` (weekly turnover-cap audit trail). |
   | 0020 | `0020_turnover_baseline_fix.sql` | `portfolio_allocation_changes` + `baseline_semantics`, the Phase 5c turnover-baseline fix — see [`history.md`](history.md)'s Phase 5c section. |

   Either:
   - **Recommended**: open the Supabase SQL Editor and paste each file's
     contents in order, `0001` through `0020`, running each before moving to
     the next. All are idempotent — safe to re-run any time they change.
   - Or, with `DATABASE_URL` set, run `python scripts/apply_migration.py
     migrations/000N_*.sql` for each file in order — **but note this path is
     currently broken** in this environment (`DATABASE_URL`/`psycopg2`
     connections have failed with "password authentication failed" for
     every migration attempted since 0011; see [`scripts.md`](scripts.md)).
     Use the Supabase SQL Editor path above until that's resolved, and
     always verify a migration actually applied via the Supabase client
     (`python -c` snippet querying the new table/column), never by trusting
     `apply_migration.py`'s own exit code.

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
- `in_asset` — whether the *system's own strategy* currently targets a
  nonzero allocation to this asset, distinct from what's actually held
  (see `holdings_ledger`/real holdings, Phase 5a onward) — kept in sync
  automatically by 3b's screening promotion logic and `POST /holdings`,
  not meant to be hand-edited under normal operation.

The universe is **not static** — 3b's screening (`--with-screening`)
auto-promotes new CoinGecko top-market candidates into `assets` over time
(see [`history.md`](history.md)), so the seed list below has grown well
past its original size. Live-queried 2026-09-16, 29 real rows, all
`active=true`:

| symbol | name | coingecko_id | in_asset |
|---|---|---|---|
| AAVE | Aave | `aave` | false |
| ADA | Cardano | `cardano` | true |
| AVAX | Avalanche | `avalanche-2` | false |
| BNB | BNB | `binancecoin` | false |
| BONK | Bonk | `bonk` | false |
| BTC | Bitcoin | `bitcoin` | true |
| BTW | Bitway | `bitway` | false |
| CRO | Cronos | `crypto-com-chain` | false |
| DOGE | Dogecoin | `dogecoin` | false |
| ENA | Ethena | `ethena` | false |
| ETH | Ethereum | `ethereum` | false |
| HYPE | Hyperliquid | `hyperliquid` | false |
| JASMY | JasmyCoin | `jasmycoin` | true |
| JTO | Jito | `jito-governance-token` | false |
| LINK | Chainlink | `chainlink` | false |
| LTC | Litecoin | `litecoin` | false |
| NEAR | NEAR Protocol | `near` | false |
| ONDO | Ondo | `ondo-finance` | false |
| S | Sonic | `sonic-3` | false |
| SOL | Solana | `solana` | true |
| STORJ | Storj | `storj` | false |
| UNI | Uniswap | `uniswap` | false |
| WBT | WhiteBIT Coin | `whitebit` | false |
| XLM | Stellar | `stellar` | false |
| XMR | Monero | `monero` | false |
| XRP | XRP | `ripple` | false |
| XTZ | Tezos | `tezos` | false |
| ZEC | Zcash | `zcash` | false |
| ZRX | 0x Protocol | `0x` | false |

Display names were corrected live 2026-09-16 for 12 of these (previously
fell back to the bare symbol due to a real bug — see
[`history.md`](history.md)'s Phase 5e section and
`scripts/reconcile_asset_names.py`). `in_asset=true` for only 4 (ADA, BTC,
JASMY, SOL) reflects the system's *current strategy target*, not real
holdings — check the dashboard's Portfolio section or `holdings_ledger`
for what's actually held.


## Daily operation

Scheduling was explicitly considered and deferred in Phase 5 (see
[`todo.md`](todo.md)'s "Deferred / gated" section for the reasoning and
revisit trigger) — this remains a **manually-triggered system**. This
section documents the current manual command sequence for running the full
advisory pipeline day-to-day. It describes today's operating reality, not
an eventual scheduled/automated system.

### Recommended: `scripts/run_daily.py`

The simplest way to run a full day's cycle is the single wrapper script:

```
python -m scripts.run_daily
```

It runs the news step, then the combined screening/derivatives/macro/
asset-intelligence/assessment/adversarial/judge/evaluate-outcomes
invocation, then `apply_execution_costs.py` and `apply_benchmark_alpha.py`
every day, and `run_reasoning_audit.py --sample-size 8` on Sundays only.
See [`scripts.md`](scripts.md) for exactly what each of those does, its
real cost, and which other scripts are recommended for a periodic (not
daily) cadence but not yet wired into this entrypoint. The manual
flag-by-flag sequence below is what `run_daily.py` runs under the hood —
use it directly only if you want a subset of the pipeline or need to
diagnose a step in isolation.

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
| `--with-assessment` | 3d's multi-model current-market assessment (Claude/OpenAI/Gemini, one call per model per candidate) over the latest `TOP_CANDIDATES`. | **$0.4115 for 10 candidates**, live-verified (claude $0.1313, openai $0.1292, gemini $0.1510) — see [`history.md`](history.md)'s Phase 3d section. Scales with candidate count. | Reads 3b's latest `TOP_CANDIDATES` — a `--with-screening` run must have happened at some point before this (same command or earlier). |
| `--with-adversarial` | 3f's bull → bear → scenario adversarial research cycle over the latest `TOP_CANDIDATES`. | **$0.2366 for 10 candidates**, live-verified (bull $0.0515, bear $0.0911, scenario $0.0940) — see [`history.md`](history.md)'s Phase 3f section. | Its own `--help` text: **requires a prior `--with-assessment` run** (reads `model_market_assessments`). |
| `--with-judge` | 3e's Judge (synthesizes 3b/3c/3d/3f/3i/Phase-2 evidence into one decision per candidate) → Risk Engine (deterministic sizing/gating) → Portfolio Construction, sized against real `holdings_ledger` ground truth (Phase 5a). | **$0.2133–$0.2407 for 10 decisions**, two independent live-measured figures from real runs today (`RUN-20260906-080647` and `RUN-20260906-114219`) — see [`history.md`](history.md)'s Phase 3e and Phase 5a sections. Full pipeline (assessment + adversarial + Judge combined) ≈ **$0.80/run**, comfortably inside `MAX_DAILY_LLM_COST=12`/`MAX_MONTHLY_LLM_COST=30` even at several runs/day. | Its own `--help` text: **requires a prior `--with-assessment` run**. Also reads `adversarial_research` and `llm_analyses` if present — both degrade gracefully to empty/`None` when absent, so it works without them, just with a narrower evidence base. |
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
value of `X_API_KEY` from your `.env` into the dashboard's key field
and click "Save key" (stored in that browser's `localStorage` only, per
the documented localhost/personal-machine deployment scope). The same
header is required for direct API calls, e.g.
`curl -H "X-API-Key: $X_API_KEY" http://127.0.0.1:8000/holdings`.
