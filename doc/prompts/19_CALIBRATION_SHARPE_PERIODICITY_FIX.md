# Fix: `/calibration/summary`'s Sharpe/DSR repeats the already-debunked periodicity bug (todo [CRITICAL][Backtest/Quant])

## Context

Read `doc/todo.md` → "A. Active research" → "[CRITICAL][Backtest/Quant]
`/calibration/summary`'s Sharpe/DSR methodology is not periodicity-matched"
first, and `doc/reviews/2026-10-02_INVESTMENT_VALIDITY_REVIEW.md` (finding
F.1) for the full writeup.

Verified 2026-10-02, read-only:

- `_directional_stats` (`app/api/routers/calibration.py:69-98`) builds
  `returns = [d[2] for d in directional if d[2] is not None]` where each
  element is one resolved decision's **total** `realized_return` over its
  own `[decision_timestamp, evaluated_at]` window (14 to 90+ days per
  `scripts/calibration_baseline.py:21,341`), then feeds that list straight
  into `sample_sharpe_stats(returns)` (`app/benchmarks/
  statistical_validation.py:99-116`) and `deflated_sharpe_ratio(...,
  n_observations=n, ...)` — one "observation" per decision, not per day.
- This is **exactly** the decision-level methodology `scripts/
  run_periodicity_fix.py` already proved inflates Sharpe: old
  decision-level ≈1.846 vs. corrected, periodicity-matched pooled-daily
  ≈0.295 (live-verified today: `calibration_runs`, `method=
  "pooled_daily_sharpe_periodicity_fix"`, `run_at=2026-09-12`,
  `sharpe_decision_level=1.8457112130507511`,
  `sharpe_pooled_daily=0.29538834156876825` — exact figures, not rounded
  restatements).
- `_directional_stats` is reused identically for **every** slice
  `/calibration/summary` reports — combined, backfilled-only, live-only,
  by-prompt-version, and **`holdout_cohort_stats`**
  (`calibration.py:223-234`, feeding `sharpe_decision_level_holdout_cohort`/
  `deflated_sharpe_ratio_holdout_cohort` and the `holdout_cohort_confirmatory`
  flag `doc/todo.md`'s embargo item depends on). **This means the one
  number meant to eventually declare the system's edge confirmatory would,
  as written today, repeat a bug the project already caught and fixed once
  elsewhere.**
- `run_periodicity_fix.py` itself (`scripts/run_periodicity_fix.py:54-70`,
  `pooled_daily_returns_for_decision`) is the existing, working fix
  methodology: fetch real daily OHLCV (Binance primary, Coinbase fallback)
  over each decision's own window, compute daily returns (SELL-inverted),
  pool across decisions, compute Sharpe over the pooled daily series. It
  is currently **backfilled-only** (`fetch_resolved_backfilled_outcomes`,
  line 73) — `doc/todo.md`'s baseline-ladder item already names "extend to
  live decisions" as a known, not-yet-actioned prerequisite gap. This
  prompt and that gap are the same underlying problem; do not build a
  second, parallel fix.
- `run_periodicity_fix.py` persists its result to `calibration_runs`
  (`CalibrationRunRecord`, `method="pooled_daily_sharpe_periodicity_fix"`)
  as a one-off batch run, not something `/calibration/summary` reads from
  or recomputes live. The live endpoint does zero external API calls today
  (pure DB aggregation) — adding a real OHLCV fetch per request would be a
  real architecture/latency change, not a drop-in fix.

## Step 0 — required, then stop

The real open design question is **where the periodicity-matched
computation lives**, not whether it's needed. Present these options with
real numbers (how many decisions/assets would need fresh OHLCV fetches,
roughly how long a full recompute takes) and **wait for my decision**:

1. **Batch, persisted, endpoint reads it**: extend `run_periodicity_fix.py`
   to cover live decisions too (closing the existing known gap), run it
   periodically (reuse the Sunday-cadence convention `doc/scripts.md`
   already uses for other weekly batch jobs), and have `/calibration/
   summary` read the latest persisted `calibration_runs` row for the
   pooled-daily figure instead of (or alongside) its own decision-level
   one — no live OHLCV fetch added to the request path.
2. **Live, on-demand**: have the endpoint fetch/cache OHLCV per request.
   Flag the real latency/cost this adds to every dashboard load.
3. **Scope to the holdout cohort only, for now**: since the holdout cohort
   has 0 rows today and won't be evaluated until it reaches n≥50 (not
   before ~2026-11-13 per the embargo item), the minimum fix needed
   *urgently* is ensuring `holdout_cohort_confirmatory`'s own Sharpe/DSR
   fields use the pooled-daily method once that cohort has data — the
   combined/backfilled/live top-level fields could keep today's
   decision-level figure (already labeled "kept for backward
   compatibility," `calibration.py:149-158`) a while longer, clearly
   additionally labeled as periodicity-mismatched, if that's preferred
   over a bigger rework right now.

Also report: real current count of resolved directional decisions needing
a pooled-daily recompute (live + backfilled), and whether `run_periodicity_
fix.py`'s existing OHLCV-fetch approach realistically scales to that count
without excessive API calls (reuse its own `HISTORICAL_FETCH_DAYS=1000`
unpaginated-fetch convention where possible, don't invent a new fetch
pattern).

## Design (decided — do not change without asking)

- Whatever Step 0 chooses, **never silently drop the existing
  decision-level fields** — `doc/todo.md`/this project's own convention is
  to keep a bug's own "before" figure visible for comparison (see how
  `run_periodicity_fix.py` itself prints OLD vs. NEW side by side). Add
  pooled-daily fields alongside, don't replace in place, unless Step 0
  explicitly decides otherwise.
