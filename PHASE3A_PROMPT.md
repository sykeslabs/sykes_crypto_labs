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
  screening + candidate discovery + a deterministic market-regime classifier
  + a deterministic composite factor score + a basic screening-stage
  anomaly/wash-trading flag.
- 3c — Official derivatives/on-chain sources: Binance funding rates, Deribit
  options, Etherscan/DefiLlama on-chain & DeFi data, on-chain valuation
  metrics and BTC-specific miner metrics, stablecoin supply *and velocity*,
  spot BTC/ETH ETF flows, CME futures positioning (CFTC COT), and
  prediction-market implied probabilities. Still zero LLM cost.
- 3d — Multi-model current market assessment, distinct from `llm_analyses`.
- 3e — Deterministic Judge, Risk Engine (vol/correlation-aware sizing),
  Portfolio Construction, and a continuous decision-outcome ledger.
- 3f — Adversarial bull/bear research, scenario modeling, a macro matrix
  extended with global-liquidity/cross-asset-correlation tracking, and the
  remaining fragile/unofficial-or-hard-to-extract sources (CoinAnk,
  CoinGlass, CryptoBubbles, PlanB/X, social/narrative sentiment, and a
  regulatory/policy event calendar), each gated on a real feasibility check.
- 3g — Statistical validation and robustness: multiple-testing-aware
  accuracy reporting (deflated Sharpe / probability of backtest overfitting
  across every prompt/logic iteration, not just the final result),
  probabilistic-forecast calibration (Brier score / reliability diagrams,
  not just directional hit-rate), regime-conditional accuracy breakdowns, a
  respected held-out decision window, and a periodic audit of whether the
  Judge's own stated reasoning follows from its cited evidence. This is what
  makes the 3e/3f "did accuracy actually improve" question answerable
  honestly rather than just answerable.
- 3h — A later addendum sub-phase, added after a gap-analysis against
  professional crypto-advisory practice: a learned (not hand-tuned) evidence-
  value ranking checked against the Judge's implicit weighting (including a
  rolling-window/regime-sliced variant to catch evidence whose predictive
  value drifts over time, not just its full-history average), and a
  deterministic portfolio tail-risk stress test. Both are reporting/checking
  tools, same spirit as 3g — neither is allowed to auto-adjust Judge or Risk
  Engine logic.
