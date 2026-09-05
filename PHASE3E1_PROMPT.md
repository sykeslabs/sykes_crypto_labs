# AI Crypto Portfolio — Phase 3e.1: Retroactive Historical Replay (Backfilled Decision Simulation)

## Context

This runs immediately after 3e (Judge, Risk Engine, Portfolio Construction,
continuous decision-outcome ledger) is complete and live-verified, and
before 3f's new evidence sources arrive.

**Motivation:** waiting months for `decision_outcomes` to accumulate
naturally is slow. This sub-phase replays the already-built pipeline
against the past ~4 weeks so accuracy signal starts accumulating faster —
but only for evidence that can be honestly reconstructed as it would have
looked at a past point in time. This is deliberately **not** the same thing
as 3g's point-in-time/look-ahead-bias audit: that audit checks whether
*real, live* decisions leaked future information; this sub-phase *creates
new, synthetic* decisions by re-running the pipeline against the past, and
carries a distinct risk — most evidence providers only expose their
*current, already-corrected* state for a past date, not what was actually
knowable then. Backfilling with today's value under a historical timestamp
is precisely the hindsight-inflation problem 3a's `is_revision_of` design
exists to prevent, just introduced through mass backfill instead of one
revised row.

**This is a diagnostic supplement, not a substitute for forward tracking.**
Nothing here should make the live, continuously-accumulating baseline from
3e look faster or slower than it really is — the two are reported
separately, always.

## Non-negotiables

- PAPER ONLY — unchanged from every other sub-phase.
- Every row this sub-phase creates in `judge_decisions` /
  `decision_outcomes` must be tagged `is_backfilled = true` (new column,
  see task 2). No existing row is touched.
- **Backfilled rows are never counted as forward-tracked evidence.**
  Specifically: never `in_holdout_window = true`; never included in 3g's
  deflated-Sharpe/PBO trial count as if they were live iterations; never
  blended into a single hit-rate/Brier number with forward-tracked
  decisions. Backfilled-window accuracy and forward-tracked accuracy are
  always reported as two distinct numbers, never one.
- **Only genuinely point-in-time-reconstructable evidence gets backfilled
  as real.** Price/volume/OHLCV history and (where the exchange exposes
  historical series) funding rates are fine. On-chain valuation metrics,
  ETF flow figures, regulatory-event classification, social sentiment, and
  entity-flow data are NOT reliably backfillable from most providers —
  these must be marked `UNAVAILABLE` for the backfilled window, exactly
  like a live `UNKNOWN`/`UNAVAILABLE` source, never fabricated by dating
  today's value with a past `retrieval_timestamp`. See task 1.
- **Real LLM calls will be made** (model-assessment + Judge stages, once
  per replayed timestamp per candidate). This is real cost, gated by
  `CostGuard` and estimated before running, same as any other cost-bearing
  task — this sub-phase is explicitly not "free because the data already
  exists." See task 4.
- No change to Phase 1/2 or to the live pipeline's real-time behavior. This
  is an additive, invoked-on-demand replay mode — it does not run
  automatically alongside live collection.

## Task detail

**1. Evidence feasibility classification.**
Before writing the replay runner, document (in the README section this
sub-phase adds) which evidence types are genuinely backfillable and which
are not:
- **Backfillable:** price/volume/OHLCV (CoinGecko/CoinMarketCap/Coinbase/
  Binance historical endpoints), and per-exchange historical funding rate
  series where the exchange actually exposes one (verify per-source, don't
  assume).
- **Not reliably backfillable (mark `UNAVAILABLE` for the replay window):**
  on-chain valuation-cycle metrics (MVRV/SOPR/NUPL), spot ETF flows,
  regulatory-event classification, social/narrative sentiment,
  entity-flow/custody-OTC data — these providers typically only serve
  current, already-corrected values for a past date.
This classification is itself a documented decision, not just an
implementation detail — it's what lets anyone reading a backfilled result
understand exactly which inputs the replayed Judge actually had.

**2. Schema: `is_backfilled` flag.**
Add `is_backfilled` (boolean, default `false`) to `judge_decisions` and
`decision_outcomes` — idempotent migration, new file, not an edit to prior
migrations.

**3. Replay runner (`app/benchmarks/replay.py` or similar).**
Given a date range (default: past 4 weeks) and granularity (default:
daily), for each historical timestamp T:
- Gather feasible evidence as it would have looked at T (real historical
  price/volume/funding data, `retrieval_timestamp` genuinely set to T, not
  today) using 3a's "value as known at time T" convention where
  applicable.
- Mark infeasible sources `UNAVAILABLE` for T — never populate them from
  current data.
- Run the same model-assessment → Judge → Risk Engine → Portfolio
  Construction pipeline 3e already built, unmodified.
- Persist the resulting `judge_decisions`/`decision_outcomes` rows with
  `is_backfilled = true`.

**4. Cost estimate & CostGuard gate.**
Before executing a full backfill run, estimate total model-assessment/Judge
calls for the chosen window × candidate count and compare against
`MAX_DAILY_LLM_COST`/`MAX_MONTHLY_LLM_COST`. If a single run would consume
a large share of the budget, require an explicit confirmation flag and/or
batch the run across multiple days rather than spending the full monthly
cap in one invocation. `judge_decisions` is already in `COST_TRACKED_TABLES`
(3e) — no new registration needed, but log actual cost/day observed.

**5. Outcome evaluation.**
Because the window being replayed is fully in the past, real subsequent
price data already exists — reuse 3e's triple-barrier-style evaluation step
directly to resolve `HIT_TARGET`/`HIT_STOP`/`TIMED_OUT` for every backfilled
decision immediately, rather than waiting on a horizon. This is the actual
payoff of backfilling: labels are real, not synthetic, for the
price-derived side of the evaluation.

**6. Reporting.**
Extend 3e's calibration script so backfilled-window hit-rate/Brier score is
always computed and reported *separately* from the live forward-tracked
baseline — never merged into one number. Persist to `calibration_runs` with
a `method` value that distinguishes it (e.g. `BACKFILL_BASELINE`) so 3g can
tell the two apart when applying multiple-comparisons correction.

**7. Tests.**
`pytest` passes without live credentials, covering:
- Infeasible sources are marked `UNAVAILABLE` in backfill mode, never
  fabricated from current data.
- `is_backfilled = true` is set correctly on every row this sub-phase
  creates, and never on rows outside it.
- A backfilled row is never marked `in_holdout_window = true`.
- The cost-estimate function returns a sane figure against a fixture
  window/candidate count.

**8. Documentation.**
Update `README.md`: document the replay capability, the evidence-feasibility
classification from task 1 (name which sources are `UNAVAILABLE` in
backfill mode and why), and report the actual backfilled-window accuracy
number observed — clearly separated from the forward-tracked baseline.

## Exit criteria

- Migration applied: `is_backfilled` exists on `judge_decisions` and
  `decision_outcomes`.
- A real replay run over a historical window (validate on a short window
  first, then scale toward ~4 weeks) produces tagged, resolved decisions.
- Evidence-feasibility classification is documented; infeasible sources
  show `UNAVAILABLE` on every backfilled row, never a fabricated
  point-in-time value.
- Cost estimated and checked against `CostGuard` caps before the full run;
  actual cost/day logged in the README.
- Backfilled-window hit-rate/Brier score reported distinctly from the
  forward-tracked baseline — never combined into one figure.
- No backfilled row is ever marked `in_holdout_window = true`.
- `pytest` green without live credentials.
- README updated.

Stop here, report the backfilled-window accuracy observed and which
evidence types turned out infeasible, and wait for confirmation before
starting 3f.
