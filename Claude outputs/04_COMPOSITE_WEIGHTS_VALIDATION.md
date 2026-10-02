# Validate: Composite factor weights (todo [HIGH][Quant])

## Context

Read `doc/todo.md` → "[HIGH][Quant] Composite factor weights — empirical validation
still unresolved" first.

Verified 2026-10-02:

- `COMPOSITE_FACTOR_WEIGHTS` in `app/market_data/factors.py` (~line 86):
  momentum_30d 0.30, momentum_7d 0.15, relative_strength_30d 0.20, volatility_30d 0.15
  (inverted), drawdown_30d 0.10 (inverted), volume_24h 0.10. Chosen, never fit.
- `scripts/run_composite_weights_validation.py` compares current vs. equal-weight vs.
  momentum-only on resolved BUY/SELL decisions joinable to `screened_universe`.
  Last check: n = 2 joinable.
- **Key observation:** the weights only rank assets. They can be evaluated **without
  any Judge decision**: `compute_point_in_time_factors` (`app/benchmarks/
  historical_factors.py`) computes the factors for any past date from OHLCV, so you can
  measure each weighting's cross-sectional rank correlation with forward returns over a
  long history, at zero LLM cost.

## Goal

A deterministic, long-history test of whether the current weights rank assets better
than equal-weight and momentum-only, by forward return.

## Step 0 — required, then stop

1. Re-run the existing script's join count read-only (no writes). Report n.
2. Propose the new test:
   - Dates: daily (or weekly, to reduce overlap) cutoffs over a window you propose,
     **ending before `TRAINING_WINDOW_END`** so the holdout cohort period stays untouched
     for later confirmation.
   - Universe per date: same asset list replay uses. **This inherits item 01's
     survivorship bias.** Say so in the output. If item 01 is fixed, use the
     point-in-time universe instead.
   - Forward return horizons: 14 / 30 days (match common Judge horizons).
   - Metric: per-date Spearman rank IC between composite score and forward return, mean
     IC, IC t-stat with overlap-adjusted (Newey-West) standard error, hit rate of
     top-N vs. bottom-N spread. Flag if you're unsure the SE correction is right.
   - Schemes: current, equal-weight, momentum-only (exactly as the existing script
     defines them).
3. Estimate the number of OHLCV fetches. **Wait for my OK.**

## Implementation

- Add a mode to `scripts/run_composite_weights_validation.py` (e.g.
  `--deterministic-history --start --end`), reusing `compute_point_in_time_factors` and
  `compute_composite_factor_scores(weights=...)`. Keep the existing mode unchanged.
- Print one table: scheme × horizon → mean IC, SE, t, n dates, top–bottom spread.
- Do **not** change `COMPOSITE_FACTOR_WEIGHTS`. If results suggest a change, write it up
  as a proposal; changing live weights is a separate decision.
- Note in output: in-sample over history, not out-of-sample confirmation.

## Tests

IC on a synthetic universe where the answer is known; weights override used correctly;
inverted factors handled; end date > `TRAINING_WINDOW_END` refused.

## Docs (show diff first)

`doc/todo.md` (status + numbers), `doc/history.md`, `doc/scripts.md`.

## Ground rules

Simplest solution. Don't touch unrelated code. Flag uncertainty. No DB writes, no LLM
calls. Don't tune weights on this data and then report the tuned result as validation.
