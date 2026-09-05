# Crypto AI Portfolio

Modular, auditable AI-driven crypto portfolio management system. **Paper trading only** —
no exchange credentials or live orders exist yet.

## Vision

The long-term goal is a full-fledged AI crypto research and advisory system: broad
market screening across an open universe (not a fixed coin list), multi-source
evidence collection (exchange-native market data, derivatives positioning,
options skew, on-chain/DeFi flows, liquidations, news, macro, independent
analysts), a deterministic market-regime classification, multi-model
independent assessment (including, optionally, xAI's Grok alongside Claude/
GPT/Gemini), adversarial (bull/bear) research, and a deterministic Judge +
Risk Engine that turns all of this into paper-only recommendations — sized
with volatility/correlation awareness, traced and versioned via optional
Langfuse instrumentation, tracked against realized outcomes over time, and
including the ability to say "no trade" when evidence is weak or
contradictory. Further out, a read/query API (FastAPI) exposes this to a
dashboard, and — only once the recommendation pipeline is proven out — a
bounded, tool-restricted execution agent handles actual order placement on a
testnet exchange.

This is a deliberate, large expansion beyond the original Phase 1/2 scope. It
is being built **in verified sub-phases**, not as one monolithic phase,
because:
- several data sources have unknown/unofficial API availability and must be
  validated for real before any code assumes they exist — **official,
  documented sources are prioritized ahead of fragile/unofficial ones**,
- every new signal source is also a new API/LLM cost center, and costs must
  stay bounded by `CostGuard` at every step, not just at the end,
- a system that gives financial-style recommendations needs its accuracy to
  be *measurable and continuously tracked* (calibration against realized
  outcomes) from the start, not bolted on at the very end,
- the recommendation pipeline (Judge/Risk/Portfolio) is deliberately kept
  deterministic and non-agentic; agentic behavior is reserved for a later,
  clearly scoped execution layer where it's actually needed, not introduced
  wherever a task involves an LLM.

- ✅ **Phase 1 — Foundation**: project structure, configuration, Supabase schema
  (`assets`, `market_snapshots`), CoinGecko market-data collector. Complete and
  verified against a live Supabase project.
- ✅ **Phase 2 — Multi-model AI**: RSS news collection + relevance matching,
  OpenRouter integration (Claude, OpenAI, Gemini), structured/validated LLM
  output, cost tracking with daily/monthly caps. Complete and verified with
  live LLM calls against a real Supabase project.
