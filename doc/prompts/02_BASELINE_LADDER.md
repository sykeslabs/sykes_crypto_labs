# Build: Simple-baseline / incremental-value ladder (todo [HIGH][Quant/Backtest])

## Context

Read `doc/todo.md` → "[HIGH][Quant/Backtest] Simple-baseline / incremental-value ladder"
and `doc/history.md`'s periodicity-fix entry (2026-09-12) first.

The central question: **does each layer add value over the simpler layer beneath it, on
the same observations?** Headline reason this matters: old decision-level Sharpe ≈ 1.846,
periodicity-corrected pooled-daily Sharpe ≈ 0.295, BTC buy-and-hold ≈ 0.313.

What already exists (verified 2026-10-02):

- `app/benchmarks/baseline_comparison.py` (`build_equal_weight_basket_path`,
  `compute_baseline_stats`) + `scripts/run_benchmark_comparison.py`: BTC B&H and
  equal-weight basket, Sharpe/max DD/total return, raw and net of `round_trip_cost_pct`.
- `scripts/run_composite_weights_validation.py`: current vs. equal vs. momentum-only
  weights, correlation/mean-score only, not P&L.
- `scripts/run_periodicity_fix.py`: pools per-decision daily returns over each
  decision's `[decision_timestamp, evaluated_at]`. **Backfilled decisions only.**
- `compute_composite_factor_scores(rows, weights=...)` in `app/market_data/factors.py`
  supports a weights override.
- Clean holdout cohort: `HOLDOUT_COHORT_START` in `app/benchmarks/schemas.py`.

None of these share assets, dates, cutoff, holding period or costs.

## Goal

One deterministic script that evaluates all rungs on **one shared observation set** with
the same holding-period, cost and metric definitions, and reports each rung's
incremental contribution over the rung below.

## Part 1 — prerequisite: extend `run_periodicity_fix.py` to live decisions

- Add live decisions, reported **separately** (backfilled / live pre-cohort / holdout
  cohort). Never pooled into one number.
- Extract the daily-return pooling into a reusable function (the ladder needs it).
  Keep the script's existing output unchanged for backfilled.
- Stop after Part 1, show me the new output, wait for OK.

## Step 0 for Part 2 — propose the observation set, then stop (required)

Propose and show me, with real counts (read-only queries):

1. **Observation set**: the set of (decision date, candidate universe) pairs all rungs
   are evaluated on. Proposed default: every date that has a persisted Judge run,
   with that day's screened universe (`screened_universe` rows, live + post-2026-09-12
   backfill). Count dates and assets per date per population.
2. **Holding period**: proposed default: each position held for the Judge decision's
   own `investment_horizon_days`; deterministic rungs use the same horizon distribution
   (ask me if a fixed horizon is simpler).
3. **Rungs reachable now** (adapt, and tell me which you drop and why):
   1. BTC buy-and-hold
   2. Equal-weight basket of that day's universe
   3. Market-cap-weighted basket (needs historical market caps — may not be reachable;
      see todo item 01. Drop with a note if not)
   4. Momentum-only (`weights` override, top-N by `momentum_30d`)
   5. Composite-factor top-N (`COMPOSITE_FACTOR_WEIGHTS`, N = `top_candidates_size`)
   6. Composite + LLM assessments (deterministic rule on persisted assessments, e.g.
      majority direction; defined in prompt 03 — leave a stub/skip if 03 isn't done)
   7. Full system (actual Judge BUY/SELL decisions after Risk Engine)
4. **Costs**: `round_trip_cost_pct` applied per entry/exit, same for all rungs.
5. **Metrics**: pooled-daily Sharpe, mean daily return, max drawdown, hit rate, turnover,
   cost drag; for each rung k ≥ 2, the **paired** daily-return difference vs. rung k-1
   with a bootstrap confidence interval. Propose the bootstrap (block length) and say
   if you're unsure it fits overlapping positions.

**Wait for my confirmation.**

## Part 2 — implementation

- One module (e.g. `app/benchmarks/baseline_ladder.py`) with pure functions, one script
  (`scripts/run_baseline_ladder.py`). Reuse the existing functions above; don't copy them.
- Output: one table, rows = rungs, columns = metrics, **one table per population**
  (backfilled / live pre-cohort / holdout cohort). Print n per cell.
- Every figure printed with "directional only — not confirmatory" unless
  `holdout_cohort_confirmatory` is true, plus the universe-selection-bias note for
  backfilled (item 01).
- Zero LLM cost. Read-only DB. Market data via the existing Binance/Coinbase fetchers.
- Don't persist results to a new table unless I ask.

## Tests

Small synthetic price paths with known answers: equal-weight path, momentum top-N
selection, cost application, paired-difference sign, population split (no row in two
populations), holdout cohort boundary.

## Docs (show diff first)

`doc/todo.md` item (keep open: the ladder existing ≠ question answered),
`doc/history.md` entry with the actual numbers, `doc/scripts.md` entry for the new script.

## Ground rules

Simplest solution; no new tables or abstractions beyond the one module. Don't touch
unrelated code. Flag uncertainty. No DB writes, no LLM calls. Never fit/select anything
on the holdout cohort.
