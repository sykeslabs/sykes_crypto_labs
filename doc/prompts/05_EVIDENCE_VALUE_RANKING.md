# Unblock + complete: Evidence-value logistic-regression ranking (todo [HIGH][Quant])

## Context

Read `doc/todo.md` → "[HIGH][Quant] Evidence-value logistic-regression ranking" first.

Verified 2026-10-02:

- `MIN_SAMPLE_SIZE = 50` in `app/benchmarks/evidence_value.py`; `rank_evidence_value()`
  at ~line 106.
- `scripts/run_evidence_value_ranking.py` loads **only** `is_backfilled=True` decisions
  and outcomes (~lines 60, 75). Current n = 46. The backfilled pool is fixed at 154 rows,
  so waiting for live decisions to resolve will **not** close the gap.
- Features: `model_agreement`, `source_agreement`, `confidence`, `risk_score`,
  `uncertainty`, `investment_horizon_days`. `composite_factor_score` and per-source
  assessment aren't joinable for old backfilled rows.

## Step 0 — decide how to reach n ≥ 50, then stop (required)

Present the options with real numbers and **wait for my decision**:

1. **More backfilled replay.** Estimate: directional rate in the current pool
   (46/154 ≈ 30%), so how many replay days are needed for +4 directional resolved
   decisions, at ≈ $0.575/day. Replay must end on or before `TRAINING_WINDOW_END`
   (2026-09-23), on dates not already replayed (list them). New rows inherit item 01's
   survivorship bias.
2. **Include live decisions from before `HOLDOUT_COHORT_START`.** Report how many are
   resolved and directional. The holdout cohort itself must **never** be used here: it
   is the future out-of-sample test set for whatever this ranking finds.
3. Both.

Also report, for each option, class balance (correct vs. incorrect) in the resulting
sample.

## Implementation (after decision)

1. Population change (option 2/3): add an explicit flag to the script (e.g.
   `--include-live-pre-cohort`), default unchanged. Print the population composition.
2. Once n ≥ 50 the analysis becomes **runnable, not validated**. Add these checks to the
   script output, simplest form each:
   - Class balance.
   - Coefficient stability: bootstrap CIs per coefficient (propose number of resamples).
   - Time-ordered out-of-sample check: fit on the earliest ~70%, evaluate on the rest
     (AUC / log-loss vs. a constant-prediction baseline).
   - Multiple testing: 6 features → report Holm-adjusted p-values.
   - Alternative specs: univariate per feature, and L2-regularized. Report whether the
     ranking order survives.
   - Clear verdict line per feature: "unproven" unless it passes all of the above.
3. Check what `rank_evidence_value()` already does first; extend it, don't duplicate.
4. Persisting results: the script already writes `evidence_value_reports`
   (`EvidenceValueReportRepository`). Ask before changing that table's shape.

## Tests

Population flag excludes the holdout cohort; below-threshold returns "insufficient";
bootstrap/Holm on a synthetic dataset with one real and five noise features gives the
expected verdicts.

## Docs (show diff first)

`doc/todo.md` (keep open until the full check passes), `doc/history.md`, `doc/scripts.md`,
`doc/decisions.md` (record the n≥50 path chosen in Step 0 and why).

## Ground rules

Simplest solution. Don't touch unrelated code. Flag uncertainty. No replay or DB writes
without explicit approval. Never fit on the holdout cohort. Shares code with prompt 06,
so keep the checks reusable but don't build a framework.
