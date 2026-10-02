# Build: portfolio-performance attribution — alpha vs. beta vs. risk-control vs. timing (todo [MEDIUM][Quant])

## Context

Read `doc/todo.md` → "A. Active research" → "[MEDIUM][Quant]
Portfolio-performance attribution (alpha/beta/risk-control/timing)" first,
and `doc/reviews/2026-10-02_INVESTMENT_VALIDITY_REVIEW.md` (§13, finding
F.6) for the full writeup. **Depends on `doc/prompts/
21_CHANGE_REASON_CAPACITY_BLOCK_FIX.md` being done first** — this
prompt's attribution is only as correct as `change_reason`'s own
classification, and 21 fixes a confirmed real misclassification in it.

Verified 2026-10-02, read-only:

- No code anywhere currently decomposes realized performance into alpha /
  beta / risk-control / timing / portfolio-construction / randomness
  buckets. `change_reason` (`"strategy"` vs. `"risk_control"`,
  `app/portfolio/schemas.py`, set in `app/portfolio/construction.py:
  121-126`) is the one real building block that exists, but it is
  currently consumed **only** by `get_turnover_since`'s budget filter
  (`app/database/repository.py:1147-1163`) — never by any performance
  report.
- `scripts/run_periodicity_fix.py`'s `pooled_daily_returns_for_decision`
  (lines 61-70) already correctly constructs a periodicity-matched,
  per-position daily return series from real OHLCV over each decision's
  own `[decision_timestamp, evaluated_at]` window — this is the return
  series to reuse for a beta regression, not a new one. (If `doc/prompts/
  19_CALIBRATION_SHARPE_PERIODICITY_FIX.md` has already extended this to
  live decisions and/or changed where it's persisted by the time this
  runs, use that version — don't duplicate the pooling logic a third
  time.)
- `portfolio_allocation_changes.change_reason` lets a resolved decision be
  joined back to whether its most recent allocation change was
  `"strategy"`-driven or `"risk_control"`-driven at the time it was made —
  this is the real join key for the strategy-vs-risk-control split.
- No existing prompt performs this attribution — confirmed by reading
  `02`/`03`/`07`/`12`/`13` in full; `12_FORENSIC_EXPLAINABILITY.md` is
  explicitly per-decision tracing, not an aggregate statistic (its own
  scope statement).

## Step 0 — required, then stop

The real open design question is the exact attribution methodology; don't
assume one. Propose, with real numbers, and **wait for my OK**:

1. **Population**: which resolved decisions are in scope (live only? Also
   backfilled, with the same survivorship/leakage caveats `01`/`11`
   already apply to any backfilled figure — if so, every output must carry
   those same caveats, not a clean-looking number that forgets them).
2. **Beta regression design**: propose the regression (e.g. per-position
   pooled daily return vs. BTC's own same-day daily return, slope = beta,
   intercept = daily alpha) and how multiple concurrent positions are
   combined (reuse `run_periodicity_fix.py`'s own disclosed simplification
   — pooling per-position daily returns rather than one blended equity
   curve — don't invent a different one without saying so).
3. **Risk-control bucket's realized-return meaning**: a `change_reason=
   "risk_control"` row by definition means the strategy's own signal was
   overridden or constrained — report its realized return as "what
   happened while risk-controlled," not as if it reflects an untouched
   signal. State this distinction explicitly in the output, don't let it
   read as a performance comparison between two "strategies."
4. **Timing component**: propose a concrete, falsifiable definition (e.g.
   comparing realized entry-day return vs. a few days before/after) rather
   than a vague "how much is timing" — if no clean definition exists,
   report "Evidence unavailable in current project state" for this
   specific sub-component rather than forcing one.
5. Report real N for each bucket (strategy-driven resolved decisions,
   risk-control-driven resolved decisions) before designing further — if
   either bucket is too thin to say anything, say so plainly per §10's
   small-sample discipline, don't produce a number anyway.

## Implementation (after Step 0)

1. New analysis module, e.g. `app/benchmarks/performance_attribution.py`
   (matches `evidence_value.py`'s placement convention), computing the
   agreed decomposition per Step 0.
2. New `scripts/run_performance_attribution.py` entrypoint, following the
   established pattern (`run_evidence_value_ranking.py`/
   `run_benchmark_comparison.py`): zero LLM cost, deterministic, prints a
   clear report, persists one row via a new `*Record`/`*Repository` pair
   or an existing one if the shape genuinely fits (ask first, don't force
   a fit).
3. Reuse `pooled_daily_returns_for_decision` and the OHLCV-fetch pattern
   exactly — don't re-derive.
4. Every output must state its population, period, and the standing
   caveats (directional-only until the holdout cohort is confirmatory;
   survivorship bias for any backfilled row; LLM-leakage risk for any
   backfilled row with an LLM-involving decision) — this is a reporting
   tool, not a new source of confirmatory claims.

## Tests

Synthetic case with a known planted beta/alpha recovers it from the
regression. Strategy-vs-risk-control bucketing correctly separates a
synthetic mixed population. Thin-bucket case (e.g. n<10 risk-control rows)
reports "insufficient data," not a number.

## Docs (show diff first)

`doc/todo.md`, `doc/history.md`, `doc/decisions.md` (record the Step-0
methodology chosen and why), `doc/scripts.md`.

## Ground rules

Simplest solution. Don't touch unrelated code. Flag uncertainty. No DB
writes beyond the new report-persistence table/row. No replay, no LLM
calls. Depends on `21` landing first — if it hasn't, stop and say so
rather than computing attribution against known-mislabeled `change_reason`
data.
