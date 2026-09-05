# AI Crypto Portfolio — Phase 3g: Statistical Validation & Robustness

## Context

This is the final sub-phase of Phase 3, and it changes no evidence
collection and no decision logic. 3a–3f built the pipeline and produced a
calibration comparison; 3g's job is to determine whether that comparison
actually means what it appears to mean, before anyone (including future
you) treats it as a validated accuracy improvement.

**Before writing any code**, inspect what actually exists: the real
`calibration_runs` rows written by 3e and 3f, the real `decision_outcomes`
shape (including `regime_at_decision`, `judge_confidence`,
`in_holdout_window` from 3e), and how many distinct prompt/logic iterations
actually happened across 3d–3f (via `prompt_templates` and `calibration_runs`
together). This sub-phase's statistical corrections are only as honest as
that trial count — get it right before computing anything.

**This task is 3g only.** Do not modify Judge prompts, Risk Engine formulas,
Portfolio Construction logic, or any collector in this sub-phase. 3g
produces findings and recommendations (e.g. "disable source X," "Judge is
overconfident in RISK_OFF regimes") — it does not silently act on them. If a
finding clearly warrants a change, report it and stop; implementing the fix
is a new, explicitly scoped follow-up, not part of 3g.

## Non-negotiables

- PAPER ONLY (unchanged from every prior sub-phase).
- No new external data sources, no new LLM-driven evidence types. The only
  new LLM calls allowed here are the Judge-reasoning-audit calls (task 5),
  and those go through `CostGuard` and are logged as their own line item,
  same as any other stage.
- Every statistical method used here (deflated Sharpe, PBO, Brier
  decomposition) is implemented and tested against fixture inputs with a
  known correct output — not just plausible-looking code. If you cannot
  verify a formula against a known reference case, say so explicitly rather
  than shipping an unverified implementation of a named statistical method.
- Findings are reported with sample-size caveats attached, always. A
  regime-conditional breakdown computed on 12 decisions is not the same
  claim as one computed on 400, and the report must say which one it is.
- This sub-phase must not retroactively change what counts as "in the
  held-out window" — if 3e/3f's held-out window turns out to be too small to
  say anything statistically meaningful, that's a finding to report (and a
  reason to let more decisions accumulate before Phase 4), not a reason to
  redefine the window after the fact.

## Task detail

**1. Trial-count reconstruction.**
Walk `prompt_templates` and `calibration_runs` to reconstruct an honest count
of how many distinct "attempts" were made across 3d–3f — every new prompt
version per stage, every re-run of the calibration script, every source
enabled/disabled toggle in `signal_sources`. Document this count and how it
was derived; it's the input every other statistic in this sub-phase depends
on, and getting it wrong (undercounting trials) is the single easiest way to
fool yourself into an inflated confidence.

**2. Deflated Sharpe Ratio / Probability of Backtest Overfitting.**
Using the decision-outcome return series (via `realized_return` in
`decision_outcomes`) and the trial count from task 1, compute a Deflated
Sharpe Ratio for the current Judge/Risk/Portfolio configuration. If sample
size and trial diversity are sufficient, also compute Probability of
Backtest Overfitting (e.g. via a combinatorial train/test split approach)
across the configurations actually tried. If sample size is too small for
either to be meaningful, say so explicitly and report the raw Sharpe/hit-rate
with that caveat rather than a fabricated-precision statistic — an honest
"insufficient data" is a valid and useful output of this sub-phase.

**3. Full calibration reporting.**
Extend 3e/3f's Brier-score baseline into a complete reliability report:
Brier score and a reliability diagram (confidence bucket vs. realized
hit-rate), each split by `regime_at_decision`. Explicitly call out any
bucket/regime combination showing systematic over- or under-confidence
(e.g. "70%+ confidence decisions in RISK_OFF resolve positively only 40% of
the time") — this is exactly the kind of finding that changes how much
weight the Risk Engine's volatility-adjusted sizing should place on Judge
confidence in that regime, even though implementing that change is out of
scope here.

**4. Held-out window report.**
Report hit-rate, Brier score, and (if sample size allows) Deflated Sharpe
computed **only** on `decision_outcomes` rows where `in_holdout_window =
true`, separately from the full-sample numbers in tasks 2–3. State plainly
whether the held-out sample is currently large enough to say anything with
confidence, and if not, what sample size or elapsed time would be needed
before it is.

**5. Judge reasoning audit.**
Formalize 3f's spot-check: sample resolved decisions (weighted toward
`requires_review = true`, low `model_agreement`/`source_agreement`, and
cases where the outcome contradicted the decision), and for each, use a
single structured LLM call — given the decision's stored `key_evidence`,
`contradictory_evidence`, and `thesis` — to flag whether the thesis is
actually supported by the cited evidence or contains an unsupported leap.
Gate this call through `CostGuard` like any other. Aggregate results (e.g.
"N of M sampled decisions show at least one unsupported claim in the
thesis") rather than treating any single flagged case as damning on its own.

**6. Source-disabling recommendations, statistically grounded.**
For each 3f source still `enabled` in `signal_sources`, revisit whether it
shows measurable value using the trial-count-aware methods from tasks 2–3
rather than a raw before/after delta. Recommend disabling any source that
doesn't clear this bar, with the specific numbers behind the recommendation
— but do not flip `signal_sources.enabled` yourself in this sub-phase;
report the recommendation for confirmation, consistent with 3f's own exit
criteria language ("consider disabling... rather than leaving it on by
default").

**7. Go/no-go statement for Phase 4.**
Write a short, direct statement: given tasks 1–6, is there currently
statistically defensible evidence that this system's recommendations beat a
naive baseline (e.g. equal-weight or BTC buy-and-hold, once Phase 4's
benchmark tracking exists conceptually) by more than chance/trial-count
would predict? "Not yet, here's what more data would be needed" is an
acceptable and expected answer at this sample size — the point is that the
statement is grounded in tasks 1–6, not asserted separately from them.

**8. Tests & docs.**
`pytest` passes without live credentials: unit tests for the Deflated
Sharpe / PBO / Brier-decomposition implementations against fixed inputs with
known correct outputs (these are testable pure functions, same as 3b's
screening factors), plus a mocked-LLM test for the reasoning-audit call.
Update `README.md`: mark 3g complete, and include the actual numbers from
tasks 1–7 — trial count, Deflated Sharpe (with caveat if PBO wasn't
computable), the calibration/reliability breakdown, the held-out-window
result, the reasoning-audit summary, and the go/no-go statement.

## Exit criteria

- Trial count reconstructed and documented.
- Deflated Sharpe Ratio reported; PBO reported if sample size allows,
  otherwise explicitly marked not-yet-computable with a reason.
- Full calibration/reliability report delivered, broken down by regime.
- Held-out-window results reported separately from full-sample results, with
  an explicit statement on whether the sample is large enough yet.
- Judge reasoning audit completed with an aggregate finding.
- Source-disabling recommendations delivered with numbers attached, no
  `signal_sources` rows changed without confirmation.
- Go/no-go statement for Phase 4 delivered, grounded in the above.
- `pytest` green without credentials.
- README updated with real numbers, not placeholders.

This completes Phase 3. Report all of the above, including "insufficient
data" findings where genuinely applicable, and wait for confirmation before
starting Phase 4 (paper trading execution, benchmarks, and ongoing accuracy
tracking against the now-validated baseline).
