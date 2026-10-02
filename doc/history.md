# Build history — Phase 2 through Phase 5d

Full per-phase build log: what was built, real live-verified findings,
known limitations and decisions, for every phase from Phase 2 onward.
Phase 1 is covered in the top-level README/Vision roadmap. This file is
the detailed historical record — nothing here is rewritten or deleted as
the system evolves, only appended to; for the current end-state
architecture see [`architecture.md`](architecture.md), for the current
decision log see [`decisions.md`](decisions.md), and for what's still open
see [`todo.md`](todo.md). See [`../README.md`](../README.md) for the
current overall status.

(Renamed from `phases.md` on 2026-09-16, no content changed by the rename
itself — see git history for the file's full history under its old name.)

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

**Cost control**: `CostGuard` checks cumulative spend against
`MAX_DAILY_LLM_COST`/`MAX_MONTHLY_LLM_COST` before every provider call,
skipping (not crashing) once a cap is hit. As of Phase 3a, the sum is computed
by `CostLedgerRepository` across every table registered in
`COST_TRACKED_TABLES` (`app/llm/cost.py`) — today just `llm_analyses`, but any
future sub-phase adding a new LLM-call-persisting table (3d, 3e, 3f, 3g)
registers it there rather than CostGuard silently missing that spend. The
pricing table in `app/llm/cost.py` is a point-in-time snapshot of OpenRouter
pricing — re-check https://openrouter.ai/models periodically, especially
after changing `CLAUDE_MODEL`/`OPENAI_MODEL`/`GEMINI_MODEL`.

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

## Phase 3a — Universe/candidate schema, evidence provenance, registries

`migrations/0003_phase3a_universe_provenance.sql` adds, empty and ready for
later sub-phases (no new external API calls, no new LLM calls, no behavior
change to any Phase 1/2 code path):

- **`asset_status_history`** — an append-only record of `HELD`/`WATCHLIST`/
  `CANDIDATE`/`REJECTED` transitions per asset, independent of
  `assets.active`/`assets.in_asset`. Seeded from the current `in_asset` flag
  (`true` → `HELD`, `false` → `WATCHLIST`) so it isn't empty for existing
  assets. Read/write via `AssetStatusRepository`
  (`app/database/repository.py`).
- **`signal_sources`** — a registry of every evidence source in the Phase 3
  vision (`app/database/models.py`'s `SignalSource`, read via
  `SignalSourceRepository`). CoinGecko and News are seeded `OK` (already
  implemented); everything else — CoinMarketCap, Coinbase, Binance, Deribit,
  Etherscan, DefiLlama, CoinAnk, CoinGlass, CryptoBubbles, PlanB, Macro, and
  the longer list of 3c/3f/3i-specific sources — is seeded `NOT_IMPLEMENTED`.
- **`market_regime_snapshots`**, **`judge_decisions`**, **`decision_outcomes`**,
  **`prompt_templates`**, **`calibration_runs`** — schema only, populated
  starting in 3b (regime snapshots), 3d (prompt templates), and 3e (Judge
  decisions, decision outcomes, calibration runs).
- **Evidence provenance convention** (`app/database/evidence_provenance.py`):
  the shared column shape (`source`, `scope`, three timestamps, `timeframe`,
  `freshness` + numeric `decay_half_life_hours`, `status`, `payload`) every
  future evidence-source table composes, plus `is_revision_of` for
  point-in-time integrity — a correction is a new linked row, never an
  `UPDATE` overwriting what was originally retrieved — and a
  `latest_value_as_of()` helper implementing the "value as known at time T"
  query convention so 3b/3c/3f don't each invent their own.
- **`DecisionValue`** (`app/judge/decisions.py`): `BUY`/`HOLD`/`SELL`/`WATCH`/
  `NO_TRADE` as a forward-looking placeholder for 3e's Judge — no
  decision-making logic yet. Deliberately separate from Phase 2's live
  `Action` type (`app/llm/schemas.py`, `BUY`/`HOLD`/`SELL` only), which stays
  untouched. `judge_decisions.decision` enforces this same vocabulary at the
  database level via a `CHECK` constraint.
- **`COST_TRACKED_TABLES`** (`app/llm/cost.py`): the CostGuard-extension
  registry — every LLM-call-persisting table gets an `estimated_cost` column
  and an entry here (table name → its timestamp column, since they aren't
  all named the same — `llm_analyses.timestamp` vs. `judge_decisions.created_at`).
  `CostLedgerRepository` sums across every registered table; `CostGuard`
  itself is unchanged (still just calls `.get_cost_sum_since(...)` on
  whatever it's given), so this was a zero-behavior-change refactor verified
  by the full pre-existing Phase 2 test suite passing unmodified.

**Known limitations / decisions** (locked before implementation — see
`prompts/PHASE3_LOCKED_DECISIONS.md` for the full reasoning):
- **History table over a status column** — chosen so status transitions
  stay auditable once 3b's candidate discovery starts moving assets between
  states; cheap to add now, expensive to retrofit once 3b–3g are writing
  against a fixed schema.
- **`judge_decisions` named now, in 3a** — `decision_outcomes.decision_id`
  needed a real FK target; without this, 3e would have had to invent (and
  migrate for) the table mid-implementation.
- **Initial `decay_half_life_hours` values** are starting estimates, not
  measured: `coingecko_price` ≈ 2h, `news` ≈ 18h, `macro` ≈ 720h (~30 days,
  "until superseded"). Refine per-source as 3b/3c/3f actually build against
  real data behavior.
- **`market_regime_snapshots.regime` and `calibration_runs.method`** are left
  as free text, not `CHECK`-constrained enums — 3b/3g define the actual
  label/method sets and may need to refine them without another migration.
- **Smart-contract/scam-safety screening** (honeypot/rug-pull checks on
  newly-discovered 3b candidates) was identified as a real gap against
  professional screening practice, flagged for an explicit decision once 3b
  started. Resolved: **out of scope for 3b** — `doc/prompts/PHASE3B_PROMPT.md`'s actual
  task list doesn't call for it, and it wasn't invented back in as scope
  creep. Still a real gap; a natural fit for 3c (already adding new
  providers) or a dedicated future check, not built here.

## Phase 3b — CoinMarketCap, Coinbase, Binance, screening, regime classification

`python -m app.main --with-screening` adds, after market data collection:

1. **CoinMarketCap** (optional, gated behind `COINMARKETCAP_API_KEY`) —
   aggregated market data, kept fully independent from CoinGecko (never
   merged), used both as a cross-check and as the source for 90d
   percent-change (needed for the altcoin-season index below — CoinGecko
   doesn't offer a 90d window). Endpoint/auth shape verified live (a 401
   with CMC's documented error code); the response shape itself has **not**
   been end-to-end verified against a real key as of this writing — verify
   once you add one.
2. **Coinbase** (`app/market_data/coinbase.py`) — public Exchange API, no key
   needed. Verified live: covers all 16 assets in the current universe
   (837 total USD products) with 200+ days of daily history.
3. **Binance** (`app/market_data/binance.py`) — public REST API, no key
   needed. Verified live: 14 sequential historical-data calls completed in
   3.7s with zero rate-limiting — this is why it's the **primary** source
   for volatility/drawdown (which need a real return series, not just a
   point-in-time percent change), not CoinGecko. Two of the current 16
   assets (HYPE, STORJ) have no Binance USDT pair — Coinbase is the
   **fallback** for those; `UNAVAILABLE` only if neither venue lists the
   asset.
   - **CoinGecko demo API key added and live-verified (2026-09-06,
     documentation pass) — does not change this decision.** A real
     `COINGECKO_API_KEY` demo-tier key was added to `.env`; the existing
     `CoinGeckoClient` already sends it as `x-cg-demo-api-key` whenever
     configured (no code change needed). Directly measured against the
     same per-asset historical endpoint (`/coins/{id}/market_chart`) this
     finding is about: **unauthenticated, 5 rapid calls succeeded then the
     6th–8th returned `429`** (reproducing the original finding exactly);
     **with the demo key, 40 rapid calls across 40 distinct real coins all
     succeeded** (the one non-200 was a 404 for an invalid coin id, not a
     rate limit), and a clean 10-call batch completed in **2.41s** —
     throughput now comparable to Binance's own 14-calls-in-3.7s figure
     above. No rate-limit-remaining headers are exposed by CoinGecko's API
     to confirm the exact ceiling, and the demo tier's monthly call cap
     was **not** tested live (would mean deliberately burning real quota
     for no operational benefit) — burst-rate-limiting specifically is
     confirmed resolved, monthly-cap behavior is not. This is a real,
     material change to the constraint this decision was originally based
     on; **see "Open / deferred work" for the resulting open decision** —
     nothing is switched over based on this finding alone.
4. **Screening universe** (`SCREENING_UNIVERSE_SIZE`, default 30) — the top
   N assets by CoinGecko market cap (stablecoins excluded via a documented
   symbol denylist, `app/market_data/stablecoins.py`), not just the 16
   currently tracked — this is where genuinely new candidates get
   discovered.
5. **Deterministic factors** (`app/market_data/factors.py`, pure functions,
   fully unit-tested without live APIs): momentum (7d/30d, direct from
   CoinGecko/CMC point returns), volatility (stdev of daily returns) and max
   drawdown (both from Binance/Coinbase daily closes), relative strength
   (vs. BTC's own 30d momentum), and liquidity (24h volume).
6. **Composite factor score** — a documented, rank-based (not raw-value)
   combination, so factors with very different natural scales (% vs.
   dollars) combine safely: `momentum_30d` 30%, `momentum_7d` 15%,
   `relative_strength_30d` 20%, `volatility_30d` 15% (inverted — lower
   ranks higher), `drawdown_30d` 10% (inverted — shallower ranks higher),
   `volume_24h` 10%. A missing factor for one asset has its weight
   redistributed across that asset's other factors rather than being
   treated as zero/neutral. Purely quantitative — stays visible alongside,
   never blended into, LLM/Judge evidence later.
7. **Anomaly/wash-trading flag** (`app/market_data/anomaly.py`) — flags (never
   excludes) an asset whose latest-day price move exceeds 50% or whose
   latest-day volume is a >3σ outlier vs. its own trailing history.
8. **Market-regime classification** (`app/market_data/regime.py`) — one
   `market_regime_snapshots` row per run: `RISK_ON`/`RISK_OFF`/`NEUTRAL` from
   BTC's price vs. its own 7d/30d moving averages plus universe breadth (%
   with positive 30d momentum); **BTC dominance** (BTC's share of screened
   market cap); an **altcoin-season index** (% of non-stablecoin assets
   outperforming BTC over 90d — `UNAVAILABLE` without a CoinMarketCap key);
   and **halving-cycle day-counts** (days since/until the nearest halving).

**Known limitations / decisions:**
- **Halving cycle is a calendar-based approximation, not live block
  height.** None of CoinGecko/CoinMarketCap/Coinbase/Binance expose current
  BTC block height (verified live — they're trading/aggregation APIs, not
  block explorers). The past halving date (2024-04-20) is a public,
  unchanging historical fact; the next is estimated as +1458 days (~210,000
  blocks at Bitcoin's ~10-minute target). Raw day-counts only, no
  cycle-phase interpretation — that's for the Judge (3e) or later scenario
  research (3f).
- **`signal_sources.enabled` is informational only for CoinMarketCap/
  Coinbase/Binance** — the screening service doesn't yet gate on it before
  attempting a source (only `status`/`last_checked_at` get updated per run).
  An operator toggle here would need real gating logic added later.
- **`SCREENING_UNIVERSE_SIZE` defaults to 30, not 50** — a directly verified
  constraint (CoinGecko's per-asset historical endpoint rate-limits after
  ~5 rapid calls on the *unauthenticated* free tier), not a guess. This
  only matters for historical calls the service *doesn't* make from
  CoinGecko (it uses Binance/Coinbase for those instead) — the constraint
  is about overall per-run call volume and runtime across every source
  combined. **Update (2026-09-06): a demo API key materially raises this
  specific limit** — see the CoinGecko finding under Binance's
  primary-source decision above, and the resulting open question in
  "Open / deferred work" — this default was not changed on that basis
  alone.
- **CoinMarketCap's response shape is implemented per its documented API
  but not live-verified end-to-end** — no key was available while building
  this. Verify once `COINMARKETCAP_API_KEY` is set.

## Phase 3c — Derivatives, CME positioning, on-chain/DeFi, stablecoin supply

`python -m app.main --with-derivatives` collects, into one shared
`evidence_observations` table (see below), zero LLM cost:

1. **Binance funding rate + open interest** (`app/market_data/binance.py`,
   extended) — for every tracked asset with a Binance perpetual (18 of 21
   currently tracked; missing STORJ, BONK, WBT — verified live).
2. **Futures term structure / annualized carry yield** — Binance's and
   Deribit's dated (quarterly) futures vs. spot, for **BTC/ETH only**:
   verified live that neither venue lists dated futures for any other
   currently tracked asset (SOL, XRP, BNB, LINK, etc. all show zero dated
   contracts despite having perpetuals). Raw basis and the annualized
   carry-yield transformation are both stored.
3. **CME Commitment of Traders (COT) positioning** (`app/market_data/cftc.py`)
   — the CFTC's free, official "Traders in Financial Futures" report via
   their public Socrata API, for BTC and ETH (as `MICRO ETHER` — CME's actual
   contract name; there's no plain "ETHEREUM" listing). Categorized by
   Dealer/Asset Manager/Leveraged Money/Other Reportables, exactly as
   professional COT analysis expects. Stored with `freshness=STALE` by
   design — the report reflects the prior Tuesday's close, published
   Fridays; `decay_half_life_hours=84` (half the ~7-day publication cycle).
4. **Deribit options** (`app/market_data/deribit.py`) — implied volatility
   (near-dated, near-the-money) and aggregate put/call open-interest ratio,
   **BTC/ETH only** (verified live: every other currency shows zero option
   instruments on Deribit, despite some listing perpetuals there).
5. **Volatility risk premium (VRP)** (`app/market_data/derivatives_factors.py`)
   — Deribit's annualized implied vol minus 3b's realized 30d volatility
   (itself annualized to match scale) for the same asset. Only computed
   when both sides are genuinely available; a documented, testable pure
   function, not a new external source.
6. **DefiLlama TVL** (`app/market_data/defillama.py`) — protocol TVL +
   1d/7d change, matched to tracked assets by governance-token symbol
   (best-effort; ties broken by highest TVL). Fully free, no key.
7. **Stablecoin supply growth** — DefiLlama's dedicated stablecoins API
   directly exposes `circulating`/`circulatingPrevWeek`/`circulatingPrevMonth`,
   so 7d/30d growth needed no derived computation or new provider. Captured
   for the top 5 stablecoins by circulating supply, as `GLOBAL_CRYPTO`-scope
   evidence (`asset_id = null`) — a market-wide capital-flow proxy, not
   asset-specific.
8. **Etherscan large-transfer proxy** (`app/market_data/etherscan.py`,
   optional, gated behind `ETHERSCAN_API_KEY`) — counts native ETH transfers
   above a threshold to/from a small set of known exchange addresses in the
   last 24h, attributed to ETH's own evidence record.
9. **Glassnode** (`app/market_data/glassnode.py`, optional, gated behind
   `GLASSNODE_API_KEY`) — on-chain valuation-cycle metrics (MVRV/SOPR/NUPL/
   cohorts) and BTC miner metrics. Client built and ready; **not
   subscribed to** (see decisions below), reports `NOT_IMPLEMENTED`.

Every raw observation is stored as-is — funding rate, open interest, the
futures curve, IV, put/call ratio, VRP, and COT positioning are all
positioning/pricing facts, not directional signals; no BUY/SELL inference
happens at the collector level anywhere in this sub-phase (that's the
Judge's job in 3e, per every per-source interpretation constraint in
`doc/prompts/PHASE3C_PROMPT.md`).

**Signal sources confirmed genuinely inaccessible this round** (investigated
live, not guessed): **Spot ETF flows** — Farside has no real API, just a
Cloudflare-protected webpage; SoSoValue's API requires an authenticated
login not available here. **Token unlock schedules** — Messari requires a
key not available here (and its tier's unlock-data coverage is unconfirmed);
TokenUnlocks.app has no discoverable public API. **Prediction markets** —
Polymarket and Kalshi both fail DNS resolution from this specific
development sandbox (confirmed it's not a general connectivity issue), so
neither could be verified at all; both are `NOT_IMPLEMENTED` pending
verification from a network that can reach them. All three remain seeded
`NOT_IMPLEMENTED` from 3a — this sub-phase confirmed why, rather than
leaving it unexamined.

**Known limitations / decisions:**
- **One shared `evidence_observations` table, not one table per source.**
  3a's evidence-provenance shape was designed as a generic, reusable shape;
  with 7+ structurally similar new sources this sub-phase, one table with a
  `source` column and a `payload` JSONB is the generalization that shape was
  built for — `market_snapshots`/`news`/`screened_universe` stay dedicated
  tables because their columns are stable and well-known in advance, which
  isn't true of most of 3c's smaller, heterogeneous observations.
- **Glassnode/CryptoQuant deliberately not subscribed to.** MVRV/SOPR/NUPL/
  cohort data and BTC miner metrics are very likely behind a paid tier at
  either provider (confirmed both require an API key; free tiers are
  typically limited to basic price data) — a real recurring-dollar-cost
  decision, not a quick free signup like Etherscan/CoinMarketCap. Deferred
  rather than committed to without deliberate consideration.
- **Etherscan's large-transfer proxy is a narrower scope than full
  exchange-reserve tracking** — it counts transfers to/from two well-known
  public exchange addresses, not a comprehensive reserve-balance product,
  and has no entity-clustering behind it (conflates genuine whale activity
  with routine exchange-internal/protocol traffic — the same caveat
  `doc/prompts/PHASE3C_PROMPT.md` itself calls out). Recorded in the observation's own
  payload, not just this doc.
- **Stablecoin supply *velocity*** (transaction volume relative to
  circulating supply) **was not built** — DefiLlama's stablecoins endpoint
  exposes supply figures but no transfer-volume field, and computing it
  properly needs on-chain transfer aggregation beyond this sub-phase's
  scope. Supply *growth* (7d/30d) is captured; velocity is not.
- **Exchange reserve balances were not built** — same reasoning: a real
  reserve-tracking product needs a curated, maintained set of known
  exchange wallet addresses per asset, which is its own research effort
  beyond what a free/cheap tier reasonably supports right now.

## Phase 3d — Multi-model current market assessment (`--with-assessment`)

`python -m app.main --with-assessment` runs, on top of the latest
`--with-screening` run's `TOP_CANDIDATES` (requires at least one prior
screening run; warns and does nothing if none exists — no silent fallback to
a stale or arbitrary universe):

1. **One shared context per run** (`app/llm/assessment_context.py`) — every
   candidate's prompt carries the **same** `market_regime_snapshots` row (3b),
   so models reason from one consistent regime label rather than each
   inferring their own. Per-asset context adds: current price/volume/change
   (Phase 1), the deterministic `composite_factor_score` and any screening
   anomaly flag (3b), every derivatives/on-chain observation on record for
   that asset (3c), recent relevant news (Phase 2), and current portfolio
   status (3a).
2. **Sanity/bad-tick check** (task 6) — before context is built, each asset's
   recent stored snapshots are run through 3b's existing `detect_anomaly()`
   (reused, not reimplemented); a flagged asset gets an explicit "possible bad
   tick, treat with caution" warning injected into its prompt rather than
   being silently excluded or handed to the model uncaveated. Covered by
   dedicated unit tests (a synthetic price-spike case, an ordinary-data case,
   and an insufficient-history case) since real live data is not guaranteed
   to contain a bad tick on any given run.
3. **Three independent models via OpenRouter** (`app/llm/assessment_provider.py`)
   — Claude, OpenAI, and Gemini (Phase 2's existing three; see decisions
   below), one batched call per provider covering every candidate in the run,
   validated against a strict Pydantic schema
   (`app/llm/assessment_schemas.py`) with the same retry-once-on-invalid-JSON
   pattern as Phase 2. One provider failing never blocks the others.
4. **Model agreement** (`app/llm/assessment_agreement.py`) — the fraction of
   models agreeing with the majority `overall_assessment` direction, computed
   once per asset per run across all configured models, then denormalized
   onto every model's row for that asset/run. Verified live to be genuinely
   distinct from — and not derived from — any individual model's confidence:
   in the run below, BTC/BNB/SOL/HYPE/LINK/NEAR/XRP show `model_agreement=1.0`
   (unanimous), while ZEC/XMR/UNI show `model_agreement=0.667` (2-of-3 split),
   with each model's own confidence values still varying independently
   underneath (e.g. BTC's three models returned short-term confidence 0.5,
   0.6, and 0.62 despite unanimous agreement).
5. **Prompt-template versioning** (`app/database/repository.py`'s
   `PromptTemplateRepository`, `prompt_templates` table from 3a) — the
   rendered system prompt's hash and version are inserted (or reused, keyed
   on name+stage+version+hash) once per run, and every
   `model_market_assessments` row stores that row's id, not a copy of the
   prompt text.
6. **New table** `model_market_assessments` (migration `0006`) — one row per
   (run, asset, provider): short/medium/long-term direction + confidence,
   expected return at 7d/30d/90d, risk score/level, the shared market regime,
   model agreement, thesis, key drivers/risks, per-source assessment,
   invalidation conditions, and the raw response — **this asset's own slice**
   of the batch response, not the full multi-asset payload (same
   cost-hygiene fix applied to Phase 2's `LLMResearchService`).

**Live-verified** (queried Supabase directly, not just a passing test —
per the standing lesson from 3c that a clean-looking report can still hide a
real gap): a combined `--with-screening --with-derivatives --with-assessment`
run against the 10 real `TOP_CANDIDATES` of that run produced exactly 30
`model_market_assessments` rows (10 assets × 3 models), one shared
`prompt_templates` row referenced by every one of them, one shared
`market_regime` (`RISK_ON`) and `data_cutoff_timestamp` across all three
providers per asset, and the model-agreement split described above. Total
cost for that run: **$0.4115** (claude $0.1313, openai $0.1292, gemini
$0.1510) — confirmed via `CostGuard`'s cumulative-spend sum, which correctly
included both `llm_analyses` and `model_market_assessments` in the same 24h
window ($0.7207 combined that day). At 10 `TOP_CANDIDATES` and 3 models, this
stage costs ~$0.41/run regardless of candidate count changes within reason
(one batched call per provider, not per asset) — comfortably inside
`MAX_DAILY_LLM_COST=5.00` even at several runs/day; no schedule/cadence is
built yet (each `python -m app.main` invocation is a manual/on-demand run).

**Known limitations / decisions:**
- **Grok (xAI) deferred, not built.** `doc/prompts/PHASE3D_PROMPT.md` offered it as an
  optional fourth model; the explicit choice here was to keep this
  sub-phase's change isolated to the richer context (regime + 3c evidence +
  sanity check) rather than also changing the model set, so any behavior
  shift this round has one cause, not two confounded ones. Addable later via
  `OPENROUTER_ASSESSMENT_MODELS=claude:...,openai:...,gemini:...,grok:...`
  with zero code changes, once Claude/OpenAI/Gemini have a baseline to
  compare a fourth model against.
- **Langfuse tracing skipped.** Optional per the prompt; most valuable once
  there's real call volume and multiple prompt versions to A/B, which starts
  mattering from 3e's decision-outcome ledger onward, not now.
- **A parallel `OpenRouterAssessmentProvider`/`AssessmentProviderResult`
  class, not a generalized Phase 2 `OpenRouterProvider`.** Phase 2's provider
  is hardcoded to validate `AnalysisBatch`; generalizing it to also handle
  `AssessmentBatch` would mean changing an already-shipped, live-verified
  class's signature across every existing call site and test. Duplicating
  the retry/content-extraction/token-summing logic costs some repetition but
  carries zero regression risk to Phase 2 — a deliberate trade-off, not an
  oversight.
- **Assessment target is exactly 3b's latest `TOP_CANDIDATES`, nothing wider
  or narrower.** No silent fallback: if `--with-screening` has never been
  run, `--with-assessment` logs a warning and does nothing, rather than
  guessing a universe.

## Phase 3e — Judge, Risk Engine, Portfolio Construction, calibration (`--with-judge`, `--evaluate-outcomes`)

`python -m app.main --with-judge` runs, over the same latest `TOP_CANDIDATES`
3d assessed (requires a prior `--with-assessment` run; warns and does nothing
otherwise):

1. **Judge** (`app/judge/`) — one LLM call per run (single synthesizing
   model, not an ensemble — the ensemble already happened in 3d) reasoning
   over: 3b's screening factors + `composite_factor_score` + regime
   (including BTC dominance/altseason/halving-cycle position), 3c's
   derivatives/on-chain evidence (with `freshness`/`decay_half_life_hours`
   shown explicitly per source), 3d's model assessments + its computed
   `model_agreement`, Phase 2's prior `llm_analyses`, recent news, and
   current portfolio status/allocation. Outputs one structured decision per
   asset (`BUY`/`HOLD`/`SELL`/`WATCH`/`NO_TRADE`), persisted in full to
   `judge_decisions` (thesis, key/contradictory evidence, key risks,
   invalidation conditions, `estimated_cost`) — a new, parallel evidence
   type again duplicating Phase 2/3d's provider-class pattern
   (`OpenRouterJudgeProvider`) rather than generalizing either shipped class,
   same deliberate zero-regression trade-off as 3d's.
2. **Risk Engine** (`app/risk/`) — deterministic, AI-uninfluenced, over the
   Judge's *unconstrained* `target_allocation`:
   - A confidence gate (`MIN_BUY_CONFIDENCE`/`MIN_SELL_CONFIDENCE`/
     `MIN_REBALANCE_CONFIDENCE`) that can downgrade a low-confidence BUY to
     WATCH or a low-confidence SELL to HOLD before any sizing happens.
   - **Volatility-adjusted sizing**: an inverse-volatility scalar
     (`RISK_TARGET_VOLATILITY / asset_volatility`, capped at 1.0 — this only
     ever de-risks, never levers up) composed with an **agreement-aware**
     scalar (average of `model_agreement`/`source_agreement`, floored at
     0.3) — the two compose multiplicatively, neither alone determines size.
   - Hard caps: `MAX_SINGLE_ASSET_ALLOCATION`, `MAX_NEW_POSITION_SIZE` (new
     positions only), and `MAX_WEEKLY_TURNOVER` (scales every proposed
     change down proportionally, fairly, if the trailing 7-day budget would
     be exceeded — never picks winners).
   - A **correlation-concentration flag** (`app/risk/correlation.py`): a
     pairwise Pearson correlation matrix over held/candidate assets' actual
     stored `market_snapshots` returns, flagging (not blocking) pairs at/
     above `CORRELATION_FLAG_THRESHOLD` that are both being increased.
3. **Portfolio Construction** (`app/portfolio/`) — classifies each
   Risk-Engine-adjusted decision into INITIATE/INCREASE/HOLD/REDUCE/REMOVE/
   HOLD_CASH against the paper book's actual current state (new
   `portfolio_positions`/`portfolio_allocation_changes` tables — see
   decisions below), and applies a capacity-driven **replacement rule**:
   above `MAX_CONCURRENT_POSITIONS`, a new candidate may only bump an
   existing holding when its `risk_adjusted_alpha` (`expected_alpha /
   max(risk_score, 0.05)`) clears the incumbent's by
   `MIN_REPLACEMENT_ALPHA_ADVANTAGE`; otherwise the new candidate is simply
   blocked (stays at 0 allocation) rather than exceeding capacity.
4. **Continuous decision-outcome ledger** — every Judge decision opens one
   `decision_outcomes` row (3a schema) with a lightweight triple-barrier
   target/stop (`app/benchmarks/triple_barrier.py`: derived from the Judge's
   own `expected_return`/`risk_score`, a floor of ±5% so a near-zero
   `expected_return` still gets a workable barrier), `regime_at_decision`,
   `judge_confidence`, and `in_holdout_window = true` — see the held-out
   window note below. `python -m app.main --evaluate-outcomes` (independent
   of every other flag, zero LLM cost) walks forward through real subsequent
   `market_snapshots` and backfills `HIT_TARGET`/`HIT_STOP`/`TIMED_OUT`,
   leaving genuinely-too-recent decisions `UNRESOLVED`.
5. **Baseline calibration script** (`scripts/calibration_baseline.py`) —
   checks Phase 1/2's existing `llm_analyses` directional calls against
   actual subsequent `market_snapshots` price movement, reporting
   directional hit-rate AND a Brier score + confidence-bucket reliability
   breakdown (two different claims — see findings below). Persists every
   invocation to `calibration_runs` as a countable attempt, per task 5.

**Live-verified** (queried Supabase directly and cross-checked against the
real deterministic formulas, not just passing tests or clean-looking logs —
per the standing lesson from 3c):
- A combined `--with-screening --with-derivatives --with-assessment
  --with-judge` run persisted exactly 10 `judge_decisions` rows (one per
  `TOP_CANDIDATE`) and 10 matching `decision_outcomes` rows, each correctly
  referencing its `judge_decisions.id`, `regime_at_decision`, and
  `judge_confidence`, all with `in_holdout_window = true`.
- Reachable decisions confirmed live: `BUY`, `HOLD`, and `WATCH` all occurred
  across three runs (e.g. ZEC/XMR got WATCH with a genuinely coherent "wait
  for X to resolve" thesis, not a default), and `requires_review = true`
  fired on 19 of 30 live decisions, correlated sensibly with lower
  confidence. `NO_TRADE` did not occur within 3b's screening-filtered
  `TOP_CANDIDATES` across those three runs — investigated directly rather
  than assumed: a genuine adversarial test (a real tracked asset deliberately
  outside `TOP_CANDIDATES`, given a maximally split 3-model ensemble,
  0.08 composite score, a screening anomaly flag, and stale/thin derivatives
  evidence) produced a real, live `NO_TRADE` from the actual model on the
  first attempt (`confidence=0.15`, thesis: *"Evidence is too thin, stale,
  and internally contradictory to support any actionable thesis... This is a
  case for NO_TRADE rather than manufacturing a directional or watch thesis
  from noise."*) — confirming `NO_TRADE` is genuinely reachable by the real
  model when warranted, not just in a unit fixture, and supporting the
  explanation below (TOP_CANDIDATES are pre-filtered for quality) over a
  residual action-bias theory.
- Recomputed the Risk Engine's exact sizing formula against the real stored
  `volatility_30d`/`model_agreement`/`source_agreement` values and confirmed
  it matches the persisted `portfolio_positions` allocations exactly — e.g.
  HYPE (`volatility_30d=0.045`) got `vol_scalar=0.663` vs. BTC's
  (`volatility_30d=0.024`) `vol_scalar=1.0` at the same target allocation
  ask, and BTC's `agreement_scalar=0.775` (model_agreement=1.0 but
  source_agreement=only 0.55) visibly shrank its position relative to a
  unanimous-agreement asset — proving the mechanism runs for real in the
  live path, not only in isolated unit tests.
- The correlation flag fired live and unprompted: `Correlated with SOL at
  0.93 (both being increased)` on BTC/SOL in a real run (only surfaced after
  a fix — see decisions below).
- `--evaluate-outcomes` ran against real data: correctly found entry prices
  for all 30 open decisions and correctly left all 30 `UNRESOLVED` (every
  decision's horizon — 21 to 90 days — is still far in the future relative
  to this project's ~2-day-old history); the `HIT_TARGET`/`HIT_STOP`/
  `TIMED_OUT` resolution paths themselves are covered by dedicated unit
  tests with synthetic past-horizon data, since no real decision has aged
  into resolution yet.
- `scripts/calibration_baseline.py --horizon-days 1` (shortened from the
  default 7 — see decisions below) against 144 real `llm_analyses` rows
  produced a genuine baseline: **hit_rate = 0.706, brier_score = 0.229** over
  51 scored BUY/SELL rows (45 HOLD rows excluded, no directional claim to
  score), with a real reliability-by-bucket breakdown showing the
  confidence~0.8 bucket hitting only 62.5% versus confidence~0.6 hitting
  87% — a genuine, useful overconfidence-at-the-top finding, not a clean
  number. Both this run and the null 7-day attempt are persisted to
  `calibration_runs` as separate, countable attempts.
- `judge_decisions` confirmed registered in `COST_TRACKED_TABLES`
  (`app/llm/cost.py`), with a test proving `CostGuard`'s cumulative sum
  reflects an inserted row, and live cost was $0.0155/asset ($0.155 for the
  10-candidate run).
- Full `pytest` suite green (226 tests) throughout.

**Known limitations / decisions:**
- **`NO_TRADE` did not occur within 3 organic live runs against real
  `TOP_CANDIDATES` — confirmed genuinely reachable, not a latent bug, via a
  targeted adversarial test.** Investigated in two stages, not left as an
  assumption: (1) the first prompt draft used the same phrase ("genuinely
  conflicting evidence") to describe both `WATCH` and `NO_TRADE`, which the
  live model resolved by always picking `WATCH` — a real prompt-clarity bug,
  fixed by sharpening `WATCH` ("a real thesis, waiting on a specific
  condition") vs. `NO_TRADE` ("no actionable view at all") and bumping
  `JUDGE_PROMPT_VERSION` to `v2`; (2) after the fix, still zero live
  `NO_TRADE`s on organic `TOP_CANDIDATES`, so a real tracked asset deliberately
  outside `TOP_CANDIDATES` was fed a maximally split 3-model ensemble, a weak
  composite score, a screening anomaly flag, and stale/thin derivatives
  evidence, through the real `OpenRouterJudgeProvider` — the live model
  returned `NO_TRADE` on the first attempt. This confirms `TOP_CANDIDATES`
  being pre-filtered for quality (not residual action bias) explains why it
  hasn't surfaced organically yet — worth re-checking once the tracked
  universe or a weaker market regime surfaces a genuinely marginal
  `TOP_CANDIDATE`.
- **New `portfolio_positions`/`portfolio_allocation_changes` tables
  (migration `0007`), not anticipated by 3a.** 3a reserved `judge_decisions`/
  `decision_outcomes`/`calibration_runs` empty for this sub-phase, but never
  anticipated that Portfolio Construction would need a real *numeric*
  current-allocation-per-asset state — `assets.in_asset` is a plain boolean
  with no size. No seed data: every asset starts at allocation 0 until the
  first live run assigns one, since Phase 1/2's `in_asset` flag was never a
  sized position.
- **Calibration baseline horizon shortened to 1 day (from a 7-day
  default).** This project's actual historical data (both `llm_analyses` and
  `market_snapshots`) only spans about 2 days so far — a 7-day horizon
  genuinely resolves zero rows right now, which the script correctly
  reported (persisted as its own null-valued countable attempt) rather than
  silently falling back to a shorter window. Re-run at the default (or a
  properly chosen) 7-day horizon once more calendar time has passed.
- **Held-out window boundary: 2026-09-05T17:07:49Z** — the `decision_timestamp`
  of this sub-phase's first live Judge decision. Every `decision_outcomes`
  row is stamped `in_holdout_window = true` unconditionally from this
  sub-phase onward (not a random subset) — the commitment is to never tune
  Judge prompts/Risk Engine formulas/Portfolio Construction logic against
  live decisions from this point forward, so 3f/3g's "did accuracy actually
  improve" comparisons mean something.
- **Replacement logic is scoped to assets judged in the SAME run only** — a
  new candidate can only displace an existing holding that also has a fresh
  `risk_adjusted_alpha` from this run's Judge output; an idle holding outside
  today's `TOP_CANDIDATES` is never displaced without fresh evidence.
- **A third parallel `OpenRouterJudgeProvider`** — same deliberate
  duplicate-over-shared-abstraction-risk trade-off as 3d's, applied again
  rather than generalizing either of the two already-shipped, live-verified
  provider classes.

## Phase 3e.1 — Retroactive historical replay (`scripts/run_replay.py`)

Re-runs 3e's exact model-assessment → Judge → Risk Engine → Portfolio
Construction pipeline, unmodified, against a past date range — so real
calibration signal starts accumulating immediately instead of waiting weeks
for live decisions to age into resolution. A diagnostic supplement, never a
substitute for the live, continuously-accumulating baseline: reported as a
completely separate number, never blended into one figure.

**Evidence-feasibility classification** (task 1, `app/benchmarks/replay.py`'s
`EVIDENCE_UNAVAILABLE_FOR_REPLAY`) — decided before writing the replay
runner, not worked out after the fact:
- **Backfillable, and used:** price/volume/OHLCV (Binance primary, Coinbase
  fallback — same source order as 3b's live screening, new
  `fetch_daily_ohlcv_with_timestamps` methods added to both clients since the
  existing live methods discard the date), and **Binance's genuinely
  historical funding-rate series** (`/fapi/v1/fundingRate` — verified live to
  return real past observations timestamped by `fundingTime`, not today's
  rate backdated). News (Phase 2's real stored articles, filtered by their
  own real `published_at` against the replay's `until` cutoff — already
  point-in-time-safe with no changes needed) and portfolio/LLM-analysis
  history (via two new as-of-safe repository methods,
  `get_latest_status_as_of`/`get_latest_by_asset_as_of`).
- **Not reliably backfillable, marked UNAVAILABLE, disclosed every replayed
  day, never fabricated:** everything else 3c supplies — dated-futures term
  structure/carry, aggregate open interest, Deribit options/VRP, CME COT,
  DefiLlama TVL, stablecoin supply/velocity, Etherscan transfers, on-chain
  valuation/miner metrics, spot ETF flows, prediction markets, token unlocks
  — plus regime-level BTC dominance and the altcoin-season index (both need
  either universe-wide historical market cap or CoinMarketCap's 90d field,
  neither a fixed reconstructable value for a past date with this system's
  sources).
- The screening/regime universe itself is scoped to the 21 **currently
  active tracked assets**, not 3b's wider 30-asset CoinGecko-discovered
  universe — CoinGecko's top-markets endpoint only exposes today's ranking,
  not a historical one, so re-deriving which assets would have ranked as
  `TOP_CANDIDATES` on a past date isn't reconstructable. A documented scoping
  decision, not an oversight.

**Safety design:** Risk Engine and Portfolio Construction run completely
unmodified, but against a fully isolated, in-memory-only simulated portfolio
state (`app/benchmarks/replay_fakes.py`) — a backfill run never reads or
writes the live `portfolio_positions`/`portfolio_allocation_changes` tables.
`judge_decisions`/`decision_outcomes` rows ARE persisted for real (migration
`0008` adds `is_backfilled`), always tagged `is_backfilled = true` and
`in_holdout_window = false` — backfilled rows are never forward-tracked
evidence, per the sub-phase's own non-negotiable.

**Live-verified, closed at 13 of the intended 28 days** (2026-08-09 through
08-19, plus the 2 validation days 09-04/09-05 run first to confirm
correctness on a short window before scaling up, per the sub-phase's own
guidance) — cut short by the OpenRouter account's real balance running out
mid-run (confirmed directly via OpenRouter's `/api/v1/credits` and `/api/v1/key`
endpoints: the account had ~$0.36 of its $105 total left, and the API key in
use had its own separate $20 sub-limit with ~$7 remaining — a real-money
constraint, not a bug in this system), not any technical or design failure:
- 129 `judge_decisions` rows and 129 matching `decision_outcomes` rows
  persisted across the 13 days, all confirmed `is_backfilled = true` and
  `in_holdout_window = false` by direct query — zero mistagging in either
  direction (no backfilled row missing the tag, no live row incorrectly
  tagged), checked against all 159 `judge_decisions` rows in the database.
- Every reachable decision value genuinely occurred: `WATCH`=47, `BUY`=42,
  `NO_TRADE`=21, `HOLD`=14, `SELL`=5 — including real `SELL` and far more
  `NO_TRADE` than any live run has produced, consistent with replay's
  genuinely thinner reconstructed evidence set surfacing more low-conviction
  cases. `requires_review = true` on 85 of 129 (66%).
- **The triple-barrier outcome resolution genuinely works on real
  backfilled data**, not just synthetic unit fixtures: 109 of 129 outcomes
  already resolved (103 `HIT_TARGET`, 6 `HIT_STOP`), immediately upon
  creation, by walking forward through the same fetched historical series
  used for reconstruction (not the live `market_snapshots` table, which only
  has ~2 days of real history and would have silently under-resolved almost
  everything — a deliberate scoping choice, see decisions below). Only the
  20 most recent decisions (from 09-04/09-05) remain genuinely `UNRESOLVED`,
  correctly, since not enough real time has passed for their horizons yet.
- `scripts/calibration_baseline.py --source backfill` produced a real,
  separate baseline: **hit-rate 0.833, Brier score 0.195** over 36 scored
  BUY/SELL decisions (93 HOLD/WATCH/NO_TRADE rows correctly excluded — no
  directional claim to score), persisted to `calibration_runs` with
  `method=BACKFILL_BASELINE`, distinct from and never combined with the
  live/Phase-2 forward-tracked baseline.
- `pytest` green throughout (242 tests, including a dedicated combined
  regression test for the incident below).

**A real incident during this sub-phase, not glossed over — the CostGuard
blind spot:** live-verifying the first larger continuation chunk revealed
that `CostGuard`'s daily/monthly cap check never actually saw the replay's
own spend for any date not coinciding with the real calendar day. Root
cause: `judge_decisions.created_at` was set to the *simulated historical
date* being replayed rather than the row's real insertion time, and since
`CostGuard` sums cost by `created_at >= today's midnight`, every
August-dated backfilled row was permanently invisible to the cap check — it
could have run indefinitely without ever tripping the daily/monthly cap.
A second, related gap compounded it: the assessment stage's cost is never
persisted to any table at all (by design, to avoid writing backfilled rows
into the live `model_market_assessments` table), so even a corrected ledger
could only ever see the Judge-stage third of the replay's true spend.
Fixed with two changes, not one: (1) `created_at` is now always
`datetime.now(UTC)` — the row's real insertion time; the simulated date
remains fully recoverable from `run_id` (e.g. `BACKFILL-2026-08-09`); (2)
`HistoricalReplayService` now snapshots the real remaining budget once via
a new `CostGuard.remaining_budget()` method, then tracks its own spend
in-process against that snapshot for the rest of the run — so it self-gates
correctly regardless of what does or doesn't get persisted to any table.
Verified with a combined regression test (`test_regression_incident_both_
bugs_covered_together`) that reproduces both mechanisms together — a
realistic ledger reading only `judge_decisions` (mirroring production
exactly) is shown to structurally under-count true spend, and the run is
confirmed to still be correctly bounded by the true total via local
tracking regardless. A related, lower-confidence finding from the same
incident: every HTTP client in this codebase set an explicit timeout except
the Supabase client (silently defaulting to supabase-py's 120s) — hardened
to 30s defensively, though this couldn't be conclusively proven as the
cause of the specific multi-minute hangs observed (no crash logs survive a
killed process); those hangs turned out to be intermittent, not
reproducible on demand, and are the reason later chunks were run as
small, background-launched, explicitly-verified-killable windows rather
than one long unattended invocation.

**Known limitations / decisions:**
- **Closed at 13/28 days by a real budget constraint, not a technical
  ceiling.** The remaining 15 days (2026-08-20 through 09-03) were not
  replayed. This is a deliberate, explicit stopping point — resuming later
  requires only re-running `scripts/run_replay.py --start 2026-08-20 --end
  2026-09-03` once the OpenRouter account has real balance again; nothing
  about the 13-day result needs redoing.
- **Outcome resolution reuses `evaluate_triple_barrier` directly but reads
  from the replay's own fetched historical series, not the live
  `OutcomeEvaluationService`/`market_snapshots` table** — deliberately, since
  this project's real snapshot history is only ~2 days deep and would have
  left nearly every backfilled decision perpetually `UNRESOLVED` for no
  genuine reason.
- **The `Bash` tool's `timeout` parameter does not kill a hung process** —
  discovered empirically (not assumed) with a deliberate `time.sleep(999)`
  test: the process was still verifiably alive after its timeout elapsed.
  `timeout` only bounds how long the tool waits synchronously before handing
  back a background task id; an actual kill requires an explicit stop call,
  confirmed to work via the same empirical test.
- **Each real invocation of the replay's simulated portfolio state starts
  fresh at zero allocations** — splitting the window across multiple
  process invocations (unavoidable given the real per-day/per-month cost
  caps) means Portfolio Construction's replacement/turnover dynamics are
  continuous only *within* one invocation's chunk, not across the whole
  13-day result. This doesn't affect the core calibration signal
  (`judge_decisions`' direction/confidence, `decision_outcomes`'
  resolution), which is 3e.1's actual payoff — only the simulated sizing
  narrative is chunk-local.

## Phase 3f — Adversarial research, macro matrix, remaining fragile sources (`--with-adversarial`, `--with-macro`)

The last evidence/decision-pipeline sub-phase of Phase 3 (3g, statistical
validation, follows next). Two new zero-and-non-zero-LLM-cost collection
stages plus a Judge extension, built and live-verified in that order.

### Feasibility findings (task 1) — decided before writing any provider code

**Confirmed working, built:**
- **Upbit** (regional exchange premium) — free, public, no key; verified
  live with real KRW-BTC ticker data.
- **SEC EDGAR full-text search** (regulatory calendar, US side) — free,
  official, no key (just a descriptive `User-Agent` per SEC's fair-access
  policy); verified live with real 8-K filing hits.
- **congress.gov** (regulatory calendar, legislative side) — free, official,
  key-gated (a quick signup, not a paid relationship); verified live with
  real bill data. No server-side full-text/keyword search on the bill-list
  endpoint (verified live: date-range filtering works, keyword filtering
  does not) — titles are keyword-matched client-side instead.
- **FRED** (Federal Reserve Economic Data) — free, official, key-gated (a
  quick signup); verified live against every series this project uses
  (`M2SL`, `WALCL`, `RRPONTSYD`, `SP500`, `DTWEXBGS`, `DEXKOUS`, plus the
  release-date endpoints for CPI/PCE/NFP). FRED's own historical gold-price
  series (`GOLDAMGBD228NLBM`) has been discontinued (verified live: "the
  series does not exist") — gold correlation instead uses **PAXG**
  (tokenized gold) via the already-integrated Binance/Coinbase clients, a
  real live-verified price (~$4432/oz, matching within cents across both
  venues) — no new vendor dependency.

**Confirmed genuinely infeasible:**
- **CryptoBubbles** — no documented API found (a guessed data endpoint
  returned 404); `robots.txt` explicitly disallows `ClaudeBot` site-wide.
- **CoinAnk** — the site is behind a BytePlus WAF bot-challenge (a JS
  challenge page, no accessible endpoint or `robots.txt`) — no legitimate
  API surface exists to build against.

**Confirmed real, deliberately deferred:**
- **CoinGlass** (liquidation heatmap) — a real, official, documented API
  exists, but is API-key-gated with tiered paid plans (Startup/Standard/
  Professional); no usable free tier confirmed. Same category as
  Glassnode in 3c — a real recurring-cost decision, deferred, not a
  technical failure.
- **LunarCrush** — even the "public" v4 endpoint requires an auth token; no
  anonymous access at all. Deferred alongside CoinGlass.
- **PlanB/X (via xAI)** — xAI's API is live and functional (verified a real
  auth-challenge response confirming the endpoint works), but no paid API
  relationship was established for this source — a deliberate choice, not
  an access failure.
- **Santiment** (social/narrative sentiment) — genuinely accessible with NO
  key for a real anonymous free tier (verified live: real
  `social_volume_total` time-series data returned), but restricted to data
  at least ~30 days old — unusable for this system's actual use case
  (current-sentiment reads for live decisions), so recorded `NOT_IMPLEMENTED`
  rather than wired in for a purpose it can't serve.

All nine of the above sources are reaffirmed live every `--with-macro` run
with real investigation notes — the exact discipline a 3c live-verification
incident established (a status never actually re-checked by code looks
identical, in a clean report, to one genuinely reaffirmed).

### What was built

1. **Macro matrix** (`app/market_data/macro_service.py`) — CPI, PCE, initial
   claims, payrolls, 10Y Treasury yield, and the effective fed funds rate,
   each reporting `actual` vs. `previous` (no free source for economist-
   **consensus** estimates was found — `surprise`/`consensus` are honestly
   `null`, never fabricated).
2. **Forward-looking macro-event calendar** — real, discrete CPI/PCE/NFP
   release dates via FRED's `release/dates` endpoint. **FOMC excluded**:
   FRED's "FOMC Press Release" release id (101) does not behave as a
   discrete meeting calendar — verified live it returns a release date for
   *every single day*, not ~8 meetings/year — so it's left out rather than
   silently faked as a real calendar.
3. **Global liquidity** (M2, Fed balance sheet, reverse repo) and **BTC's
   rolling 30d/90d correlation** to S&P 500, gold (PAXG), and DXY — computed
   deterministically from real stored/fetched price series, never
   editorialized into a signal at the collector level.
4. **Regional exchange premium** — Upbit KRW-BTC vs. the global USD price,
   converted via FRED's real KRW/USD rate (`DEXKOUS`).
5. **Regulatory event calendar** — SEC EDGAR (crypto-keyword full-text
   search) + congress.gov (keyword-matched bill titles), both **global/
   macro-scope only**: reliable per-asset attribution isn't achievable at an
   acceptable false-positive rate from a title/filing match alone, per the
   sub-phase's own explicit allowance for a narrower version.
6. **Adversarial research cycle** (`app/llm/adversarial_service.py`) — one
   model, three sequential batched calls covering every `TOP_CANDIDATE`:
   bull case → bear case (explicitly attacks the specific bull thesis,
   required to name which bull catalyst/evidence item each attack point
   rebuts) → bull/base/bear scenarios. Persisted to a new `adversarial_research`
   table (migration `0009`), registered in `COST_TRACKED_TABLES`. Uses a new,
   genuinely generic `OpenRouterStructuredProvider` (`app/llm/structured_provider.py`)
   parameterized by response schema — unlike Phase 2/3d/3e's provider
   classes, this one has no existing call sites to risk regressing, so a
   real generalization was the right call here, not a shortcut.
7. **Judge extension** (`app/judge/context.py`, migration `0010`) — the
   Judge now receives the shared macro/liquidity backdrop
   (`JudgeContext.macro_evidence`, one latest reading per single-value
   source), the forward-looking macro-event calendar and regulatory-event
   calendar as their own distinct multi-entry lists
   (`JudgeContext.scheduled_events`/`regulatory_events` — see the bug fixed
   below), and each candidate's bull/bear/scenarios
   (`AssetJudgeContext.adversarial`), and must produce a new required
   `macro_sensitivity` field — explicit, per-asset reasoning about how the
   shared macro backdrop affects *that specific asset*, never a blanket
   "liquidity up = bullish" rule. Both new inputs degrade gracefully to
   empty/`None` when unavailable (e.g. 3e.1's replay, which never collected
   macro/adversarial evidence) rather than requiring changes to
   already-shipped code.

### Live-verified findings

- **Cost, real per-stage breakdown** (not just a summed total, per explicit
  request): bull **$0.0515**, bear **$0.0911**, scenario **$0.0940** — total
  **$0.2366** for 10 candidates. All three came in well under the
  pre-verification estimate (~$0.48 total, anchored to Judge/assessment's
  real per-call costs) — and notably, the scenario call (carrying the most
  accumulated context: bull + bear + its own reasoning) did **not** cost
  noticeably more than bear, meaning input-token accumulation mattered less
  here than the estimate assumed. Full pipeline (assessment + adversarial +
  Judge) ≈ **$0.80/run**, comfortably inside `MAX_DAILY_LLM_COST` even at
  several runs/day — no candidate-count reduction needed.
- **Bull/bear is demonstrably adversarial, not generic**: UNI's live bear
  case directly quotes the bull thesis's own language ("Claude's own thesis
  states the price move has 'vastly outpaced' fundamental TVL growth...")
  and argues the TVL figure can't justify the composite-score claim; HYPE's
  bear case turns a data-quality flag from the bull thesis itself into an
  attack point and raises unlock/dilution risk the bull case never
  mentioned. `attacks_bull_point` correctly names the specific bull
  catalysts verbatim in both cases.
- **The Judge genuinely uses both new inputs, not just has them in
  context**: `macro_sensitivity` reasoning is real and per-asset, citing
  actual numbers (e.g. BNB: "...elevated 10Y yields (4.77%) and a
  near-zero reverse repo balance suggest limited fresh liquidity impulse
  feeding through to BNB specifically") and correctly differentiating asset
  classes (privacy coins reasoned as "idiosyncratic regulatory/narrative
  dynamics... limited direct read-through" vs. high-beta L1s reasoned as
  "benefits at the margin from RISK_ON" vs. XRP explicitly noting "no
  XRP-specific macro catalyst is present") — never one rule applied
  uniformly. Separately, UNI's `contradictory_evidence` directly quotes the
  bear case's exact phrasing, and both UNI's and HYPE's final confidence/
  decision were visibly tempered by the specific bear attack points, not
  just decoratively mentioning them.
- **Recalibration attempted honestly, not fabricated**: extended
  `scripts/calibration_baseline.py` with a `--source live` mode (splits real
  live Judge decisions into pre-3f/post-3f eras via `macro_sensitivity IS
  NOT NULL`, with a by-regime breakdown). Real result: **zero resolved
  decisions exist anywhere in the project yet** — all 40 live Judge
  decisions (30 pre-3f, 10 post-3f) are `UNRESOLVED` (real horizons of
  14–90+ days haven't elapsed), and only one regime (`RISK_ON`) has ever
  occurred in this project's real history. Persisted as two honest null
  attempts (`LIVE_PRE_3F_BASELINE`, `LIVE_POST_3F_BASELINE`, both
  `sample_size=0`) rather than a fabricated comparison.
- **Judge reasoning spot-check** (task 9): sampled 6 live decisions weighted
  toward `requires_review=true`/low-confidence/low-agreement. 5 of 6 showed
  the thesis directly and traceably following from `key_evidence`/
  `contradictory_evidence`, correctly reflecting genuine tension rather than
  glossing over it (e.g. ZEC's WATCH thesis correctly weighs the bull-side
  quant strength against negative funding, a bearish model outlier, and
  unaddressed regulatory tail risk). One minor wording ambiguity found, not
  a synthesis error — see decisions below. Findings logged, not used to
  auto-correct the Judge this sub-phase, per the prompt's own instruction.
- `pytest` green throughout (287 tests).

**A real incident during this sub-phase — two FRED bugs, found and fixed
live:**
1. `FredClient.fetch_recent_observations` used `sort_order=asc` + `limit`,
   which FRED interprets as "the *oldest* N observations from the series'
   entire history" (e.g. SP500 from 2016, DTWEXBGS from 2006), not the most
   recent N — this silently produced **zero** shared trading days between
   BTC and SP500/DXY, so correlation for those two references was silently
   never computed. Fixed by requesting `sort_order=desc` (genuinely the most
   recent) then reversing to the oldest-first contract callers expect.
2. `FredClient.fetch_release_dates` needs `include_release_dates_with_no_data=true`
   — without it, FRED silently excludes exactly the future/not-yet-published
   dates this method exists to find (verified live: omitting it returned
   `count: 0` for a real, known upcoming CPI release date). Both were caught
   by live-verifying the actual returned data against expectations, not by
   the code merely running without error — the same discipline the 3c and
   3e.1 incidents established.
3. A smaller, related bug: gold-PAXG correlation was initially gated behind
   `FRED_API_KEY` being configured, even though it needs no FRED data at
   all (it's Binance-sourced) — caught by a test that legitimately expected
   it to work without a FRED key.
4. **A fourth bug, found during this task's own final self-check (task 10),
   after the Judge extension had already been reported as working**:
   `build_judge_context`'s macro-evidence collection used
   `macro_evidence.setdefault(obs.source, ...)` — correct for a genuine
   single-value "latest reading" source (e.g. `macro_cpi`), but silently
   wrong for a source name shared by many distinct real observations. Two
   sources hit this: `scheduled_macro_event` (22 real rows, spanning 11
   distinct CPI/PCE/NFP dates through December 2026 — only 1 survived) and
   `regulatory_event_sec_edgar`/`regulatory_event_congress` (45 real rows —
   only 1 survived). The forward-looking calendar and regulatory calendar
   both genuinely existed in the database exactly as designed, but the
   Judge only ever saw one arbitrary entry from each — a gap invisible from
   a passing test suite or a clean run log, only caught by directly
   querying `EvidenceObservationRepository.get_latest_global_all()` and
   counting real rows per source. Fixed by routing these two source
   families into their own deduped-by-content lists
   (`JudgeContext.scheduled_events`, `JudgeContext.regulatory_events`,
   the latter capped at `MAX_REGULATORY_EVENTS_SHOWN=10`) instead of the
   single-value `macro_evidence` dict, and rendering both as their own
   labeled sections in the Judge prompt. Live re-verified with zero LLM
   cost (pure context-building, no model call involved): rebuilding the
   real Judge context against live Supabase data now surfaces all 11 real
   distinct scheduled dates and 10 (of 20 real, capped) distinct regulatory
   filings in the actual rendered prompt text, not just one of each. Three
   regression tests added directly targeting this bug class.

   **Both the task 9 reasoning spot-check and the earlier live `--with-judge`
   run predate this fix** — their persisted decisions were built against the
   buggy single-entry context, so a fresh live decision was pulled
   post-fix (run `RUN-20260906-080647`, real cost **$0.2407** across 10
   decisions) to confirm the Judge's *reasoning*, not just the prompt text,
   genuinely engages with more than one scheduled-event entry. Confirmed:
   SOL's and DOGE's `invalidation_conditions` both name two distinct real
   dates from the calendar by role — "a macro risk-off shock around the
   2026-09-11 CPI or 2026-10-02 NFP prints before horizon" (SOL) and "watch
   macro prints: CPI 2026-09-11, NFP 2026-10-02" (DOGE) — not a single
   generic date or a copy-pasted line, and consistent with the two distinct
   real release dates nearest the decision horizon. This is a genuine
   reasoning-level confirmation, not merely a prompt-rendering check.

### Known limitations / decisions

- **FOMC meeting dates are not in the forward-looking calendar** — FRED's
  only plausible release id for this doesn't behave as a real meeting
  calendar (see above); no other free, documented, official source was
  found within reasonable effort. CPI/PCE/NFP dates are real and populated.
- **No macro "surprise" (actual vs. consensus)** — FRED only publishes
  actual released values, never economist-consensus estimates; no free
  source for the latter was found. `actual`/`previous` are real; `surprise`/
  `consensus` are honestly `null`.
- **The regulatory event calendar is global/macro-scope only, never
  per-asset attributed** — a title/filing keyword match can't reliably
  distinguish "this SEC filing/bill concerns crypto broadly" from "this
  specifically affects asset X," per the sub-phase's own explicit
  allowance for a narrower version over an unacceptable false-positive
  rate.
- **congress.gov coverage is keyword-matched titles only** — the API has no
  server-side full-text/keyword search on its bill-list endpoint (verified
  live), so this is a naive keyword filter with the same false-positive/
  false-negative risk explicitly called out for this kind of extraction,
  not a claimed complete legislative feed.
- **CoinGlass, LunarCrush, and PlanB(xAI) deliberately deferred** — real,
  working access paths exist for all three, but each requires a new paid
  relationship (a subscription tier, or an xAI API account) that wasn't
  committed to this round. Binance funding rates (3c) and Santiment's
  lagged data already cover a meaningful slice of the underlying signal
  types.
- **The bull-rebuts-bear second pass was not built** — task 3's own
  language framed it as optional ("where practical"); kept to 3 calls to
  control cost, the same trade-off logic 3d used to defer Grok.
- **A minor prompt-clarity item, not a synthesis error**: one spot-checked
  decision (XRP, a live run on 2026-09-06) had `key_evidence` say "claude
  and openai cite strong medium-term momentum as the core bullish anchor"
  while `contradictory_evidence` said "all three models rate XRP NEUTRAL,
  not bullish" — these aren't strictly contradictory (a model can cite a
  bullish factor while still landing NEUTRAL overall) but read confusingly
  side-by-side. Didn't change the well-justified WATCH conclusion or invent
  anything; noted for future prompt wording, not acted on this sub-phase.
- **Recalibration (task 8) could not produce a real before/after number**
  — not a gap in the mechanism, a real fact about this project's age: zero
  live Judge decisions (pre- or post-3f) have had enough real time pass to
  resolve, and only one market regime has ever occurred. The `--source
  live` mode is built and ready to report a genuine comparison the moment
  real resolved data exists.
- **A third parallel provider-style class rationale, but genuinely
  different this time**: `OpenRouterStructuredProvider` generalizes over
  response schema rather than duplicating per-schema, unlike Phase 2/3d/3e's
  deliberately-separate provider classes — because it has no existing
  shipped call sites to risk regressing. Both trade-offs (duplicate vs.
  generalize) are deliberate, evaluated case-by-case, not a fixed rule.

## Phase 3g — Statistical validation & robustness

The last sub-phase before 3h (adaptive weighting/stress testing) and 3i
(a further evidence-collection addendum), and the gate this project treats as
the actual determinant of whether Phase 3's pipeline improved decision
quality, rather than a raw before/after delta. Changes no evidence
collection and no decision logic — produces findings and recommendations
only, per its own non-negotiable, even where a finding clearly warrants a
follow-up change.

### Task 1: trial-count reconstruction

Walked `prompt_templates` (4 rows: `market_assessment` v1, `judge_decision`
v1 and v2, `adversarial_research` v1) and `calibration_runs` (5 rows) to
reconstruct an honest count of real calibration attempts. Finding:
**`judge_decision` v1 was never calibrated at all** — the 10 decision_outcomes
rows referencing it are all from one early live run
(`RUN-20260905-165829`), all still `UNRESOLVED`; v2 superseded it before any
resolved data ever existed to score it against. Of the 5 `calibration_runs`
rows, 2 (`phase2_llm_analyses_directional_baseline`) used an entirely
different mechanism (Phase 2's `llm_analyses` table directly, not
`judge_decisions`/`decision_outcomes` at all) and aren't comparable Judge
"trials"; 2 (`LIVE_PRE_3F_BASELINE`/`LIVE_POST_3F_BASELINE`) are honest null
attempts (sample_size=0); only 1 (`BACKFILL_BASELINE`) reflects a real
calibration against resolved outcomes, and it used only `judge_decision` v2.
**Honest trial count: 1** real configuration ever calibrated against
resolved data. `signal_sources.enabled` was checked as a possible second
counting dimension per the task's own wording — found to be a static value
seeded once in migrations and never toggled by any app code (`update_status`
only ever writes `status`, never `enabled`), so there is no real toggle
history to reconstruct; this dimension contributes nothing to the trial
count, reported as such rather than fabricated.

### Task 2: Deflated Sharpe Ratio / PBO

Implemented in `app/benchmarks/statistical_validation.py`: Probabilistic
Sharpe Ratio (Bailey & Lopez de Prado, 2012) built on Lo (2002)'s closed-form
Sharpe-ratio standard error, and Deflated Sharpe Ratio (Bailey & Lopez de
Prado, 2014) on top of that. Verified against known-correct outputs, not
just "plausible-looking code": PSR at `sharpe_ratio == benchmark_sharpe`
must equal exactly 0.5 for any n/skew/kurtosis (an exact mathematical
identity — tested); PSR independently cross-checked against Lo (2002)'s
formula recomputed a second, separate way in the test itself (not calling
the module's own helper) — matches to 1e-12; DSR at `n_trials=1` (this
project's real trial count) must reduce exactly to `PSR(0)`, since with only
one configuration ever tried there is no selection bias to correct for —
`n_trials=1` returning `expected_max_sharpe_under_null=0.0` is a genuine
degenerate case, not an approximation (the formula's own
`Φ⁻¹(1 - 1/1) = Φ⁻¹(0) = -∞` is undefined at n=1).

On the 36 directional (BUY/SELL) resolved backfilled decisions: **Sharpe
1.82** (skew −0.25, kurtosis 7.26 — noticeably fat-tailed), n=36. **DSR ≈
0.9998** at the real trial count of 1. **Caveat, load-bearing**: this is the
backfilled/simulated return series (11 replayed historical days), not live
paper-trading results, and applies zero multiple-comparisons correction
(correctly, for n_trials=1) — it says "distinguishable from zero on this
backfilled sample," not "expect this Sharpe going forward."

**PBO: not computable.** Requires ≥2 independently-tried configurations to
compare in-sample vs. out-of-sample rank (Bailey, Borwein, Lopez de Prado,
Zhu, 2014); this project has only ever calibrated 1. The CSCV method is
implemented and tested against the one case provable by hand construction
(two configurations, one a constant-shift-up of the other in every period —
proven by hand to always win in-sample AND out-of-sample, so PBO must be
exactly 0.0) plus a second hand-provable case (two literally identical
configurations tie on every split, so by the tie convention PBO must be
exactly 0.5) — **not** cross-checked against a published numeric worked
example, disclosed honestly rather than overclaimed, per the sub-phase's own
non-negotiable.

### Task 3: full calibration reporting

Brier score **0.195** (reliability 0.073, resolution 0.015, uncertainty
0.139). The classical 3-term Murphy (1973) decomposition
(`BS = Reliability - Resolution + Uncertainty`) is only an *exact* identity
when every point's forecast equals its bucket's mean — true for discrete
forecast values, false for continuous confidence values grouped into
ranges. Found this the hard way: an initial test asserting exact
reconstruction failed at the 3rd decimal (0.067 vs. 0.068) on real
continuous test data. Fixed by adding and reporting a fourth term,
`within_bucket_dispersion` — the information lost by substituting each
point's forecast with its bucket mean — making
`reliability - resolution + uncertainty + within_bucket_dispersion` an exact
identity for any bucketing, verified across several synthetic datasets. A
second real bug found the same way: `int(f / bucket_size)` misclassifies
exact bucket boundaries under float error (`0.3 / 0.1 == 2.9999999999999996`
truncates into the wrong bucket) — fixed with a small epsilon before
truncation, with a regression test targeting this exact float-boundary case.

Reliability by confidence bucket (all n small): 0.4–0.5 (n=4, 50% hit-rate),
0.5–0.6 (n=16, 87.5%), 0.6–0.7 (n=13, 84.6%), 0.7–0.8 (n=3, 100%) — hit-rates
run *above* stated confidence at every bucket (underconfidence, not
overconfidence), though n is small everywhere. By `model_agreement`: MED
n=19 (84.2%) vs. HIGH n=17 (82.4%) — **no evidence high agreement resolves
better than medium** at this sample size. By `source_agreement`: MED n=28
(78.6%) vs. HIGH n=7 (100%) vs. LOW n=1 — directionally consistent with
`source_agreement` earning its keep as a sizing input, but n=7/n=1 are too
small to call real.

**By-regime breakdown: not computable — a real persistence gap, not a
sample-size problem.** Every one of the 109 resolved backfilled outcomes has
`regime_at_decision = NULL`. 3e.1's replay computes a real
`MarketRegimeSnapshot` per simulated day and uses it live in the Judge's
prompt, but that snapshot is constructed with `id=None` and never persisted
to `market_regime_snapshots` — so `decision_outcomes.regime_at_decision`
(a real FK) has nothing to link to, for any backfilled row. The regime
string itself is not recoverable from the database for any backfilled
decision. Reported as a finding, not fixed — changing `replay.py` is outside
3g's scope (no new evidence collection or decision logic).

### Task 3a: point-in-time / look-ahead audit — CLEAN

Verified at the code level, not by re-trusting the design intent:
`HistoricalSeries.as_of` correctly slices to `date <= cutoff`; the funding-
rate evidence builder filters `funding_time <= cutoff` before selecting the
latest; Phase 2 LLM analyses and asset-status both route through genuine
`get_latest_by_asset_as_of`/`get_latest_status_as_of` point-in-time methods;
news correctly bounds `published_at <= until`. Every other revisable 3c/3f
source (on-chain valuation metrics, ETF flow figures, regulatory-event
extraction, ETF/CFTC positioning) was deliberately marked
`EVIDENCE_UNAVAILABLE_FOR_REPLAY` rather than reconstructed — exactly
avoiding the lookahead risk those sources pose. No contamination found in
any pathway replay actually uses.

### Task 3b: purged/embargoed walk-forward check — gap absent, primary blocker for task 7

**No embargo exists between the training (backfilled, `in_holdout_window=
false`) and holdout (live, `in_holdout_window=true`) samples.** The
backfilled decisions run 2026-08-09 through 2026-09-05; the live decisions
start 2026-09-05 — **the gap is negative** (≈ −1d23h; they overlap slightly
in wall-clock terms) against a **45-day** longest resolution horizon.
**100% of the 50 holdout decisions sit within one resolution-horizon's
distance of the training boundary.** Mitigating factor: the specific
slow-moving/sticky evidence types that pose the worst autocorrelation risk
(derivatives, on-chain) were excluded from replay entirely (see 3a above) —
but price-momentum/regime persistence (used in both sets) remains a real,
unaddressed leakage channel. This is not a defect in tasks 2–3's numbers
themselves (which are honest in-sample descriptions of the backfilled data);
it means a *future* "the holdout period confirms it" claim, once holdout
decisions resolve, would not constitute a clean, independent test without
first adding an embargo — the reason task 7 cannot issue a go/no-go on
sample-size grounds alone, even once more time passes.

### Task 4: held-out window — insufficient data

50 live decisions, all `in_holdout_window=true`, **zero resolved**. Horizons
present: 14/21/30/45 days; only ~1 day of real calendar time has elapsed
since the first live decision. Nothing to report yet beyond "wait" — and per
task 3b, even the eventual result will need the embargo caveat attached.

### Task 5: Judge reasoning audit

Formalized 3f's manual spot-check into a persisted, repeatable check — new
`judge_reasoning_audits` table (migration `0011`), registered in
`COST_TRACKED_TABLES` (tested). A single structured LLM call per sampled
decision, given ONLY that decision's own stored `thesis`/`key_evidence`/
`contradictory_evidence` (never live evidence, which may have since decayed
or resolved differently) — a pure internal-consistency check: does the
thesis actually follow from its own cited evidence.

Sampling (`app/benchmarks/reasoning_audit.py::select_audit_sample`) is
weighted, in priority order: outcome-contradicted-decision (rarest, most
diagnostic — all 6 real cases in this project's history), `requires_review=
true` (70 of 109 resolved), then low model/source agreement (<0.6, 59 of
109). Real cost, exact: a single test call **$0.002268** (confirmed real,
below even the low end of the pre-run estimate — this call's input is much
smaller than assessment/adversarial calls, just one decision's evidence text
plus a short instruction), then the remaining sample for **$0.024570**;
**$0.026838 total** across 9 calls (8 distinct decisions — one duplicate
occurred, see below).

**Real finding: 1 of 8 audited decisions (12.5%) shows a genuine
unsupported claim.** A SELL decision (`requires_review=true`,
model_agreement=1.0 but source_agreement=0.65, outcome contradicted the
call) recommended trimming exposure but never addressed its own cited
contradicting evidence (a slightly positive funding rate, flat-to-positive
90-day returns) and only nominally acknowledged a "still-decent composite
score" without reconciling it with the bearish conclusion. The other 7
(including 5 of the 6 contradicted-outcome cases) showed internally
consistent reasoning — e.g. one decision's thesis was confirmed to
genuinely weigh cited bullish evidence against cited bearish signals rather
than ignoring either side. n=8 is small — a real, useful signal, not a
generalizable rate.

**A real script gap, disclosed rather than hidden**: `select_audit_sample`
has no memory of prior audit runs, so re-running the script reselected an
already-audited decision, producing 2 audit rows for it (both agreeing
`supported=true`, so no impact on the finding above, but wasted real spend).
Noted as a known limitation below, not silently fixed after the fact.

### Task 6: source-disabling recommendations

**No source named in the task can currently be evaluated for measurable
value** — every one is blocked by a different reason, not a weak effect
size: `SPOT_ETF_FLOWS`, `PREDICTION_MARKETS`, and `ON_CHAIN_MINER_METRICS`
are `NOT_IMPLEMENTED` (nothing to evaluate). `STABLECOIN_SUPPLY_VELOCITY_
AND_EXCHANGE_RESERVES` and `CME_COT_POSITIONING` are genuinely operational
(`status=OK`) but were deliberately excluded from 3e.1's replay
(`EVIDENCE_UNAVAILABLE_FOR_REPLAY`, per 3a's audit above) — zero resolved
decisions have ever used them. `GLOBAL_LIQUIDITY_MACRO` and
`REGULATORY_EVENT_CALENDAR` (3f) are operational but postdate replay
entirely — only used in the 50 still-unresolved live decisions. For
`composite_factor_score`: the intended "agreed vs. diverged" hit-rate
comparison hit the **same persistence gap as task 3's regime finding** —
`screened_universe` (which holds the real, joinable score) only has rows
for live `RUN-*` run_ids, never replay's `BACKFILL-*` run_ids, so no
backfilled decision has a joinable composite_factor_score on record. The
score IS narratively embedded in `key_evidence` free text (e.g. "Composite
score 0.637..."), but a regex extraction from inconsistently-phrased
narrative text was deliberately rejected as too misparse-prone for a
statistical comparison — reported as not computable rather than risking a
silently-wrong number. **No `signal_sources` row is recommended for
disabling; none can be, on real evidence, yet.**

### Task 7: go/no-go statement for Phase 4

**Not yet — and the primary reason is the missing embargo (task 3b), not
sample size alone.** Even once the 50 live holdout decisions resolve (the
earliest possible in ~13 more days, at the 14-day horizon), that result
would not constitute a clean, independent out-of-sample test without an
embargo gap first: 100% of those decisions sit within one resolution-horizon
of the training boundary, and price-momentum/regime persistence — present
in both the training and holdout data — is a real, unaddressed
autocorrelation channel. Sample size compounds this (zero holdout
resolutions exist right now at all) but is not the deeper problem; a larger
unembargoed holdout sample would still not license a go/no-go claim on its
own. Getting to a real answer needs, in order: (1) let holdout decisions
resolve to have *any* out-of-sample number, then (2) either introduce a
genuine embargo gap for the *next* holdout cohort, or treat any earlier
non-embargoed holdout result as directionally suggestive only, never
confirmatory. This is a statement about what's missing, not a negative
verdict on the system — the backfilled Sharpe/Brier numbers (tasks 2–3) are
a positive signal, just not yet one that has cleared the bar this sub-phase
exists to apply.

### Tests

327 tests passing (`pytest`, no live credentials needed):
`tests/test_statistical_validation.py` (20 tests — PSR/DSR against known-
correct degenerate cases and an independent cross-check, PBO against the two
hand-provable constructions, Brier decomposition's exact-reconstruction
identity including the float-boundary regression), `tests/
test_reasoning_audit.py` (13 tests — sampling priority/dedup/cap, prompt
rendering, schema validation, `CostGuard` registration, a mocked-LLM call).

### Known limitations / decisions

- **By-regime and composite-factor-score breakdowns are blocked by the same
  underlying gap**: 3e.1's replay computes real regime/score values
  in-memory for context-building but never persists them as clean,
  joinable rows for backfilled decisions — only their narrative embedding
  in free text survives. A real, reportable structural gap in replay's
  bookkeeping, not fixed here (out of 3g's scope).
- **DSR/PBO's honest ceiling is this project's youth, not a flaw in the
  method**: with only 1 real calibrated configuration and 0 resolved live
  decisions, there's genuinely little for deflation/overfitting-correction
  machinery to correct yet — both are built, tested, and ready the moment
  there's more than one trial or a resolved holdout to check.
- **PBO's implementation is verified only against 2 hand-provable
  degenerate cases**, not a published numeric worked example — disclosed
  plainly rather than overclaimed, consistent with the sub-phase's own
  non-negotiable on unverified formula implementations.
- **The reasoning-audit script has no run-to-run memory** — a repeat
  invocation can reselect and re-audit an already-audited decision (real,
  wasted spend observed this run). Not fixed here; a natural task-5
  follow-up if the audit becomes a recurring, repeated process.
- **`DATABASE_URL` (used only by `scripts/apply_migration.py`) had a stale
  password this sub-phase** — migration `0011` was applied manually via the
  Supabase SQL Editor instead (the script's own documented fallback).
  `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY` (used by the real app/tests)
  were unaffected.
- **A fourth evidence-pipeline bug of the same class as 3f's macro-evidence
  dedup was found and fixed this sub-phase, before 3g's own tasks began**:
  `binance_futures_term_structure`/`deribit_futures_term_structure` are
  collected per dated-futures instrument (up to 12 distinct BTC instruments
  per run on Deribit alone), but all three per-asset evidence-context
  builders (Judge, 3d assessment, 3f adversarial research) deduped by
  source name, silently collapsing the whole term-structure curve to one
  arbitrary point — worse than 3f's bug, since ties in `retrieval_timestamp`
  make "which point survives" non-deterministic, not even reliably
  "nearest expiry." Fixed via one shared, tested helper
  (`group_observations_by_multi_entry_source` in
  `app/database/evidence_provenance.py`) reused by all three consumers
  rather than tripling the fix; also bumped
  `EvidenceObservationRepository.get_latest_by_asset`'s default query limit
  50→150, since multi-entry sources alone were nearing that ceiling and
  risked crowding out single-value sources' latest readings. Live-verified
  using BTC's real evidence data through all three real `render_prompt`
  functions: all 12 real Deribit instruments and 2 real Binance instruments
  now render as the full curve. **3 real, still-`UNRESOLVED` live
  `judge_decisions` (all BTC) reasoned from the pre-fix single collapsed
  point** — flagged here as a caveat on those specific decisions rather than
  rerun; none of the 109 resolved backfilled outcomes ever cited term
  structure, so no calibration number is affected.

## Phase 3h — Adaptive evidence-value weighting & portfolio stress testing

A later addendum to Phase 3, added after a gap-analysis against
professional crypto-advisory/quant-research practice. Both capabilities are
diagnostic/reporting-only, same standing as 3g's findings — neither is wired
into the live Judge/Risk Engine pipeline, and no `signal_sources`,
Judge-prompt, or Risk Engine change was made.

### Task 1/1a: adaptive evidence-value ranking + drift detection

Implemented `app/benchmarks/evidence_value.py`: a logistic regression
written from scratch (batch gradient descent, standardized features, a
small L2 penalty for stability) rather than adding numpy/scikit-learn as a
new dependency — this project already declines new tooling that doesn't
match a specific, scoped need, and a hand-rolled fit over ≤6 features and a
few dozen real observations is fully tractable in pure Python.

**Verified against engineered fixtures with a known relationship before
running on real data** (per the task's own non-negotiable): a
perfect-predictor-vs-pure-noise case (one feature constructed to perfectly
determine the label, another constructed — via an exact block structure,
not probabilistic luck — to have precisely zero sample correlation with the
label) confirms the mechanism recovers a large coefficient for the real
signal and a near-zero one for noise; a regime-dependent case (the same
feature is perfectly predictive in one synthetic "regime" and pure noise in
another) confirms the regime-sliced drift check specifically recovers
regime-dependence, not just that the aggregate model runs. 8 tests, all
passing.

**Minimum sample size: 50**, documented reasoning — ~10 observations per
candidate feature is a conservative, commonly-cited rule of thumb for a
stable logistic-regression fit (Peduzzi et al., 1996), and this project's
real candidate feature set has up to 6 fields (implying ~60 by the strict
rule; 50 is used as a slightly relaxed but still defensible, honestly
reachable bar as more decisions resolve).

**Real result: insufficient data.** n=36 real directional resolved
decisions (the same dataset 3g's DSR/Brier work used) — below the required
50. Reported and persisted honestly as `sufficient_sample=false`, not
forced into a fabricated ranking. Rolling-window variants (20, 16) are
smaller still, same honest result.

**A further real limitation, found while building this task, not
anticipated by the phase prompt's own framing**: the intended candidate
feature set — `source_assessment` entries (the Judge's per-named-source
read) and `composite_factor_score` — turned out to be **entirely
unusable**, not merely small-sample. Neither is joinable to any of the 109
resolved decisions: `model_market_assessments` (which holds
`source_assessment`) has **zero** rows with a `BACKFILL-*` run_id — 3e.1's
replay builds these records in-memory to feed the Judge's context but never
persists them to the real table — and `composite_factor_score` hits the
identical gap already found in 3g (`screened_universe` only has live
`RUN-*` run_ids). This is the **same root persistence pattern as 3g's
`regime_at_decision` finding**, now confirmed a third time across three
independent fields (regime, composite score, source assessment) — 3e.1's
replay consistently computes real values in-memory for context-building but
never persists a clean, joinable record of them alongside the resulting
decision, leaving only their narrative embedding in free text. The usable
candidate feature set was therefore restricted to fields genuinely
persisted on every `judge_decisions` row: `model_agreement`,
`source_agreement`, `confidence`, `risk_score`, `uncertainty`,
`investment_horizon_days` — a real, disclosed narrowing, not silently
substituted for the task's original intent. A regex-based extraction of
`composite_factor_score` from `key_evidence` free text was considered and
rejected as too misparse-prone for a statistical input (inconsistent
phrasing across decisions, e.g. "Composite score 0.637" vs. "Highest
composite score among momentum leaders (0.668)") — same discipline 3g
applied when it hit this identical question.

**Regime-sliced drift: not computable**, for the same reason —
`regime_at_decision` is NULL for every resolved backfilled decision, so
there is no real regime label to slice by. Both null results persisted to
`evidence_value_reports` (migration `0012`) alongside the full-history and
rolling-window attempts — 4 real rows, all `sufficient_sample=false`,
each with its specific reason.

### Task 2: portfolio tail-risk stress testing

Extended `app/risk/` with `app/risk/stress_test.py` — pure, deterministic,
zero LLM cost. Two scenarios, chosen to satisfy all three of the task's
named examples without redundancy (the first scenario below directly
satisfies both the "~70% BTC drawdown, 2022-style" example and the "at
least one scenario using actual historical returns" requirement in a single
real computation):

1. **`HISTORICAL_WORST_DRAWDOWN`** — each asset's own real historical
   peak-to-trough drawdown, computed from real fetched Binance/Coinbase
   daily OHLCV (`scripts/run_stress_test.py`, same clients 3e.1's replay
   already verified live). **A real, disclosed constraint**: Binance's
   kline endpoint caps at 1000 daily candles per call counted back from
   "now," so the reachable real window is ~2.7 years (2023-12-12 to
   2026-09-06 in this project's real timeline) — it does **not** reach back
   to the actual 2022 cycle. **BTC's real computed -53.0% is explicitly the
   worst drawdown within that ~2.7-year reachable window, not BTC's true
   all-time historical worst drawdown** — the real 2022 top-to-trough move
   (~Nov 2021 ATH to ~Nov 2022 low) was deeper than this and simply isn't
   reachable through the existing client method without adding pagination
   (`startTime`/`endTime`) to `BinanceClient`, which was deliberately not
   done here (see Known limitations). This is disclosed, not silently
   patched over by fabricating deeper history or rounding up to the task's
   own "~70%" example figure.

   Fetching per-asset drawdowns for the full active universe (a broader
   check than the live stress-test run itself, which only fetches
   currently-allocated assets plus BTC) found two more honest findings,
   **neither of which currently affects the reported live-portfolio
   numbers below, since neither asset is presently allocated**: **`WBT` has
   no real data on either exchange** (would fall back to the documented
   BTC proxy if ever allocated) and **`XMR`'s real data is genuinely
   stale** — its series ends 2024-02-20, not near the current date
   (consistent with Monero's real exchange delistings around that period).
   If XMR were ever allocated to, its real (if outdated) -67.2% drawdown
   would be used as-is — real data, not fabricated — but flagged
   `is_stale=true` distinctly from a proxy, so it would never be silently
   treated as equally current as a fresh reading; whether an 18-month-old
   figure still represents XMR's true current tail risk is exactly what
   that flag exists to let a reader judge for themselves, not something
   this module resolves on its own. `HYPE`'s real window is short (214
   days, since 2026-02-05) — its real drawdown (-29.9%) likely understates
   its true tail risk given limited history, noted as such.
2. **`ALTCOIN_CONTAGION_LUNA_FTX_STYLE`** — a stated scenario ASSUMPTION,
   not fitted from data (correlations move toward 1 in a contagion event):
   BTC/ETH assumed to fall 50%, every other asset assumed to fall 85% — a
   modeling choice broadly consistent with (though not derived from) this
   project's own real per-asset numbers above, where every real altcoin
   drawdown was meaningfully deeper than BTC's/ETH's.

Each scenario's "CVaR-style estimate" is deliberately identical to its
portfolio drawdown — with one deterministic scenario per template (not a
return distribution), expected-loss-beyond-a-threshold reduces exactly to
that scenario's own loss; disclosed as a real simplification, not dressed
up as a full historical VaR computation, consistent with the task's own
instruction to keep this simple and inspectable.

**Real result, run against the real live portfolio** (BTC 5.78%, HYPE
0.76%, BNB 6.40%, SOL 4.66%, LINK 3.16% — 20.75% total allocated, the rest
in cash):

| Scenario | Portfolio drawdown | Flagged (`MAX_STRESS_SCENARIO_DRAWDOWN`=50%) |
|---|---|---|
| `HISTORICAL_WORST_DRAWDOWN` | **-12.94%** | No |
| `ALTCOIN_CONTAGION_LUNA_FTX_STYLE` | **-15.62%** | No |

Neither scenario flags at the current allocation level — but this
reflects the portfolio being only ~21% deployed right now (per-asset
drawdowns are severe: -53% to -76% under scenario 1 alone), not low
underlying asset risk. If fully allocated at the current asset mix, both
figures would scale roughly proportionally (≈5x, since ~21%→100%),
putting `ALTCOIN_CONTAGION_LUNA_FTX_STYLE` close to the flag threshold —
worth keeping in mind as allocation grows, not a static "safe" reading.

### Task 3: cost sizing

Confirmed: this sub-phase added **zero new LLM cost**. Both capabilities
are deterministic — evidence-value ranking is pure Python gradient descent
over already-persisted structured fields, and the stress test is pure
arithmetic over freely-fetched real market data (no API key, no LLM call).
No optional LLM-based explanation step was added.

### Tests

344 tests passing (`pytest`, no live credentials needed):
`tests/test_evidence_value.py` (8 tests — the perfect-predictor and
regime-dependent fixture recoveries, sample-size gating, rolling-window
splitting, schema serialization) and `tests/test_stress_test.py` (8 tests —
hand-computed known drawdowns for both scenarios, proxy fallback, stale-data
handling, threshold flagging).

### Known limitations / decisions

- **The `source_assessment`/`composite_factor_score`/`regime_at_decision`
  persistence gap is now confirmed across three independent fields** —
  3e.1's replay computes real values in-memory for context-building but
  never persists a clean, joinable record of them for backfilled decisions.
  This is a real, reportable structural gap in replay's bookkeeping, not
  fixed here (changing `replay.py` is outside both 3g's and 3h's scope) —
  worth a dedicated look if backfilled data is ever relied on again for a
  learned-model or regime-conditional analysis.
- **`HISTORICAL_WORST_DRAWDOWN` cannot reach the actual 2022 cycle** —
  Binance's kline endpoint's 1000-candle-per-call cap, counted back from
  "now," limits the real reachable window to ~2.7 years. Extending this
  would need pagination (`startTime`/`endTime` params) added to
  `BinanceClient` — a real, scoped follow-up, not implemented here to avoid
  touching a collector client beyond this sub-phase's stated scope.
- **`evidence_value_reports` carries no `estimated_cost` column and is not
  registered in `COST_TRACKED_TABLES`** — correctly, since this sub-phase
  adds zero LLM cost (task 3).
- **The evidence-value ranking's real result (insufficient data) means task
  1's "disagreement between the learned ranking and the Judge's implicit
  weighting" comparison has nothing to compare yet** — there is no learned
  ranking to disagree with the Judge's weighting until n≥50 real directional
  decisions resolve. Not a gap in the mechanism (verified against fixtures);
  a real fact about this project's current age, same standing as 3g's DSR/
  PBO/held-out-window findings.

## Phase 3i — Entity-flow intelligence, custody/OTC flow, network & developer fundamentals (`--with-asset-intelligence`)

The last **required** sub-phase of Phase 3 (3j remains optional/gated; Phase
4 follows). New evidence-collection work, wired into the existing Judge the
same way 3f extended the input set — zero new LLM calls, zero Judge/Risk
Engine/Portfolio Construction code changes.

### Feasibility findings (task 1) — decided before writing any provider code

**Confirmed working, built:**
- **Nansen** (entity-flow / smart-money netflow) — real, documented, free
  tier confirmed live: 100 one-time credits + 10/day refill, "all API
  endpoints available." Auth (`apikey` header) verified with a real key;
  the `smart-money/netflow` endpoint returned genuine per-token data
  including one of this project's own real universe assets (ENA: real
  net-flow figures, 8 tracked "smart money" traders).
- **Etherscan, per-token network usage** — the network-*wide* `stats/
  dailytx` endpoint genuinely requires Etherscan's separate paid Pro tier
  (verified live: an explicit "Sorry, it looks like you are trying to
  access an API Pro endpoint" rejection on the free key) — but a per-*token*
  proxy built from the free `account/tokentx` endpoint (real ERC-20
  transfer events) is free-tier-accessible and, arguably, more directly
  relevant to a per-asset Judge input anyway.
- **GitHub** (developer activity) — confirmed live, free, no key required
  (60 requests/hour; an optional token raises this to 5000/hour). A small,
  curated, explicitly-verified map of 10 assets to an unambiguous primary
  repo (BTC, ETH, SOL, XRP, LINK, NEAR, UNI, ZEC, XMR, XTZ) — every other
  symbol in the universe is closed-source, multi-repo, or a meme/community
  token with no core dev team, and is marked `UNAVAILABLE` rather than
  guessed, per this task's own explicit instruction.

**Confirmed genuinely infeasible:**
- **Arkham Intelligence** — `api.arkhamintelligence.com` is Cloudflare
  bot-challenge-gated on every path tried (including a plausible real
  endpoint), and `platform.arkhamintelligence.com` returns 403. No
  legitimate API surface exists to build against without an already-
  authenticated account. Same standard as CoinAnk in 3f.
- **Custody/OTC desk flow** — unlike 3c's exchange hot-wallet proxy (real,
  publicly documented addresses), no reliable, independently-verifiable
  source of real custody-provider addresses (Coinbase Custody, Fidelity
  Digital Assets, etc.) exists — these aren't in any official public
  registry, only pieced together over time by on-chain sleuthing. Building
  this would mean fabricating or presenting unverified addresses as real,
  which this project's core discipline does not permit. Recorded
  `NOT_IMPLEMENTED` — a genuine infeasibility, not a shortcut.

### What was built

1. **Entity-flow intelligence** (`app/market_data/nansen.py`,
   `app/market_data/asset_intelligence_service.py`) — one real
   `smart-money/netflow` call per distinct Nansen-supported chain among the
   current `TOP_CANDIDATES` (not one call per asset — far more
   credit-efficient given the free tier's real scarcity), matching returned
   tokens back to candidates **by the `token_symbol` Nansen itself
   returns**, never a self-supplied contract address (avoids the risk of a
   wrong address silently returning data for the wrong token). Real,
   disclosed coverage gap: Nansen's smart-money chains are EVM/Solana only
   — **BTC and every native-chain coin (SOL, BNB, HYPE, etc.) are not
   covered at all**, and native-token inclusion specifically wasn't
   verified live (credit scarcity), so this project's `NANSEN_CHAIN_BY_
   SYMBOL` map deliberately only covers confirmed ERC-20/SPL *token* assets
   (7 on Ethereum, 2 on Solana), not native coins.
2. **Network usage** (`app/market_data/etherscan.py`'s new
   `fetch_token_transfers`) — real ERC-20 transfer events for 7
   live-verified contract addresses (each individually confirmed by
   querying real `tokentx` data and checking the returned `tokenSymbol`/
   `tokenName` match before hardcoding — a wrong address would silently
   return real data for the wrong token, so nothing here was taken from
   memory alone), yielding a distinct-active-address/transfer-count proxy.
3. **Developer activity** (`app/market_data/github_activity.py`) — real
   commit counts (since a 30d cutoff) and contributor counts (GitHub's own
   `stats/contributors`) for the 10 curated assets above.
4. Both `entity_flow_intelligence` and `network_fundamentals_usage`/
   `developer_activity` reuse 3a's shared `evidence_observations` shape —
   no new tables needed, matching 3c/3f's own precedent. New decay
   half-lives added, explicitly differentiated per the task's own
   instruction: entity-flow and network-usage at 24h (on-chain-transaction-
   scale), developer activity at 720h/30d (inherently slow-moving).

### Live-verified findings

- **A real bug caught during live verification, fixed before shipping**:
  the network-usage proxy's first live run showed `transfer_count=200`
  (exactly the fetch limit) for **every single** tested token — a red flag,
  not a coincidence. Investigating confirmed why: for actively-traded
  tokens, even 1000 fetched transfers (after raising the limit from 200)
  cover mere **hours** of real activity, not the nominal 7-day window —
  LINK's most recent 1000 transfers spanned only **~0.09 days (≈2.2
  hours)**; UNI ~0.06 days; ENA ~0.16 days; ONDO ~0.29 days; JASMY ~1.43
  days; STORJ ~1.50 days; ZRX ~2.57 days. Silently labeling all of these
  "7-day activity" would have been genuinely misleading (comparing tokens
  of very different trading volume as if on equal footing). Fixed by
  reporting the **real, computed `actual_window_days_covered`** and a
  `possibly_truncated` flag per observation instead of an unconditional
  nominal window — a regression test (`test_network_usage_flags_possibly_
  truncated_for_a_busy_token`) targets this exact case.
- **Entity-flow intelligence: real call succeeded, zero real matches this
  run.** Of this run's `TOP_CANDIDATES`, only LINK and UNI map to a
  Nansen-supported chain (both Ethereum) — a single real API call
  succeeded (`ENTITY_FLOW_INTELLIGENCE` status `OK`), but neither symbol
  appeared in the returned page of currently-tracked smart-money-active
  tokens. Consistent with an earlier live test this sub-phase, whose
  general (unfiltered) query returned mostly smaller-cap/newer tokens
  (e.g. one real universe asset, ENA, did appear with real data) —
  Nansen's tracked "smart money" cohort attention appears to concentrate
  away from large, established blue-chips like LINK/UNI, at least in the
  current window. A real, honest "no data this run" result, not a
  technical failure.
- **Judge wiring verified with zero LLM cost**: rebuilt the real Judge
  context for a live `TOP_CANDIDATE` (LINK) and confirmed both
  `network_fundamentals_usage` and `developer_activity` appear in the
  actual rendered prompt text, with **no changes to `app/judge/context.py`
  at all** — the existing generic per-asset `evidence_by_source` rendering
  (built in 3c) already surfaces any new `evidence_observations` source
  automatically.
- **Calibration re-run** (`scripts/calibration_baseline.py --source live`),
  persisted as a new, honestly-counted trial: still **0 resolved live
  decisions** (real horizons of 14–90+ days haven't elapsed) — reported as
  a genuine null result, same provisional framing 3f/3g/3h established, not
  presented as a confirmed before/after delta.

### Cost sizing

Confirmed: **zero new LLM cost**. Nansen's free tier is a real dollar-cost
consideration if ever upgraded (Pro: $49–69/month, documented here per the
task's own instruction, same treatment as 3c's Glassnode/3f's CoinGlass
deferrals) — not committed to this round; the free tier's real
constraint (10 credits/day, 5 credits/call) is disclosed above rather than
treated as unlimited.

### Tests

369 tests passing (`pytest`, no live credentials needed): `tests/
test_nansen.py` (4), `tests/test_github_activity.py` (6), `tests/
test_etherscan_tokentx.py` (4, including a live-verified real-address
sanity check), `tests/test_asset_intelligence_service.py` (11, including
mocked `UNAVAILABLE`/not-configured cases for every source and the
`possibly_truncated` regression).

### Known limitations / decisions

- **Entity-flow intelligence has no native-chain-coin coverage** — BTC,
  SOL, BNB, HYPE, and every other native coin in this project's universe
  are excluded from `NANSEN_CHAIN_BY_SYMBOL` deliberately, since verifying
  native-token inclusion behavior would have cost additional scarce free-
  tier credits. A real, disclosed gap, not an oversight.
- **The free Nansen tier's real sustainable rate is far better than
  initially estimated** — grouping by chain (not by asset) means a full
  `TOP_CANDIDATES` run typically costs only 1–3 real API calls (5 credits
  each), not one call per asset; the original "~1–2 assets/day" estimate
  was conservative and is superseded by this finding.
- **Network-usage figures are NOT a consistent N-day window across
  tokens** — busier tokens' `actual_window_days_covered` is much shorter
  than quieter tokens'; always check `possibly_truncated`/
  `actual_window_days_covered` before comparing two assets' figures
  directly.
- **CUSTODY_OTC_FLOW stays `NOT_IMPLEMENTED`** by explicit user decision,
  given no verifiable address source exists — revisit only if a real,
  citable source of custody-provider addresses is identified.

## Phase 4 — Paper trading execution, benchmarks, ongoing accuracy tracking

Builds the execution-simulation and benchmarking layer *underneath* the
decisions Judge/Risk Engine/Portfolio Construction already produce — no
Judge/Risk/Portfolio decision-logic changes. Every 3g/3h calibration/
stress-test number up to this point assumed costless, instant mark-to-mid
fills; this phase makes that assumption explicit and re-reports the
accuracy picture net of realistic execution costs, alongside (never
instead of) the original numbers.

### Task 1: order-book-aware fill simulator (`app/trading/`)

`app/trading/fill_simulator.py` — two real fill methods, each recorded on
every result:

- **`DEPTH_WALKED`**: a real order-book snapshot is available — walks the
  book level-by-level to compute a genuine volume-weighted average
  execution price, and reports a real **partial fill** (`fully_filled=
  False`, `filled_usd < requested_usd`) when the order exceeds the fetched
  depth, rather than assuming unlimited liquidity. Backed by two new,
  live-verified real client methods: `BinanceClient.fetch_order_book_depth`
  (public `/api/v3/depth`, no key — verified live: 100 real bid/ask levels
  for BTCUSDT) and `CoinbaseClient.fetch_order_book_depth` (public
  `/products/{id}/book?level=2`, no key — verified live: ~22,000/21,000
  real bid/ask levels for BTC-USD).
- **`VOLATILITY_SCALED_ESTIMATE`**: a documented, clearly-labeled fallback
  (a simple square-root market-impact form: slippage scales with recent
  realized volatility and the order's participation rate relative to
  typical daily volume) — used whenever no real depth snapshot exists.
  **This is every currently-resolved decision** — order books are not
  stored historically anywhere in this project, and exchanges don't serve
  historical depth via free APIs, so retroactive `DEPTH_WALKED` fills are
  genuinely impossible for past decisions (a real point-in-time
  constraint, not a shortcut). `DEPTH_WALKED` is built, tested, and
  live-verified, ready for real-time use the moment this system executes
  a fill as it happens.

Fee rates (`TAKER_FEE_RATE_BY_EXCHANGE`): Binance spot standard/VIP0 (0.10%
maker/taker, no BNB discount) and Coinbase Advanced Trade base tier (0.40%
maker/0.60% taker, <$10K 30-day volume) — each exchange's own commonly-
published standard rate; **not fetched from a live authenticated
fee-schedule API** (both exchanges' fee-schedule pages returned bot-
detection/JS-rendering walls when checked live, and exact current tiers
are account-specific) — re-verify periodically, same convention as
`llm/cost.py`'s `PRICING_PER_1K_TOKENS`.

### Task 2: extending `decision_outcomes` evaluation

Migration `0013` adds `realized_return_net_of_costs`/`assumed_fill_method`,
always stored alongside the original `realized_return`.
`scripts/apply_execution_costs.py` computed a net-of-costs figure for all
**109** currently-resolved decisions (all backfilled — no live decision has
resolved yet), using real historical volatility/volume as of each
decision's own entry and exit dates (point-in-time-safe via the same
`HistoricalSeries.as_of` convention 3e.1's replay established), with a
documented `ASSUMED_PORTFOLIO_NOTIONAL_USD=$10,000` paper-bankroll
reference for sizing the participation-rate term (this project tracks
fractional allocation only, no dollar total — a documented assumption, not
a measured figure).

A real methodological simplification, disclosed rather than hidden: a
one-time round-trip fee doesn't change how an asset's price moves day to
day (return/drawdown ratios are scale-invariant to a flat one-time cost),
so `realized_return_net_of_costs = realized_return - round_trip_cost_pct`
— a flat drag on the terminal directional-call figure, not a reconstructed
position-level P&L series. `round_trip_cost_pct` combines entry+exit fee
and entry+exit volatility-scaled slippage; verified with a known hand
computation in `tests/test_fill_simulator.py`.

**Real result — the calibration/reliability picture barely changes**:

| | Mark-to-mid | Net-of-costs | Delta |
|---|---|---|---|
| Hit rate (n=36 directional) | 0.8333 | 0.8333 | +0.0000 |
| Brier score | 0.1949 | 0.1949 | +0.0000 |
| Sharpe (decision-level) | 1.8214 | 1.7866 | −0.0348 (~3.5% relative) |
| DSR (n_trials=1) | 0.999985 | 0.999984 | negligible |

Hit-rate/Brier are **exactly unchanged** — no single decision's directional
call flipped sign once costs were applied (average drag: **0.21 percentage
points/decision**, small relative to this sample's typically much larger
real moves — single digits to +20%/-10%). This is a real, honest finding
at this project's current assumed position size ($10K notional,
single-digit-percent allocations), not a claim that execution costs never
matter — a materially larger real portfolio (higher participation rate
against real order-book depth) would show a bigger effect. Persisted as a
new calibration trial (`PHASE4_NET_OF_COSTS_COMPARISON`), same provisional
framing as every prior calibration re-run.

### Task 3: benchmark tracking (`app/benchmarks/baseline_comparison.py`)

Compared the system against real BTC buy-and-hold and a real equal-weight-
across-universe buy-and-hold (19 real assets with a full matching window),
over the exact real calendar window the system's own resolved decisions
span (2026-08-09 to 2026-09-05, 28 real daily points), identically costed
via the same `round_trip_cost_pct` methodology:

| | System (decision-level) | BTC buy-and-hold | Equal-weight universe |
|---|---|---|---|
| Sharpe | 1.7866 | 0.3135 (daily) | 0.3368 (daily) |
| Max drawdown | −0.1060 (worst single decision) | −0.0363 | −0.0620 |
| Total return, net of costs | — (directional, not cumulative) | +0.2279 | +0.3670 |

**A real methodological limitation, disclosed prominently, not glossed
over**: the system's Sharpe is computed over 36 individual decision-level
returns (each its own realized outcome over its own horizon), while the
baselines' Sharpe is computed over 28 continuous daily returns of a single
buy-and-hold position — **these are not the same statistical object** and
are not directly comparable in magnitude (a decision-level return
aggregates far more information per "observation" than one day's price
move, so the system's Sharpe is structurally larger for reasons unrelated
to genuine skill vs. buy-and-hold). No "the system beats the market" claim
is made from this comparison — it's reported as the real, honestly-costed
numbers with this caveat attached, consistent with 3g/3h's own standard
for what counts as a validated claim. A true apples-to-apples comparison
needs the system's own resolved decisions reconstructed as a continuous
portfolio equity curve, which requires live decisions to actually resolve
first (3g's own held-out-window finding) — noted as follow-up work, not
solved here.

### Task 4: portfolio-construction sizing review — decided against, for now

**Explicit decision: do not add a fuller portfolio-optimization step (risk
parity, constrained mean-variance) at this time.** Reasoning, grounded in
tasks 1–3's real findings:
- Execution costs are demonstrably small at this project's current
  position sizes (task 2's 0.21pp average drag) — there's no cost-driven
  case for smarter sizing yet.
- 3g found no genuine out-of-sample validation exists yet (the embargo gap
  finding), and 3h found insufficient real data (n=36 < required 50) to
  even validate the CURRENT simple sizing scheme's evidence weighting.
  Adding portfolio-optimization complexity now would introduce a new
  source of overfitting risk before the more fundamental data/validation
  gap closes — the same philosophy 3j's own gating already applies to new
  evidence sources.
- Revisit once either (a) enough live decisions resolve to give 3h's
  ranking and 3g's held-out-window check a real sample, or (b) real
  turnover/fee costs become material at larger position sizes or higher
  trading frequency than currently observed.

### Tests

392 tests passing (`pytest`, no live credentials needed): `tests/
test_fill_simulator.py` (13 — hand-computed VWAP/partial-fill/round-trip-
cost cases, the volatility-scaled fallback, and its known reference
computation), `tests/test_order_book_fetch.py` (4 — real response-shape
parsing for both exchanges, mocked), `tests/test_baseline_comparison.py`
(6 — hand-computed basket/drawdown/return cases).

### Known limitations / decisions

- **No live decision has resolved yet** — every net-of-costs/benchmark
  number in this phase uses the 109 backfilled decisions; the 50 real live
  decisions (3f/3g/3h/3i) remain unresolved, same standing finding as 3g's
  held-out-window result.
- **Fee rates are commonly-published standard rates, not live-fetched from
  an authenticated fee-schedule API** — both exchanges' public fee pages
  are bot/JS-gated; re-verify periodically.
- **`ASSUMED_PORTFOLIO_NOTIONAL_USD=$10,000` is a documented sizing
  assumption**, not a real tracked total — this project has no dollar-
  denominated portfolio value, only fractional allocation.
- **The system-vs-baseline Sharpe comparison mixes two different return
  periodicities** (decision-level vs. daily) — disclosed above, not
  resolved; a genuine apples-to-apples comparison needs a continuous
  system equity curve, which needs resolved live decisions to build.
- **`DEPTH_WALKED` fills are built, tested, and live-verified but not yet
  used on any real decision** — every currently-resolved decision predates
  this phase or is backfilled, so only the volatility-scaled estimate has
  real applicability today; the depth-walked path is ready for genuine
  real-time use going forward.

## Phase 5 — Read/query API, scheduling & dashboard

A read/query and orchestration layer over already-existing state (see
`doc/prompts/PHASE5_PROMPT.md`) — no new evidence sources, no Judge/Risk Engine/
Portfolio Construction changes, no order placement (that's Phase 6).

### Deployment scope — decided before any endpoint code was written

**Localhost/personal-machine only, not a public deployment.** Reasoning:

- Every phase of this project (1 through 4) has been operated entirely via
  local CLI by a single user, with credentials living in a local `.env`
  file never intended for shared or hosted use.
- No hosting/deployment infrastructure exists anywhere in this repo — no
  Dockerfile, no cloud config, no reverse proxy, no domain.
- The project's own safety posture has been consistently conservative
  throughout (PAPER ONLY everywhere; live trading explicitly gated behind
  a future, separate safety review in Phase 6+). Introducing a publicly-
  reachable service now would be a materially larger security surface than
  anything built so far, with no stated need for it.
- Phase 5's own stated purpose — replacing manual Supabase queries and CLI-
  log reading with a local view, for the single person operating this
  system — does not require remote or public access at all.

**Consequence for the access-control non-negotiable**: a single
env-configured API-key header (`X_API_KEY`) is a genuinely *sufficient*
minimum bar for this scope, not a deliberately under-scoped stand-in for a
public deployment. **If this is ever exposed beyond localhost** (accessed
from another device on a home network, or actually deployed to a server),
the security posture must be revisited *before* that happens — at minimum
TLS, a stronger auth mechanism than one static header, and rate limiting —
not treated as already covered by this decision.

### Task 1: FastAPI read/query layer (`app/api/`)

20 real, read-only (`GET`-only) endpoints, every one using an existing
Pydantic schema directly as its FastAPI response model (no parallel
redefinitions) — plus 4 small composed/join view models
(`app/api/schemas.py`) used only where no existing schema already fit
(e.g. joining a portfolio position with its decision's tracked outcome).
Adding these required several new, purely-additive read methods on
existing repositories (`get_recent`, `get_by_id`, `get_latest_full_universe`,
`get_cost_sum_by_table_since`, etc.) — no existing method was changed.

- **Screening**: `/screening/candidates`, `/screening/universe`,
  `/screening/regime`.
- **Assessments**: `/assessments/latest`, `/assessments/asset/{asset_id}`,
  `/assessments/adversarial/recent`, `/assessments/adversarial/asset/{asset_id}`.
- **Judge**: `/judge/decisions/recent` (filterable by `is_backfilled`),
  `/judge/decisions/{decision_id}`, `/judge/decisions/asset/{asset_id}/latest`,
  `/judge/reasoning-audits/recent`, `/judge/reasoning-audits/decision/{decision_id}`.
- **Portfolio**: `/portfolio/positions` (raw), `/portfolio/state` (joined
  with each position's tracked outcome — mark-to-mid vs. net-of-costs and
  **`assumed_fill_method` surfaced explicitly per fill**, never hidden
  again after Phase 4 built it specifically to make this visible).
- **Calibration**: `/calibration/runs/recent`, `/calibration/outcomes/recent`
  (filterable by `is_backfilled`), `/calibration/evidence-value/recent`,
  and `/calibration/summary` — a **live-computed** (never cached/hardcoded)
  hit-rate/Brier/Sharpe/DSR summary, re-derived from real `decision_outcomes`
  on every request using the same `app/benchmarks/statistical_validation.py`
  functions 3g built, so it stays accurate as more decisions resolve. Both
  the by-regime and held-out-window gaps render as explicit, worded null
  states, not omitted fields.
- **Signal sources**: `/signal-sources` — every source's real status/notes,
  exactly as stored.
- **Cost**: `/cost/summary` — `COST_TRACKED_TABLES` sums by table, for
  today and this month, against configured caps, with an explicit note
  that this is the app's own tracked ledger, not a live provider-billing
  balance (the cost-reconciliation non-negotiable).

Point-in-time integrity note: none of these endpoints reconstruct
"what did the system know as of date X" from revisable evidence — they
serve already-computed, already-persisted records (candidates, decisions,
outcomes), so 3a's `as_of` convention doesn't directly apply to anything
built in this pass. It remains the correct convention to reach for if a
future endpoint ever needs genuine point-in-time evidence reconstruction.

### Task 2: access control

A single `X_API_KEY` (env-configured, checked via the `X-API-Key`
header on every endpoint except `/health`) — see the deployment-scope
decision above for why this is a sufficient bar for this project's scope.
Every unhandled exception is caught by a global handler that returns a
hardcoded, generic `{"detail": "Internal server error"}` body — never the
real exception message or traceback, which could otherwise leak a
configured secret embedded in a lower-level client's own error string.
Verified with a test that deliberately raises an exception containing
realistic fake Supabase/OpenRouter/database-URL secret substrings and
confirms none of them reach the response body.

### Task 3: scheduling — deferred, not built

**Decided against building scheduling in this phase.** Reasoning:

- This project is still under active, manual, deliberately-reviewed
  development (3j remains gated on 3h's findings, which haven't changed;
  Phase 6 hasn't started) — introducing autonomous scheduled runs now would
  let cost and decisions accumulate faster than they're being manually
  reviewed, cutting against this project's own "verify before continuing"
  discipline that every sub-phase so far has depended on.
- The real current bottleneck (3g's embargo/held-out-window finding, 3h's
  insufficient sample size) is **elapsed real-world time** for existing
  decisions to resolve (real horizons of 14–90+ days) — running the
  pipeline more often on a timer would not accelerate this at all, only
  add more pending decisions to the same queue.
- Scheduling has a real, non-trivial cost of its own per this phase's
  non-negotiables (a new job-history table and migration, wall-clock
  timeout enforcement, CostGuard re-verification) for a benefit that isn't
  clearly needed yet — the same "don't add complexity before a validated
  need" reasoning already applied in Phase 4's sizing-review decision and
  3j's own gating philosophy.
- Revisit once either the system reaches a more stable, less-actively-
  changing state, or a concrete cadence need emerges that manual
  triggering genuinely can't keep up with (e.g. wanting fresh candidate
  discovery daily without a human present to run it).

### Task 4: minimal dashboard

A single static HTML page (`app/api/static/dashboard.html`, served at `/`)
with vanilla JS `fetch()` calls to the JSON endpoints above — no new
frontend framework or build step, consistent with "pick whichever is less
work." The page itself carries no data and needs no key to load; the
viewer pastes their `X_API_KEY` once into a field (stored in that
browser's `localStorage` only), and every subsequent data fetch goes
through the same `X-API-Key`-gated endpoints as any other caller — the
dashboard has no special, unauthenticated access path of its own. Sections:
signal sources, cost/spend, portfolio state (with per-fill
`assumed_fill_method`), calibration summary, and recent Judge decisions
with full thesis text — backfilled/live and null/insufficient-data states
rendered as distinct, visibly-labeled badges, never merged into one figure.

### Real findings from live-wiring against the actual Supabase project

**Verification method, disclosed honestly**: the JSON API's 20 endpoints
were live-verified with a real running server (`uvicorn app.api.main:app`)
against the real Supabase project. The dashboard's own inline JS was
verified by extracting it and executing it headlessly under Node against
that same real running server (DOM calls stubbed just enough to capture
rendered HTML) — **not in an actual browser**: the Chrome browser tool's
extension wasn't connected in this environment, so a real-browser
screenshot check wasn't possible. This headless method still exercises the
literal shipped JS unmodified against real data end-to-end, and it's what
actually caught both bugs below — but it's a real, disclosed substitute
for the non-negotiable's "at least one real, known value confirmed
end-to-end," not the identical thing.

**Two real bugs found and fixed via this live-verification pass:**

1. `/calibration/summary` crashed on real data — `JudgeDecisionRecord.
   macro_sensitivity` was declared as a required `str`, but every one of
   the 109 real backfilled `judge_decisions` rows genuinely has `NULL`
   there (the column didn't exist before migration 0010/Phase 3f). This
   had never surfaced before because every previously-shipped code path
   only ever read a decision's *latest* row per asset — always a real,
   macro_sensitivity-populated, post-3f decision — never reached back into
   older, pre-3f rows the way this phase's `get_recent`/`get_by_id`
   endpoints legitimately do. Fixed by making `JudgeDecisionRecord.
   macro_sensitivity` nullable (`str | None = None`, `None` meaning
   "predates 3f," never a fabricated placeholder) — `JudgeDecisionItem`
   (the LLM-output validation schema for brand-new decisions) correctly
   stays required, unchanged. A regression test targets this exact case.
2. The dashboard's inline JS had a genuine syntax error in the calibration
   section (an unnecessarily backslash-escaped quote inside a template
   literal, `\\"..\\"` where the literal needed none) — this would have
   broken the **entire** script block in a real browser, not just that one
   section, silently leaving all five panels stuck on "Loading…". Only
   caught because the headless check actually executes the shipped JS
   rather than eyeballing the source; fixed by using single-quoted nested
   strings instead.

After both fixes, every endpoint and every dashboard section was
re-verified against real data, including the slow path below.

**A real, measured performance finding**: `/calibration/summary` takes
**~8.6 real seconds** to respond over HTTP against the live project — the
N+1 query pattern already flagged below (one repository round-trip per
resolved decision, 179 of them) is not just a theoretical concern but a
real, measured latency, confirmed with `curl` timing against the running
server. Usable today at this project's real scale, but the first thing to
fix if this endpoint is ever called more frequently or the decision
history grows materially.

Real values confirmed in every section: e.g. `/calibration/summary`
correctly reproduced the exact hit_rate=0.8333/brier=0.1949/DSR≈0.99999
figures 3g/Phase 4 already established, now computed live rather than
hardcoded; the dashboard's Judge-decisions panel rendered a real, current
live UNI thesis; the signal-sources panel rendered real `CoinGecko`/`News`
`OK` rows and a real `CoinGlass` `NOT_IMPLEMENTED` row.

### Tests

418 tests passing (`pytest`, no live credentials needed): `tests/
test_api_auth.py` (5 — health check needs no key, missing/wrong key
rejected, correct key accepted, missing configured key fails safely),
`tests/test_api_endpoints.py` (18 — one or more per endpoint group, using
FastAPI's `dependency_overrides` with fixture data, never a live call),
`tests/test_api_secrets.py` (2 — the explicit secret-leak test described
above, plus confirming a submitted wrong key is never echoed back). No
scheduling-related test was needed since scheduling wasn't built.

### Known limitations / decisions

- **`/calibration/summary` does one repository call per resolved decision**
  (a real N+1 query pattern) — measured live at **~8.6 real seconds** over
  HTTP against the live project (179 `decision_outcomes` rows). Usable
  today at this scale, but the first thing to fix (a proper join/batch
  method) if this endpoint is called more frequently or history grows
  materially.
- **The dashboard stores its API key in browser `localStorage`**, matching
  this project's localhost/personal-machine deployment scope — would need
  a real secret-management approach if this were ever exposed beyond that
  scope (see the deployment-scope decision above).
- **RESOLVED (2026-09-06): real-browser visual verification.** Originally
  tracked as an outstanding item because the Chrome browser tool's
  extension would not connect (verified only headlessly — Node executing
  the real shipped JS against the real live server — plus `node --check`
  for syntax). The extension connected in a later documentation-and-
  verification pass; the dashboard was opened in an actual browser against
  the real running server and every panel — including both known-fragile
  empty states, the regime-NULL calibration-by-regime message and
  `Resolved (live): 0` — rendered correctly as honest empty/zero states,
  not blank or silently broken. Zero JavaScript console errors on load,
  on reload, or after interacting with the (empty-submit) holdings form.
  This closes the item — no further headless-substitute caveat applies to
  this dashboard.
- **No scheduling was built** — see task 3's reasoning above; this can be
  revisited without any of today's endpoint/dashboard code changing.

## Phase 5a — Real current-holdings ground truth

Before this sub-phase, nothing in the system tracked what was actually held.
`current_allocation` — the fraction Portfolio Construction and the Risk
Engine size every decision against — has to come from somewhere; this
sub-phase found where it actually came from, showed why that wasn't a real
ground-truth input, and replaced it with one.

### Task 1 finding: the existing mechanism was self-derived, not ground truth

`portfolio_positions` (`PortfolioPositionRepository`) was the sole prior
source of `current_allocation`, read in `app/main.py` and fed through the
Risk Engine into Portfolio Construction. On inspection it turned out to be:

- **Entirely self-derived.** The only writer of this table was
  `PortfolioConstructionService.apply()`'s own `.upsert()` call
  (`app/portfolio/construction.py`) — the system was sizing every new
  decision against the *output of its own prior sizing decision*, never
  against anything entered from outside. There was no real ground truth
  anywhere in the loop.
- **Mutation-based, not append-only**, breaking this project's own
  point-in-time-integrity convention (used everywhere else since 3a) — a
  historical "what did the system believe it held on date T" query wasn't
  answerable.
- **A stored fraction, never a real quantity or cost basis** — no way to
  represent "I hold 0.3 BTC" as such, only "the system currently treats BTC
  as 24% of a hypothetical whole."

### New table: `holdings_ledger`

```sql
create table holdings_ledger (
    id              uuid primary key default gen_random_uuid(),
    asset_id        uuid references assets(id) on delete restrict,
    quantity        numeric not null check (quantity >= 0),
    cost_basis_usd  numeric,
    recorded_at     timestamptz not null default now(),
    created_at      timestamptz not null default now()
);
```

(migration `0014_phase5a_holdings_ledger.sql`, applied via the Supabase SQL
Editor — `scripts/apply_migration.py` continues to fail on the same
long-stale `DATABASE_URL` password noted for migrations 0011–0013.)

- **Append-only.** Editing a holding is a new row with a newer
  `recorded_at`; removing one is a new row with `quantity=0`. Nothing is
  ever updated or deleted in place — "what did I hold as of date T" stays
  answerable via `GET /holdings/history`, consistent with every other
  revisable-state table in this project since 3a.
- **`asset_id=NULL` is the reserved cash line.** `quantity` on that row is a
  stated USD amount directly, not asset units. This convention exists
  specifically because the real portfolio runs at ~21% allocated (Phase 4's
  stress-test finding) — most of it is cash, and Portfolio Construction is
  explicitly designed to allow that ("never forces full capital
  deployment"). If total portfolio value were derived purely from summed
  real-asset holdings, entered holdings would always equal 100% of that
  total by construction, with no way to represent uninvested cash at all.
  Requiring an explicit cash line closes that gap without introducing any
  new separately-tracked total-value state — confirmed with the user before
  implementing, per their explicit correction to the original design.
- **`compute_current_allocations`** (`app/portfolio/holdings.py`) is a pure
  function: latest holdings (one row per asset plus the cash line) × real
  current prices (via `MarketSnapshotRepository.get_latest_snapshot`) → a
  `{asset_id: fraction}` dict, cash included in the denominator only.
  Explicitly handles, rather than crashing or silently falling back:
  - **Cold start** (empty ledger, before any real holdings are ever
    entered) → every asset's fraction is `0.0`. This is a legitimate
    existing state (an all-cash portfolio that hasn't recorded its cash
    line yet), not an error.
  - **Zero or negative total value** → every fraction is `0.0` rather than
    a division error.
  - An asset with a recorded holding but no available price snapshot is
    skipped from the total rather than crashing the whole computation.
  - 8 tests in `tests/test_holdings.py` cover all of the above plus
    multi-asset-plus-cash, no-cash-line, removed-holding-as-zero, and
    no-entered-holding-defaults-to-zero.

### `portfolio_positions`: retired as an input, kept as derived output

`app/main.py`'s judge pipeline now sources `current_allocation` solely from
`holdings_ledger_repo.get_latest_holdings()` + real price lookups, never
from `portfolio_positions`. `PortfolioConstructionService` itself is
**unchanged** — it still writes `portfolio_positions` via its own
`.upsert()` after every run, and that continues going forward. Stated
plainly, as asked: `portfolio_positions` is fully retired as an input to
`current_allocation` computation, and kept only as Portfolio Construction's
own derived bookkeeping/audit record of "what the system's last sizing
decision produced" — it is no longer read by anything upstream of that
service.

### New endpoints (`app/api/routers/holdings.py`)

The one narrow, intentional exception to Phase 5's otherwise strictly
read-only API — ground truth only, never a decision override. The request
schema has no `decision`/`target_allocation`/or any other Judge/Risk
Engine/Portfolio Construction output field, by construction, not just by
convention.

- `POST /holdings` — validates `asset_id` against a real, currently-tracked
  asset (422 if unknown) unless `null` (the cash line); always **inserts**
  a new row, never updates. Returns 201.
- `GET /holdings` — latest row per asset (including cash) — the actual
  ground-truth state Portfolio Construction reasons against right now.
- `GET /holdings/history` — full append-only history, optionally filtered
  by `asset_id` or `cash=true`; omitting both returns everything ever
  recorded.
- Dashboard: a new "Real holdings (ground truth)" form (asset symbol/id or
  blank/"CASH" for the cash line, quantity, optional cost basis) plus a
  render of current holdings — verified with `node --check` for syntax
  (confirmed clean) but, like the rest of the dashboard, not yet checked in
  an actual browser (see Phase 5's still-outstanding real-browser item
  above, which now also covers this new form).
- **Minor known limitation, not a non-negotiable violation**: `POST
  /holdings`'s response echoes back the submitted fields with `id: null`
  rather than the database-assigned id, since the handler returns the
  locally-constructed record rather than re-querying after insert. `GET
  /holdings`/`/holdings/history` correctly return the real database id.
  Cosmetic only — the insert itself, and everything read afterward, is
  correct.

### Live verification (non-negotiable, not skipped)

Performed against the live Supabase project and a live local API server
(`uvicorn app.api.main:app`), then a real `python -m app.main --with-judge`
run against live OpenRouter — not fixture tests alone:

1. Confirmed cold start first: before any row existed, `select * from
   holdings_ledger` returned `[]` — the intended pre-entry state.
2. `POST /holdings` (via `curl` against the real running server, real
   `X-API-Key`) three times: a cash line (`$2000`), a real BTC holding
   (`0.01 BTC`, asset not this run's `TOP_CANDIDATE` — included to confirm
   holdings outside this run's candidate set are still priced and included
   in the total), and a real SOL holding (`5 SOL`, SOL *was* one of this
   run's real `TOP_CANDIDATE`s). `GET /holdings` immediately reflected all
   three with real database ids and timestamps.
3. Ran `python -m app.main --with-judge` for real (run
   `RUN-20260906-114219`, real cost **$0.2133**, well inside the
   $10.55/$25.88 real remaining daily/monthly `CostGuard` budget checked
   beforehand). The run re-fetched live prices for BTC ($79,910) and SOL
   ($106.41), producing a real Judge decision set including SOL.
4. Added a permanent audit-log line
   (`app/main.py`, right after `compute_current_allocations`) logging the
   full computed allocations dict for every run going forward. Its output
   for this run showed **SOL: 0.15971961634870838** and
   **BTC: 0.23988712606757426**. Hand-computed independently from the same
   real prices and quantities: SOL = `5 × 106.41 / (2000 + 0.01×79910 +
   5×106.41)` = 0.159720; BTC = `0.01×79910 / (same total)` = 0.239887 —
   **exact match to 6 decimal places**.
5. Portfolio Construction's real output for this run included `('SOL',
   'REDUCE', 0.1542)` — a REDUCE action starting from the real
   0.159720 current allocation, turnover-capped down to 0.1542 (SOL
   appeared in this run's real turnover-capped list). This is direct
   confirmation that Portfolio Construction reasoned against the entered
   ground-truth holdings, not a stale or fixture value.
6. Confirmed `portfolio_positions` was updated afterward with SOL's
   `current_allocation = 0.15417854094437008` — the same 0.1542 figure,
   full precision, written by `PortfolioConstructionService`'s own
   `.upsert()` exactly as expected of its now-derived-output-only role.
7. Confirmed `holdings_ledger`'s history after the run still contained
   exactly the 3 rows entered — append-only, nothing mutated by the
   pipeline run itself.

Both the cash-handling design and the `portfolio_positions`-retirement/
cold-start behavior were confirmed explicitly with the user before
implementation began, per their own request, and both are borne out by the
live run above.

### Tests

436 tests passing total (`pytest`, no live credentials needed) — 18 new
since Phase 5's close: `tests/test_holdings.py` (8, the pure-function edge
cases above), `tests/test_api_holdings.py` (9, endpoint validation +
append-only-history behavior via `dependency_overrides`, no live calls),
plus one addition to `tests/test_api_secrets.py` confirming the same
secret-leak protection covers the new `/holdings` write path.

## Phase 5b — Dashboard live pricing, transactional holdings, symbol entry, P&L

Driven entirely by real user feedback while using the Phase 5a dashboard
day-to-day, not a pre-planned sub-phase: a genuine Windows concurrency bug
was hit first, then three separate feature requests arrived incrementally
(current price display, a Judge-decisions token column, and finally a
substantial holdings-model change), each investigated and implemented in
turn.

### Fix: real WinError 10035 concurrency bug under the dashboard's load

The user reported real request failures on dashboard load. Root cause: a
single cached (`@lru_cache`) `Client`'s shared `httpx.Client`, hit
concurrently by FastAPI's sync-endpoint threadpool — a genuine Windows-
specific httpx/httpcore rough edge (`httpx.ReadError`, `WinError 10035`,
"a non-blocking socket operation could not be completed immediately"),
not a Supabase- or app-logic problem. A stress-test script
(`concurrent.futures.ThreadPoolExecutor`, 8 endpoints × 15 rounds = 120
calls against the live local server) measured a real **40% failure rate**
before any fix. Passing a custom `httpx.Client` with a retrying transport
(`httpx.HTTPTransport(retries=3)`) into `create_client(...,
options=ClientOptions(httpx_client=...))` (`app/database/client.py`)
brought that to **0/120 failures, confirmed on two independent runs** —
proven empirically, not just reasoned about.

### Stored (collected) price vs. genuinely live spot price

The user first asked for a "current price" display; once shown, they
caught for themselves that it was really just the last *collected* price
(`python -m app.main` is a manual, periodic batch step, not a live
stream) — a real, user-caught gap, not a self-caught one. Resolved by
adding a second, entirely separate live price rather than replacing the
first, so the real pipeline (Risk Engine, Portfolio Construction) and the
dashboard's stored-value numbers can never silently disagree with a
display-only figure:

- `app/market_data/live_price.py`'s `fetch_live_price()` tries Binance's
  `/ticker/24hr` first, falls back to Coinbase's `/products/{sym}-
  USD/ticker` for symbols with no Binance USDT pair (confirmed live for
  HYPE, STORJ) — the same Binance-primary/Coinbase-fallback convention
  Phase 3b established for volatility/drawdown.
- `price_usd`/`price_as_of` (stored, from `market_snapshots`) feed
  `value_usd`/`allocation`/`unrealized_pnl_*` everywhere; `live_price_usd`/
  `live_price_as_of`/`live_price_source` are display-only on `GET
  /holdings` and `GET /portfolio/state`, never read by any real
  computation.
- Dashboard renders both with visually distinct labels/timestamps
  (`renderStoredPrice`/`renderLivePrice`) so freshness is never
  overstated, consistent with this project's "Last decided"/"Last
  updated" timestamp convention elsewhere.

### Recent Judge decisions: token column

Same class of gap as Phase 5a's original `portfolio_positions`/regime
fixes — `JudgeDecisionRecord` only stored `asset_id` (a raw UUID). Added
`JudgeDecisionView` (`app/api/schemas.py`) wrapping the existing record
whole (`decision: JudgeDecisionRecord`) plus a joined `symbol: str`,
resolved in `get_recent_decisions()` via the same active-assets lookup
dict pattern used elsewhere.

### Holdings: from snapshot-per-asset to genuinely transactional

The user asked to see per-unit cost and unrealized P&L against real
holdings; walking through the implementation surfaced that
`cost_basis_usd` was a *total*, not a per-unit price, and had no
enforced or documented semantic anywhere in the code. Resolving that,
the user asked for three things at once, each confirmed explicitly
before implementation: (1) P&L computed against the stored price only,
never the live spot price — for the same reasons `price_usd` stays
separate from `live_price_usd` above; (2) a real `purchased_at`
timestamp distinct from `recorded_at`, explicitly reframing
`holdings_ledger` as a transactional ledger rather than a snapshot-per-
asset table; (3) symbol-based entry (`"SOL"`, not a raw asset UUID)
with server-side lookup/validation.

Requirement (2) had a real, non-obvious implication for the live
pipeline the user was asked to confirm before it was touched: did
multiple BUY rows for the same asset now need to **sum** (a genuinely
transactional position), replacing Phase 5a's "latest row wins" semantic
that `get_latest_holdings()` implemented? The user confirmed yes.

- **Migration `0015_phase5b_holdings_transactions.sql`** (applied via the
  Supabase SQL Editor, same stale-`DATABASE_URL` pattern as every
  migration since 0011) adds `purchased_at timestamptz` (nullable — no
  fabricated backfill onto pre-existing rows) and `transaction_type text
  not null default 'BUY' check (in ('BUY','SELL'))` to `holdings_ledger`.
- **`aggregate_current_holdings()`** (`app/portfolio/holdings.py`, new,
  pure) replaces `get_latest_holdings()` as the input to
  `compute_current_allocations()` (itself left completely unchanged — it
  already assumed "one row per asset," now true by construction rather
  than by "latest wins"). Per asset: BUYs add to quantity and cost basis;
  a SELL reduces quantity and reduces cost basis *proportionally*
  (weighted-average-cost method, an explicit, stated policy choice — not
  FIFO/LIFO), and defensively clamps quantity at zero rather than going
  negative or crashing. The cash line (`asset_id=None`) is explicitly
  **unchanged** by this — it stays the single latest absolute stated USD
  total, never summed across multiple cash rows, a deliberately narrow,
  explicitly-scoped choice (not a deposit/withdrawal ledger).
- **SELL validation** happens at two layers: the pure aggregation function
  defensively clamps at zero (never crashes/goes negative) but isn't the
  real gate; `POST /holdings` itself rejects (422) a SELL that would
  exceed the real current aggregated position, checked live —
  `{"asset_symbol":"SOL","quantity":9999,"transaction_type":"SELL"}`
  against a real 5-SOL position returned `422 "Cannot sell 9999.0 SOL —
  only 5.0 currently held."`
- **Symbol-based entry**: `AssetRepository.get_by_symbol()` (case-
  insensitive `ilike`, same "any tracked status, not just active" rule as
  `get_by_id`) resolves `HoldingsEntryRequest.asset_symbol`; an unknown
  symbol is rejected 422 rather than silently creating a row — checked
  live, `{"asset_symbol":"NOTAREALTOKEN","quantity":1}` returned `422
  "'NOTAREALTOKEN' is not a tracked asset symbol..."`. A new `GET
  /holdings/valid-symbols` endpoint (active assets only — a deliberately
  narrower, real UX choice than what `POST /holdings` itself accepts, not
  a validation-rule change) backs the dashboard form's `<datalist>`
  autocomplete, confirmed live to return the real 22-symbol active list.
- **`GET /holdings`** now also returns `cost_per_unit` (`cost_basis_usd /
  quantity`) and `unrealized_pnl_usd`/`unrealized_pnl_pct` (against
  `value_usd`, i.e. the stored price — never the live spot price),
  `None` whenever no cost basis was ever entered. Confirmed live against
  the real portfolio: SOL (5 units, $500 total cost basis) → cost/unit
  $100, value $531.10 at the real $106.22 collected price →
  **+$31.10 (+6.22%)**; BTC (0.01 units, $600 cost basis) → cost/unit
  $60,000, value $798.16 at $79,816 → **+$198.16 (+33.03%)** — both
  hand-verified against the real API response.
- Dashboard form rebuilt: symbol input with `<datalist>` autocomplete
  (confirmed live to populate with the real active-symbol list), a
  Buy/Sell selector, and a purchased-date input, posting `asset_symbol`/
  `transaction_type`/`purchased_at` per the new schema. The holdings
  table gained Cost/unit and color-coded Unrealized P&L columns
  (`renderPnl`, green/red by sign, consistent with the existing
  `renderDivergingBar` convention). A new collapsed "Show full
  transaction history" panel (`GET /holdings/history`, unchanged
  endpoint) makes the transactional model visible in the UI, not just
  correct server-side — confirmed live to render real BUY rows with
  their type badge, per-transaction cost basis, and purchased-at date.

### Live verification (non-negotiable, not skipped)

Performed against the live Supabase project (post-migration) and a
restarted local API server: `GET /holdings/valid-symbols` returned the
real 22-symbol active list; `GET /holdings` returned the real aggregated
SOL/BTC/CASH position with correct `cost_per_unit`/`unrealized_pnl_usd`/
`unrealized_pnl_pct` (hand-verified above); the oversell and invalid-
symbol rejections were both confirmed live (422s, exact messages above,
no rows written on rejection); the dashboard was reloaded in an actual
browser — screenshot-confirmed rendering of the new price columns, P&L
column, symbol datalist (verified via direct DOM inspection that it
contains the real live symbol list), and expanded transaction-history
table, with zero console errors on page load. A real successful BUY/SELL
submission through the form itself was deliberately left to the user
rather than performed automatically, since it permanently writes a real
row to the user's own ground-truth ledger — not run without asking.

### Tests

461 tests passing total (`pytest`, no live credentials needed) — 25 new
since Phase 5a's close: 6 in `tests/test_holdings.py` for
`aggregate_current_holdings` (multi-buy summing, proportional-cost-
reduction on partial sell, full-sell removal, oversell clamping, cash-
never-summed, integration with `compute_current_allocations`);
`tests/test_api_holdings.py` fully rewritten (26 tests, replacing the
prior 9) covering symbol lookup/validation, SELL validation, transactional
summing through the real API, cost/PnL computation, the new
`/holdings/valid-symbols` endpoint, and `purchased_at`/`transaction_type`
round-tripping; plus a portfolio-state stored/live-price test in
`tests/test_api_endpoints.py` and a fix to `tests/test_api_secrets.py` for
the `asset_id`→`asset_symbol` rename.

### Addendum: decision horizon/resolution date, and a first-ever news endpoint

Two more real gaps, found by the user directly reading the dashboard and
asking "is X shown?" rather than a planned addition:

- **`investment_horizon_days`/"resolves by"** — the Judge already stores a
  real per-decision `investment_horizon_days`, returned by `GET
  /judge/decisions/recent` since Phase 5a, but the dashboard's "Recent
  Judge decisions" table never rendered it. Added as two columns:
  `Horizon` (the raw stored value, e.g. `45d`) and `Resolves by` — computed
  **client-side** in `dashboard.html` as `created_at + horizon_days`,
  deliberately the exact same formula
  `app/benchmarks/evaluation_service.py`'s real resolution logic uses
  (`horizon_end = outcome.decision_timestamp + timedelta(days=outcome.horizon_days)`,
  and `decision_timestamp` is set from the same `now` as the decision
  record's own `created_at` in `app/judge/service.py`) — not a new,
  separately-invented "next update" concept. No backend or schema change
  needed; both source fields were already in the API response.
- **`GET /news/recent`** (new — `app/api/routers/news.py`) — the first-ever
  API exposure of `app/news/`'s collected articles. That data has existed
  since the news-ingestion pipeline was built (feeding the Judge's
  research context internally via `NewsRepository.get_recent_relevant_news`),
  but was never reachable outside the pipeline itself until now.
  `NewsRepository` has no "all news, unfiltered" read method — only a
  per-symbol one — so the endpoint calls it once per currently-active
  asset symbol, merges, de-dupes (an article relevant to multiple assets
  would otherwise appear once per symbol), and sorts by `published_at`
  (`days` window default 7; see the addendum below for `limit`'s later
  change to "unlimited by default"). Returns
  `NewsArticle` directly (no join/view wrapper needed — `relevant_assets`
  already stores real symbols, per `app/news/relevance.py`'s keyword
  matcher, never raw asset ids). A new "Recent news" dashboard panel
  renders it — confirmed live to show real CoinTelegraph/CoinDesk/Decrypt
  articles matched to real held/tracked assets (BTC, ETH, XRP). Article
  title/source/summary are genuinely untrusted third-party RSS content
  (unlike the LLM-authored thesis text elsewhere on this page) — escaped
  via a new `escapeHtml()` helper before going into `innerHTML`, and a
  title is only rendered as a clickable link when its URL scheme is
  `http(s)://`, closing an XSS gap this feature would otherwise have
  introduced.

461 → **466 tests** (5 new in `tests/test_api_news.py`: empty-result
cold start, newest-first sorting, cross-asset dedup, `limit` truncation,
and confirming `relevant_assets` carries real symbols). Live-verified
against the real Supabase `news` table and a restarted local server —
real articles returned, real symbols joined correctly, dashboard
screenshot-confirmed with zero console errors.

### Addendum 2: deterministic decision ordering, unlimited news, a "Screened tokens" section

Three more requests from the same read-the-dashboard-and-ask-questions
pattern:

- **"Recent Judge decisions" column order, not a row re-sort** — the
  request ("sort the columns: date desc, then token name, then source and
  then decision, and then confidence") was initially misread as a
  multi-key ROW sort (by `created_at`, then `symbol`, then source, then
  `decision`, then `confidence`) and implemented client-side in
  `loadJudgeDecisions()`. That was wrong: the user flagged it as
  incorrectly sorted. Corrected to what was actually asked — a COLUMN
  reorder (Date, Token, Source, Decision, Confidence, ...; Token now
  comes before Source), with rows left in the API's own order (already
  newest-first — `JudgeDecisionRepository.get_recent` orders by
  `created_at desc`), no client-side row sort at all. Root cause of the
  original "incorrect" appearance: the Date column showed only the date
  portion (`created_at.slice(0, 10)`), so decisions from the same run
  looked tied even though their real timestamps differ — fixed by showing
  the full timestamp (`new Date(created_at).toLocaleString()`) instead of
  just the date, so the real (correct) API order is visibly correct too.
- **`GET /news/recent`'s `limit` now defaults to `None` (unlimited)**,
  not 20 — the dashboard's "Recent news" panel showed only a top-20 slice
  of the last 7 days by construction, not because more didn't exist.
  `NewsRepository.get_recent_relevant_news`'s own per-symbol cap is still
  a required int (real internal callers in `app/judge/context.py` and
  `app/llm/*.py` rely on that contract to bound LLM prompt size), so
  `limit=None` is translated to a large internal sentinel
  (`_EFFECTIVELY_UNLIMITED_PER_SYMBOL_CAP = 10_000`) rather than changing
  that method's signature. `limit` still works as an explicit cap for any
  caller that wants one (`tests/test_api_news.py`'s existing truncation
  test still passes `limit=2`). Confirmed live: 45 real articles now
  returned for the last 7 days (up from a hard 20), 46 real rows (45 +
  header) confirmed rendered via direct DOM inspection.
- **New "Screened tokens" section** (`GET /screening/tracked`, new;
  `/screening/universe` and `/screening/candidates` already existed since
  Phase 5 but were never surfaced on the dashboard) — answers the user's
  own question ("only a certain set of tokens is tracked, not the whole
  universe?") visually, grouped by the three real narrowing layers:
  **Layer 1** (screened universe — top `SCREENING_UNIVERSE_SIZE`, default
  30, by CoinGecko market cap; `ScreenedUniverseRepository.get_latest_full_universe()`),
  **Layer 2** (top candidates — the top `TOP_CANDIDATES_SIZE`, default 10,
  of Layer 1 by composite factor score; `get_latest_top_candidates()`),
  **Layer 3** (currently tracked — `AssetRepository.get_active_assets()`,
  accumulated across every screening run's Layer-2 promotions plus the
  initial manually-seeded set, sorted by symbol; this is the actual set
  news matching, Judge decisions, and holdings entry all operate on).
  Confirmed live against the real screened_universe/assets tables: 30 /
  10 / 22 rows respectively — Layer 3 (22) exceeds Layer 2's per-run size
  (10) because it accumulates over multiple runs, exactly as documented,
  not a bug. `Asset` and `ScreenedAsset` are reused directly as response
  models (both already existed, no view wrapper needed). Layer 1's rows
  are sorted by `market_cap` descending (its own defining criterion — "top
  N by market cap") rather than by the `rank` column (a separate
  composite-factor rank, kept visible with a clarifying tooltip since it
  no longer matches this table's row order) — confirmed live: BTC
  ($1.6T) first down to BUIDL ($2.8B) last, `rank` values now genuinely
  scattered (13, 12, 8, 10, 5, ...) since they reflect a different
  ordering criterion.

461 → 466 → **468 tests** (2 new: `test_no_limit_by_default_returns_every_matching_article`
in `tests/test_api_news.py`, and `test_get_tracked_assets_sorted_by_symbol`
in `tests/test_api_endpoints.py`. Neither the Judge-decisions column
reorder nor Layer 1's market-cap sort has pytest coverage — both are
dashboard-only JavaScript — verified live in the browser instead, per
this project's live-verification discipline for frontend-only logic).

### Addendum 3: `signal_sources.enabled` removed — dead since 3a, never wired to real behavior

A user question about the dashboard's "Signal sources" panel ("Binance
shows `OK`/not enabled — but Binance data is already being sourced?")
surfaced that `enabled` had been actively misleading, not just unused.
Root cause, confirmed by grep across the whole codebase: it was seeded in
Phase 3a (`migrations/0003_phase3a_universe_provenance.sql`) — before any
source besides CoinGecko/News existed, so every other row defaulted to
`false` — and nothing ever wrote to it afterward as sources were later
actually implemented (`SignalSourceRepository.update_status` only ever
writes `status`; see also the Phase 3g calibration-trial-count aside above
that independently found the same thing). Its only read anywhere was the
dashboard's own "yes"/"no" display column (Phase 3b's known-limitation
bullet above already flagged it as "informational only," but the column
persisted, still showing stale `false` values for real, working, free
sources like Binance).

Rather than fix the data (a one-time `UPDATE ... SET enabled = true WHERE
status = 'OK'`) or build real per-source gating logic, the column was
**dropped entirely** (`migrations/0016_drop_signal_sources_enabled.sql`)
— there was no real plan to ever wire it into actual behavior, so keeping
dead schema around to repair indefinitely wasn't worth it over just
removing it. Removed from `SignalSource` (`app/database/models.py`),
`SignalSourceRepository`'s docstring, and the dashboard's Signal Sources
table (`Enabled` column deleted). 468 tests unchanged in count — three
existing tests (`test_api_endpoints.py`, `test_judge.py`,
`test_phase3a.py`) constructed `SignalSource(...)` with an `enabled=`
kwarg and were updated to drop it, not new coverage.

## Phase 5b addendum 4 — Screening/quant follow-ups, stress-test pagination, in_asset reconciliation

A cluster of smaller, independently-scoped fixes and diagnostic scripts,
done in the same working period, each triggered by a specific dashboard
TODO item rather than a planned sub-phase.

- **`SCREENING_UNIVERSE_SIZE` raised 30 → 50** (`app/config/settings.py`,
  `.env`) — the original default was set because CoinGecko's per-asset
  historical endpoint rate-limited after ~5 rapid unauthenticated calls; a
  real demo API key (added and live-verified earlier) raises this to 40+
  rapid calls with no rate-limiting observed, and today's screening
  pipeline sources volatility/drawdown from Binance/Coinbase klines anyway,
  not that CoinGecko endpoint. Raising this only means more sequential
  Binance/Coinbase OHLCV calls (longer real run time), not more LLM cost —
  `top_candidates_size` (10) is unchanged, so LLM spend is unaffected.
- **`scripts/run_composite_weights_validation.py`** (new) — checks whether
  `COMPOSITE_FACTOR_WEIGHTS`' momentum-tilted weighting actually selects
  better-performing assets than an equal-weight or momentum-only
  alternative, using every resolved directional decision genuinely joinable
  back to its own `screened_universe` peer group. Real, disclosed
  limitation: this join only exists for live decisions or backfilled
  decisions made after this same period's `screened_universe` persistence
  fix (below) — real joinable sample currently n=2, below the same
  50-observation bar `evidence_value.py` uses. **Not yet validated either
  way** — re-run periodically as more directional decisions accumulate
  (see [`scripts.md`](scripts.md)).
- **`screened_universe` persistence fix** (`app/benchmarks/replay.py`) —
  backfilled/replayed decisions previously had no joinable
  `regime_at_decision`/`composite_factor_score` at all (the same root
  persistence gap 3g/3h found — see their sections above); replay now
  persists a real `market_regime_snapshots` row and the full
  `screened_universe` batch every replayed day. The pre-fix backfilled
  decisions (111 at the time) still have no regime/score on record —
  retroactively fixing them would mean re-running replay for those same
  historical dates at real (small) LLM cost, not done here.
- **`scripts/run_periodicity_fix.py`** (new) — Phase 4's system-vs-baseline
  Sharpe comparison mixed two different return periodicities (decision-level
  vs. daily) — see Phase 4's own section above. Real fix: pools each
  resolved directional backfilled decision's own real daily OHLCV over
  exactly its own holding window into one series, computing Sharpe over
  that instead. Real result: the old (buggy) decision-level Sharpe was
  **1.846**; the periodicity-matched pooled-daily Sharpe is **0.295**,
  nearly identical to BTC buy-and-hold's own daily Sharpe of **0.313** over
  the same window — the old metric's apparent edge was substantially a
  periodicity-mismatch artifact, not real evidence of skill. **Scoped to
  backfilled decisions only** — as live decisions resolve, this comparison
  will not include them until the script is re-run or extended; see
  [`scripts.md`](scripts.md).
- **`HISTORICAL_WORST_DRAWDOWN` pagination fix** (`BinanceClient.fetch_daily_ohlcv_paginated`,
  used by `scripts/run_stress_test.py`) — 3h's original stress test was
  capped at Binance's 1000-candle-per-call limit (~2.7 reachable years),
  missing BTC's real 2022 (and, deeper still, 2017-2018) drawdown entirely.
  Paginating backward past that cap now reaches BTC's actual 2017-08-17
  Binance listing date (3314 real days) — real result: BTC max_drawdown
  **-83.2%** (deeper than 2022 alone), BNB **-80.0%**, LINK **-90.2%**, SOL
  **-96.3%**. Zero LLM cost.
- **`scripts/reconcile_in_asset.py`** (new, one-time) — `assets.in_asset`
  was set once at asset-creation time and never updated as real holdings
  changed (confirmed live: "S"/Sonic had `in_asset=true` with zero real
  transactions ever recorded). `POST /holdings` now keeps this in sync
  going forward; this script performed the one-time retroactive
  correction — real result: **11 of 25** tracked assets were stale (10
  falsely `true`, 1 falsely `false`), all corrected and cross-checked
  against the live `/holdings` response.
- **`model_agreement` continuous alternative** (migration `0018`) — 3d/3e's
  `model_agreement` can only take 2 real values at n=3 models (1.0 or
  0.667) despite being used as a continuous Risk Engine sizing input. Added
  `compute_return_dispersion` (`app/llm/assessment_agreement.py`) computing
  the real spread (population stdev) of the 3 providers' own
  `expected_return_30d` figures, persisted as a new
  `expected_return_dispersion_30d` column, wired into both the live
  pipeline and replay. Real, disclosed limitation: `model_agreement`
  itself is **unchanged** and still the only agreement figure the Risk
  Engine's sizing scalar actually reads — this is a new checking signal
  only, not yet validated against real outcomes or wired into sizing.
- **3f-in-replay gap found and fixed** — building an ablation study for the
  "is the 3f bull→bear→scenario chain genuinely independent" question
  surfaced a bigger, previously undisclosed gap first: **3f had never run
  during backfill/replay at all** (`build_judge_context`'s `adversarial_repo`
  param defaulted to `None`, and `replay.py` never passed it — not even
  disclosed in `EVIDENCE_UNAVAILABLE_FOR_REPLAY`). Every one of the 141
  backfilled decisions made before this fix had no 3f context whatsoever,
  while every live decision does (`scripts/run_daily.py` always passes
  `--with-adversarial`) — a real, structural backfilled-vs-live difference,
  undisclosed until found. Fixed: `HistoricalReplayService` takes optional
  `adversarial_provider`/`adversarial_repo` (both `None` by default — every
  existing replay call is unaffected), and `scripts/run_replay.py
  --with-adversarial` opts a run into a real, persisted bull/bear/scenario
  cycle per replayed day. **Real ablation run** (2026-09-13): replayed
  2026-08-20 to 2026-08-22 with 3f enabled, real cost **$2.57** — 30/30
  decisions got real persisted adversarial research, 20 of 30 Judge
  theses/evidence genuinely reference bull/bear/scenario-shaped content
  (confirmed real incorporation, not silently ignored).
- **LLM parametric-knowledge-leakage mitigation, re-tested against a real
  crash window** — both prompts (`app/llm/assessment_context.py`,
  `app/judge/context.py`) now instruct models to flag any claim not
  traceable to the run's own evidence as an unverified prior rather than a
  confirmed fact (`ASSESSMENT_PROMPT_VERSION` v1→v2, `JUDGE_PROMPT_VERSION`
  v2→v3). Re-tested live against the real FTX collapse window
  (2022-11-08 to 2022-11-10, real cost **$1.84**): the underlying
  assessment-model leakage still occurs (models still generate
  FTX-shaped narratives from training priors), but under the new prompts
  the Judge caught it every time and never let it drive a directional
  call — all 30 decisions across the 3 days landed on WATCH/NO_TRADE, a
  real, measured behavior change vs. the pre-mitigation Aug 2024 test
  (see Phase 2's/3f-adjacent section above), where the same leakage class
  did drive an eventual SELL call.

534 tests passing throughout this period (`pytest`, no live credentials
needed).

## Phase 5c — Turnover baseline redesign (real incident, 2026-09-14)

A real live incident, not a planned sub-phase: a fresh Judge run
(`RUN-20260914-171535`, BTC HOLD-resize, ETH BUY, SOL SELL, NEAR BUY) was
fully reverted to no-op by `RiskEngine.apply_turnover_cap`, with zero
visibility anywhere except a stdout `logger.warning` (this project has no
log file — `app/logging_config.py`).

**Immediate cause**: `turnover_used_this_week` computed to
`0.30000000000000004` against a `0.3` cap — a ~4e-17 float-summation
artifact from real historical `portfolio_allocation_changes` rows, not a
genuine overage. Fixed with `TURNOVER_EPSILON = 1e-9`
(`RiskEngine.remaining_turnover_budget` now snaps a near-zero remaining
budget to exactly `0.0` in either direction) and a new, persisted
`TurnoverCapEvent` record (migration `0019`,
`GET /portfolio/turnover-cap-events/recent`) so a capped/blocked run is
never invisible again.

**Root cause, found on full review the same day**: `apply_turnover_cap`
measured proposed change against `current_allocation` (real, ground-truth
holdings, Phase 5a) instead of the strategy's own previous target — so a
manual `/holdings` trade that moved real holdings away from the system's
last target got silently, and often repeatedly, charged against the
STRATEGY's own turnover budget every subsequent run, until the gap
happened to close on its own.

**Real backtest evidence** (all 14 real live Judge runs replayed offline,
zero new LLM cost, later re-verified by calling the actual deployed
`RiskEngine._strategy_turnover_delta`/`apply_turnover_cap` directly rather
than a parallel reimplementation — an earlier draft script had produced a
wrong headline figure, caught and corrected during the pre-production
audit below): total raw turnover across the 14 runs was **318.30%**
measured the old way vs. **104.18%** measured against the strategy's own
previous target — a 67% reduction entirely attributable to removing this
double-counted external drift. The 2026-09-13 incident specifically:
**51.33% old vs. 7.78% new** — under the corrected baseline, that exact
run would **not** have been blocked at all, at the same unchanged 7-day/
30% cap.

**Fixed**: `SizedDecision.previous_system_target` (new field — the
system's own last recorded target, 0.0 if never targeted before);
`RiskEngine._strategy_turnover_delta` (WATCH/NO_TRADE always 0.0 — they
are not sizing decisions, by construction, matching `size_one`'s own
`final_allocation = current_allocation` for these; real holdings never
used for turnover math again); `PortfolioConstructionService`'s
classify/replacement-capacity logic switched to the same baseline;
`portfolio_allocation_changes` gained `actual_allocation_before` (real
holdings, audit-only, never summed into turnover) and `baseline_semantics`
(migration `0020` — annotates pre-fix rows as `"actual_holdings"` without
rewriting them; new rows are `"system_target"`).
`get_turnover_since`/`get_recent` now filter/report by this baseline.
**Window/budget explicitly not changed**: the user's own explicit
instruction was "do not blindly accept a 30-day/60-75% hypothesis, backtest
it, let the historical data determine the conclusion" — backtested 7d/14d/
30d × multiple budgets: with only ~10 real days of history, 14d/30d windows
are statistically indistinguishable from 7d, and the naive 30d/60-75%
hypothesis floated earlier in the investigation would have made the
2026-09-13 incident *worse*, not better. No evidence supports changing
either the window or the 30% budget.

**Independent pre-production audit** (same day, before the migration was
trusted in production): re-traced all code, added tests for gaps the audit
itself identified (multi-run no-double-charge, a genuine multi-day churn
sequence, an exact 10%→50%/30%-budget scenario), found and fixed a real
migration-idempotency bug (the original `0020` backfill `UPDATE` had no
guard against re-labeling genuine new `"system_target"` rows if re-run
after they existed — fixed by adding `AND actual_allocation_before is
null`), and — the audit's own most important catch — found and corrected
a real error in the investigation's own first-reported headline figures
(89.23%/5.33%, from a flawed draft reimplementation script) via
re-verification against the actual deployed code, yielding the corrected
104.18%/7.78% figures used above. Final verdict: **READY WITH
CONDITIONS** (re-apply the hardened migration file — done live 2026-09-15,
confirmed a no-op against current data; track the Judge-context finding
below as a separate follow-up).

**The migration file itself had a real, concrete defect, found and fixed
during this same pre-production audit**: `migrations/0020_turnover_
baseline_fix.sql`'s original backfill `UPDATE` matched only on
`baseline_semantics = 'system_target'`, with no guard against rows the
fixed code itself creates — re-running it after the fixed code had
already written new rows would have silently mislabeled them. Fixed by
adding `AND actual_allocation_before is null`, making the migration
genuinely idempotent at any point in time. Applied live 2026-09-15 via
the Supabase SQL Editor (direct `psycopg2` application blocked by a
recurring auth failure — same manual-apply process already used for
0019/0020) and verified afterward: still 24 rows, all correctly labeled
`actual_holdings`, 0 rows matching the old unguarded condition — a
genuine no-op against current live data, as expected, closing the latent
future risk without touching any already-correct row.

**Also undocumented until now, same window**: `MAX_CONCURRENT_POSITIONS`
(8) and `MIN_REPLACEMENT_ALPHA_ADVANTAGE` (0.03) had no stated empirical
basis — same category of arbitrary-but-undocumented constant as
`COMPOSITE_FACTOR_WEIGHTS`. Documented honestly (2026-09-13, `app/config/
settings.py`) rather than fit or backtested: `max_concurrent_positions`
is a conservative starting cap so the replacement rule has any teeth at
all; `min_replacement_alpha_advantage` is a hysteresis/switching-cost
buffer preventing a marginally-better candidate from generating real
turnover/fee cost every run for a negligible expected-alpha gain. Real
sensitivity-testing needs enough resolved decisions across enough actual
*replacement events* specifically (narrower than the general
resolved-decision count) — not yet available, still open.

19 new/updated tests this phase; 524 passing at the time.

## Phase 5d — Judge-context "current allocation" fix

A direct, explicit follow-up to Phase 5c's own disclosed out-of-scope
finding: `app/judge/context.py`'s "Current allocation" prompt field was
silently sourced solely from `portfolio_position_repo.get_all()` — the
strategy's own last target (exactly Phase 5c's `previous_system_target`
concept), never real holdings, and never labeled as such.

**Real historical replay** (all 14 live Judge runs, zero new LLM cost)
found the divergence was not cosmetic: SOL's real holdings sat at ~22% the
entire week of 2026-09-06 to 09-14 while the Judge was told a shrinking
15.42%→9.10% (its own earlier SELL calls apparently never executed in
reality); BTC's real holdings reached 33.52%/33.83% on 2026-09-13/09-14
while the Judge was told just 5.78%/16.32% (gaps of 27.75pp and 17.51pp) on
both HOLD decisions. This was a Judge-*reasoning*-quality issue, not a
risk-control bypass — the Risk Engine's own real-holdings-based gating
(`is_new_position`, the rebalance-confidence gate, `flag_correlations`'
concentration check) was unaffected throughout, confirmed by diff.

**Investigated first, implemented only after explicit approval** (per the
user's own explicit "do NOT implement yet" instruction): considered four
options (keep target-only, replace with real holdings, show both, other) —
chose **show both, clearly labeled**, not a pure swap, because the gap
itself is a real signal (whether the user is actually executing
recommendations) that a pure swap would erase.

**Fixed**: `AssetJudgeContext` now carries `actual_allocation` (real,
same `holdings_ledger`/`compute_current_allocations` pipeline the Risk
Engine uses) and `previous_system_target` (renamed from the old,
misleading `current_allocation`) as two distinct fields, both reaching the
actual LLM prompt as `"Actual holdings (real, ground truth): X% | Last
strategy target (this system's own prior decision, may not be reflected in
actual holdings): Y%"`, with new system-prompt guidance telling the Judge
to reason from actual holdings for portfolio risk/concentration.
`app/main.py`'s real-allocation computation was moved to run *before* the
Judge (previously computed only after), and `JudgeService.run()`/
`build_judge_context()` both thread it through — no duplicate aggregation
logic. 7 new tests, including an end-to-end one asserting the real
33.83%/16.32% BTC figures both reach the actual rendered LLM prompt
string.

## Phase 5e — Dashboard consolidation, LunarCrush investigation, asset-name bug fix

A cluster of dashboard restructuring requests plus two independent real
bug investigations, done in the same working period.

**Dashboard: "AI Portfolio" and "My Portfolio" merged into one "Portfolio"
section.** Both donuts shown side by side (AI Portfolio pinned left, My
Portfolio pinned right, legends mirrored innermost); both holdings-style
tables (`buildHoldingsTable`, shared column definitions and widths between
the AI-Portfolio-target table and the real-holdings table, `nowrap` +
horizontal-scroll so no cell ever wraps or overlaps); the old bar-chart
comparison replaced by a sortable "Comparison" table (My vs AI %/USD +
delta columns); a new "Recommended allocation history" table (collapsed by
default, same expand behavior as the existing transaction history) backed
by a genuinely new endpoint, `GET /portfolio/allocation-changes/recent`
(`PortfolioAllocationChangeRepository.get_recent`, new) — the first UI
exposure of `portfolio_allocation_changes`, previously an explicitly
declined dashboard addition (superseded by this direct request). The
turnover-cap banner and the holdings-entry form/transaction-history panel
were both relocated as part of this restructuring; the standalone "My
Portfolio" section (and its now-dead `loadHoldings()` renderer) was
removed entirely once its content lived in the merged section.

**LunarCrush social-sentiment source, re-investigated with a real user
API key (2026-09-15)**: live-tested `/public/coins/list/v1`,
`/public/coins/{symbol,id}/v1`, and `/public/topic/{topic}/v1` — every
endpoint returned HTTP 402 "requires an Individual or higher subscription,"
including the coins-list endpoint LunarCrush's own docs cite as
free-tier-accessible. User chose not to upgrade — recorded as a deferral,
same category as CoinGlass/Glassnode, not built.

**Real asset-name bug found and fixed (2026-09-16)**: `ScreeningService
._promote_new_candidates` created new `assets` rows with `name=row.symbol`
(e.g. `"ZEC"`) instead of CoinGecko's real display name (e.g. `"Zcash"`) —
even though the real name was already fetched into `_build_universe`'s own
dict, it was never threaded through `ScreenedAsset` (which had no `name`
field at all) to reach asset creation. Live-confirmed: 14 of 29 tracked
assets had `name == symbol`; cross-checked against live CoinGecko data and
found 12 genuinely wrong (2 — XRP, BNB — coincidentally have a real name
identical to their symbol, left correctly unchanged). Fixed going forward
(`ScreenedAsset.name`, transient/not persisted to `screened_universe`,
threaded through to asset creation) and retroactively
(`scripts/reconcile_asset_names.py`, one-time, run live with explicit
approval — corrected all 12 confirmed-wrong names, zero cost, one batched
CoinGecko call).

534 tests passing throughout this phase (17 in `test_screening_service.py`
including a new regression test for the name-propagation bug, plus a new
`test_get_recent_allocation_changes` in `test_api_endpoints.py`).

## Phase 5f — Historical-fetch boundary, REMOVE-action semantics, held-symbol screening coverage (2026-09-16)

Three of the six real findings from a deep investigation of a real
`scripts.run_daily` run (RUN-20260916-181920/182912) were implemented after
independent validation; the other three (WATCH's `MAX_SINGLE_ASSET_
ALLOCATION` interaction, same-day decision idempotency, and the entry-price/
permanently-unresolvable evaluation design) require an explicit product/
methodology decision and were deliberately left unimplemented.

**Historical-fetch boundary, fixed.** `scripts/apply_execution_costs.py`
and `scripts/apply_benchmark_alpha.py` both fetched a flat 1000-day Binance
window anchored to *today* (`fetch_daily_ohlcv_with_timestamps`) — the same
bug class already found and fixed in `run_replay.py`/`run_stress_test.py`
(this same file's Phase 5b addendum 4 and the pagination fix referenced
there). Confirmed live: this run's 12/27 execution-cost skips and 13/28
benchmark-alpha skips were exactly the 2022-11/2024-08 ablation rows, which
sit before the fetched window's 2023-12-22 start date. Both scripts now
call `BinanceClient.fetch_daily_ohlcv_paginated` with a depth computed from
the oldest resolved decision still needing the calculation (`_required_
fetch_days`, never less than the old 1000-day floor) — the boundary no
longer moves against live decisions as real time passes. Does not
retroactively resolve the 2022/2024 ablation rows (a separate, deliberately
deferred design decision) or assets with no Binance/Coinbase pair at all
(confirmed live: BTW has none).

**REMOVE-action semantics, clarified.** `PortfolioAction` (the transient,
log-only object `PortfolioConstructionService.apply()` returns — not the
persisted `portfolio_allocation_changes` row, which already carried this)
gained `actual_allocation_before`, populated from the same real-holdings
value already computed for the persisted row. Confirmed live this run: BNB
and HYPE both received `REMOVE` while their real holdings were already
0.0% — correct per `_classify`'s own turnover-accounting purpose, but
previously indistinguishable from "a real position is being closed"
without a separate `holdings_ledger` join. No change to `_classify` itself
or to any portfolio/risk decision logic.

**Held-symbol screening coverage, extended.** `ScreeningService._build_
universe` only ever fetches the top `screening_universe_size + 15` assets
by market cap; the existing held-symbol Judge-coverage override
(`_rank_and_tag_candidates`) could only rescue a held asset already inside
that fetch — confirmed live for JASMY this run (fell outside the top 65
entirely, logged its own WARNING). `_merge_missing_held_assets` now fetches
only the held symbols genuinely missing from that top-N universe, via one
batched CoinGecko `fetch_markets` call by `coingecko_id`, normalized into
the same shape (`_normalize_market_entry`, shared with `_build_universe`)
so merged assets flow through the identical factor/ranking pipeline. A
lookup failure (network error, or the asset genuinely not found even
directly) degrades to the existing WARNING rather than crashing the run.
Never widens the global market-cap universe itself, never fetches an
already-present symbol twice.

549 tests passing (15 new: `_required_fetch_days`/`fetch_historical_series`
coverage in both scripts, `PortfolioAction.actual_allocation_before` for
both a real and a zero prior holding, and three new screening-service
cases — rescued via direct lookup, lookup failure handled gracefully,
already-present symbol not duplicated).

## Phase 5g — WATCH/NO_TRADE target-allocation cap (2026-09-16)

**Real bug, independently validated then fixed.** `RiskEngine.size_one()`'s
WATCH/NO_TRADE branch (`app/risk/engine.py`) set
`final_allocation = current_allocation` unconditionally, with no
`MAX_SINGLE_ASSET_ALLOCATION` check at all. Live-traced incident: on
2026-09-13 a turnover-costly REDUCE brought BTC's system target down
toward compliance; on 2026-09-15 the Judge returned WATCH — its own
`contradictory_evidence` field explicitly noted real holdings were "more
than double the system's own last strategy target" — and because
WATCH/NO_TRADE is (correctly, by design) exempt from turnover accounting
(`_strategy_turnover_delta` returns 0.0 for both, unconditionally, per the
Phase 5c fix above), the target snapped straight back to real holdings for
zero turnover cost, erasing the REDUCE's progress in one free step. This
could oscillate indefinitely with no guaranteed convergence: a paced,
budget-costly REDUCE followed by a free WATCH-driven reset, repeated.

**Fix**: WATCH/NO_TRADE now computes
`final_allocation = min(current_allocation, MAX_SINGLE_ASSET_ALLOCATION)`
instead of a bare passthrough — a one-line change, isolated to this single
branch. `current_allocation` (real holdings) itself is never modified;
only the DESIRED TARGET this branch expresses is bounded. SELL and
BUY/HOLD-with-resize sizing are untouched. Because WATCH/NO_TRADE's
turnover delta stays hard-zero regardless of this clamp (unchanged,
pre-existing behavior), the fix takes effect immediately, every run,
without needing any new turnover-budget exemption — none was added.

**Explicitly not done here**: actual holdings can still remain above the
cap for a real stretch of time, since only the ordinary, budget-paced
turnover mechanism now governs how fast the portfolio actually moves
toward the (now correctly bounded) target — whether a genuine cap
violation should receive turnover-budget priority over discretionary moves
is a separate, deliberately deferred design decision (see
[`todo.md`](todo.md)). No same-day idempotency guard and no entry-price
evaluation fallback were touched in this pass either — both remain
separate, pending decisions from the same investigation.

555 tests passing (6 new in `tests/test_risk.py`: below-cap/at-cap/
above-cap for WATCH, above-cap for NO_TRADE, confirmation the clamp isn't
charged against or reverted by the turnover cap, and a conceptual
reproduction of the REDUCE-then-WATCH oscillation).

## Phase 5i — Same-day production Judge idempotency, B1 (2026-09-16)

**Real incident, independently investigated then fixed (B1 only — B2's
historical-calibration treatment remains a separate, open task).**
`--with-judge` had no idempotency guard at all: `JudgeService.run()`
created a fresh `judge_decisions`/`decision_outcomes` row set on every
invocation with zero awareness of an earlier same-day decision for the
same asset. Confirmed live: on 2026-09-05 and again on 2026-09-06,
`--with-judge` was run 3 times each day (manual re-testing during the 3e
go-live week), producing 40 independent extra live decisions with
genuinely different LLM outputs per run (e.g. BTC: BUY/0.60/15% →
BUY/0.55/7% → HOLD/0.60/7%), not mechanical duplicates. Because
`portfolio_positions` is a real `asset_id`-keyed upsert table, whichever
run happened to execute last that day silently became the production
portfolio state — a confirmed race, not a hypothetical (BTC's target
moved 0%→5%→5.6%→5.775% across the three 2026-09-05 runs, only the last
value surviving). A full design analysis compared three options (skip+log,
skip-with-explicit-override, supersede-and-mark) — see
[`decisions.md`](decisions.md) for the adopted rationale.

**Fix (Option A — skip + log, no override built)**: `JudgeDecisionRepository.
get_live_decisions_on_day(asset_ids, day)` (new) queries for an existing
`is_backfilled=false` decision within the UTC calendar day for each
candidate asset. `JudgeService.run()` calls this **before** rendering the
prompt or calling the LLM (`_exclude_already_decided_today`), removing any
already-decided asset from the candidate list — so a duplicate attempt
costs zero LLM tokens, not just a discarded result. A skip is logged per
asset (existing `run_id`/timestamp vs. the new attempt's `run_id`) and
surfaced in `JudgeResult.duplicate_skipped`, which flows into the existing
"Judge finished: ..." summary line with no other log-line changes needed.
A genuinely failed/incomplete prior run (cost-cap skip, provider error —
persists no row at all) never blocks a later same-day retry, since there's
nothing to find. Replay/backfilled decisions are structurally unaffected:
`app/benchmarks/replay.py` has always had its own separate persistence
path and never calls `JudgeService` at all, so this guard is never even
reachable from replay's code path — confirmed, not just designed around.

**Explicitly NOT done in this pass**: the 40 existing historical duplicate
rows were **not modified in any way** — no delete, no update, no new
status field, no recalculated calibration. B2 (how those rows should be
treated for calibration purposes, given `_directional_stats` currently
double-counts exactly one of them — NEAR, 2026-09-06) remains a separate,
deliberately deferred task. No override/rerun mechanism and no
`superseded` schema were built — a real rerun need was never observed in
this repository's history, so building either would have been speculative.

567 tests passing (12 new in `tests/test_judge.py`: duplicate skipped with
no new rows and no LLM call, an unrelated asset unaffected, a different
day allowed, backfilled rows never considered, the real repository query
verified to exclude backfilled/other-day rows, a failed-prior-run retry
allowed, one duplicate among several not aborting the run, the skip
observable via the run summary and log, a zero-duplicate run staying
unobtrusive, and three UTC-midnight-boundary tests for `utc_day_bounds`).

## Phase 5j — Historical duplicate treatment in calibration/evaluation, B2 (2026-09-16)

**Implements the design chosen after a full B2 analysis** (three
row-selection rules -- earliest, latest, "reflects final portfolio state"
-- were each found to either introduce hindsight, fail to produce an
answer for every group, or both; a durable `superseded` field was found to
add schema/migration complexity with no demonstrated benefit over a
query-level check; see [`decisions.md`](decisions.md) for the full
reasoning). **The database was not touched in any way** -- no delete, no
update, no new column, no migration. All 60 rows across the 20 historical
duplicate groups (2026-09-05/09-06, confirmed unchanged: 20 groups, 60
rows, live-verified again at implementation time) remain exactly as they
were, fully visible in every audit/history view and fully counted in LLM
cost accounting.

**What changed**: `app/database/repository.py` gained
`compute_duplicate_group_decision_ids()` -- a pure function taking
`(decision_id, asset_id, created_at, is_backfilled)` tuples and returning
every `decision_id` belonging to a same-UTC-day group of more than one
LIVE decision. No canonical row is ever chosen; the entire group is
excluded. It depends only on `judge_decisions` fields, never on outcome
resolution status, so the excluded set is provably stable regardless of
when it's computed -- confirmed against the real NEAR/2026-09-06 group,
which has mixed resolved/unresolved rows today. Applied identically in
the three real consumers of the live directional population found during
the B2 analysis: `app/api/routers/calibration.py`'s `/calibration/summary`
(filtered inside `pairs_for()`, so every directional/calibration figure --
combined, backfilled, live, and per-prompt-version -- uses the same
de-duplicated population), `scripts/run_composite_weights_validation.py`,
and `scripts/calibration_baseline.py`'s `--source live` branch.

**Deliberately left unfiltered**: `resolved_backfilled_count`/
`resolved_live_count`/`unresolved_backfilled_count`/`unresolved_live_count`
remain raw audit counts of every real `decision_outcomes` row in each
state -- a distinct operational statistic from calibration sample
composition, not silently redefined. `CalibrationSummary` gained a new
`excluded_duplicate_group_decision_count` field so the population change
is disclosed explicitly rather than only implied by a smaller
`directional_sample_size`.

**Verified live, post-implementation**: 20 duplicate groups / 60 rows
independently reconfirmed via `compute_duplicate_group_decision_ids`
against the real database. `/calibration/summary`'s live directional
figures moved from the pre-B2 status quo (n=5, hit_rate=1.0, Brier=
0.26866, Sharpe=3.8057, DSR=0.99944) to n=1 (hit_rate=1.0, Brier=0.2704,
Sharpe/DSR undefined below n=2) -- exactly the "exclude all 20 groups"
sensitivity view computed analytically during the design pass, now
confirmed as the real, implemented behavior. `resolved_live_count`/
`unresolved_live_count` remained unchanged at 50/115. This is a
sample-integrity fix, not a performance claim -- the live directional
sample was already far below any statistically meaningful size before
and after.

582 tests passing (15 new: `compute_duplicate_group_decision_ids` unit
tests including the UTC-midnight-boundary and resolution-independence
cases, a cost-accounting-isolation test, `/calibration/summary`
integration tests for a duplicate group, a group that becomes fully
resolved later, and WATCH/BUY interaction, plus dedicated new test files
for `run_composite_weights_validation.py` and `calibration_baseline.py`'s
live branch).

**Post-implementation review follow-up (2026-09-16, same day)**: a review
found that `calibration.py`/`run_composite_weights_validation.py`'s
duplicate-detection fetch (`judge_repo.get_recent(limit=2000, ...)`) could
in principle see only part of an old duplicate group once total live
decision volume exceeds 2000 (ordered newest-first, so the oldest rows
would be silently dropped) -- not affecting today's real data (165 live
decisions), but a real correctness dependency on data volume. Fixed by
passing `limit=None` at both call sites, using `get_recent`'s existing
"`None` means unlimited" mode (already established by `/news/recent`) --
no new repository method needed. `calibration_baseline.py`'s live branch
already had no such cap. Also: `CalibrationSummary.
excluded_duplicate_group_decision_count` gained a real
`Field(description=...)` (this project's first use of per-field OpenAPI
descriptions) so its meaning -- decision ROWS excluded, not group count --
is discoverable from the API schema itself, not only from a source
comment. Re-verified live: still 20 groups / 60 rows / 60 excluded,
calibration figures unchanged. 584 tests passing (2 new: a fixture
reproducing the exact >2000-row split scenario without creating 2001 real
rows, and a schema test confirming the new field description is exposed).

## Phase 5k — Turnover-accounting semantic fix: `change_reason` (2026-09-17)

**Real bug, found via a live run, forensically traced, then fixed.** One
controlled real `python -m scripts.run_daily --with-judge` production run
(RUN-20260917-180748/181505, real LLM cost ≈$1.706) found the 7-day
turnover budget already fully exhausted before the run started (0.3149
used vs. the 0.30 `MAX_WEEKLY_TURNOVER` cap) — so a real, compliant BTC
rebalance the Risk Engine had itself computed (0.30 -> 0.15, correctly
bounded by `MAX_SINGLE_ASSET_ALLOCATION`) was fully reverted to zero net
change by `apply_turnover_cap`, and SOL was blocked identically. Only the
two WATCH/NO_TRADE-driven free moves (NEAR, JASMY) persisted.

Forensic tracing (read-only, no code changed) found the root cause:
`RiskEngine._strategy_turnover_delta` already treats WATCH/NO_TRADE as
zero strategy turnover at decision time (the Phase 5g design), but
`PortfolioConstructionService.apply()` persisted every
`portfolio_allocation_changes` row identically regardless of `d.decision`
— so the exemption existed only in memory (on `SizedDecision`) and was
lost the instant the row was written. `get_turnover_since()` then summed
every persisted row uniformly, re-counting WATCH/NO_TRADE corrections
(the A1/Phase 5g `min(current_allocation, MAX_SINGLE_ASSET_ALLOCATION)`
clamp) as real strategy turnover on every subsequent read. Re-verified
live against all 8 real historical `portfolio_allocation_changes` rows
(never trusted from a prior analysis pass without re-derivation): 5 of 8
(0.1849 of 0.3149 total recorded delta, 58.7%) were risk-control
corrections, including a case that required re-deriving the confidence
gate rather than trusting the raw `judge_decisions.decision` — NEAR's
2026-09-17 row shows raw `decision="BUY"` at confidence 0.50, but
`_apply_confidence_gate` (MIN_BUY_CONFIDENCE=0.55) downgraded it to WATCH
before sizing, and it must classify as risk_control, not strategy.

**Design decision** (see [`decisions.md`](decisions.md) for the full
three-option comparison): keep `MAX_WEEKLY_TURNOVER` scoped to strategy
decisions only (unchanged, 0.30/7-day); classify WATCH/NO_TRADE
corrections as a separate, visible category with **no independent
numeric cap** of their own, since they are structurally self-limiting —
`size_one`'s clamp can only fire while real holdings sit above the cap,
and a second WATCH/NO_TRADE decision on an already-corrected asset
produces `final_allocation == previous_system_target`, writing no new row
at all (unlike the pre-Phase-5g bug, it cannot repeat or oscillate).

**Implemented**: `PortfolioAllocationChange` (`app/portfolio/schemas.py`)
gained `change_reason: Literal["strategy", "risk_control"] = "strategy"`,
included in `to_row()`. `PortfolioConstructionService.apply()`
(`app/portfolio/construction.py`) sets it from `d.decision in ("WATCH",
"NO_TRADE")` — the already-gated `SizedDecision` value, never
reconstructed later from `judge_decisions.decision` or confidence.
`PortfolioAllocationChangeRepository.get_turnover_since()`
(`app/database/repository.py`) gained `.eq("change_reason", "strategy")`,
alongside its existing `baseline_semantics="system_target"` filter — no
join to `judge_decisions`. The in-memory replay/backtest fake
(`app/benchmarks/replay_fakes.py`'s `InMemoryAllocationChangeRepo`) got
the identical filter, so offline replay turnover accounting stays
consistent with the live repository. `migrations/0021_turnover_change_
reason.sql` adds the column (`not null default 'strategy'`, so every
unclassified/future row defaults to the conservative, budget-consuming
side) and backfills exactly the 5 verified historical risk_control rows
by id — applied via the Supabase SQL Editor (the `DATABASE_URL`/psycopg2
path remains confirmed broken, same "password authentication failed"
failure as every migration attempt since 0011) and independently
re-verified live post-apply: all 8 rows classified exactly as predicted
(5 risk_control, 3 strategy).

**Corrected turnover, re-derived live post-implementation**: 7-day
strategy-only turnover 0.1300 (vs. 0.3149 under the old, uncorrected
accounting that mixed in risk-control rows), remaining budget 0.1700 (vs.
~0 before the fix). This does not itself implement A2 (whether a
`MAX_SINGLE_ASSET_ALLOCATION` violation should get turnover-budget
priority over discretionary moves) — **A2 remains open and unimplemented**
(see [`todo.md`](todo.md)); the corrected accounting changes the evidence
behind that decision (the observed BTC blockage would likely have been a
partial reduction, not a full revert, under this fix) and the natural
next step is a fresh live re-observation, not yet performed.

599 tests passing (15 new: 6 in `tests/test_portfolio.py` covering
WATCH/NO_TRADE-with-real-change -> risk_control, BUY/SELL -> strategy, a
capped-BUY-that-reduces-allocation staying strategy (classification
follows `d.decision`, never the derived REDUCE/INCREASE action type), a
confidence-gated BUY-downgraded-to-WATCH -> risk_control reproducing the
real NEAR case, and a WATCH no-op persisting no row at all; 3 schema
tests for `change_reason`'s default/round-trip/Literal-validation; 3 in
new `tests/test_turnover_change_reason.py` for
`get_turnover_since()`'s new filter combined with its existing
`baseline_semantics`/window filters, plus an insert/get_recent round-trip;
1 in `tests/test_replay.py` for the in-memory replay fake's matching
filter; the other 2 come from the parametrized BUY/SELL strategy test
covering both decision types).

## Phase 5l — A2: cap-compliance corrections exempt from `MAX_WEEKLY_TURNOVER` (2026-09-17)

**Implements the policy resolved through a multi-pass forensic/design
analysis** (see [`decisions.md`](decisions.md) for the full reasoning:
`MAX_WEEKLY_TURNOVER`'s own documented purpose in `app/config/
settings.py`, "a circuit breaker against excessive STRATEGY TARGET
CHURN," excludes compliance-driven movement by definition; A1's own
WATCH/NO_TRADE exemption, unconditional since Phase 5g, is the direct
precedent this generalizes). Real motivating incident: BTC's Risk Engine
computed the fully cap-compliant target (0.15) on both 2026-09-16 and
2026-09-17 (independently re-derived via real `size_one()` calls against
the actual persisted `judge_decisions`/`screened_universe` rows for those
runs), but the ordinary turnover-cap mechanism blocked or scaled it back
above cap both times, with no guaranteed convergence.

**What changed**: `app/risk/engine.py` gained a new module-level, pure
function `is_cap_compliance_correction(d, max_single_asset_allocation)` --
true when `d.decision not in ("WATCH", "NO_TRADE")` (A1's own, separate,
unmodified territory) AND `d.previous_system_target` is genuinely
oversized (`> max_single_asset_allocation + TURNOVER_EPSILON` -- the
existing epsilon constant, reused, not a new one) AND `d.final_allocation`
both moved down from that oversized value AND lands at or below the cap
(SELL-to-zero included, deliberately -- no distinct "exit" category
exists anywhere in this project). `RiskEngine._strategy_turnover_delta()`
now returns `0.0` for this condition too, alongside its existing,
untouched WATCH/NO_TRADE check. `PortfolioConstructionService.apply()`
classifies `change_reason="risk_control"` using the exact same shared
function -- never a separately-written, potentially-drifting predicate.
No schema change, no migration (the `risk_control` value already
existed), no change to `apply_turnover_cap`'s algorithm, `MAX_SINGLE_
ASSET_ALLOCATION`, `MAX_WEEKLY_TURNOVER`, confidence thresholds, Judge
behavior, B1, or B2 -- the exemption is entirely a consequence of
`_strategy_turnover_delta()` returning zero, exactly the same mechanism
A1 already used.

**Verified via direct code execution** (real remaining budget = 0.01,
BTC HOLD 0.30->0.15, ADA BUY 0.05->0.10 competing for the same budget):
BTC's correction proceeds in full (`final_allocation=0.15`,
`turnover_capped=False`, contributes 0 to `proposed_turnover`), while ADA
is scaled using only its own demand (`final_allocation=0.06`,
`turnover_capped=True`) -- the BTC correction consumes none of ADA's
turnover budget, confirming the mixed-batch behavior the policy analysis
required.

**Multi-asset behavior**: each qualifying correction is independently
exempt -- no ordering, no shared sub-limit, confirmed by a live test with
three simultaneously-oversized assets (BTC/ETH/SOL) all reaching
compliance under a fully-exhausted strategy budget.

**Replay**: no changes required to `app/benchmarks/replay.py` or
`replay_fakes.py` -- replay instantiates the real `RiskEngine` and
`PortfolioConstructionService` classes directly (not fakes for these two),
so both layers' new behavior is inherited automatically. Confirmed by
re-running the full `tests/test_replay.py` suite unchanged and green.

**Explicitly not done here**: no live production run was executed to
empirically exercise this against a freshly-generated decision -- BTC's
existing oversized state (target 0.298932, cap 0.15) has not yet been
re-evaluated by a real Judge decision since this fix shipped; that
remains a natural next step (see [`todo.md`](todo.md)), not performed in
this task.

620 tests passing (21 new/updated: 12 in `tests/test_risk.py` --
normal-compliant-not-A2, reduced-to-exactly-cap, reduced-below-cap,
sell-to-zero, A1-regression, final-still-above-cap-does-not-trigger,
previous-exactly-at-cap-does-not-trigger, two epsilon-boundary cases,
mixed-batch-with-ordinary-strategy, multiple-simultaneous-corrections,
and a no-repeat/convergence case; 2 in `tests/test_portfolio.py` for the
A2 HOLD and SELL-to-zero classifications, plus a 7-case parametrized
equivalence test guarding that the Risk Engine and Portfolio Construction
layers can never classify a decision differently; 1 existing test
(`test_turnover_decrease_25_to_10_is_15pp`) adjusted -- its fixture
happened to use a previous target above the (default) cap, which now
correctly qualifies as an A2 case; its values were changed to keep
testing its original, unrelated "plain decrease magnitude" intent without
crossing the new predicate's boundary).

## Phase 5m — Supabase's 1000-row cap: real pagination for "get everything" reads (2026-09-18)

**Real bug, found via the dashboard's own "LLM prompts & answers" panel**:
"Research prompt -- 1000 answers" was suspiciously round. Confirmed live:
`llm_analyses` has 1379 real rows, but a query with no `.limit()` at all
(exactly what `LLMAnalysisRepository.get_recent(limit=None)` issued) --
and even an explicit `.limit(5000)` -- both silently returned exactly
1000 rows. This is Supabase/PostgREST's own server-side max-rows default,
not anything in this codebase; no error surfaces anywhere, the caller
just silently gets an incomplete result. `market_snapshots` (1266 rows)
and `evidence_observations` (2749 rows) are real, already-over-the-cap
tables too, but have no reachable "fetch everything" API endpoint today
(every real consumer is per-asset/date-scoped), so they're not currently
exhibiting the symptom -- not touched here.

**Fixed**: `app/database/repository.py` gained `_fetch_all_paginated()`, a
shared helper that pages through `.range()` in chunks of
`_SUPABASE_MAX_ROWS_PER_REQUEST` (1000) until a page returns fewer rows
than requested, instead of issuing one unbounded request. Applied to the
two real "None means unlimited" consumers reachable via the dashboard:
`LLMAnalysisRepository.get_recent()` (confirmed truncating today, 1379
real rows) and `JudgeDecisionRepository.get_recent()` (384 rows today,
under the cap for now, but following the identical vulnerable pattern --
fixed proactively rather than waiting for it to silently truncate too).
Both now order by an explicit `id` tiebreaker in addition to their real
timestamp column, since ties are real here (a provider's whole per-asset
batch is persisted with one shared `timestamp` computed once per call) --
plain `.range()` pagination over a non-uniquely-ordered column risks a
row silently duplicated across two pages or dropped between them.

**Live-verified post-fix**: `LLMAnalysisRepository.get_recent(limit=None)`
now returns all 1379 real rows (was 1000); `JudgeDecisionRepository
.get_recent(limit=None)` returns all 384 (unchanged, already under the
cap, but now via the same safe code path). The dashboard's "Research
prompt" panel now reads "1379 answers".

7 new tests (`tests/test_repository_pagination.py`): `_fetch_all_paginated`
directly (single page, empty result, an exact-page-boundary case, real
multi-page pagination via a monkeypatched small page size, and a
per-page server-side cap smaller than the caller's own requested range),
plus `LLMAnalysisRepository.get_recent()` both past and under the real
cap. Two pre-existing fake Supabase-client test helpers
(`tests/test_judge.py`'s `_FakeJudgeDecisionsTableQuery`,
`tests/test_run_composite_weights_validation.py`'s `_FakeQuery`) gained
`.range()` support to stay compatible with the new pagination code path
-- the former also needed its `.order()` changed from an immediate,
independent re-sort per call to a deferred, properly-composed multi-key
sort, since the fix chains two `.order()` calls (timestamp, then id) and
the old implementation would have silently discarded the first key.
631 tests passing (624 + 7 new).

## Phase 5n — `calibration_baseline.py`'s Judge-decision retrieval: repository pagination migration (2026-09-19)

**Real gap found during B2 forensic validation**: Phase 5m (above) fixed
`JudgeDecisionRepository.get_recent()` itself, but
`scripts/calibration_baseline.py`'s `run_live_baseline()` and
`run_backfill_baseline()` never went through that repository method at
all -- both issued their own raw, unpaginated
`client.table("judge_decisions")...execute()` call, with no `.range()`
and no `.order()`, bypassing the Phase 5m fix entirely. Dormant today
(205 real live rows, 192 real backfilled rows, both under the 1000-row
cap), but the identical vulnerable pattern, and B2's whole-group
duplicate exclusion (Phase 5j) specifically requires the *complete* live
population to detect a group correctly -- a silently truncated fetch
could split a duplicate group across the cutoff and let the visible half
through unexcluded.

**Fixed**: both functions now call
`JudgeDecisionRepository(client).get_recent(limit=None, is_backfilled=...)`
-- `False` for the live branch, `True` for the backfill branch --
converting each returned `JudgeDecisionRecord` to the same plain-dict
shape the rest of each function already expected, so nothing else in
either function needed to change. `created_at` is now a real `datetime`
from the repository model rather than a string, so the old
`datetime.fromisoformat(...)` round-trip before calling
`compute_duplicate_group_decision_ids()` was removed as dead code.

**Live-verified post-fix**:
`JudgeDecisionRepository.get_recent(limit=None, is_backfilled=False)`
returns all 205 real live rows; `is_backfilled=True` returns all 192 real
backfilled rows -- both match the raw table counts exactly. Neither
population is near the 1000-row cap today, so this closes a dormant risk
rather than an active truncation (contrast Phase 5m's `llm_analyses`,
which was actively truncating in production).

New tests in `tests/test_calibration_baseline.py` (new file): 4 tests
total, including a dedicated page-boundary regression
(`test_run_live_baseline_uses_repository_pagination_not_a_single_page`) --
a same-day duplicate group deliberately split across a monkeypatched
small page size, engineered so the old raw-query code and the new
paginated code diverge to different `sample_size` values, not a
coincidental tie -- confirmed by temporarily reverting the fix and
observing the test genuinely fail before restoring it. 633 tests passing.

See [`decisions.md`](decisions.md) for the corresponding decision entry.

## Phase 5p — Remaining raw `judge_decisions` consumers: repository pagination migration (2026-09-27)

**Follow-up to Phase 5n**, not a duplicate of it: Phase 5n fixed
`calibration_baseline.py`'s two raw retrievals. A repository-wide forensic
search afterward found three more production consumers still bypassing
`JudgeDecisionRepository` with their own raw, unpaginated
`client.table("judge_decisions")...execute()` calls — `scripts/
apply_execution_costs.py`, `scripts/run_evidence_value_ranking.py`, and
`scripts/run_reasoning_audit.py`. None was near Supabase's ~1000-row cap
today (488 total judge_decisions: 256 live / 232 backfilled), so none was
an active truncation — same dormant-risk class Phase 5m/5n already closed
elsewhere, not a new bug class.

**Fixed, one consumer at a time, with different required semantics**:
- `apply_execution_costs.py` intentionally needs BOTH live and backfilled
  decisions (its own docstring: "all backfilled, plus any live ones once
  they resolve") — migrated to `get_recent(limit=None, is_backfilled=None)`,
  extracted into a small `fetch_decisions_by_id()` helper for testability,
  matching this file's own existing convention of separately-testable
  helper functions.
- `run_evidence_value_ranking.py` needs the complete backfilled population
  in ASCENDING chronological order (its rolling-window drift analysis
  builds non-overlapping windows over time) — `get_recent()` returns
  DESCENDING order, so the migration reverses it via a new
  `fetch_backfilled_decisions_chronological()` helper. **Caveat found
  during this migration, deliberately left unfixed as out of scope**: this
  reversal does not actually make `fetch_directional_examples`'s own
  returned example list chronological — that list's order is driven
  entirely by a separate `decision_outcomes` query with no `.order()`
  clause of its own, and never had one. Documented in-code; not fixed here
  (a pre-existing, non-pagination ordering gap on a different table).
- `run_reasoning_audit.py` had no `.order()` at all on its raw query —
  not merely dormant-truncation-vulnerable but already lacking any
  ordering guarantee for `select_audit_sample`'s within-priority-group
  tie-breaking (today's apparent stability was an implementation
  accident, not something the code was entitled to rely on).
  `get_recent()`'s deterministic `created_at DESC` order now reaches the
  sampler instead, closing that gap as a side effect of the pagination
  fix.

No repository extension was needed for any of the three — `get_recent()`
already supported every required filter/population; only dict-access →
`JudgeDecisionRecord`-attribute-access adaptation was needed at each call
site. None of the three uses B2 duplicate-group semantics (confirmed
independently for each — none group by same-asset/same-day), so none was
touched.

New tests: 4 in `tests/test_apply_execution_costs.py`, 4 in
`tests/test_evidence_value.py`, 4 in `tests/test_reasoning_audit.py` — each
set covers the exact repository call arguments, population completeness
past the old 1000-row boundary, and the consumer's own specific ordering
requirement (or lack thereof). Confirmed genuinely protective (not merely
asserting a mock was called): temporarily reverting all three production
scripts to their pre-migration raw-query form and re-running these 12
tests reproduces real failures (an `ImportError` for two consumers whose
new helper functions didn't exist pre-migration, an `AttributeError` for
the third, which called `JudgeDecisionRepository` under its own,
unchanged function name) — restored immediately afterward, no production
script was executed. Full suite: 665 passed, 0 failed, 0 skipped (12 of
which are new from this migration; the gap from Phase 5n's 633 also
reflects unrelated work from intervening sessions, not solely this
change).

See [`decisions.md`](decisions.md) for the corresponding decision entry.

## Phase 5q — DecisionOutcome repository pagination, Phase 1: repository + `/calibration/outcomes/recent` + `OutcomeEvaluationService` (2026-09-27)

**Follow-up to Phase 5p**, on a sibling table: a forensic audit found
`DecisionOutcomeRepository` had NO pagination capability at all (unlike
`JudgeDecisionRepository`/`LLMAnalysisRepository`) — every method took a
plain `int` limit with no `limit=None` escape hatch, and several
production consumers relied on hardcoded 500/1000/2000 ceilings or raw,
unpaginated queries to approximate a complete population. Not yet an
active truncation (488 total `decision_outcomes` today), but the same
dormant-growth-boundary class already closed for `judge_decisions`.

**This is Phase 1 only** — repository pagination plus the two consumers
whose fix was unambiguous. The remaining analytical consumers
(`GET /calibration/summary`, `run_composite_weights_validation.py`,
`run_periodicity_fix.py`, `apply_execution_costs.py`,
`apply_benchmark_alpha.py`, `calibration_baseline.py`,
`run_benchmark_comparison.py`, `run_evidence_value_ranking.py`,
`run_reasoning_audit.py`) are deliberately **not** migrated yet — a
separate, later batch.

**Repository (`DecisionOutcomeRepository`)**: `get_recent`, `get_unresolved`,
`get_resolved_without_net_of_costs`, and `get_resolved_without_benchmark_alpha`
all gained `limit: int | None`, using the exact same `_fetch_all_paginated`
helper `JudgeDecisionRepository` already uses — no second pagination
implementation. Bounded (`limit=N`) behavior is byte-for-byte unchanged;
`limit=None` pages through the complete result. `get_recent` keeps its
existing `decision_timestamp DESC` primary sort and adds `decision_id DESC`
as the unique deterministic tiebreaker `_fetch_all_paginated` itself
requires for correct page merging (mirrors `JudgeDecisionRepository.
get_recent`'s identical `created_at DESC, id DESC` convention). The other
three had no pre-existing sort at all, so each gained a bare
`.order("decision_id")` — a pure pagination-correctness tiebreaker,
**not** a FIFO/business-priority ordering (see the design investigation
below for why this distinction matters).

**`GET /calibration/outcomes/recent`**: `limit` default changed from `200`
to `int | None = None`. This directly follows an already-established
project convention, not a new one — `/judge/decisions/recent` and
`/assessments/research/recent` already default to unlimited for exactly
this reason (their own repositories already had pagination). The
dashboard's own existing `?limit=2000` query param continues to work
unchanged (explicit limits are unaffected); no frontend change was made or
needed this phase.

**`OutcomeEvaluationService.run()`**: now calls `get_unresolved(limit=None)`
instead of relying on the old 500-row default. A dedicated design
investigation (2026-09-27, see `decisions.md`) traced the full invocation
path — `--evaluate-outcomes` runs unconditionally on every
`scripts/run_daily.py` invocation — and searched code, docs, and tests for
any FIFO/deadline/priority requirement. None was found. The evaluation
step is zero-cost and deterministic (no LLM/API call, just already-stored
`market_snapshots` arithmetic), so there is no evidenced reason to keep
any per-run cap at all: every genuinely UNRESOLVED row is now evaluated
every run, which makes the ordering question moot for correctness
(nothing is ever silently left unprocessed) without introducing any
business-priority ordering policy.

**Tests**: 10 new in `tests/test_repository_pagination.py` (bounded
behavior preserved + `limit=None` pagination correctness + filter
correctness for all four methods, including a dedicated same-timestamp
tiebreaker-determinism test for `get_recent`), 1 new in
`tests/test_benchmarks.py` (proves `OutcomeEvaluationService.run()`
requests `get_unresolved(limit=None)`, not the old default — deliberately
no FIFO test, since no ordering policy was introduced), 3 new in
`tests/test_api_endpoints.py` (default-permits-complete-retrieval,
explicit-limit-still-works, ordering-passthrough). Full suite: 679
passed, 0 failed, 0 skipped (14 new).

**Live validation** (read-only, no writes): `decision_outcomes` totals
unchanged from the prior audit (488 total, 165 unresolved, 323 resolved).
`get_unresolved(limit=None)` returned all 165 unresolved rows (matching
the raw unfiltered count exactly). `get_recent(limit=None)` returned all
488 rows in verified `decision_timestamp DESC` order.
`get_resolved_without_net_of_costs(limit=None)`/
`get_resolved_without_benchmark_alpha(limit=None)` returned 11 and 0 rows
respectively, matching the prior audit's live counts exactly.

See [`decisions.md`](decisions.md) for the corresponding decision entry.

## Phase 5r — DecisionOutcome consumer migration batch 1: apply_execution_costs.py, apply_benchmark_alpha.py, run_composite_weights_validation.py (2026-09-27)

**Follow-up to Phase 5q**: the first of several planned consumer-migration
batches. Three of the nine consumers Phase 5q's audit confirmed required
the complete population were migrated this pass; the remaining six
(`GET /calibration/summary`, `run_periodicity_fix.py`,
`calibration_baseline.py`, `run_benchmark_comparison.py`,
`run_evidence_value_ranking.py`, `run_reasoning_audit.py`) are **not**
migrated yet — deliberately held for later, smaller batches.

**`apply_execution_costs.py`/`apply_benchmark_alpha.py`**: both changed
their single hardcoded `limit=1000` call to `limit=None`, each now
wrapped in a small named helper (`fetch_resolved_outcomes_without_net_of_costs`/
`fetch_resolved_outcomes_without_benchmark_alpha`) purely so the exact
repository call and its argument are independently testable, mirroring
`apply_execution_costs.py`'s own pre-existing `fetch_decisions_by_id`
convention from the JudgeDecision migration. No other behavior changed —
resolved-only filtering, the `IS NULL` semantics, cost-formula/benchmark-
alpha calculations, the `decision_row is None → continue` guard, and
persistence are all untouched.

**`run_composite_weights_validation.py`**: `outcome_repo.get_recent(limit=2000)`
→ `outcome_repo.get_recent(limit=None)`. **A real discrepancy was found
and corrected during implementation**: the task that specified this
migration assumed the population should become `is_backfilled=False`
(live-only), but the function's own pre-existing behavior — confirmed by
`main()`'s explicit `n_backfilled`/`n_live` reporting, the `is_backfilled`
field captured per example, and an already-passing test
(`test_fetch_joinable_directional_examples_ignores_backfilled_rows_for_
grouping`, which predates this migration) — has never been live-only; it
is an intentionally MIXED live+backfilled population, despite the
function's own docstring wording suggesting otherwise. Applying
`is_backfilled=False` as instructed would have been a real, silent
regression (dropping every backfilled observation from the correlation/
mean-score statistics). The migration therefore preserves the existing
`is_backfilled=None` (unfiltered) behavior exactly, flagged here rather
than silently complying with the mismatched premise.

**Tests**: 6 new (2 per consumer) — one confirming `limit=None` reaches
the correct repository method, one proving the consumer itself doesn't
reintroduce a truncation on top of the (already pagination-tested)
repository result, using populations well past each old ceiling (1200 for
the two `limit=1000` scripts, 2005 for the old `limit=2000` script). A
third new test on `run_composite_weights_validation.py` additionally
locks in the mixed-population finding above. Full suite: 685 passed, 0
failed, 0 skipped (6 new).

**Live validation** (read-only, no writes): `apply_execution_costs`'s
consumer returned 11 rows (matches the raw "resolved, missing
net_of_costs" count exactly). `apply_benchmark_alpha`'s consumer returned
0 rows (matches the raw "resolved, missing effective_alpha" count
exactly — this backlog is already fully caught up). `run_composite_
weights_validation`'s consumer returned 44 joinable directional examples
(5 backfilled, 39 live; 41 skipped for no joinable screening row, 42
skipped as same-day live duplicates) — confirms the migration reaches
real Supabase data end-to-end, read-only.

**Stale-limit search**: confirmed zero remaining `limit=1000`/`limit=2000`/
`limit=500` occurrences and zero raw `client.table("decision_outcomes")`
queries in all three files.

See [`decisions.md`](decisions.md) for the corresponding decision entry.

## Phase 5s — DecisionOutcome consumer migration batch 2: run_periodicity_fix.py, calibration_baseline.py, run_benchmark_comparison.py (2026-09-27)

**Follow-up to Phase 5r**: the second of several planned consumer-
migration batches. Migrates 3 of the remaining 6 consumers Phase 5q's
audit confirmed required the complete population; two consumers
(`run_evidence_value_ranking.py`, `run_reasoning_audit.py`) remain
deliberately deferred to a later batch. **The DecisionOutcome migration
is not yet complete.**

**`run_periodicity_fix.py`**: `outcome_repo.get_recent(limit=2000,
is_backfilled=True)` → `limit=None`, wrapped in a new
`fetch_resolved_backfilled_outcomes()` helper for testability. No
ordering dependency existed to preserve — `window_start`/`window_end`
were already derived via an explicit Python `sorted()` over the
directional decisions' own timestamps, never database order.

**`run_benchmark_comparison.py`**: the raw, fully unbounded
`client.table("decision_outcomes").select("decision_timestamp").eq(
"is_backfilled", True).execute()` (no `.range()`, no `.limit()` at all —
the single riskiest raw query found in the Phase 5q audit, feeding
directly into a min/max comparison-window calculation) → `DecisionOutcomeRepository
(client).get_recent(limit=None, is_backfilled=True)`, wrapped in a new
`fetch_backfilled_decision_timestamps()` helper. The `datetime.fromisoformat()`
round-trip is gone (the repository already returns real `datetime`
objects); the now-fully-unused `datetime`/`UTC` import was removed as a
direct, minimal consequence of that change, not unrelated cleanup. No
resolution filter was added — every backfilled decision's own timestamp
still counts toward the window regardless of resolution status, matching
the original query exactly.

**`calibration_baseline.py`** required a genuine repository extension,
not just an argument change: neither `get_recent` nor either
`get_resolved_without_*` method can express the file's actual need — a
"resolved outcomes for THIS specific, already-paginated set of
decision_ids" join. New method `DecisionOutcomeRepository.
get_resolved_by_decision_ids(decision_ids)` added, using the same
`_fetch_all_paginated` pattern, with `decision_id` as its own unique
tiebreaker (mirroring every other DecisionOutcome pagination method added
in Phase 5q). Both `run_backfill_baseline`'s and `run_live_baseline`'s
raw `.in_(decision_ids).neq("outcome_label", "UNRESOLVED")` queries (no
`.range()` — the same dormant class already fixed for the `judge_decisions`
side of these exact two functions in Phase 5n) now go through it. The
live/backfilled classification, the B2 same-day duplicate-group
exclusion, and the decision_ids→outcome join relationship are all
unchanged — only completeness past the row cap changed.

**Tests**: 15 new. `tests/test_repository_pagination.py` (+3): empty-list,
filter-correctness, and >1000-row completeness for the new
`get_resolved_by_decision_ids`. `tests/test_calibration_baseline.py` (+3,
on top of the 4 already there): decision_outcomes-side pagination
(monkeypatched tiny page size, 5 backfilled decisions/outcomes split
across 3 pages), correct `.in_(decision_ids)` scoping against
cross-population "noise", and combined decision_outcomes-pagination +
B2-exclusion in one scenario. New test files `tests/test_run_periodicity_fix.py`
(+5) and `tests/test_run_benchmark_comparison.py` (+4), since neither
consumer had any prior test coverage at all.

**Genuinely verified, not assumed**: temporarily reverted
`scripts/calibration_baseline.py` alone (via `git stash`, tests
untouched) and re-ran its test file — the new decision_outcomes-pagination
test failed exactly as expected (`sample_size == 2` instead of `5`), and
a pre-existing Phase 5n test also newly failed as useful collateral
confirmation, since the fake client's own "capped without `.range()`"
simulation had to be extended from `judge_decisions`-only to also cover
`decision_outcomes` for this to be possible — restored immediately
afterward; full suite re-confirmed passing after restoration. Full suite:
700 passed, 0 failed, 0 skipped (15 new).

**Live validation** (read-only, no writes): `run_periodicity_fix`'s
consumer returned 154 resolved backfilled outcomes, matching a raw
reference count exactly. `run_benchmark_comparison`'s consumer returned
232 backfilled timestamps (all resolution statuses), matching a raw
reference count exactly, spanning 2022-11-08 → 2026-09-23.
`calibration_baseline`'s new method returned 154 resolved outcomes for
232 backfilled decision_ids, and 127 resolved outcomes for 196 live
decision_ids (256 live decisions minus 60 B2-excluded duplicates) — both
cross-checked against an independent raw `.in_()` reference query with an
exact match, confirming no rows are lost by pagination.

See [`decisions.md`](decisions.md) for the corresponding decision entry.

## Phase 5t — DecisionOutcome consumer migration batch 3: run_evidence_value_ranking.py, run_reasoning_audit.py (2026-09-27)

**Follow-up to Phase 5s**: the third and final batch of the originally
audited migration set. **This completes the audited production
consumers** — all 9 consumers Phase 5q's audit confirmed required the
complete population are now migrated. This is not a claim that no future
raw query can ever be added elsewhere; it closes the specific set this
audit identified, not the concept in general.

**`run_evidence_value_ranking.py`** required the most care of any
consumer in this whole migration, because its `decision_outcomes` query
is what actually determines `fetch_directional_examples`'s returned
`examples` order — the very thing `rolling_window_drift` depends on for
its "chronological, non-overlapping windows" to mean anything. Mapped
before touching anything: the raw query (`.eq("is_backfilled", True)
.neq("outcome_label", "UNRESOLVED")`, no `.range()`/`.limit()`/`.order()`
at all) was the SOLE source of `examples`'s order — the separate,
already-paginated `judge_decisions` retrieval (`fetch_backfilled_
decisions_chronological`, fixed in the earlier JudgeDecision migration)
only ever feeds a lookup dict, never iteration order.

Migrated to `DecisionOutcomeRepository.get_recent(limit=None,
is_backfilled=True)`, with the `UNRESOLVED` exclusion applied in Python
(no repository filter for that exists, same pattern as `run_periodicity_
fix.py`/`run_benchmark_comparison.py` in batch 2). **Ordering decision,
made explicitly rather than left accidental**: the old query's order was
genuinely undefined (Postgres/PostgREST give no guarantee without
`.order()`) — not "accidentally correct," just untested luck. Since
`rolling_window_drift`'s own docstring already states examples must be
chronologically ordered, and every observation here is a real, historical,
already-resolved decision (sorting a complete historical dataset by its
own real timestamp introduces no lookahead — it uses no information that
wasn't already true and already resolved), the fix explicitly sorts
`outcomes` ascending by `decision_timestamp` in Python before building
`examples`. This is a genuine, deliberate behavior change from "whatever
undefined order happened to come back" to "genuinely chronological,"
made because the population being fixed for pagination-safety was
simultaneously the one place where the undefined order was actually
consequential — not introduced speculatively.

**`run_reasoning_audit.py`**: the raw `.in_(decision_ids)` query (no
`.range()`) — the same dormant class already fixed for `calibration_
baseline.py`'s two identical queries in batch 2 — now uses the same
`DecisionOutcomeRepository.get_resolved_by_decision_ids(decision_ids)`
added in that batch. No new repository capability needed. Ordering here
was confirmed irrelevant to candidate selection: `candidates` is built by
iterating `decisions` (already deterministically ordered by the earlier
JudgeDecision migration), never by iterating `outcomes` — `outcome_by_
decision` is a pure `.get()` lookup dict, so this migration has zero
effect on `select_audit_sample`'s tie-breaking.

**Tests**: 3 new in `tests/test_evidence_value.py` — a >1000-row
completeness proof, and, critically, two tests that construct decisions/
outcomes with deliberately non-chronological input order and verify the
ACTUAL output sequence (via a unique per-decision `investment_horizon_
days` marker, not just "some value comes back"): one confirms ascending-
by-timestamp order, the other confirms that order is independent of
input order (feeding the same observations forwards and reversed
produces identical output — proof against accidental order-dependence/
lookahead). `tests/test_reasoning_audit.py` gained no net new tests
(its existing 3 already covered call arguments, ordering pass-through,
and >1000-row completeness) but its fixtures/fakes were extended to
validate full `DecisionOutcome` rows through the new method, exactly as
`test_calibration_baseline.py`'s were in batch 2.

**Genuinely verified, not assumed**: temporarily reconstructed each
script's exact pre-migration form in place (not `git stash`, which would
have reverted past the earlier JudgeDecision migration too) and re-ran
both test files — all 4 new/ordering-sensitive tests failed exactly as
predicted (truncation at the old boundary, and, for evidence-value
ranking, the reversed-input test produced `[3.0, 2.0, 1.0]` instead of
`[1, 2, 3]`, directly proving the old code's order was input-order-
dependent, not genuinely chronological). Restored immediately afterward;
full suite re-confirmed passing. Full suite: 703 passed, 0 failed, 0
skipped (3 new).

**Live validation** (read-only, no writes): `run_evidence_value_
ranking`'s consumer returned 154 resolved backfilled outcomes (matches
raw reference exactly), confirmed strictly ascending by
`decision_timestamp`, spanning 2022-11-08 → 2026-09-23; end-to-end
`fetch_directional_examples` produced 46 directional examples.
`run_reasoning_audit`'s consumer returned 154 resolved outcomes for 232
backfilled decision_ids (matches an independent raw `.in_()` reference
exactly), with every returned row confirmed to belong to the requested
decision_ids set; end-to-end `fetch_candidates` produced 122 candidates.

**Global search confirms the migration set is closed**: zero raw
`.table("decision_outcomes")` calls remain anywhere in `scripts/*.py` —
every remaining `decision_outcomes` reference is either inside `app/
database/repository.py`'s own `DecisionOutcomeRepository` implementation,
a docstring/comment, or `scripts/run_replay.py`'s write-only (`.insert()`/
`.update_outcome()`) usage, which was never a retrieval risk.

See [`decisions.md`](decisions.md) for the corresponding decision entry.

## Phase 5u — Correction: `GET /calibration/summary` was the one missed consumer; now migrated (2026-09-27)

**Correcting Phase 5t's own claim, not rewriting it**: Phase 5t stated
the audited production consumer migration was complete. A subsequent
application-wide audit (same day) found this was not accurate —
`GET /calibration/summary` (`app/api/routers/calibration.py`) was the
very first consumer named in Phase 5q's original 9-item list, but it was
never assigned to any of Batches 1–3 (which only ever covered the 8
`scripts/*.py` consumers) and still called `outcome_repo.get_recent(
limit=2000)` — the exact same hardcoded-ceiling class this whole effort
exists to close. This entry documents the follow-up fix; Phase 5t's own
text is left as written (a real record of what was believed true at the
time), not retroactively edited to look complete.

**Fixed**: `outcome_repo.get_recent(limit=2000)` → `get_recent(limit=None)`
— a single-line change. `DecisionOutcomeRepository` already provided
pagination-safe complete retrieval (added in Phase 5q); no repository or
`_fetch_all_paginated` change was needed. No calibration methodology,
B2 duplicate-group exclusion, response schema, or any other repository
call in this endpoint changed.

**Tests**: 1 new in `tests/test_api_endpoints.py`, verifying both the
call contract (`limit=None` reaches the repository, not the old `2000`)
and completeness behavior (2005 real, resolved, directional outcomes —
past the old ceiling — are all counted in the response, not merely that
a mock was called). Genuinely verified: temporarily reverted the one-line
fix and re-ran — the test failed exactly as predicted (`[2000] == [None]`
assertion failure) — restored immediately afterward. Full suite: 704
passed, 0 failed, 0 skipped (1 new).

**Live validation** (read-only, no writes): `decision_outcomes` totals
unchanged (488 total, 256 live, 232 backfilled, 323 resolved, 165
unresolved). The endpoint's own retrieval call returned all 488 rows,
matching the raw table count exactly. B2 duplicate-group exclusion
confirmed still excluding 60 live decisions, matching the prior audit's
figure. The full endpoint calculation was invoked directly, read-only,
against real data and succeeded end to end (154 resolved backfilled, 169
resolved live, 85 directional, hit_rate=0.8).

**Repeat repository-wide search**: zero remaining `limit=500`/`1000`/
`2000`/`5000` DecisionOutcome ceilings anywhere in `app/` or `scripts/`.
Every DecisionOutcome retrieval in the codebase is now one of: paginated-
complete, intentionally bounded (an explicit caller-supplied limit),
single-row, or write-only.

**This closes the application-wide DecisionOutcome pagination/completeness
issue** across every audited production consumer found by the Phase 5q
forensic audit and the subsequent application-wide audit — not a claim
that no future code can ever introduce a new raw query, only that the
specific gap these audits identified is now fully closed.

See [`decisions.md`](decisions.md) for the corresponding decision entry.

## Phase 5v — A2 confirmed live-exercised; TODO sweep (2026-09-27)

**Follow-up to Phase 5l, not a rewrite of it**: Phase 5l's own text
(2026-09-17) said A2's cap-compliance-correction path (`app/risk/
engine.py`'s `is_cap_compliance_correction`) was implemented and
unit-/live-DB-verified but not yet exercised by a real production run.
That text stands as written — a real record of what was true then.

**Live-verified today**: it has since fired for real. Run
`RUN-20260918-123050` (2026-09-18) gave BTC a raw **HOLD** decision (not
WATCH/NO_TRADE) while its system target sat at 0.299 — above
`MAX_SINGLE_ASSET_ALLOCATION` (0.15) — and the target was correctly
reduced to exactly 0.15, persisted as `change_reason="risk_control"` on
the real `portfolio_allocation_changes` row. This is precisely the A2
condition (`decision not in ("WATCH","NO_TRADE")`, `previous_system_target
> cap`, `final_allocation <= cap`), confirmed directly against the live
`judge_decisions`/`portfolio_allocation_changes` tables, not inferred.
`doc/todo.md`'s open item describing this as not-yet-exercised has been
removed as resolved.

**Same pass**: did a live re-check of every other open `doc/todo.md`
item still time-sensitive enough to drift (embargo gap, evidence-value
sample size, the `/calibration/summary` N+1 pattern's row count/latency,
`market_snapshots`/`evidence_observations` row counts) and refreshed each
figure to its current real value — see `doc/todo.md`'s own entries for
the updated numbers. No item's *status* changed as a result except A2;
the rest remain open, just with current figures instead of 2026-09-12/17
ones. Structural/design-gap items not expected to drift on their own
(replay universe point-in-time, `run_stress_test.py` reading target
instead of real holdings, the reliability-diagram item) were spot-checked
against the current code and confirmed still accurately open.

See [`decisions.md`](decisions.md)'s A2 entry for the original design
analysis — unchanged, this is a live-exercise confirmation, not a policy
revision.

## Phase 5w — Genuine embargoed holdout cohort, `EMBARGO_HOLDOUT_COHORT_PROMPT.md` (2026-10-02)

Implements option (a) of the "no genuine temporal embargo" CRITICAL
finding (`doc/todo.md`'s "A. Active research" section) — a real,
pre-assessed implementation prompt, not improvised. Full design
reasoning, the frozen constants, and the no-migration/n≥50 criterion are
recorded in [`decisions.md`](decisions.md)'s corresponding entry; this
section covers what was actually built and verified.

**Step 0 (read-only, before any code)**: live query against real
`decision_outcomes` on 2026-10-02 — 232 backfilled rows (max
`decision_timestamp` = 2026-09-23T00:00:00Z), 326 live rows (min
`decision_timestamp` = 2026-09-05T17:07:49Z). `TRAINING_WINDOW_END` set
to the backfilled max; `HOLDOUT_COHORT_START` = that + 45 days =
2026-11-07T00:00:00Z. A pre-existing open question (whether
`TRAILING_WINDOW_DAYS`, the live feature trailing window, could exceed
the 45-day embargo and leave feature-window overlap uncovered) was
resolved favorably during pre-assessment: `TRAILING_WINDOW_DAYS = 31`
(`app/benchmarks/historical_factors.py`) < 45, so no embargo-length
change was needed.

**Built**:
- `TRAINING_WINDOW_END`/`HOLDOUT_EMBARGO_DAYS`/`HOLDOUT_COHORT_START` as
  frozen module constants in `app/benchmarks/schemas.py` (not
  `app/config/settings.py` — these are data-derived, not env-var-tunable,
  same convention as `IN_HOLDOUT_WINDOW` in `app/judge/service.py`).
- `/calibration/summary` (`app/api/routers/calibration.py`) gains
  `holdout_cohort_start`, `holdout_cohort_decision_count`,
  `directional_sample_size_holdout_cohort`, `hit_rate_holdout_cohort`,
  `brier_score_holdout_cohort`, `sharpe_decision_level_holdout_cohort`,
  `deflated_sharpe_ratio_holdout_cohort`, `holdout_cohort_contaminated`,
  `holdout_cohort_confirmatory` (`app/api/schemas.py`'s
  `CalibrationSummary`) — computed at read time, reusing the existing
  `_directional_stats`/`pairs_for` machinery so B2's same-day-duplicate
  exclusion applies to the cohort exactly as it does to every other
  directional slice. `held_out_window_note` now also states the cohort's
  start date and resolved-directional count.
- `HistoricalReplayService.run()` (`app/benchmarks/replay.py`) refuses
  `end_date > TRAINING_WINDOW_END` unless a new `allow_post_training_
  cutoff: bool = False` parameter is passed — checked at the service
  level (not just the CLI), so a direct caller is blocked too. Using the
  override logs a loud warning and permanently taints the cohort.
  `scripts/run_replay.py` adds the same check up front (fails fast,
  before the cost-estimate/confirmation prompt) plus a new
  `--allow-post-training-cutoff` CLI flag.
- Dashboard (`app/api/static/dashboard.html`): a "Directional only — not
  confirmatory" badge now appears on the Calibration summary's Hit rate/
  Brier/Sharpe/Deflated Sharpe Ratio rows and the "By prompt version"
  table's Hit rate column whenever `holdout_cohort_confirmatory` is
  false; a new "Holdout cohort (embargoed, clean)" row shows the cohort's
  start date, decision count, contamination/confirmatory badges, and its
  own hit rate/Sharpe once computable. `scripts/run_periodicity_fix.py`
  and `scripts/calibration_baseline.py` each print one caveat line next
  to their system-level Sharpe/hit-rate output.

**Tests**: 8 new, all genuinely regression-proving. 5 in
`tests/test_api_endpoints.py` — cohort membership boundary (exactly at
`HOLDOUT_COHORT_START` is in, one second before is out, a backfilled row
at the same instant is never in), an empty cohort (null stats, `false`
flags, no crash), contamination (blocks `confirmatory` even at a
sufficient sample), the `confirmatory` flip at exactly `MIN_SAMPLE_SIZE`
(49 → false, 50 → true), and B2 duplicate-group exclusion applying
inside the cohort. 3 in `tests/test_replay.py` — refuses past
`TRAINING_WINDOW_END` without the override, proceeds with it, unaffected
exactly at/before the boundary. Regression-proof performed on the
highest-risk piece (the n≥50 boundary): temporarily changed `>=` to `>`
against `MIN_SAMPLE_SIZE`, confirmed the boundary test failed exactly as
predicted (`False is True`), restored immediately. Full suite after:
**711 passed** (703 pre-existing + 8 new), same single pre-existing,
unrelated failure as every other recent run
(`test_forward_calendar_only_includes_future_dates_within_horizon`,
broken by the real system clock advancing past its hardcoded
`"2026-10-01"` "future" date — not caused by this or any other change
this session).

**Explicitly not closed by this phase**: the CRITICAL "no embargo"
`doc/todo.md` item stays Open — a clean cohort now *exists*, but
`holdout_cohort_confirmatory` is false (0 decisions in it yet, since
`HOLDOUT_COHORT_START` is 2026-11-07, still in the future as of this
write-up) and won't flip true for an estimated ~3 months (45-day embargo
+ time for n≥50 resolved-directional decisions), a wait the user
explicitly accepted before implementation began. No production run or
database mutation was performed — every constant came from a single
read-only query.

