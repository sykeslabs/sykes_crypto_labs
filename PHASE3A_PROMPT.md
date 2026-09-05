# AI Crypto Portfolio — Phase 3a: Universe/Candidate Schema, Evidence Provenance, Registries

## Context

This is an existing project. Before doing anything else, inspect the
repository and read `README.md` in full — it describes the current
architecture (Phase 1: Supabase + CoinGecko market data; Phase 2: RSS news +
multi-model OpenRouter research with cost controls) and the long-term Phase 3
vision.

**Do not rebuild Phase 1 or Phase 2.** Both are complete and verified against
a live Supabase project. Extend the existing code cleanly:

```
app/
  config/    database/    market_data/    news/    llm/
  judge/     portfolio/   risk/           trading/  benchmarks/
  main.py
tests/  migrations/  scripts/
```

**The long-term goal** (do not implement all of it now) is a full crypto
research/advisory system: an open, screened universe; independent evidence
from many official sources (exchange-native market data, derivatives,
options, on-chain/DeFi, news, macro, independent analysts); a deterministic
market-regime classification; multi-model independent assessment; adversarial
bull/bear research; and a deterministic Judge + Risk Engine producing
paper-only, volatility/correlation-aware recommendations — with accuracy
tracked continuously against realized outcomes, not just assessed once.

This is built in **verified sub-phases**, official/documented sources before
fragile/unofficial ones:

- **3a (this task)** — schema, provenance, and registries. No new external
  source, no new LLM calls.
- 3b — CoinMarketCap, Coinbase, Binance (all official/documented) + market
  screening + candidate discovery + a deterministic market-regime classifier.
- 3c — Official derivatives/on-chain sources: Binance funding rates, Deribit
  options, Etherscan/DefiLlama on-chain & DeFi data. Still zero LLM cost.
- 3d — Multi-model current market assessment, distinct from `llm_analyses`.
- 3e — Deterministic Judge, Risk Engine (vol/correlation-aware sizing),
  Portfolio Construction, and a continuous decision-outcome ledger.
- 3f — Adversarial bull/bear research, scenario modeling, macro matrix, and
  the remaining fragile/unofficial sources (CoinAnk, CoinGlass, CryptoBubbles,
  PlanB/X), each gated on a real feasibility check.
- 3g — Statistical validation and robustness: multiple-testing-aware
  accuracy reporting (deflated Sharpe / probability of backtest overfitting
  across every prompt/logic iteration, not just the final result),
  probabilistic-forecast calibration (Brier score / reliability diagrams,
  not just directional hit-rate), regime-conditional accuracy breakdowns, a
  respected held-out decision window, and a periodic audit of whether the
  Judge's own stated reasoning follows from its cited evidence. This is what
  makes the 3e/3f "did accuracy actually improve" question answerable
  honestly rather than just answerable.

**You are only implementing 3a right now.** Stop after 3a is complete and
verified, summarize what you built and any decisions you made, and wait for
explicit confirmation before starting 3b. Do not write code for 3b–3f yet,
even scaffolding.

## Non-negotiables (apply to all of Phase 3, not just 3a)

- System is **PAPER ONLY**. No live trading, no exchange credentials, no
  leverage, no shorts, ever.
- Every source of evidence is preserved independently — never collapse
  multiple sources into one generic sentiment score.
- Missing or unavailable data is `UNKNOWN` / `UNAVAILABLE`, never treated as
  neutral or silently defaulted.
- No invented API access. If a data source's programmatic access is unclear,
  that's a 3b/3c/3f problem to investigate then — not a 3a concern.
- Every LLM call, from any future stage, goes through the existing
  `CostGuard`, without exception — not relevant to 3a since 3a adds no LLM
  calls, but do not add any as part of this task.
- Every observation and prediction carries provenance timestamps — needed for
  later backtesting. No look-ahead bias, ever.

## Sub-phase 3a — Task detail

**1. Candidate/portfolio status.**
Today `assets` has two independent flags: `active` (tracked at all) and
`in_asset` (currently held). Add an explicit status so the following are all
representable and distinct: `HELD`, `WATCHLIST`, `CANDIDATE`, `REJECTED`.
Decide whether this is a column on `assets` or a separate
`asset_status_history` table if you want status changes auditable over time —
prefer the history table if it's cheap to add. Do not remove or repurpose
`active`/`in_asset`.

