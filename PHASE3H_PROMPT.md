# AI Crypto Portfolio — Phase 3h: Adaptive Evidence-Value Weighting (incl. Regime Drift Detection) & Portfolio Stress Testing

## Context

This is a later addendum to Phase 3, added after 3a–3g's original scope was
complete, following a gap-analysis against how professional crypto-advisory
and quant research desks build their evidence and risk stack. That same
gap-analysis also identified further evidence sources worth adding
(entity-flow intelligence, custody/OTC flow, network/developer
fundamentals); those are new evidence-collection work and are scoped
separately as 3i, which follows this sub-phase. 3h itself remains
diagnostic/reporting-only — Phase 4 (paper trading execution, benchmarks,
ongoing accuracy tracking) follows 3i.

**Before writing any code**, inspect what actually exists: the real
`decision_outcomes` shape and its accumulated history, the real
`signal_sources`/`source_assessment` shapes, 3g's calibration/reliability
findings, and the Risk Engine's current sizing logic (3e). This sub-phase
adds three independent, reporting-only capabilities on top of an
already-working pipeline — it does not change how the Judge decides or how
the Risk Engine sizes positions.

This sub-phase exists to close three specific gaps identified relative to
professional practice:
1. Source value is currently assessed by manual before/after calibration
   comparison (3f, 3g) and a human decision to toggle `signal_sources.enabled`.
   There is no systematic, learned ranking of which evidence fields actually
   predict outcomes — the kind of feature-importance check a quant desk
   would run before trusting (or continuing to pay for) a data source.
2. The Risk Engine (3e) has per-asset allocation caps, volatility-adjusted
   sizing, and a correlation-concentration flag, but nothing tests the
   *whole portfolio* against a historical stress scenario (a sharp
   correlated drawdown, a contagion-style event) the way an institutional
   risk desk would before treating current sizing as adequately safe.
