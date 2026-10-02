# Validate: LLM self-reported confidence / uncertainty / source_agreement (todo [HIGH][AI])

## Context

Read `doc/todo.md` → "[HIGH][AI] LLM self-reported confidence/uncertainty/source
agreement" first.

Verified 2026-10-02:

- `confidence`, `source_agreement`, `uncertainty` are pure LLM self-reports on
  `judge_decisions`. `model_agreement` is a real majority-vote fraction.
- They drive sizing in `app/risk/engine.py`: `_apply_confidence_gate` (~line 158,
  `min_buy_confidence` / `min_sell_confidence` / `min_rebalance_confidence`) and
  `_agreement_scalar` (~line 181, `(model_agreement + source_agreement) / 2`).
- `scripts/calibration_baseline.py --source live` already does hit rate + Brier +
  reliability buckets for live decisions (pre/post-3f split).

Two separate questions. Passing (1) alone is not enough.

1. **Calibration**: does stated `confidence` predict correctness? **Live only.**
2. **Incremental information**: do these three numbers predict outcomes *after*
   accounting for deterministic signals (`model_agreement`, `composite_factor_score`
   where joinable, `risk_score`, horizon)?

## Step 0 — required, then stop

1. Read-only counts of resolved directional live decisions: pre-cohort and holdout
   cohort separately, and how many have `composite_factor_score` joinable.
2. Check whether prompt 05's checks (bootstrap, time-ordered OOS, Holm) exist yet in
   `app/benchmarks/evidence_value.py`. If yes, reuse them. If no, tell me. Don't build a
   second copy.
3. Propose the exact models for question 2 (base vs. base + self-reports; likelihood
   ratio test and AUC delta). **Wait for my OK.**

## Implementation

1. Calibration (question 1): extend `calibration_baseline.py --source live` to report
   pre-cohort and holdout cohort separately (it currently splits pre/post-3f; keep
   that too). Reliability buckets + Brier + Brier decomposition (function already exists
   in `statistical_validation`). Also bucket by `uncertainty`.
2. Incremental information (question 2): nested logistic regression as agreed, with the
   reused robustness checks. Verdict per variable: "adds information" / "redundant" /
   "insufficient data".
3. Output labeled "directional only — not confirmatory" unless the holdout cohort is
   confirmatory.
4. **Do not change the Risk Engine.** If a variable turns out redundant or miscalibrated,
   write a proposal in the history entry. Changing sizing is a separate decision.

## Tests

Population split correct; nested comparison on synthetic data (one informative,
one redundant variable) gives expected verdicts; below-threshold returns "insufficient".

## Docs (show diff first)

`doc/todo.md`, `doc/history.md`, `doc/scripts.md`.

## Ground rules

Simplest solution. Don't touch unrelated code. Flag uncertainty. No DB writes, no LLM
calls. Never blend backfilled into the calibration answer.