- 3i — A second later addendum, added from the same gap-analysis pass as 3h:
  three further official/paid-tier evidence sources identified by comparing
  this project against how institutional on-chain research desks actually
  work — wallet-entity-clustering/"smart money" flow intelligence (Nansen or
  Arkham-class), custody/OTC desk flow tracking (a growing share of
  institutional buying since spot-ETF approval never touches public order
  books), and network usage/developer-activity fundamentals (active
  addresses, fee revenue, GitHub commit velocity). Unlike 3h, this is a new
  evidence-collection sub-phase (like 3b/3c), not a diagnostic-only one — it
  wires new inputs into the already-built Judge (3e), the same integration
  pattern 3f used when it added bull/bear/macro evidence after 3e already
  existed. Still zero new LLM cost. This is now the last sub-phase of Phase 3.

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
- **Point-in-time integrity is a correctness requirement, not an optimization.**
  Several evidence types get revised after the fact by their own provider —
  on-chain valuation metrics (realized cap / MVRV can be restated), ETF flow
  reports (early-day figures get corrected), and regulatory-event extraction
  (a filing's classified relevance may be refined later). If a later backtest
  or calibration run reads whatever value is *currently* in the table for a
  past `observation_timestamp`, instead of the value that was actually known
  at `retrieval_timestamp`, every downstream accuracy/calibration number
  (3e/3g) is silently inflated by hindsight the system never actually had.
  Evidence rows are **append-only for revisable fields**: a correction is a
  new row (with its own `retrieval_timestamp`), never an `UPDATE` that
  overwrites the originally-retrieved value. Historical queries used for
  backtesting/calibration must always resolve "what was the latest known
  value as of decision time T," not "what is the latest value now."

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
- `is_revision_of` (nullable FK to an earlier row of the same source +
  `observation_timestamp`) so a provider's later correction is stored as a
  new, linked row rather than an overwrite — see the point-in-time
  non-negotiable above. Add a small helper/query convention now (e.g. "value
  as known at time T" = latest row by `retrieval_timestamp` where
  `retrieval_timestamp <= T`, following the `is_revision_of` chain) so 3b/3c/
  3f don't each invent their own version of this query later.
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
in 3c), **`STABLECOIN_SUPPLY_VELOCITY_AND_EXCHANGE_RESERVES`** (net
stablecoin supply growth, supply *velocity* — transaction volume relative to
circulating supply, a distinct usage-vs-hoarding proxy from raw supply
growth — plus exchange reserve balances; a capital-rotation/dry-powder proxy
distinct from DefiLlama's protocol-level TVL, built in 3c),
**`SPOT_ETF_FLOWS`** (daily net flows for spot BTC/ETH ETFs, via an
aggregator such as Farside Investors or SoSoValue rather than scraping each
issuer individually — a medium/long-horizon institutional-capital proxy,
built in 3c), and **`PREDICTION_MARKETS`** (implied probabilities for
relevant macro/crypto event contracts from a documented API such as
Polymarket or Kalshi — market-priced probability evidence, distinct in kind
from both LLM confidence and options-implied volatility, built in 3c),
**`ON_CHAIN_VALUATION_METRICS`** (MVRV / MVRV Z-Score, SOPR, NUPL, and
LTH-MVRV/STH-MVRV cohort breakdowns via a documented on-chain analytics API
such as Glassnode or CryptoQuant — a cycle-position valuation signal
distinct in kind from the transfer-flow/TVL data already scoped for 3c;
paid-tier access is acceptable here since it's a dollar cost, not an LLM
cost, but real access/pricing at your account tier must still be verified
before relying on it, same rule as every other source, built in 3c),
**`FUTURES_TERM_STRUCTURE`** (dated-futures basis / contango-backwardation
curve across expiries on Binance/Deribit — distinct from both the
perpetual funding rate and open interest already scoped for 3c, since it
reflects where futures desks price forward expectations rather than
perpetual positioning or raw contract magnitude, built in 3c),
**`TOKEN_UNLOCK_SCHEDULE`** (vesting/unlock calendar data via a documented
source such as Messari or TokenUnlocks — a calendar-dated, forward-looking
known-event signal, structurally different from every other 3c source
because the event date is known in advance rather than inferred from
current data, built in 3c), and **`SOCIAL_NARRATIVE_SENTIMENT`** (aggregate
social volume / trending-narrative-rotation tracking via a source such as
Santiment or LunarCrush — grouped with the fragile/unofficial sources since
reliable programmatic access and signal quality are unverified, feasibility-
gated in 3f like CoinAnk/CryptoBubbles/PlanB), **`CME_COT_POSITIONING`** (the
CFTC's weekly Commitment of Traders report for CME BTC/ETH futures, broken
down by trader category — leveraged funds, asset managers, dealers, other
reportables — a free, official, government-published source giving a
regulated-futures view of institutional positioning distinct from spot ETF
flows (capital movement into a fund) and perpetual funding rates (perpetual-
specific leverage); built in 3c), **`ON_CHAIN_MINER_METRICS`** (BTC-specific
hash rate, difficulty, miner reserve balances, and miner-to-exchange flows —
a standard on-chain category, typically available from the same on-chain
analytics provider already scoped for `ON_CHAIN_VALUATION_METRICS`
(Glassnode/CryptoQuant), so likely near-zero marginal integration cost once
that vendor relationship exists; built in 3c), **`GLOBAL_LIQUIDITY_MACRO`**
(FRED — Federal Reserve Economic Data — series for M2 money supply growth,
Fed balance sheet (WALCL), and reverse repo levels, plus rolling BTC-vs-
traditional-risk-asset correlation (S&P 500, gold, DXY) computed from data
already collected elsewhere — a free, official, documented API; grouped with
the macro matrix and built in 3f since that's where the existing macro-
evidence-matrix logic lives, even though FRED itself is an official source),
and **`REGULATORY_EVENT_CALENDAR`** (dated regulatory/policy catalysts — SEC
enforcement actions and filings via SEC EDGAR's full-text search API,
legislative developments via congress.gov's API, both free and official —
grouped with the fragile/feasibility-gated sources in 3f not because the
underlying APIs are unofficial, but because reliably extracting a dated,
asset-specific, investment-relevant event from them is an unverified
extraction problem, the same category of risk as PlanB/X's post-parsing, not
a raw-access problem), **`REGIONAL_EXCHANGE_PREMIUM`** (structural
cross-region price divergence — e.g. the historically-documented "Kimchi
premium" on Korean exchanges such as Upbit/Bithumb — as a proxy for
regional retail speculative intensity and capital-control-driven flow,
distinct from the ordinary cross-venue disagreement already logged between
CoinGecko/CoinMarketCap/Coinbase/Binance in 3b, since it reflects a
structural regional gap rather than routine aggregation noise; grouped with
3f's fragile/feasibility-gated sources since reliable, ToS-compliant
programmatic access to the relevant regional exchanges is unverified going
in), **`ENTITY_FLOW_INTELLIGENCE`** (wallet-entity-clustering and "smart
money" wallet-flow tracking via a documented paid API such as Nansen or
Arkham — distinct from the raw, unclustered large-transfer-count proxy
already scoped for Etherscan in 3c, since it labels *who* is moving funds,
not just that a large transfer occurred; built in 3i),
**`CUSTODY_OTC_FLOW`** (custody-provider and OTC-desk balance/flow tracking
— e.g. known Coinbase Custody/Fidelity Digital Assets address balances — as
a proxy for institutional accumulation that happens off public exchange
order books entirely, distinct from both the exchange-reserve proxy and the
spot-ETF-flow source already scoped for 3c; built in 3i), and
**`NETWORK_FUNDAMENTALS_DEV_ACTIVITY`** (network usage fundamentals — active
addresses, transaction throughput, fee revenue — plus developer/build
activity such as GitHub commit velocity, e.g. via an Electric Capital
Developer Report-style feed — a slower-moving, more fundamentals-oriented
evidence type distinct from both price-derived screening factors and
on-chain valuation-cycle metrics already scoped; built in 3i) as
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

**Note for 3b:** whatever table 3b uses to persist the full screened universe
(per its own task 7) should reserve a `composite_factor_score` (numeric,
nullable) column now, even though it isn't computed until 3b. This is a
deterministic, non-LLM composite of the same screening factors 3b already
computes (momentum, volatility, drawdown, relative strength) — it exists so
3e's Judge has a purely quantitative, non-narrative input to compare against
the LLM/adversarial-research evidence, without conflating the two into one
blended number. Schema only here; 3b computes and populates it.

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
- Evidence provenance shape supports `is_revision_of` and a documented
  "value as known at time T" query convention, so 3b/3c/3f collectors and
  3e/3g backtests share one point-in-time-correct pattern instead of each
  risking their own look-ahead bug.
- `market_regime_snapshots`, `decision_outcomes`, `prompt_templates`,
  `calibration_runs` tables exist (empty), ready for later sub-phases.
- No behavior change to any existing Phase 1/2 code path.
- `pytest` passes without credentials.
- Zero new external API calls, zero new LLM calls, zero new cost.
- README updated.

Stop here, report what was built and any decisions you made, and wait for
confirmation before starting sub-phase 3b.