3. A single, full-history importance ranking (gap 1) can hide a source whose
   predictive value has genuinely shifted over time — crypto regimes change
   fast enough (pre-ETF vs. post-ETF, 2022's deleveraging vs. later periods)
   that a source which mattered in one stretch and went quiet in another can
   average out to "mediocre" rather than surface as the more useful,
   actionable finding: "this source's value is regime-dependent." Nothing in
   3g or task 1 below currently checks for that drift.

## Non-negotiables

- PAPER ONLY.
- All capabilities in this sub-phase are **diagnostic/reporting tools**,
  same standing as 3g's findings: they produce numbers and recommendations,
  they do not auto-adjust the Judge's prompt/logic, the Risk Engine's
  formulas, or `signal_sources.enabled` themselves. Any suggested change
  goes back to a human for explicit confirmation, exactly like 3g's
  source-disabling recommendations.
- The evidence-value learner in task 1 (both the full-history ranking and
  the rolling-window/drift variant in task 1a) is a **checking model**, not
  a new decision-maker — it must never be wired into the live Judge/Risk
  Engine pipeline to auto-reweight evidence. Its only consumer is the report
  it produces. This mirrors how `composite_factor_score` (3b) exists to be
  weighed *alongside* the Judge's narrative synthesis, never blended into
  it, and never becomes the decision-maker itself.
- Any new LLM call in this sub-phase (there should be very few, if any —
  most of this is deterministic statistics) goes through `CostGuard` and is
  tracked as its own line item.
- Sample-size honesty carries over from 3g: every learned weight or stress-
  test result is reported with the sample size / historical window behind
  it. An importance ranking learned from 40 resolved decisions is not
  reported with the same confidence as one learned from 400.
- This sub-phase must not retroactively change `in_holdout_window` tagging
  or 3g's already-reported findings.

## Task detail

**1. Adaptive evidence-value ranking.**
Using the structured evidence fields already persisted per decision — the
Judge's `source_assessment` entries, `model_agreement`/`source_agreement`,
`composite_factor_score` and its agreement/divergence with the Judge (per
3g task 6), macro-sensitivity outputs, and any other structured,
already-stored field — train a simple, inspectable supervised model (e.g.
logistic regression or a small gradient-boosted-tree model; avoid anything
that isn't reasonably explainable) against `decision_outcomes.outcome_label`/
`realized_return`. The goal is a learned importance ranking of which
evidence fields actually correlate with realized outcomes, independent of
how much narrative weight the Judge's prompt currently gives them.
- Require a minimum sample size (document your chosen threshold and reasoning)
  before treating any ranking as meaningful; below it, report "insufficient
  data" explicitly, same discipline as 3g's Deflated Sharpe/PBO gating.
- Report cases where the learned ranking and the Judge's apparent implicit
  weighting (inferable from how often a given `source_assessment` entry
  appears in `key_evidence` vs. `contradictory_evidence` on resolved
  decisions) disagree — that disagreement is itself the useful finding,
  not something to reconcile automatically.
- Persist results to a new table, e.g. `evidence_value_reports`
  (`id, run_at, method, sample_size, decision_outcomes_window, feature_importances (JSONB), notes`),
  so this is itself a countable, reproducible event like `calibration_runs`.
- Validate the model code against a fixture with a known, engineered
  relationship (e.g. a synthetic dataset where one feature is constructed to
  be perfectly predictive and another pure noise) so `pytest` can confirm
  the ranking mechanism actually recovers the known relationship, not just
  that it runs without erroring.

**1a. Evidence-value drift detection (rolling-window / regime-sliced).**
Task 1's ranking is trained once against the full `decision_outcomes`
history, which is the right first pass but can mask a source whose value
has shifted over time. Re-run the same modeling approach from task 1 over
rolling windows (e.g. trailing N decisions or a fixed time window,
whichever gives an honest sample size at your current history length) and,
separately, sliced by `regime_at_decision` — using the same minimum-sample-
size gating as task 1, reporting "insufficient data" per window/regime
slice rather than forcing a number out of too few decisions.
- Report any evidence field whose learned importance changes materially
  across windows or regimes as its own finding (e.g. "source X ranked
  highly in RISK_OFF windows but contributed near-zero importance in
  RISK_ON windows") — this is the actionable output of this task, distinct
  from and complementary to task 1's single aggregate ranking, not a
  replacement for it.
- Persist these results to the same `evidence_value_reports` table from
  task 1, with `method` distinguishing the full-history run from the
  rolling/regime-sliced run(s), so both are equally countable/reproducible
  events.
- Validate against a fixture with an engineered regime-dependent
  relationship (a feature that's predictive only within one synthetic
  "regime" label and noise in the other) so `pytest` can confirm the
  windowing/slicing mechanism actually recovers the regime-dependence, not
  just that task 1's aggregate model runs.

**2. Portfolio tail-risk stress testing (`app/risk/`).**
Extend the Risk Engine module with a deterministic, non-LLM stress-test
step, run against the current/candidate portfolio composition:
- Define a small set of historical or scenario-based stress templates (e.g.
  a broad ~70% BTC drawdown scenario modeled on 2022, a correlated
  altcoin-contagion scenario modeled on a LUNA/FTX-style event where
  altcoin correlations move toward 1, and at least one scenario using
  actual historical returns from `market_snapshots` where available).
  Where real historical data doesn't reach far enough back for a given
  asset (most of the altcoin-tier universe), use a documented, clearly-
  labeled proxy (e.g. apply the BTC/large-cap-alt historical drawdown
  percentage to the smaller-cap asset as an assumption) rather than
  inventing asset-specific historical data that doesn't exist — label these
  assumptions explicitly in output, don't present them as measured.
- Apply each scenario to the current/candidate allocation and report
  estimated portfolio-level drawdown and a simple VaR/CVaR-style estimate
  under each. Keep the formula simple and inspectable — this is a paper
  system's stress-test, not a production risk desk's — consistent with how
  3e's volatility-adjusted sizing and correlation check were deliberately
  kept simple.
- Flag (do not block) any current/candidate allocation whose estimated
  stress-scenario drawdown exceeds a configurable threshold (e.g.
  `MAX_STRESS_SCENARIO_DRAWDOWN`). This is a reporting flag surfaced in
  output/logs, same standing as `requires_review` from 3e — it does not
  change Portfolio Construction's output in this sub-phase.
- This step should be runnable both ad hoc (given the current portfolio
  state) and against any historical portfolio snapshot, so it can also be
  used to retroactively ask "how would this have looked pre-existing crash."

**3. Cost sizing.**
Task 1's model training and task 2's stress-test computation are both
non-LLM, deterministic, offline computation — confirm and document in the
README that this sub-phase adds zero new LLM cost (barring any optional
LLM-based explanation step you choose to add, which must be justified,
CostGuard-gated, and clearly optional).

**4. Tests & docs.**
`pytest` passes without live credentials: the evidence-value learner tested
against the synthetic-relationship fixture from task 1, the rolling-window/
regime-drift variant tested against the engineered regime-dependent fixture
from task 1a, and the stress-test module tested against a fixture portfolio
with a known expected drawdown under each scenario template. Update
`README.md`: mark 3h complete, report the actual learned importance ranking
(with sample size and the insufficient-data caveat if applicable), any
disagreement found between the learned ranking and the Judge's implicit
weighting, any evidence-value drift found across rolling windows/regimes (or
an explicit insufficient-data statement if history is too short), and the
stress-test results for the current live portfolio composition under each
scenario.

## Exit criteria

- Evidence-value ranking computed against real `decision_outcomes` history
  (or explicitly reported as insufficient-sample if the history isn't large
  enough yet), persisted to `evidence_value_reports`.
- Any disagreement between the learned ranking and the Judge's implicit
  evidence weighting is reported as a finding, not silently resolved.
- Rolling-window/regime-sliced evidence-value drift check computed (or
  explicitly reported as insufficient-sample per window/regime), with any
  found drift reported as its own finding, persisted to
  `evidence_value_reports`.
- Stress-test step runs against the current live portfolio and reports
  estimated drawdown/VaR-style figures under each defined scenario, with
  every cross-asset historical-data assumption explicitly labeled as such.
- None of these capabilities altered Judge prompts, Risk Engine formulas,
  Portfolio Construction logic, or `signal_sources.enabled` — all are
  report-only in this sub-phase.
- `pytest` green without credentials, including the synthetic-relationship,
  regime-drift, and known-drawdown fixture tests.
- README updated with real numbers, not placeholders.

Report the evidence-value ranking findings (full-history and rolling/
regime-sliced) and the stress-test results, and wait for confirmation
before starting 3i (entity-flow intelligence, custody/OTC flow, and
network/developer fundamentals) — now the last sub-phase of Phase 3 —
before Phase 4 (paper trading execution, benchmarks, and ongoing accuracy
tracking against the now fully-validated and stress-tested baseline).