**2. `NO_TRADE` decision value.**
Add `NO_TRADE` as a valid decision value alongside `BUY / HOLD / SELL / WATCH`
wherever a decision enum will eventually live. No decision-making logic is
built yet (that's 3e) — just make the value exist.

**3. Evidence provenance shape, with numeric freshness decay.**
Design a generic shape every future evidence-source table (3b, 3c, 3f) will
reuse:
- `source`, `asset_id` (nullable for GLOBAL/MACRO scope), `scope`
  (`ASSET`/`GLOBAL_CRYPTO`/`MACRO`)
- `observation_timestamp`, `publication_timestamp`, `retrieval_timestamp`,
  `timeframe`
- `freshness` (`REALTIME`/`RECENT`/`STALE`/`UNKNOWN`) — kept as a convenience
  bucket, but also add `decay_half_life_hours` (numeric, per source *type*,
  not per observation) so downstream consumers can compute a continuous
  freshness weight instead of only a coarse bucket. Different source types
  decay at very different rates (a liquidation snapshot is stale in minutes;
  a macro print is relevant until the next release) — document sensible
  starting half-life values per source type you already know about
  (CoinGecko price ≈ short; news ≈ hours-to-a-day depending on the story;
  macro ≈ until superseded), and leave room for the rest to be filled in as
  each source is actually built.
- `status` (`OK`/`UNAVAILABLE`/`UNKNOWN`)
- `payload` (JSONB, source-specific fields)

**4. Signal source registry.**
Add a `signal_sources` table: `name, enabled (bool), status
(OK/UNAVAILABLE/UNKNOWN/NOT_IMPLEMENTED), last_checked_at, notes`. Seed it
with every source in the long-term vision — CoinGecko and News as `OK`
(already implemented); CoinMarketCap, Coinbase, Binance, Deribit, Etherscan,
DefiLlama, CoinAnk, CoinGlass, CryptoBubbles, PlanB, Macro,
**`AGGREGATE_OPEN_INTEREST`** (Binance/Deribit futures open interest —
distinct from the funding-rate source, additive positioning evidence, built
in 3c), and **`STABLECOIN_SUPPLY_AND_EXCHANGE_RESERVES`** (net stablecoin
supply growth + exchange reserve balances — a capital-rotation/dry-powder
proxy distinct from DefiLlama's protocol-level TVL, also built in 3c) as
`NOT_IMPLEMENTED`.

**5. Schema groundwork for later sub-phases (structure only, not populated
yet):**
- `market_regime_snapshots` — for 3b's deterministic regime classifier.
  Suggested columns: `id, run_id, computed_at, regime (RISK_ON/RISK_OFF/
  NEUTRAL or similar), inputs (JSONB), notes`.
- `decision_outcomes` — for 3e's continuous calibration ledger. Suggested
  columns: `id, decision_id (FK to wherever Judge decisions will live),
  asset_id, decision_timestamp, horizon_days, target_return, stop_return,
  realized_return, outcome_label (HIT_TARGET/HIT_STOP/TIMED_OUT/UNRESOLVED),
  evaluated_at, regime_at_decision (FK to `market_regime_snapshots`,
  denormalized for cheap per-regime accuracy breakdowns later),
  judge_confidence (denormalized from the Judge decision row, so calibration
  queries don't need to join back through a decisions table that doesn't
  exist yet), `in_holdout_window` (bool, default false)`. The last column
  exists so that, starting in 3e, a defined slice of decisions can be marked
  as never-touched-during-iteration — the only slice later sub-phases (3g)
  may honestly call "out of sample." Nothing populates this yet — it's
  schema only, so 3e doesn't need a schema migration mid-implementation.
- `prompt_templates` — for prompt/template versioning starting in 3d.
  Suggested columns: `id, name, stage, version, template_hash, created_at`.
  Again, schema only.
- `calibration_runs` — for tracking calibration/backtest attempts themselves
  as first-class, countable events, starting with 3e's baseline script and
  extended by 3g. Suggested columns: `id, run_at, method (e.g.
  BASELINE_HIT_RATE/BRIER/DEFLATED_SHARPE/PBO), sample_size,
  prompt_template_ids (JSONB array — which template versions were in effect),
  hit_rate, brier_score, notes`. The reason this exists as its own table
  rather than being inferred after the fact: correcting for how many times a
  prompt/logic change was tried and re-evaluated (multiple-comparisons bias)
  requires an honest count of *attempts*, not just a count of resolved
  decisions — and that count is easy to lose track of retroactively. Schema
  only; first populated in 3e.

You do not need to get every column exactly right — the point is that these
concepts exist in the schema now so later sub-phases extend rather than
retrofit them. Note any assumptions in the migration comments.

**6. Migrations.**
Follow the existing style in `migrations/` — idempotent, safe to re-run. New
migration file(s), not edits to `0001_init.sql` / `0002_llm_and_news.sql`.

**7. Tests.**
`pytest` must pass without requiring live credentials (mocks/fakes, no live
network or database calls), matching how Phase 1/2 tests work today.

**8. Documentation.**
Update `README.md`: mark 3a complete in the Status section, and add a short
"Known limitations / decisions" note (matching the style of the existing
Phase 2 section) covering anything decided ambiguously — e.g. status column
vs. history table, and the initial decay half-life values chosen.

## Exit criteria for 3a

- Migration(s) applied and verified against the live Supabase project.
- `assets` (or new history table) can represent `HELD` / `WATCHLIST` /
  `CANDIDATE` / `REJECTED` without ambiguity.
- `signal_sources` table exists, seeded correctly for all planned sources.
- `market_regime_snapshots`, `decision_outcomes`, `prompt_templates`,
  `calibration_runs` tables exist (empty), ready for later sub-phases.
- No behavior change to any existing Phase 1/2 code path.
- `pytest` passes without credentials.
- Zero new external API calls, zero new LLM calls, zero new cost.
- README updated.

Stop here, report what was built and any decisions you made, and wait for
confirmation before starting sub-phase 3b.
