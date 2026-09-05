# AI Crypto Portfolio — Phase 3g: Statistical Validation & Robustness

## Context

This is the statistical-validation sub-phase of Phase 3 — 3h (adaptive
evidence-value weighting and portfolio stress testing) and then 3i
(entity-flow intelligence, custody/OTC flow, and network/developer
fundamentals) follow this one before Phase 4. This sub-phase changes no
evidence collection and no decision logic. 3a–3f built the pipeline and
produced a calibration comparison; 3g's job is to determine whether that
comparison actually means
what it appears to mean, before anyone (including future you) treats it as
a validated accuracy improvement.

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

Also split the same reliability breakdown by `model_agreement`/
`source_agreement` bucket (from 3d/3e), not only by regime. The Judge's
`uncertainty` output and the models' raw disagreement are only useful as
risk-sizing inputs if low-agreement decisions are actually shown to resolve
less reliably than high-agreement ones at the *same* stated confidence —
report whether that's true. If low-agreement decisions turn out to be just
as well-calibrated as high-agreement ones, that's a real finding too (it
would mean disagreement isn't currently earning its keep as a sizing input),
not a result to omit.

**3a. Point-in-time / look-ahead bias audit.**
Before trusting any number from tasks 2–4, spot-check whether it could be
contaminated by hindsight. For a sample of resolved `decision_outcomes`,
re-derive what each revisable evidence input (on-chain valuation metrics,
ETF flow figures, regulatory-event extraction, any source using 3a's
`is_revision_of` chain) would have shown *as of* `decision_timestamp` —
using 3a's "value as known at time T" convention — and confirm it matches
what was actually fed to the Judge at the time, not a since-revised value.
Report any discrepancy found (even one confirmed case of look-ahead
contamination is a finding that must be surfaced, since it calls the
surrounding calibration numbers into question), and state plainly whether
the audit found the pipeline point-in-time-clean or not. This is a
correctness check on tasks 2–4, not a new statistical method — if it
uncovers contamination, tasks 2–4's numbers should be reported with that
caveat rather than presented as clean.

**3b. Purged/embargoed walk-forward check.**
This is a different failure mode from 3a's point-in-time audit: even if every
evidence value is correctly "as known at time T," a train/tune/test split
that draws adjacent time windows can still leak information through
autocorrelation — on-chain valuation metrics, funding rates, and open
interest all move in slow, sticky regimes, so a decision timestamped an hour
after a "held-out" boundary is often not statistically independent from the
data just inside it. Before trusting tasks 2–4's numbers, confirm whether the
held-out window (and any rolling/regime-sliced split used elsewhere, e.g.
3h's forthcoming drift check) has an explicit **embargo/purge gap** — a
buffer period immediately adjacent to each split boundary that is excluded
from both sides — sized relative to the longest resolution horizon used in
`decision_outcomes` (e.g. if the longest horizon is 30 days, an embargo
materially shorter than that leaves room for leakage). If no such gap exists,
report this as a finding (not a silent fix): quantify how much of the
held-out sample sits within one resolution-horizon's distance of the
training boundary, and state plainly whether that undermines tasks 2–4's
numbers. Introducing the embargo itself, if warranted, is a follow-up change
to 3e's held-out-window definition — out of scope for 3g to apply
retroactively per this sub-phase's own non-negotiables above — but the
finding must be surfaced with the same weight as a point-in-time
contamination finding, since an un-embargoed split can quietly inflate every
downstream calibration and Deflated Sharpe number in the same way look-ahead
bias does.

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
For each source still `enabled` in `signal_sources` — this now includes 3c's
`SPOT_ETF_FLOWS`, `STABLECOIN_SUPPLY_VELOCITY_AND_EXCHANGE_RESERVES`,
`PREDICTION_MARKETS`, `CME_COT_POSITIONING`, and `ON_CHAIN_MINER_METRICS`;
3f's `GLOBAL_LIQUIDITY_MACRO` and `REGULATORY_EVENT_CALENDAR`; and 3b's
`composite_factor_score`, not only 3f's original fragile sources — revisit
whether it shows measurable value using the
trial-count-aware methods from tasks 2–3 rather than a raw before/after
delta. Recommend disabling any source that doesn't clear this bar, with the
specific numbers behind the recommendation — but do not flip
`signal_sources.enabled` yourself in this sub-phase; report the
recommendation for confirmation, consistent with 3f's own exit criteria
language ("consider disabling... rather than leaving it on by default").
For `composite_factor_score` specifically, also report whether Judge
decisions that agreed with the factor score outperformed those that
diverged from it — that comparison is a distinct, useful finding regardless
of the disable/keep recommendation, since it speaks to whether the
quantitative and narrative evidence are actually complementary.

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
computable), the calibration/reliability breakdown, the point-in-time and
purged/embargoed-split audit findings, the held-out-window result, the
reasoning-audit summary, and the go/no-go statement.

## Exit criteria

- Trial count reconstructed and documented.
- Deflated Sharpe Ratio reported; PBO reported if sample size allows,
  otherwise explicitly marked not-yet-computable with a reason.
- Full calibration/reliability report delivered, broken down by regime and by
  model/source-agreement bucket.
- Point-in-time/look-ahead audit completed, with an explicit clean/
  contaminated finding and caveats attached to tasks 2–4 if contamination
  was found.
- Purged/embargoed walk-forward check completed, with an explicit
  gap-present/gap-absent finding, a quantified estimate of any leakage
  exposure if absent, and the same caveat-attachment treatment as the
  point-in-time audit.
- Held-out-window results reported separately from full-sample results, with
  an explicit statement on whether the sample is large enough yet.
- Judge reasoning audit completed with an aggregate finding.
- Source-disabling recommendations delivered with numbers attached, no
  `signal_sources` rows changed without confirmation.
- Go/no-go statement for Phase 4 delivered, grounded in the above.
- `pytest` green without credentials.
- README updated with real numbers, not placeholders.

Report all of the above, including "insufficient data" findings where
genuinely applicable, and wait for confirmation before starting 3h (adaptive
evidence-value weighting and portfolio stress testing), followed by 3i
(entity-flow intelligence, custody/OTC flow, and network/developer
fundamentals — a further evidence-collection addendum) — before Phase 4
(paper trading execution, benchmarks, and ongoing accuracy tracking against
the now-validated baseline).
