# Build: LLM incremental-value / ablation test (todo [HIGH][AI/Quant])

## Context

Read `doc/todo.md` → "[HIGH][AI/Quant] LLM incremental-value / ablation test" and the
"Confirmed [CRITICAL][AI] LLM parametric-knowledge leakage" item first.

Question: does the LLM layer add predictive information beyond the deterministic
factors? Compare (1) factors only, (2) + LLM assessments, (3) + adversarial, (4) full Judge.

**Depends on prompt 02 (baseline ladder).** Reuse its observation set, holding-period,
cost and metric code. If `app/benchmarks/baseline_ladder.py` doesn't exist yet, stop
and tell me.

Persisted data available (verified 2026-10-02):

- `screened_universe` (composite score per asset per run), `model_market_assessments`
  (per model, with `raw_response`, `run_id`), `adversarial_research` (bull/bear/scenario,
  scenarios have `probability`), `judge_decisions` (with `model_agreement`,
  `source_agreement`, `confidence`), `decision_outcomes`.
- `scripts/run_replay.py --with-adversarial` exists (paired with/without 3f possible).

## Two levels — decide in Step 0

**Level 1 (offline, zero LLM cost):** turn each layer's *persisted* output into a
deterministic signal on the same observations:

1. Factors: composite top-N (= ladder rung 5)
2. + assessments: e.g. majority direction across the 3 models, among the composite top-N
3. + adversarial: e.g. scenario probability-weighted direction, among (2)
4. Judge: actual decisions

Limitation to state plainly: the Judge saw all layers, so this measures each layer's
standalone signal and nested incremental information, **not** a true causal ablation.

**Level 2 (true ablation, costs money):** re-run the Judge on the same replay days with
inputs removed (no assessments / no adversarial). Needs a small replay-time flag to
drop inputs from the Judge context, and paired replays. Each replay day ≈ $0.575
(+$0.30 with adversarial).

## Step 0 — required, then stop

1. Count, per population (backfilled / live pre-cohort / holdout cohort), how many
   observations have all four layers persisted (join on `run_id` + `asset_id` — verify
   these keys actually match between stages; tell me if they don't).
2. Propose the exact deterministic rules for signals 2 and 3.
3. Recommend Level 1 only, or Level 1 + Level 2. For Level 2, give the replay window,
   number of days and estimated cost, and answer: **where do ablation rows go?** They'd
   land in the backfilled population and change its stats. Propose a way to tag/exclude
   them (ask before any migration).
4. **Wait for my decision.**

## Implementation (Level 1)

- Add rungs 6 (assessments) and the adversarial rung to the ladder module from 02, or a
  thin script on top of it. Don't duplicate ladder code.
- Report: per-step paired difference with CI, plus nested logistic regression
  (outcome ~ composite; ~ composite + assessment signal; ~ … + adversarial) with
  likelihood-ratio test or AUC delta. Report n per step. If n is too small for a
  meaningful test, say "insufficient data", don't print a p-value as if it means
  something.
- Label output "directional only — not confirmatory" unless the holdout cohort is
  confirmatory.

## Implementation (Level 2, only if approved)

- Smallest possible change: a replay option that omits named inputs from the Judge
  context. Default behaviour unchanged. Run only after I approve the exact cost.

## Tests

Signal rules on synthetic assessments/scenarios; join correctness; nested-model
comparison returns "insufficient" below threshold. Full suite passes.

## Docs (show diff first)

`doc/todo.md` (keep open unless the result is clean and confirmatory), `doc/history.md`.

## Ground rules

Simplest solution. Don't touch unrelated code. Flag uncertainty. No LLM calls or DB
writes without explicit approval. Don't conclude the LLM adds value because its
narratives look plausible.