- ⬜ **Phase 3 — Broad intelligence, discovery & judgment** (see
  `PHASE3A_PROMPT.md` through `PHASE3F_PROMPT.md`, one per sub-phase),
  split into verified sub-phases:
  - **3a** — Candidate/universe status schema, evidence provenance + numeric
    freshness-decay convention, `signal_sources` registry, and schema
    groundwork for market-regime snapshots, a decision-outcome ledger, and
    prompt/template versioning (all populated in later sub-phases)
  - **3b** — CoinMarketCap + **Coinbase** + **Binance** exchange-native data,
    deterministic market screening, candidate discovery, and a **deterministic
    market-regime classifier** computed once per run
  - **3c** — Official derivatives & on-chain sources: **Binance funding
    rates**, **Deribit options** (implied volatility, put/call skew),
    **Etherscan/DefiLlama** on-chain & DeFi TVL flows — all documented APIs,
    zero LLM cost
  - **3d** — Multi-model current market assessment (separate from
    `llm_analyses`), now with consistent regime/derivatives/on-chain context,
    prompt-template versioning, an optional **Grok (xAI)** model in the
    OpenRouter model set, and optional **Langfuse** call tracing
  - **3e** — Deterministic Judge, Risk Engine (volatility/correlation-aware
    sizing), Portfolio Construction, and a **continuous decision-outcome
    ledger** for ongoing calibration (plus a baseline backtest against
    existing Phase 1/2 data)
  - **3f** — Adversarial bull/bear research, scenario modeling, macro matrix,
    and the remaining exploratory/fragile sources (CoinAnk, CoinGlass
    liquidation heatmap, CryptoBubbles, PlanB/X — the latter accessed via
    **xAI's API**, which has native X/Twitter search) — each gated on a real
    access-feasibility check; re-run calibration afterward to check whether
    they actually improved accuracy
- ⬜ Phase 4 — Paper trading execution, benchmarks, ongoing accuracy tracking
- ⬜ Phase 5 — Dashboard, scheduling, and a **FastAPI** read/query layer over
  the Evidence Store (candidates, assessments, Judge decisions, portfolio
  state, cost reports)
- ⬜ Phase 6 — Exchange integration (testnet only): a bounded **execution
  agent** (LangChain/LangGraph) that turns Portfolio Construction's approved
  target changes into actual (testnet) orders — the only agentic component
  in the system, scoped to an explicit, allow-listed toolset, with Risk
  Engine constraints re-checked at execution time

Each sub-phase is implemented, verified against the live Supabase project, and
reviewed before the next begins — same methodology as Phase 1 and 2 (see
"Development methodology" below). `pytest` must keep passing without live
credentials at every step; any source that turns out to have no reliable
programmatic access is recorded as `UNAVAILABLE`/`NOT_IMPLEMENTED` in
`signal_sources` rather than silently skipped or faked.

## Architecture

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                              EXTERNAL DATA SOURCES                              │
└────────────────────────────────────────────────────────────────────────────────┘
        │              │              │              │              │
        ▼              ▼              ▼              ▼              ▼
   CoinGecko      CoinMarketCap   Coinbase        Binance        Deribit
   (Phase 1)      (3b)            (3b)            (3b, 3c)       (3c)
   aggregated     aggregated      exchange-       exchange-      options IV,
   price/mcap     price/mcap      native trade    native funding put/call skew
                                  price, spread    rate, price
        │              │              │              │              │
        │              │              │              │              ▼
        │              │              │              │         ┌─────────┐
        │              │              │              │         │  xAI /  │
        │              │              │              │         │  Grok   │──┐
        │              │              │              │         └─────────┘  │
        │              │              │              │      (3d model +     │
        │              │              │              │       3f PlanB/X)    │
        ▼              ▼                                                     │
   Etherscan      DefiLlama       RSS News        CoinAnk*      CoinGlass*   │
   (3c)           (3c)            (Phase 2)       (3f)          (3f)         │
   on-chain flow  TVL/DeFi        CoinDesk,       long/short    liquidation   │
   proxies        rotation        CoinTelegraph,  ratio         heatmap       │
                                  Decrypt                                     │
                                                        CryptoBubbles* (3f)    │
                                                        market-cap bubbles     │
                                                                               │
   (* = fragile/unofficial, feasibility-gated in 3f)                         │
        │              │              │              │              │        │
        └──────┬───────┴──────┬───────┴──────┬───────┴──────┬───────┴────────┘
               ▼               ▼              ▼              ▼
        ┌──────────────────────────────────────────────────────────┐
        │              PROVIDER / INGESTION LAYER                  │
        │   app/market_data · app/news · per-source 3c/3f modules  │
        │   - normalizes each response to the evidence-provenance  │
        │     shape (source, scope, timestamps, decay_half_life)   │
        │   - never fabricates missing data → UNAVAILABLE/UNKNOWN  │
        └───────────────────────────┬────────────────────────────┘
                                     ▼
        ┌──────────────────────────────────────────────────────────┐
        │             EVIDENCE STORE — Supabase / Postgres          │
        ├──────────────────────────────────────────────────────────┤
        │ assets · market_snapshots · news · signal_sources ·        │
        │ model_market_assessments · market_regime_snapshots ·       │
        │ decision_outcomes · prompt_templates · llm_analyses        │
        │ (JSONB columns: payload, key_drivers, source_assessment)   │
        └───────────────────────────┬────────────────────────────┘
                                     ▼
        ┌──────────────────────────────────────────────────────────┐
        │      SCREENING & REGIME CLASSIFICATION (3b)                │
        │      pure Python, zero LLM cost                            │
        └───────────────────────────┬────────────────────────────┘
                                     ▼
        ┌──────────────────────────────────────────────────────────┐
        │              MULTI-MODEL ASSESSMENT (3d)                   │
        └───────────────────────────┬────────────────────────────┘
                                     │
                    ┌────────────────┼────────────────┬──────────────┐
                    ▼                ▼                ▼              ▼
              OpenRouter        OpenRouter        OpenRouter    OpenRouter
              → Claude          → GPT             → Gemini      → Grok (opt.)
                    │                │                │              │
                    └────────────────┴────────────────┴──────────────┘
                                     │
                        ┌────────────┴────────────┐
                        ▼                          ▼
                   CostGuard                  Langfuse (optional)
                   (hard spend cap,            trace prompt/response/
                   checked pre-call)           cost/latency, versioned
                                                against prompt_templates
                                     │
                                     ▼
        ┌──────────────────────────────────────────────────────────┐
        │            ADVERSARIAL RESEARCH (3f)                        │
        └───────────────────────────┬────────────────────────────┘
                    │                │                │
                    ▼                ▼                ▼
              Bull research    Bear research    Scenario modeling
              (OpenRouter LLM  (OpenRouter LLM  (OpenRouter LLM,
              call, CostGuard) rebuts bull,     bull/base/bear per
                                CostGuard)       candidate, CostGuard)
                    │                │                │
                    └────────────────┼────────────────┘
                                     ▼
                              Macro evidence matrix
                              (ADP, CPI, PCE, DXY, yields —
                              manual/API feed, no LLM cost to collect)
                                     │
                                     ▼
        ┌──────────────────────────────────────────────────────────┐
        │      JUDGE (3e) — single structured OpenRouter call        │
        │      wrapped in deterministic weighing logic;              │
        │      gated by CostGuard, versioned via prompt_templates    │
        └───────────────────────────┬────────────────────────────┘
                                     ▼
        ┌──────────────────────────────────────────────────────────┐
        │      RISK ENGINE (3e) — deterministic Python, no LLM       │
        ├──────────────────────────────────────────────────────────┤
        │ env-configured caps: MAX_SINGLE_ASSET_ALLOCATION,           │
        │ MAX_NEW_POSITION_SIZE, MAX_WEEKLY_TURNOVER,                 │
        │ MIN_BUY/REBALANCE/SELL_CONFIDENCE                           │
        │        │                              │                    │
        │        ▼                              ▼                    │
        │  volatility-adjusted sizing     correlation-matrix check    │
        │  (inverse-vol / capped Kelly,   (flags concentrated,        │
        │  from 3b screening factors)     co-moving exposure)         │
        └───────────────────────────┬────────────────────────────┘
                                     ▼
        ┌──────────────────────────────────────────────────────────┐
        │       PORTFOLIO CONSTRUCTION (3e) — deterministic Python    │
        │       replacement logic vs. risk_adjusted_alpha threshold   │
        └───────────────────────────┬────────────────────────────┘
                                     ▼
        ┌──────────────────────────────────────────────────────────┐
        │   DECISION-OUTCOME LEDGER (3e/3f)                            │
        │   decision_outcomes table + scheduled/manual evaluation      │
        │   step, backfilled from market_snapshots (triple-barrier-    │
        │   style HIT_TARGET/HIT_STOP/TIMED_OUT)                       │
        └───────────────────────────┬────────────────────────────┘
                                     ▼
        ┌──────────────────────────────────────────────────────────┐
        │   PAPER TRADING EXECUTION (Phase 4)                          │
        │   simulated fills, fees, slippage — no live exchange         │
        └───────────────────────────┬────────────────────────────┘
                                     ▼
        ┌──────────────────────────────────────────────────────────┐
        │   EXCHANGE EXECUTION AGENT (Phase 6, testnet only)           │
        ├──────────────────────────────────────────────────────────┤
        │   LangChain/LangGraph agent                                  │
        │        │                                                     │
        │        ▼                                                     │
        │   allow-listed tools: place_order · cancel_order ·            │
        │   check_balance  →  Testnet/Sandbox exchange API              │
        │   (Risk Engine re-checked at execution time)                  │
        └──────────────────────────────────────────────────────────┘

  Cross-cutting, reads from the Evidence Store (does not write decisions):
     FastAPI (Phase 5) ── read/query API ──▶ Dashboard (Phase 5)
```

### Component purposes

| Component | Introduced | Purpose |
|---|---|---|
| **Provider/ingestion layer** (`app/market_data`, `app/news`, future per-source modules) | Phase 1–3c | Talks to each external API/feed, normalizes its response into the shared evidence-provenance shape, and tags freshness/status — the only layer allowed to touch a raw external API. |
| **Evidence Store** (Supabase/Postgres) | Phase 1 | Single source of truth for every observation, model output, and decision. Relational, so backtesting and the decision-outcome ledger can join across tables by asset/time; JSONB columns give document-like flexibility for nested, source-specific fields without needing a second database. |
| **Screening & regime classification** (3b) | 3b | Deterministic, no-LLM factor computation that ranks/filters the open asset universe into candidates, and classifies one shared market regime per run so every downstream stage sees the same label instead of inferring its own. |
| **Multi-model assessment** (`app/llm`, 3d) | Phase 2 / 3d | Sends each candidate's evidence to multiple independent LLMs (Claude, GPT, Gemini, optionally Grok) via OpenRouter, validates strict JSON output, and persists each model's standalone view plus a computed `model_agreement` — evidence, not a decision. |
| **Adversarial research** (3f) | 3f | Generates an explicitly opposing bull case and bear case per serious candidate, plus scenario modeling and a macro evidence matrix — additional evidence layers for the Judge, not decisions themselves. |
| **Judge** (`app/judge`, 3e) | 3e | Synthesizes every evidence layer above into one structured recommendation per asset, with confidence explicitly decoupled from model/source agreement, and a `NO_TRADE` outcome always available. |
| **Risk Engine** (`app/risk`, 3e) | 3e | Deterministic, non-negotiable position-sizing and exposure limits (volatility-adjusted sizing, correlation-concentration checks, hard caps) that the Judge's output cannot override. |
| **Portfolio Construction** (`app/portfolio`, 3e) | 3e | Turns Risk-Engine-adjusted Judge output plus current holdings/watchlist into concrete increase/hold/reduce/remove/initiate decisions, never forcing full capital deployment. |
| **Decision-outcome ledger** (3e/3f) | 3e | Records every decision with a resolution horizon and backfills realized returns, giving the system a continuously-updated, ground-truth accuracy measure instead of a one-off backtest. |
| **CostGuard** (`app/llm/cost.py`) | Phase 2 | Cross-cutting spend cap checked before every LLM call from any stage; skips (not crashes) once a cap is hit. |
| **Langfuse (optional)** | 3d onward | Cross-cutting, additive tracing of LLM calls (prompt, response, cost, latency) for debugging and comparing prompt versions from `prompt_templates` against real outcomes. Never a dependency of the decision pipeline — Supabase remains authoritative. |
| **Paper Trading Execution** (`app/trading`) | Phase 4 | Simulates fills for Portfolio Construction's target changes without touching any real exchange. |
| **FastAPI + Dashboard** | Phase 5 | Read/query API over the Evidence Store (candidates, assessments, decisions, portfolio state, cost reports) for a UI; Pydantic-native, so it reuses the same schemas already defined for Phase 2/3 rather than duplicating them. |
| **Exchange Execution Agent** (LangChain/LangGraph) | Phase 6 | The only agentic component in the system. Given Portfolio Construction's already-approved target changes (not open-ended instructions) and a small, explicit, allow-listed toolset (place order, cancel order, check balance) against a **testnet** exchange API. Risk Engine constraints are re-checked at execution time; live trading remains gated behind a separate, explicit safety review per the project's development methodology. |

## Technology stack decisions

Recorded here so the reasoning behind each choice — including the ones
deliberately *not* adopted — doesn't get lost as the project grows.

- **FastAPI — adopted, Phase 5 only.** Pydantic-native, which matches this
  project's validation-heavy style throughout Phase 2/3 (strict schemas for
  LLM output, Judge output, etc.), so a future API layer can reuse those
  models almost directly. Not introduced earlier because nothing outside the
  CLI run needs to call this system until there's a dashboard to serve.
- **xAI (Grok) — adopted, in two places.** (1) As an optional fourth model in
  `OPENROUTER_ASSESSMENT_MODELS` for 3d, routed through OpenRouter like the
  other three, under the same `CostGuard`/schema rules — no special-cased
  integration. (2) As the access mechanism for the PlanB/X source in 3f,
  since Grok has native X/Twitter search and that's a more realistic path
  than unofficial scraping. Both uses still require the same real
  feasibility/cost verification as any other source before being relied on.
- **MongoDB — not adopted.** The evidence-provenance design already gets
  document-like flexibility from Postgres/Supabase's JSONB columns
  (`payload`, `key_drivers`, `source_assessment`, etc.) without giving up
  relational integrity — and that relational integrity is exactly what the
  decision-outcome ledger and calibration backtests depend on (joining
  `market_snapshots` ⋈ `model_market_assessments` ⋈ `decision_outcomes` ⋈
  `assets` by timestamp and asset). A second database would mean a second
  source of truth and duplicated infra/auth for no corresponding benefit
  here.
- **LangChain/LangGraph — adopted, Phase 6 only.** Every stage through
  Phase 3/4/5 is a fixed, deterministic pipeline with structured JSON in and
  out — there's no agent decision-making involved, so an agent framework
  would mean rewriting working code to fit someone else's abstraction for no
  benefit. Phase 6 is different: interacting with a live/testnet exchange API
  to place, monitor, and potentially adjust orders is exactly the bounded,
  tool-using loop an agent framework is built for. When that phase starts,
  the agent's toolset is explicitly allow-listed (place order, cancel order,
  check balance — not arbitrary API access), its task input is Portfolio
  Construction's already-approved target change (not an open-ended
  instruction), and Risk Engine constraints are re-checked at execution
  time, not just at recommendation time.
- **Langfuse — adopted, optional starting 3d.** Complements, not replaces,
  the manual prompt-versioning (`prompt_templates`) and cost tracking
  (`CostGuard`, `estimated_cost` columns) already designed into Phase 3 —
  it adds a UI for tracing individual calls and comparing prompt versions
  once there's enough call volume and outcome data (from 3e's
  decision-outcome ledger) to make that comparison meaningful. Strictly
  additive instrumentation: the decision pipeline must run identically
  whether or not Langfuse is configured.

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
  database/      Supabase client + repositories (assets, market_snapshots, news, llm_analyses, and Phase 3 tables)
  market_data/   CoinGecko client, normalization, collection service; extended in 3b with CoinMarketCap/Coinbase/Binance and screening/regime classification
  news/          RSS collection, relevance matching, dedup (Phase 2)
  llm/           OpenRouter integration, structured output, cost guard (Phase 2); extended in 3d with the current-market-assessment stage (optional Grok, optional Langfuse tracing)
  judge/         Phase 3e — deterministic decision synthesis
  portfolio/     Phase 3e — portfolio construction
  risk/          Phase 3e — deterministic risk engine
  trading/       Phase 4 — paper trading execution; Phase 6 — testnet execution agent (LangChain/LangGraph)
  benchmarks/    Phase 4 — performance tracking; decision-outcome calibration (3e/3f)
  api/           Phase 5 — FastAPI read/query layer (not yet created)
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

Starting with Phase 3, this also applies *within* a phase: Phase 3 is large
enough that it is split into sub-phases (3a–3f), each with its own live
verification and cost check, rather than implemented as one block. Rules that
carry across every sub-phase:

- **Official, documented sources come before fragile/unofficial ones.**
  Coinbase, Binance, Deribit, Etherscan, and DefiLlama all have real,
  documented, free-or-cheap APIs and are built in 3b/3c. CryptoBubbles,
  CoinAnk, and PlanB/X have unclear or unofficial access and are deliberately
  built last (3f), gated on a real feasibility check each time.
- **No new external source is assumed reliable until checked.** Programmatic
  access is verified for real before code is written against it; sources that
  turn out to be unavailable are recorded as such (`signal_sources` table),
  not faked or silently dropped.
- **No new evidence source ships without a cost estimate** against
  `MAX_DAILY_LLM_COST` / `MAX_MONTHLY_LLM_COST`. Any sub-phase that adds LLM
  calls (3d, 3f) estimates calls/day and cost/day before merging. Market-data
  sources (3b, 3c) have no LLM cost but should still be checked against
  provider rate limits.
- **Predictions are tracked against reality, continuously.** Starting in 3e,
  every Judge decision is recorded in a decision-outcome ledger and later
  backfilled with realized returns, so the system's own accuracy — not just
  its internal model agreement — is measurable and improves the design over
  time rather than being assessed once at the end.
- **New tooling earns its place by matching a real need, not by being
  available.** FastAPI, xAI, LangChain/LangGraph, and Langfuse are each
  adopted for a specific, scoped reason (see "Technology stack decisions"
  above) and introduced only in the phase where that reason applies —
  MongoDB was considered and deliberately not adopted, for the same kind of
  reasoning.