- `holdout_cohort_confirmatory`'s definition (`calibration.py`, this
  session's embargo work) — uncontaminated AND `directional_sample_size_
  holdout_cohort >= MIN_SAMPLE_SIZE` — stays unchanged by this prompt.
  This prompt only changes **what Sharpe/DSR value is reported once that
  flag is true**, not the flag's own logic.

## Implementation (after Step 0)

1. Whichever option Step 0 picks, reuse `pooled_daily_returns_for_decision`
   and `sample_sharpe_stats`/`deflated_sharpe_ratio` exactly as `run_
   periodicity_fix.py` already calls them — do not re-derive the pooling
   math.
2. If extending `run_periodicity_fix.py` to live decisions (closing the
   existing known gap either way): keep backfilled/live as separate pooled
   series, matching every other backfilled/live split already in
   `CalibrationSummary` — never silently blend them.
3. Add new field(s) to `CalibrationSummary` (`app/api/schemas.py`) and the
   corresponding computation in `calibration.py`, following the exact
   naming convention already used for the `_holdout_cohort` suffix fields
   added this session.
4. Dashboard: add the new figure next to the existing Sharpe/DSR rows,
   reusing the existing `triStat`/badge patterns — no new UI component.

## Tests

A synthetic case where decision-level Sharpe and pooled-daily Sharpe
diverge (the exact OLD/NEW divergence `run_periodicity_fix.py`'s own
docstring describes) proves the new field is genuinely periodicity-matched,
not a re-labeled copy of the old one. Boundary/empty-population cases
matching the existing `_directional_stats` test conventions
(`tests/test_api_endpoints.py`).

## Docs (show diff first)

`doc/todo.md` (close this CRITICAL item only once the chosen fix is live
and verified against real data — not merely implemented), `doc/history.md`,
`doc/decisions.md` (record which Step-0 option was chosen and why),
`doc/scripts.md` if `run_periodicity_fix.py`'s cadence changes.

## Ground rules

Simplest solution. Don't touch unrelated code. Flag uncertainty. No DB
writes beyond what Step 0's chosen design requires. Never report a
"confirmatory" Sharpe/DSR figure computed with the decision-level method
once this ships — if the fix isn't ready yet, the existing
`held_out_window_note`/directional-only caveat stays in force.
