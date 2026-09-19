# Decisions

Recorded here so the reasoning behind each choice — including the ones
deliberately *not* adopted, and the ones later superseded — doesn't get
lost as the project grows. (Renamed from `technology-decisions.md` on
2026-09-16 and extended beyond evidence-source stack choices to cover
every significant architectural/policy decision; see git history for the
file's history under its old name.)

Entries below the "Technology stack decisions" heading are the original
per-evidence-source adopt/reject log, largely written at *planning* time
(the "3j"/"3k" framing) — cross-check against [`history.md`](history.md)
and the live `signal_sources` table for what a given source's real,
final outcome actually was; a decision to "adopt" a source here does not
by itself mean it shipped working (e.g. Glassnode/CoinGlass/LunarCrush
were all "grouped as fragile" or paid-tier-gated and remain deferred — see
"Later decisions" below and [`todo.md`](todo.md)). New entries from
2026-09-14 onward are written after the fact, from real implementation
outcomes, and are dated.

## Later decisions (2026-09-14 onward)

- **Turnover-cap baseline: measure against the strategy's own previous
  target, never real holdings — adopted, 2026-09-14.** Real incident: a
  manual `/holdings` trade moving real holdings away from the system's
  last target was getting silently, repeatedly charged against the
  strategy's own `MAX_WEEKLY_TURNOVER` budget. Real backtest (14 live
  Judge runs, zero LLM cost): turnover measured the old way totaled
  318.30%; measured against the strategy's own previous target, 104.18% —
  a 67% reduction attributable entirely to removing this double-counted
  drift. See [`history.md`](history.md)'s Phase 5c section for the full
  incident, the pre-production audit, and the corrected figures (an
  earlier draft script had reported wrong headline numbers, caught and
  fixed by re-verifying against the actual deployed code).
- **`MAX_WEEKLY_TURNOVER` window (7 days) and budget (30%) — reaffirmed
  unchanged, 2026-09-14, evidence-driven.** Explicitly investigated
  whether to move to a longer window/higher budget (a 30-day/60-75%
  hypothesis was floated mid-investigation). Backtested 7d/14d/30d ×
  multiple budgets against real history: with only ~10 real days of
  data, 14d/30d windows are statistically indistinguishable from 7d, and
  the 30d/60-75% hypothesis would have made the real 2026-09-13 incident
  *worse*, not better. Per the user's own explicit instruction not to
  force the data to fit a pre-supplied hypothesis, the recommendation is
  to leave both unchanged — no evidence supports moving either.
- **Judge's "current allocation" context: show both real holdings and the
  system's own last target, clearly labeled — adopted, 2026-09-15,
  supersedes the original design.** The original (undocumented,
  effectively default-by-omission) choice was to show only the system's
  own target, unlabeled as such — found to have silently misled the
  Judge by up to 27.75 percentage points on real historical decisions
  (see [`history.md`](history.md)'s Phase 5d section). Considered
  replacing it outright with real holdings instead, but chose to show
  both because the gap between the two is itself a real, useful signal
  (whether past recommendations were actually executed) that a pure
  swap would have erased.
- **LunarCrush (social/narrative sentiment) — deferred, re-confirmed
  2026-09-15 with a real paid API key.** Originally deferred in 3f
  because even the "public" endpoint required an auth token; a real user
  key was later added and live-tested against every plausible endpoint
  (coins list, single coin, topic) — all returned HTTP 402, requiring an
  "Individual" tier or higher, including the endpoint LunarCrush's own
  docs describe as free-tier-accessible. User chose not to upgrade — same
  category as CoinGlass/Glassnode (a real paid-tier decision, not a
  technical failure).
- **`portfolio_allocation_changes` dashboard exposure — reversed,
  2026-09-16.** Originally declined (see [`todo.md`](todo.md)'s
  "Declined" section) on the reasoning that current allocation plus "last
  changed" already covered it. Directly requested and built as a real,
  collapsible "Recommended
  allocation history" table plus a new `GET
  /portfolio/allocation-changes/recent` endpoint — the earlier
  "redundant" reasoning didn't anticipate wanting the full historical
  delta-by-delta record, not just the latest state.
- **Same-day production Judge idempotency (B1) — Option A (skip + log)
  adopted, 2026-09-16; no override mechanism built.** Real incident: a
  same-day `--with-judge` rerun (2026-09-05/06, no guard existed) produced
  40 independent extra live decisions, with whichever run happened to
  execute last silently becoming the production portfolio state — see
  [`history.md`](history.md)'s Phase 5i section. A design analysis first
  compared three options (skip+log / skip-with-explicit-override /
  supersede-and-mark); Option A was chosen because the repository showed
  **zero evidence of any currently legitimate same-day rerun workflow** —
  building override machinery for a hypothetical need would be exactly the
  kind of speculative complexity this project's own methodology argues
  against (see `doc/methodology.md`'s "new tooling earns its place by
  matching a real need, not by being available"). The invariant is scoped
  to live (`is_backfilled=false`) decisions only, checked per-asset before
  the batched LLM call — a genuinely failed/incomplete prior run (no
  persisted row) never blocks a later retry. **Deliberately NOT resolved
  by this decision**: whether a real rerun need ever emerges and, if so,
  whether an override should be able to affect production state directly
  (a separate open question from the B/B2 design analysis, not decided
  here); and how the 40 existing historical duplicate rows should be
  treated for calibration purposes (B2, explicitly deferred, historical
  rows left completely untouched).
- **Historical duplicate-decision calibration treatment (B2): whole-group
  query-level exclusion, no canonical row, no schema change — adopted,
  2026-09-16.** Real, live-confirmed contamination: `/calibration/summary`
  double-counted one asset-day (NEAR, 2026-09-06 — two resolved BUY rows
  from the same duplicate group), 20% of a live directional sample of 5.
  Four row-selection rules were evaluated and rejected before reaching this
  design:
  - **Earliest run**: mechanically simple, but nothing marked it
    authoritative at the time — two more runs followed it unopposed that
    same day, under the pre-B1 system that had no idempotency guard at all.
  - **Latest run**: matches nothing more than an execution-order accident;
    a later same-day run may have used fresher information, or been
    triggered because an operator disliked the first result — a real
    outcome-selection-bias risk, not classic look-ahead, but a bias
    mechanism nonetheless. It also fails a real case outright: NEAR's
    2026-09-06 latest row is still unresolved today, so "always prefer
    latest" would discard two already-resolved, real observations in
    favor of nothing.
  - **Row reflected in final portfolio state**: the clearest case of
    conflating operational fact (which run a human happened to execute
    last) with model evaluation (whether the decision was any good) — and,
    live-confirmed, not even a stable historical property: the one
    duplicate-group row `portfolio_positions.last_decision_id` currently
    points to (LINK, 2026-09-06) is only that group's latest row because
    nothing else has touched LINK's position since; a single later,
    unrelated decision would silently make that no longer true for any of
    that group's three rows, changing the "canonical" answer with no
    connection to the historical day itself.
  - **A durable `superseded`/status field**: would need a new column, a
    migration, and a backfill script reproducing the exact same
    group-membership computation a query-level check already does for
    free — with no offsetting benefit found, since duplicate-group
    membership is a fixed, cheap-to-recompute property (the dataset can't
    grow now that B1 exists) rather than something worth paying schema
    complexity to cache.

  **Adopted instead**: exclude every member of a same-UTC-day,
  same-asset, live (`is_backfilled=false`) group of more than one Judge
  decision from calibration/evaluation entirely — no survivor chosen.
  This is the only option that is simultaneously mechanically derivable
  for all 20 real historical groups (including ones with no BUY/SELL row
  and ones with mixed resolved/unresolved rows), introduces no hindsight,
  and — critically — is **stable regardless of when it's computed**: group
  membership depends only on `judge_decisions` (`asset_id`/`created_at`/
  `is_backfilled`), never on outcome resolution status, so the excluded
  set for a group like NEAR/2026-09-06 (2 resolved + 1 still-unresolved
  today) is provably identical before and after its third row resolves.
  Implemented as a pure, shared, query-level function
  (`compute_duplicate_group_decision_ids`), applied identically across
  every real consumer of the live directional population found during the
  analysis (`/calibration/summary`, `run_composite_weights_validation.py`,
  `calibration_baseline.py`'s live branch) — no database migration, no
  deletion, no modification of any historical row. Raw resolved/unresolved
  audit counts (`resolved_live_count` etc.) are a deliberately separate,
  unfiltered statistic — they answer "how many decision_outcomes rows
  exist," not "how many are valid calibration observations," and changing
  their long-standing meaning was judged out of scope for a fix whose
  purpose is sample integrity, not a redefinition of an unrelated audit
  figure. LLM cost accounting (`app/llm/cost.py`'s `COST_TRACKED_TABLES`)
  is structurally independent of this filter and remains completely
  unaffected — every historical duplicate decision remains real, fully
  counted spend.

- **`MAX_WEEKLY_TURNOVER` measures STRATEGY turnover only; WATCH/NO_TRADE
  risk-control corrections get a separate, uncapped classification, not a
  separate numeric budget — adopted, 2026-09-17.** Real incident: a live
  `--with-judge` run (2026-09-17) found the turnover budget already fully
  exhausted before the run started (0.3149 used vs. 0.30 cap), so a
  compliant BTC rebalance the Risk Engine itself had computed
  (0.30 -> 0.15, correctly bounded by `MAX_SINGLE_ASSET_ALLOCATION`) was
  reverted to zero net change by `apply_turnover_cap`. Forensic tracing
  found the root cause: `RiskEngine._strategy_turnover_delta` already
  treats WATCH/NO_TRADE as zero strategy turnover at decision time (a
  deliberate Phase 5g design choice), but `PortfolioConstructionService
  .apply()` persisted every `portfolio_allocation_changes` row identically
  regardless of `d.decision` — so the exemption existed only in memory and
  was lost the moment the row was written. `get_turnover_since()` then
  re-counted every WATCH/NO_TRADE correction as real strategy turnover on
  every later read. Live-confirmed: 5 of the 8 real historical rows
  (0.1849 of 0.3149 total recorded delta, 58.7%) were risk-control
  corrections, not strategy decisions.

  Three candidate accounting models were considered: (a) exempt
  risk-control rows from the existing strategy budget entirely (chosen);
  (b) give risk-control corrections their own separate numeric weekly
  budget; (c) leave all target movement, including risk-control, inside
  one undifferentiated budget (the status quo being fixed). (c) is the
  proven-incorrect status quo. (b) was rejected: a WATCH/NO_TRADE
  correction is structurally self-limiting, not an independent, repeatable
  source of turnover — `size_one`'s `min(current_allocation,
  max_single_asset_allocation)` clamp can only fire while real holdings
  sit above the cap; the moment it corrects the target to the cap, a
  second WATCH/NO_TRADE decision on the same asset produces
  `final_allocation == previous_system_target` (no new
  `portfolio_allocation_changes` row at all, by `apply()`'s own
  `!=` guard) — it cannot oscillate or repeat the way a discretionary
  strategy rebalance could, so a dedicated cap would police a category of
  risk that doesn't actually recur. (a), the adopted model, matches the
  category's real behavior: track it separately for visibility and audit
  (`change_reason`), but don't budget-limit something that is already
  self-limiting by construction.

  **Implemented**: `PortfolioAllocationChange.change_reason`
  (`"strategy"`/`"risk_control"`, new field, default `"strategy"`), set in
  `PortfolioConstructionService.apply()` from `d.decision` — the
  already-gated `SizedDecision` value — never reconstructed later from
  `judge_decisions.decision` (the raw, pre-confidence-gate value; the real
  2026-09-17 NEAR row's raw decision was "BUY" at confidence 0.50, gated
  to WATCH before sizing, and must classify as risk_control, not
  strategy). `get_turnover_since()` filters `change_reason="strategy"`.
  8 pre-existing historical rows backfilled via `migrations/0021` after
  independently re-deriving each row's real gated decision from
  `actual_allocation_before` + the real confidence-gate thresholds (never
  trusted from a prior analysis pass without re-verification) — 5
  `risk_control`, 3 `strategy`, matching the forensic analysis exactly.
  Corrected 7-day strategy turnover re-derived live post-implementation:
  0.1300 (vs. 0.3149 under the old, uncorrected accounting), remaining
  budget 0.1700 (vs. ~0). This changes the evidence behind the still-open
  A2 (cap-violation-vs-turnover-budget priority) design decision — see
  [`todo.md`](todo.md) — but A2 itself remains **not implemented**; the
  next step is a fresh live re-observation under the corrected accounting,
  not yet performed.

- **A2 resolved: a BUY/HOLD/SELL decision that reduces a genuinely
  oversized `previous_system_target` to, or below,
  `MAX_SINGLE_ASSET_ALLOCATION` is exempt from `MAX_WEEKLY_TURNOVER` —
  adopted, 2026-09-17 (Option C, "risk-control exemption").** A technical
  decision, not a business/risk judgment call — derived directly from this
  project's own existing documented semantics, not chosen on preference.

  **Why this is the technically consistent choice, grounded in the
  repository's own words**: `MAX_WEEKLY_TURNOVER` is documented in
  `app/config/settings.py`'s own comment as *"a circuit breaker against
  excessive STRATEGY TARGET CHURN"*, backed by a real transaction-cost
  analysis (147 resolved decisions) finding average net-of-costs drag of
  only ~0.26pp/decision — too small to justify any specific cap size. A
  forced reduction toward an already-enforced hard constraint
  (`MAX_SINGLE_ASSET_ALLOCATION`) is not discretionary churn by this
  project's own chosen definition of the term. Separately,
  `doc/history.md`'s own architecture summary lists `MAX_SINGLE_ASSET_
  ALLOCATION` and `MAX_WEEKLY_TURNOVER` as co-equal "hard caps" — neither
  is documented as subordinate to the other — so this decision does not
  rest on one cap being "more important," only on `MAX_WEEKLY_TURNOVER`'s
  own stated scope excluding compliance-driven movement.

  **A1 provides the direct precedent**: WATCH/NO_TRADE corrections
  (`size_one`'s `min(current_allocation, max_single_asset_allocation)`
  clamp, Phase 5g) have been unconditionally exempt from
  `apply_turnover_cap` since that fix shipped — confirmed by direct code
  execution with an artificially exhausted budget
  (`turnover_used_this_week=999.0`) leaving a WATCH clamp's target
  completely untouched. A2 is the minimal generalization of this same,
  already-proven mechanism to a second, independent trigger condition
  (a BUY/HOLD/SELL decision whose Risk-Engine target is compliant, coming
  from an oversized previous target) — not a new mechanism.

  **Real motivating incident**: BTC's Risk Engine computed the fully
  cap-compliant target (0.15) on both 2026-09-16 and 2026-09-17 (verified
  by independently re-deriving both via a real `size_one()` call against
  the actual persisted `judge_decisions`/`screened_universe` rows for
  those runs), but the ordinary turnover-cap mechanism blocked or scaled
  it back above cap both times (`TurnoverCapEvent` rows confirm this
  live) — with no guaranteed convergence under the old behavior.

  **Three sub-questions resolved from existing project evidence, not
  invented**:
  - **SELL-to-zero**: treated identically to a partial cap-compliance
    reduction — no code, test, doc, or historical decision anywhere in
    this project distinguishes "reduce to compliance" from "exit
    entirely" as different turnover-policy categories, so inventing that
    distinction now would add an unjustified new concept.
  - **`change_reason`**: reused as `"risk_control"` — no new
    `"cap_correction"` value. Every real consumer of `change_reason`
    (`get_turnover_since()`'s filter, the replay fake's filter, every
    existing test) only ever needs the binary strategy/risk_control
    distinction for budget purposes; distinguishing an A1-triggered row
    from an A2-triggered one remains fully available via the existing
    `decision_id → judge_decisions.decision` join whenever actually
    needed, at zero schema cost.
  - **Epsilon**: `TURNOVER_EPSILON` (already existing, `app/risk/
    engine.py`, introduced for the 2026-09-14 accumulated-float-noise
    incident) is reused for the `previous_system_target > cap` boundary
    only — no new constant. `final_allocation <= cap` needs no epsilon at
    all, since it is always the direct output of a `min()` call, exact by
    construction, never an accumulated sum.

  **Multi-asset behavior**: each qualifying correction is independently
  exempt; no ordering, no shared sub-limit between simultaneously-
  oversized assets — nothing in `apply_turnover_cap`'s actual (unmodified)
  algorithm requires or benefits from one, and Options B ("applied first")
  and C ("excluded from the sum") were verified to be operationally
  identical under this architecture, since both explicitly specify the
  correction never consumes the shared budget.

  **Explicitly rejected, with reasons**: Option D (separate risk-control
  budget) would require inventing a numeric parameter with zero
  supporting evidence anywhere in this project's history — a worse
  epistemic position than even the already-criticized, un-optimized
  30%/7-day `MAX_WEEKLY_TURNOVER` figure. Option E (hybrid) requires an
  undefined safety constraint with no existing precedent to build from.
  Option A (status quo) was rejected because it directly contradicts
  `MAX_WEEKLY_TURNOVER`'s own documented scope.

  **Implemented**: `is_cap_compliance_correction()` (new, module-level,
  pure function, `app/risk/engine.py`) — the single, shared predicate used
  by both `RiskEngine._strategy_turnover_delta()` (the turnover exemption)
  and `PortfolioConstructionService.apply()` (the `change_reason`
  classification), guaranteeing the two layers cannot silently disagree
  (regression-tested). A1's own condition (`decision in ("WATCH",
  "NO_TRADE")`) is completely unchanged, evaluated first, independent of
  A2's condition. No schema change, no migration (the `risk_control` value
  already existed), no `apply_turnover_cap` algorithm change — the desired
  behavior emerges entirely from `_strategy_turnover_delta()` returning
  `0.0` for a qualifying decision, exactly as it already did for A1.
- **`scripts/calibration_baseline.py`'s live/backfill Judge-decision
  retrieval: migrate to `JudgeDecisionRepository.get_recent(limit=None,
  ...)` — adopted, 2026-09-19.** Problem: both `run_live_baseline()` and
  `run_backfill_baseline()` retrieved `judge_decisions` via a raw,
  unpaginated `client.table("judge_decisions")...execute()` call, with no
  `.range()` and no `.order()` — bypassing the repository's own pagination
  abstraction (`_fetch_all_paginated()`, Phase 5m, 2026-09-18) entirely.
  Not yet truncating live (205 real live / 192 real backfilled rows today,
  both under Supabase's real ~1000-row-per-request cap), but the identical
  vulnerable pattern already found and fixed for `llm_analyses`, and B2's
  whole-group duplicate exclusion (this file's B2 entry, above) specifically
  depends on receiving the *complete* live population — a silently
  truncated fetch could split a duplicate group across the cutoff and let
  the visible half through unexcluded.

  **Decision**: both paths now call the existing
  `JudgeDecisionRepository.get_recent(limit=None, is_backfilled=...)` —
  `is_backfilled=False` for `run_live_baseline()`, `is_backfilled=True` for
  `run_backfill_baseline()` — reusing `_fetch_all_paginated()` unchanged.
  No new pagination mechanism was introduced; this is a migration of an
  existing raw-query consumer onto an abstraction that already existed for
  exactly this purpose, not a new fix.

  **Scope**: limited to `run_live_baseline()` and `run_backfill_baseline()`.
  B2's duplicate-group semantics — exclusion of every member of a
  same-UTC-calendar-day, same-asset, live group of more than one Judge
  decision — are unchanged; pagination affects only how completely the
  population is fetched before that grouping logic runs, never the
  grouping rule itself.

  **Validation** (forensic, read-only, 2026-09-19): current live population
  205 decisions, backfilled 192 — both currently under the 1000-row cap, so
  no real production truncation boundary has actually been crossed yet; the
  page-boundary-split-duplicate-group case was instead verified with an
  engineered test (a monkeypatched small page size forcing a real duplicate
  group across a page boundary), not a live 1000+-row dataset. Focused
  tests: 11 passed. Full suite: 633 passed, no failures, no skips. No
  production run or database mutation was performed during validation. See
  [`history.md`](history.md)'s Phase 5n section for the full writeup.

---

# Technology stack decisions (original evidence-source log)

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
- **Deflated Sharpe Ratio / Probability of Backtest Overfitting — adopted,
  3g.** A raw hit-rate or Sharpe ratio computed after several rounds of
  prompt/logic iteration (3d–3f each version bumps, plus repeated
  calibration re-runs) is a classic multiple-comparisons setup: enough
  attempts against the same historical data will eventually produce a
  good-looking number by chance alone, independent of whether the system
  actually has an edge. Deflated Sharpe / PBO exist specifically to correct
  for this, and this project has the bookkeeping to do it properly
  (`prompt_templates`, `calibration_runs`) because that bookkeeping was
  designed in from 3a rather than reconstructed after the fact.
- **Brier score / reliability diagrams — adopted, 3e onward.** The Judge and
  every model assessment emit an explicit `confidence` value that the Risk
  Engine uses directly for position sizing — so whether that confidence is
  *calibrated* (a 70%-confidence call actually resolving positively ~70% of
  the time) is a separate, and arguably more actionable, question than
  whether calls are directionally right on average. Computed per regime, not
  just in aggregate, since a system calibrated in one regime and
  overconfident in another is a materially different (and more dangerous)
  system than one that's uniformly miscalibrated.
- **Held-out decision window — adopted, 3e onward.** Every sub-phase from
  3e forward tags decisions as inside or outside a window that's never used
  to tune prompts or logic, so the 3f/3g "did accuracy improve" comparison
  has at least one slice of results that wasn't iterated against. Cheap to
  add (one boolean column, decided once), and the alternative — discovering
  after months of iteration that there was never a genuinely untouched
  sample — is much more expensive.
- **Order-book / limit-order-book microstructure features (order-flow
  imbalance, spread, price-impact, toxicity) — considered, not adopted.**
  Current research shows these features have real, portable short-horizon
  predictive value on official, already-integrated venues (Binance/Deribit),
  so this isn't a source-availability rejection like CoinAnk/CryptoBubbles —
  it's a scope rejection. This project's Judge operates on multi-day to
  multi-month horizons via structured LLM reasoning; LOB features are
  validated for sub-minute to intraday statistical/ML models with their own
  walk-forward and leakage-control methodology, not for the Judge's evidence
  format. Revisit explicitly (as its own scoped phase, with its own
  validation approach) rather than folding it into an existing sub-phase if
  a shorter-horizon component is ever wanted. Re-examined during the 3k
  gap-analysis pass and reaffirmed unchanged — the horizon-mismatch
  reasoning above doesn't depend on which other evidence sources exist, so
  it wasn't reopened just because 3k was looking at nearby data (order-book
  depth) for other purposes.
- **Aggregate open interest, stablecoin supply/velocity, and exchange-reserve
  flow — adopted, 3c.** All are official/documented-API-accessible from
  venues already integrated by 3c (Binance, Deribit, DefiLlama, the existing
  on-chain explorer), so they're near-zero marginal cost, and each captures
  a distinct fact — position magnitude (OI), capital entering the crypto
  ecosystem (stablecoin supply), whether that capital is actually moving
  (velocity), and capital sitting on exchanges specifically (reserves) —
  that the funding-rate and TVL sources already in scope don't capture on
  their own.
- **Spot ETF flows — adopted, 3c.** Institutional-desk practice increasingly
  treats spot BTC/ETH ETF net flows as the primary medium/long-horizon
  proxy for institutional positioning, read *alongside* (not instead of)
  derivatives leverage data to distinguish capital-driven demand from
  leveraged speculation. Accessed via a documented aggregator (Farside
  Investors / SoSoValue) rather than per-issuer scraping, so it fits the
  same "official/documented source" bar as everything else in 3c. Not
  adopted earlier (3b) because it's a capital-flow fact, not a screening
  input over the open universe — most assets in the universe don't have a
  spot ETF at all.
- **Prediction markets — adopted, 3c, narrowly scoped.** Polymarket/Kalshi
  implied probabilities are a genuinely distinct evidence *type* — a
  market-priced probability for a specific, well-defined outcome, unlike
  options IV (which prices uncertainty magnitude, not a specific outcome) or
  LLM-stated confidence (which isn't backed by capital at risk). Scoped
  narrowly to a curated, liquid contract set rather than broad coverage,
  since thin-liquidity implied probabilities are noise, not signal — this is
  a "verify real access and real liquidity before relying on it" source like
  everything else in 3c, not an assumed-reliable one.
- **Deterministic composite factor score — adopted, 3b.** The Judge's
  primary evidence (3d model assessments, 3f adversarial research) is all
  LLM-narrative-derived, even when it's reasoning over real numbers. A
  simple, deterministic, non-LLM combination of the screening factors
  already computed in 3b (momentum, volatility, drawdown, relative
  strength) gives the Judge — and later, 3g's validation — a purely
  quantitative reference point to check the narrative against, at zero
  marginal LLM cost. Deliberately kept simple and inspectable (documented
  weights, not a trained model) rather than a fitted quant model, consistent
  with this project's "simple and auditable over sophisticated and opaque"
  approach to every other deterministic component (Risk Engine sizing,
  regime classifier).
- **On-chain valuation-cycle metrics (MVRV/SOPR/NUPL/LTH-STH cohorts) —
  adopted, 3c.** Professional on-chain research treats these as the
  foundational metric set for cycle-position valuation — distinct from both
  the transfer-flow/TVL data already in 3c (which measures capital
  movement, not where the holder base sits relative to cost basis) and from
  the LLM-narrative evidence in 3d/3f. Accessed via a documented provider
  (Glassnode or CryptoQuant); a paid tier may be required for full
  coverage, which is a dollar cost to weigh against project budget, not an
  LLM cost, so it doesn't touch `CostGuard`. Coverage is expected to be
  BTC/ETH-strong and thin-to-absent for most smaller-cap assets in the
  universe, consistent with how every other 3c source handles uneven
  per-asset coverage.
- **Futures term structure / basis — adopted, 3c.** The perpetual funding
  rate (already in 3c) captures perpetual-specific positioning and open
  interest captures magnitude, but neither captures how futures desks price
  forward expectations across concrete expiries the way a dated-futures
  contango/backwardation curve does — a materially different signal, at
  near-zero marginal integration cost since it's the same Binance/Deribit
  venues already integrated for funding and options.
- **Token unlock/vesting schedule — adopted, 3c.** Structurally unlike every
  other source in this project: it's a calendar-dated *known future event*
  rather than a read of current market/on-chain state. Particularly
  relevant to this project's altcoin-heavy `in_asset = true` universe
  (ONDO, ENA, JASMY, S, STORJ, JTO, etc.), where scheduled unlocks are a
  real, foreseeable supply-side catalyst that price/volume/on-chain data
  alone won't surface in advance. A natural input to the Judge's
  `invalidation_conditions` (3e) rather than just another risk factor,
  since the event date is known rather than inferred.
- **Social/narrative sentiment — adopted, 3f, fragile.** Aggregate social
  volume / trending-narrative tracking (Santiment/LunarCrush-style) is a
  genuinely distinct evidence type from both Phase 2's RSS news (editorial
  coverage) and 3f's PlanB/X source (one named analyst's stated opinion) —
  it's an aggregate attention signal across many unnamed accounts. Placed
  in 3f rather than 3c because reliable, reasonably priced programmatic
  access is unverified going in, unlike the documented-API sources in 3c;
  a low-effort/`UNAVAILABLE` outcome here is an acceptable result, same as
  CoinAnk or CryptoBubbles.
- **CME futures positioning (CFTC COT) — adopted, 3c.** A free, official,
  weekly government report giving a regulated-futures view of institutional
  positioning by trader category — distinct in kind from spot ETF flows
  (fund-level capital movement) and perpetual funding rate (crypto-native
  leverage), both already in 3c. Deliberately does not hard-code the
  traditional "commercials are smart money" reading, since independent
  analysis of BTC's COT data finds that relationship doesn't reliably
  transfer from other commodities — the raw category breakdown is stored,
  and any smart-money inference is left to the Judge.
- **BTC miner metrics — adopted, 3c.** Hash rate, difficulty, and miner
  reserve/exchange-flow data are a standard on-chain research category
  (miner capitulation/recovery signals) sitting alongside the MVRV/SOPR/
  NUPL metrics already scoped for 3c, typically from the same vendor
  (Glassnode/CryptoQuant), so the marginal integration cost is low.
  BTC-specific only — the mining security-budget dynamic doesn't transfer
  to most of the rest of the universe.
- **Global liquidity & cross-asset correlation (FRED) — adopted, 3f.** M2
  growth, Fed balance sheet, and reverse-repo levels are widely treated in
  crypto-macro research as a more informative multi-month driver than any
  single data print, and BTC's rolling correlation to equities/gold/DXY
  speaks directly to whether crypto is currently trading as a macro risk
  asset. FRED is free, official, and documented, which keeps this to the
  same reliability bar as everything else — placed in 3f because that's
  where the macro-evidence-matrix logic already lives, not because the
  access itself is fragile.
- **Regulatory/policy event calendar — adopted, 3f, feasibility-gated.**
  SEC EDGAR and congress.gov are both free, official, documented government
  APIs — the access itself is not the risky part. What's unverified is
  reliably extracting a dated, asset-specific, investment-relevant event
  from raw filings/bills without an unacceptable false-positive/negative
  rate, which is a similar risk profile to PlanB/X's post-parsing. Grouped
  with 3f's feasibility-gated sources for that reason; a global/macro-scope
  version (not attributed to a specific asset) is an acceptable fallback if
  per-asset attribution isn't reliably achievable.
- **Adaptive evidence-value ranking — adopted, 3h, diagnostic only.**
  3f/3g's before/after calibration comparisons and manual
  `signal_sources.enabled` toggling answer "did this source help" only in
  aggregate and only when a human explicitly re-runs the comparison. A
  simple, inspectable supervised model trained on `decision_outcomes`
  produces a learned importance ranking across all structured evidence
  fields at once, checked against — never blended into — the Judge's own
  implicit weighting. Kept strictly diagnostic (same rule as
  `composite_factor_score`'s relationship to the Judge) because turning a
  small-sample learned model into a live re-weighting mechanism risks
  exactly the overfitting-to-noise failure mode 3g's Deflated Sharpe/PBO
  correction exists to catch.
- **Evidence-value drift detection (rolling-window/regime-sliced) —
  adopted, 3h.** A single full-history importance ranking (above) can hide
  a source whose predictive value has genuinely shifted — crypto regimes
  turn over fast enough (pre-ETF vs. post-ETF, a deleveraging year vs. a
  quieter one) that a source informative in one stretch and inert in
  another can average out to "mediocre" rather than surface as the more
  actionable finding, "this source's value is regime-dependent." Re-running
  task 1's method over rolling windows and regime slices, with the same
  minimum-sample-size gating, catches that distinction at negligible extra
  cost since it reuses the same modeling approach and data.
- **Portfolio tail-risk stress testing — adopted, 3h.** The Risk Engine's
  per-asset caps, volatility-adjusted sizing, and correlation-concentration
  flag (3e) are all real-time/forward-looking checks; none of them asks
  "what would this portfolio's drawdown have been in a historical
  correlated-crash scenario," which is standard practice at institutional
  risk desks before sizing is trusted. Kept simple and inspectable
  (documented scenario templates, not a fitted tail-risk model), consistent
  with every other deterministic component in this project, and explicitly
  labels any cross-asset historical-data assumption as an assumption rather
  than measured history.
- **Screening-stage anomaly/wash-trading flag — adopted, 3b.** The smaller-
  cap tier of an open, discovery-driven universe is exactly where wash
  trading and pump-and-dump volume patterns are most likely to surface as
  a "candidate" on raw momentum/volume factors alone. A cheap z-score/
  percentage-jump check at screening time, before any evidence collection
  or LLM cost is spent on an asset, is a proportionate response — flagging
  rather than excluding, so the anomaly stays visible rather than silently
  filtering the universe.
- **BTC dominance / altcoin-season index — adopted, 3b.** The risk-on/
  risk-off regime classification answers "is crypto broadly attracting or
  shedding capital," but not the orthogonal, equally-watched professional
  question of whether capital is rotating *within* crypto, from BTC into
  alts or back. A derived, zero-marginal-cost computation from data 3b
  already collects (BTC's share of screened-universe market cap and its
  trend, plus the standard "% of the universe outperforming BTC over a
  trailing window" formulation) gives the regime snapshot that second axis
  without a new external source or a new table.
- **Volatility risk premium (VRP) — adopted, 3c.** Deribit's implied
  volatility (already captured) says how much uncertainty options are
  pricing in, but professional options desks read that relative to
  realized volatility — the spread between the two is what actually prices
  the risk premium options sellers earn, and it behaves differently from
  either input alone. A derived field pairing task 3's IV with 3b's
  already-computed realized-volatility factor, at zero marginal cost.
- **Annualized futures basis/carry yield — adopted, 3c.** The raw
  dated-futures basis curve (already captured) is comparable within an
  asset across expiries but awkward to compare across assets or against a
  risk-free-rate benchmark. Annualizing it — a straightforward
  transformation of data already collected — makes the term-structure
  signal directly usable the way a fixed-income desk reads a carry trade,
  without adding a new source or an interpretation judgment at the
  collector level.
- **Regional exchange premium — adopted, 3f, fragile.** A structural,
  region-specific price gap (historically documented as the Korean "Kimchi
  premium") reflects a genuinely different economic mechanism — capital
  controls and regionally concentrated retail speculative intensity — than
  the ordinary cross-venue aggregation noise 3b already logs between
  globally arbitraged venues. Grouped with 3f's fragile sources because
  reliable, ToS-compliant programmatic access to the relevant regional
  exchange is unverified going in; a low-effort/`UNAVAILABLE` outcome is an
  acceptable result, same as CoinAnk or CryptoBubbles.
- **Entity-flow intelligence (Nansen/Arkham-class) — adopted, 3i.** 3c's
  Etherscan-based on-chain source explicitly documents a known limitation:
  a raw large-transfer count has no entity clustering behind it, so it
  conflates genuine whale accumulation with routine exchange-internal
  traffic. A paid, documented wallet-entity-clustering provider closes that
  specific gap by labeling *who* is moving funds, not just that a transfer
  occurred — a materially higher-confidence fact, though still not a
  directional signal on its own (a labeled "smart money" cohort can be
  wrong same as anyone). Scoped to 3i, after 3h, since it's genuinely new
  evidence-collection work identified in the same gap-analysis pass that
  produced 3h, not a diagnostic addition.
- **Custody/OTC desk flow tracking — adopted, 3i.** A growing share of
  institutional crypto activity, especially post-spot-ETF, happens through
  custody providers or OTC desks and never touches a public exchange order
  book — meaning it's invisible to both 3c's exchange-reserve proxy and
  its spot-ETF-flow source. Tracking known custody-provider address
  balances (e.g. Coinbase Custody, Fidelity Digital Assets) closes that
  visibility gap at near-zero marginal cost, reusing the on-chain explorer
  relationship already established in 3c.
- **Network usage & developer-activity fundamentals — adopted, 3i.**
  Distinct from both price-derived screening factors (3b) and on-chain
  valuation-cycle metrics (3c, which describe where the holder base sits
  relative to cost basis): active addresses, transaction throughput, and
  fee revenue measure raw usage, and developer/commit activity measures
  building activity — both slower-moving, more fundamentals-oriented
  evidence types that professional long-horizon research treats as
  differentiated inputs, fitting the Judge's existing 90-day-and-longer
  horizon reasoning.
- **Langfuse — adopted, optional starting 3d.** Complements, not replaces,
  the manual prompt-versioning (`prompt_templates`) and cost tracking
  (`CostGuard`, `estimated_cost` columns) already designed into Phase 3 —
  it adds a UI for tracing individual calls and comparing prompt versions
  once there's enough call volume and outcome data (from 3e's
  decision-outcome ledger) to make that comparison meaningful. Strictly
  additive instrumentation: the decision pipeline must run identically
  whether or not Langfuse is configured.

