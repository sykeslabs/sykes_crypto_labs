# TODO / open work

Everything currently open, deferred, declined, or proposed-but-undecided,
in one place. For what's already **done**, see [`history.md`](history.md)
— this file intentionally does not repeat completed work in full, only
points to it, so there is one authoritative place for "what happened" and
one for "what's still needed."

**Live source of truth**: the dashboard's own TODO section
(`app/api/static/dashboard.html`, `#todo-section`) used to track the same
items in narrative form; as of 2026-09-27 every item there marked
done/done-partial was cross-checked against `history.md` (closing two
real documentation gaps — migration `0020`'s idempotency defect and the
`MAX_CONCURRENT_POSITIONS`/`MIN_REPLACEMENT_ALPHA_ADVANTAGE` rationale,
both now in `history.md`'s Phase 5c entry) and removed from the
dashboard. The dashboard section is a static snapshot, not actually
live-derived — treat this file as the current one, not the dashboard.
**Last structural reorganization: 2026-10-02** (this pass). **Last live-
data check: 2026-10-02** (figures below re-verified this pass; see each
item for exact numbers).

**Implementation prompts**: most open items below (sections A, B, and one
in Deferred/gated) now link their own ready-to-run implementation prompt
in [`prompts/`](prompts/) — each independently reviewed read-only against
this repo on 2026-10-02 (every factual/code claim verified, not assumed;
see each prompt's own Context section for citations). One exception: the
FAISS historical-similarity-retrieval item (Section A, HIGH) didn't exist
here until its own prompt (`17`) was written first and introduced it — the
usual direction (todo item → prompt) reversed for that one entry only. A prompt being
"ready" means its claims check out and any genuinely open design question
is correctly routed to an explicit Step-0 "ask the user" gate, not that
it's unconditionally safe to run unattended — several involve real LLM
cost or a real deferred/gated status (see each item's own note). Suggested
dependency order and cross-cutting risks (new replay rows contaminating
the main backfilled population, the holdout cohort, item 01's
survivorship bias) are in [`prompts/00_INDEX.md`](prompts/00_INDEX.md).
**`prompts/done/`** holds completed work: the original phase-by-phase
build prompts, plus any of the above once actually implemented (so far,
`EMBARGO_HOLDOUT_COHORT_PROMPT.md` — see the CRITICAL embargo item below).

---

## Methodological principle (read this before the list below)

**The project's current bottleneck is empirical evidence, not
architectural sophistication.** Every major reliability/engineering
defect found so far (pagination truncation, stale `in_asset`, the
turnover-baseline bug, the Judge-context stale-target bug, the Sharpe
periodicity mismatch, etc. — see [`history.md`](history.md)) has been
found and fixed. None of that answers the one question that actually
determines whether this system is worth running:

> **Does the system provide predictive/economic value beyond simpler
> quantitative strategies, after removing leakage, selection bias, and
> metric artifacts?**

The intended order of work from here is:

**clean independent observations → simple baselines → controlled
ablations → incremental-value evidence → robustness**

— not more complexity first. Two explicit rules follow from this:

- A higher Sharpe, a better hit rate, or a more sophisticated
  architecture is **not, by itself, sufficient evidence** of investment
  edge — see the periodicity-fix finding below for a concrete, measured
  example of exactly this trap.
- A component (an evidence source, a model layer, a weighting scheme) is
  considered **validated** only when its incremental contribution is
  demonstrated on observations genuinely separated from where it was
  built/tuned, and is robust to reasonable methodological alternatives —
  not merely because the full system performs well, or because its
  narrative output looks plausible.

Do not read every unresolved engineering/observability question below as
a research priority — most aren't. The Engineering/Product/Ops section
exists specifically to keep those separate from the handful of questions
that actually bear on investment validity.

---

## A. Active research — investment validity

### CRITICAL — backtest validity

- **[CRITICAL][Backtest] No genuine temporal embargo between the
  backfilled training window and the live holdout window.**
  **Evidence**: Phase 3g's own audit found the gap negative against a
  45-day longest resolution horizon; the live-computed `embargo_gap_days`
  (Calibration summary) confirms this is still true today
  (**re-checked 2026-10-02: -17.3 days**, i.e. the two windows overlap in
  wall-clock time) with 100% of live decisions sitting within one
  horizon's distance of the boundary. Price-momentum/regime persistence
  is present in both the backfilled and live samples, creating a
  plausible dependency channel between them.
  **What this does and does not prove**: window overlap and a plausible
  dependency channel are not the same claim as proven feature-level
  information leakage — the project's own point-in-time audit
  (`doc/history.md`, "Task 3a: point-in-time / look-ahead audit") found
  no actual look-ahead at the feature level. Do not read the overlap
  alone as proof that future information entered a feature; read it as
  proof that the backfilled and live samples cannot currently be treated
  as statistically independent.
  **Decision criterion**: until a genuinely independent temporal holdout
  cohort exists, current/past holdout results are **directional evidence
  only, not confirmatory evidence**.
  **Fix**: either (a) introduce a real embargo gap for the *next* holdout
  cohort (a future window with a genuine temporal buffer past the
  longest resolution horizon from anything used in training/backfill),
  or (b) continue treating every current/past holdout result as
  non-confirmatory and say so everywhere a backfilled Sharpe/hit-rate
  figure is shown. The Calibration summary's `held_out_window_note`
  already states this caveat live; the underlying no-embargo condition
  itself remains unresolved.
  **Status (2026-10-02, `EMBARGO_HOLDOUT_COHORT_PROMPT.md` implemented —
  still Open, do not close)**: option (a) is now real, not just proposed.
  `TRAINING_WINDOW_END` (`app/benchmarks/schemas.py`, frozen at
  2026-09-23, the live `max(decision_timestamp)` over backfilled
  `decision_outcomes` confirmed at implementation time) plus a 45-day
  embargo defines `HOLDOUT_COHORT_START` (2026-11-07). `/calibration/
  summary` now reports `holdout_cohort_*` fields for this slice alone
  (same B2 duplicate-exclusion as every other directional figure), and
  `scripts/run_replay.py`/`HistoricalReplayService.run()` both refuse a
  replay past `TRAINING_WINDOW_END` unless `--allow-post-training-cutoff`
  is passed (which permanently flags the cohort `contaminated`). This
  item closes only when `holdout_cohort_confirmatory` goes true — needs
  the cohort uncontaminated AND its resolved-directional sample to reach
  n≥50, estimated (at the live resolution rate measured 2026-10-02,
  across all outcome types, likely optimistic for the directional-only
  subset actually required) around **2026-11-13 at the earliest** — user
  explicitly accepted this multi-month no-op window. Until confirmatory,
  every hit-rate/Sharpe figure in this project (not just this cohort's
  own) remains directional evidence only, exactly as before.

- **[CRITICAL][Backtest] The historical replay's candidate universe is
  not point-in-time.** **Evidence, verified directly in code
  (2026-10-02)**: `HistoricalReplayService.run()` (`app/benchmarks/
  replay.py`) still calls `get_active_assets()` once and reuses TODAY's
  active-asset list for every simulated historical day, rather than
  reconstructing which assets would genuinely have ranked in the
  screened universe on that historical date. This is a real hindsight/
  survivorship effect — today's asset list reflects which assets turned
  out to matter, information a genuine point-in-time backtest would not
  have had.
  **Explicitly distinct from an already-fixed, unrelated bug**: this is
  not the same issue as the Binance historical-fetch date-anchor/
  pagination bug (fixed — see `history.md`'s Phase 5f/5m entries,
  which closed a total data-reachability failure for windows >~5 weeks
  old). That fix made historical OHLCV *retrievable*; it does nothing
  for *which assets were eligible to be retrieved* on a given historical
  day. Do not mark this item resolved on the strength of the OHLCV fix.
  **Fix**: reconstruct a genuine point-in-time candidate universe if a
  historical market-cap/ranking source is reachable, or — if not
  technically feasible — explicitly label every backfilled Sharpe/hit-
  rate figure as subject to universe-selection bias, not clean
  out-of-sample evidence.
  **Implementation prompt**: [`prompts/01_PIT_CANDIDATE_UNIVERSE.md`](prompts/01_PIT_CANDIDATE_UNIVERSE.md)
  — reviewed 2026-10-02, ready to run (its own Step 0 gates the real
  open decision — whether a point-in-time source is actually reachable —
  behind a live, bounded probe + explicit confirmation, rather than
  assuming either way).

### HIGH — the central empirical question and its components

- **[HIGH][Quant/Backtest] Simple-baseline / incremental-value ladder —
  the central open research question.** The real open question is not
  "what is the system's Sharpe" but **whether each layer of sophistication
  adds value over the simpler layer beneath it, on the same observations**.
  **What already exists (verified 2026-10-02, not building from zero)**:
  `app/benchmarks/baseline_comparison.py` + `scripts/run_benchmark_
  comparison.py` already compute BTC buy-and-hold and an equal-weight-
  universe basket (Sharpe, max drawdown, total return raw/net-of-costs)
  over the real backfilled comparison window. `scripts/run_composite_
  weights_validation.py` already compares the live `COMPOSITE_FACTOR_
  WEIGHTS` scheme against an equal-weight and a momentum-only
  alternative, but only as a correlation/mean-score check against
  `realized_return` — not a full P&L backtest. `scripts/run_periodicity_
  fix.py` already produced the project's single most important
  methodology finding to date (below). None of these three scripts share
  the same assets/dates/cutoff/cost assumptions today — they're
  fragments of a ladder, not a controlled comparison.
  **Needed**: one controlled comparison, same assets, same dates, same
  information cutoff, same holding-period definition, same transaction-
  cost assumptions, same evaluation metrics, same OOS/holdout
  observations, across progressively more complex approaches (adapt the
  exact rungs to what's reachable in this repo, roughly): (1) BTC
  buy-and-hold, (2) equal-weight crypto basket, (3) market-cap-weighted
  basket, (4) momentum-only, (5) deterministic composite-factor
  strategy, (6) composite factors + LLM research, (7) full system
  (Judge + adversarial + Risk Engine).
  **Measure, not just Sharpe**: incremental predictive accuracy,
  incremental return, incremental risk-adjusted performance, drawdown,
  turnover/cost impact, calibration where applicable, statistical
  uncertainty, and — critically — whether each additional layer adds
  information **conditional on** the layer beneath it, not just whether
  the full stack looks good in isolation. A complex layer is not useful
  merely because the full system performs well; its incremental
  contribution must survive controlled ablation against the simpler
  preceding system.
  **Known prerequisite gap**: `run_periodicity_fix.py` (the methodology
  this ladder should reuse) is currently scoped to backfilled decisions
  only (found 2026-09-16, not yet actioned) — extend it to cover live
  decisions too before/while building this ladder, so the comparison
  isn't silently backfilled-only.
  **The headline finding that makes this question concrete, not
  abstract** (`history.md`'s periodicity-fix entry, 2026-09-12,
  live-verified): the OLD decision-level Sharpe was **≈1.846** — looked
  like a clear "beats the market" signal. The CORRECTED, periodicity-
  matched pooled-daily Sharpe is **≈0.295**, nearly identical to BTC
  buy-and-hold's own daily Sharpe of **≈0.313** over the same real
  window. The old metric's apparent edge was substantially a periodicity-
  mismatch artifact, not evidence of skill. This is exactly the kind of
  result this ladder is built to catch systematically instead of by
  accident.
  **Implementation prompt**: [`prompts/02_BASELINE_LADDER.md`](prompts/02_BASELINE_LADDER.md)
  — reviewed 2026-10-02, ready to run.

- **[HIGH][AI/Quant] LLM incremental-value / ablation test.** A narrower,
  AI-specific instance of the item above: does the LLM research layer
  add predictive information beyond the deterministic quantitative
  signals already computed? Compare, at minimum, using the same
  historical/OOS observations where feasible: (1) deterministic factors
  only, (2) deterministic factors + LLM assessments, (3) deterministic
  factors + LLM + adversarial analysis, (4) the full Judge pipeline.
  Measure directional accuracy, return, risk-adjusted return, drawdown,
  turnover, costs, calibration, and incremental contribution at each
  step. **Do not conclude the LLM layers add value because their output
  is sophisticated or because individual narratives read as plausible**
  — that is exactly the failure mode the LLM-leakage finding below
  already demonstrates models are capable of.
  **Implementation prompt**: [`prompts/03_LLM_ABLATION.md`](prompts/03_LLM_ABLATION.md)
  — reviewed 2026-10-02, ready to run (gates on `prompts/02_BASELINE_
  LADDER.md`'s artifacts existing first — stops and says so if they don't).

- **[HIGH][Quant] Composite factor weights — empirical validation still
  unresolved.** `COMPOSITE_FACTOR_WEIGHTS` (`app/market_data/factors.py`)
  remains "a chosen convention, documented rather than tuned by feel,"
  not fit or backtested — and this gates which assets every downstream
  stage (assessment, adversarial, Judge, Risk Engine) even sees.
  **Distinguish infrastructure from validation**: the comparison
  infrastructure is built and real (`compute_composite_factor_scores`'s
  `weights` override, `scripts/run_composite_weights_validation.py`) —
  that part is done. The empirical validation itself is not: real
  joinable sample was n=2 at last check, far below any usable threshold,
  and current vs. equal-weight vs. momentum-only remains genuinely
  untested. Do not over-prioritize this relative to the clean-OOS
  baseline-ladder item above — it is a subordinate, narrower instance of
  the same underlying question (does this specific deterministic
  weighting scheme add value over simpler alternatives), not a separate
  track.
  **Implementation prompt**: [`prompts/04_COMPOSITE_WEIGHTS_VALIDATION.md`](prompts/04_COMPOSITE_WEIGHTS_VALIDATION.md)
  — reviewed 2026-10-02, ready to run.

- **[HIGH][Quant] Evidence-value logistic-regression ranking.**
  `MIN_SAMPLE_SIZE=50` has never been cleared — **re-checked live
  2026-10-02: n=46**, unchanged from the prior check despite 21 more live
  decisions resolving in the interim, because `run_evidence_value_
  ranking.py` draws only from the backfilled population (`is_backfilled=
  True`), which is fixed at 154 rows unless more replay is run. **This
  means passively waiting for live decisions to resolve will NOT close
  this gap** — reaching n≥50 requires either running more backfilled
  replay, or a deliberate design decision to extend this analysis to
  include live decisions too (not yet made).
  **`n≥50` is an eligibility threshold, not a validation result**: once
  n≥50, the analysis becomes *runnable*, not automatically *predictive*.
  After clearing it, still need to inspect coefficient stability, class
  balance, uncertainty, out-of-sample performance where possible,
  multiple-testing concerns, incremental predictive value, and whether
  results survive reasonable alternative specifications. Treat every
  current evidence category (`model_agreement`, `source_agreement`,
  `confidence`, `risk_score`, `uncertainty`, `investment_horizon_days`)
  as unproven until that full check passes, not merely until n≥50.
  **Implementation prompt**: [`prompts/05_EVIDENCE_VALUE_RANKING.md`](prompts/05_EVIDENCE_VALUE_RANKING.md)
  — reviewed 2026-10-02, ready to run (Step 0 requires picking how to
  reach n≥50 before any replay/population change).

- **[HIGH][AI] LLM self-reported confidence/uncertainty/source agreement
  — calibration AND incremental information.** `source_agreement`,
  `confidence`, and `uncertainty` remain pure LLM self-reported numbers
  with no deterministic cross-check (unlike `model_agreement`, a real
  majority-vote fraction), used directly as a Risk Engine sizing input.
  Two distinct validation questions, both unresolved — test both:
  (1) **calibration**: does stated `confidence` predict realized
  correctness (live-only, not blended with backfilled data)?
  (2) **incremental information**: do these self-reported numbers predict
  outcomes *after* accounting for the deterministic signals and other
  Judge inputs already available — or are they redundant with
  information already captured elsewhere? Passing (1) alone is not
  sufficient; a well-calibrated but redundant signal adds no real value.
  **Implementation prompt**: [`prompts/06_LLM_SELF_REPORTED_CALIBRATION.md`](prompts/06_LLM_SELF_REPORTED_CALIBRATION.md)
  — reviewed 2026-10-02, ready to run (reuses prompt 05's robustness
  checks rather than duplicating them, once they exist).

- **[HIGH][AI] Adversarial (3f) chain — incremental value, not
  infrastructure.** The chain is confirmed sequential (bear receives the
  bull case, scenario receives both — not 3 independent angles), and
  real replay support for 3f now exists (`HistoricalReplayService`'s
  optional `adversarial_provider`/`adversarial_repo`, `scripts/
  run_replay.py --with-adversarial`) — that part is built. **The
  remaining question is purely empirical: does adversarial analysis add
  incremental predictive value over the Judge's single synthesizing
  call, once 3f is available for enough decisions to test?** The fact
  that adversarial output is referenced in a decision's thesis is not
  evidence that it improved the decision — Judge theses can genuinely
  incorporate content without that content having changed the directional
  outcome. Treat as unanswered until tested directly.
  **Implementation prompt**: [`prompts/07_ADVERSARIAL_INCREMENTAL_VALUE.md`](prompts/07_ADVERSARIAL_INCREMENTAL_VALUE.md)
  — reviewed 2026-10-02, ready to run. Involves real paired-replay LLM
  cost (~$0.30/day extra) and new `is_backfilled=true` rows — the prompt's
  own Step 0 requires explicit cost approval and a decision on how to
  keep experiment-replay rows from silently contaminating the main
  backfilled population before anything runs.

- **[HIGH][AI/Quant] Historical-similarity retrieval (FAISS) — does
  retrieving semantically similar past news/events add incremental
  predictive value?** A genuinely new candidate evidence source, not yet
  built. **Real data constraint, verified 2026-10-02**: the `news` table
  (`migrations/0002_llm_and_news.sql`) stores only `title` + a *nullable*
  `summary` per article — no full article body anywhere in this system —
  so what exactly gets embedded (title-only vs. title+summary, and how
  to handle rows with no summary) is a real open question, not something
  to assume away. No embedding/vector infra exists anywhere in this repo
  today (confirmed via repo-wide grep). `NewsRepository.get_recent_
  relevant_news`'s `until` bound (`app/database/repository.py:240-265`,
  threaded through replay via `as_of` in `app/llm/assessment_context.py:
  42`) already enforces no-lookahead for backfill — any FAISS retrieval
  must reuse this exact mechanism, not invent new leakage-prevention
  logic.
  **Two phases, deliberately different risk**: (1) the retrieval
  infrastructure itself — local `faiss-cpu` + a small local
  sentence-transformer, zero marginal cost, fully modular/disableable via
  a new `FAISS_ENABLED` setting (default off, preserving current
  behavior exactly). Low-risk, reversible. (2) **whether wiring retrieved
  historical context into the assessment/Judge prompts actually changes
  and improves decisions** — this is NOT free: it requires a paired
  backfill replay (same day/asset, with vs. without retrieved context),
  real LLM cost, and the same new-`is_backfilled=true`-row contamination
  risk already solved once for the adversarial-value item above. Do not
  conflate "the retrieval layer works" with "the retrieval layer helps" —
  only phase 2, measured via a genuine temporal out-of-sample split (not
  a random split), answers the real question. **Not a duplicate of** the
  Deferred "Dedicated web/financial retrieval layer (You.com/Tavily/Exa)"
  item below — that fetches *new* external content; this is local
  semantic search over the project's *own already-ingested* news archive.
  **Implementation prompt**: [`prompts/17_FAISS_SIMILARITY_RETRIEVAL.md`](prompts/17_FAISS_SIMILARITY_RETRIEVAL.md)
  — reviewed 2026-10-02, ready to run for phase 1 (local, free, fully
  reversible); phase 2 (the actual predictive-value evaluation) gates on
  the same Step-0 cost/contamination-approval pattern as prompt 07, and
  explicitly treats a null result as a valid, documented close rather
  than a reason to keep adding complexity.

### MEDIUM — robustness (keep concise; do not over-specify ahead of evidence)

- **[MEDIUM] Regime robustness** — whether the system's apparent edge (if
  any, per the baseline ladder above) holds consistently across
  RISK_ON/RISK_OFF/NEUTRAL regimes, or is concentrated in one. Not yet
  scoped in detail — needs the baseline-ladder item resolved first to
  have a real effect size worth slicing by regime at all.
  **Implementation prompt**: [`prompts/08_REGIME_ROBUSTNESS.md`](prompts/08_REGIME_ROBUSTNESS.md)
  — reviewed 2026-10-02, ready to run *later*: it correctly gates itself
  on prompt 02's artifacts existing first and will stop immediately if
  they don't (verified 2026-10-02: they don't exist yet).
- **[MEDIUM] Parameter sensitivity** — `MAX_CONCURRENT_POSITIONS` (8) and
  `MIN_REPLACEMENT_ALPHA_ADVANTAGE` (0.03) are documented as a chosen
  convention (same status as `COMPOSITE_FACTOR_WEIGHTS`), not fit or
  backtested. Needs enough resolved decisions across enough actual
  *replacement events* specifically (narrower than the general
  resolved-decision count) — not yet available; genuinely low priority
  until the central question above has a real answer.
  **Implementation prompt**: [`prompts/09_PARAMETER_SENSITIVITY.md`](prompts/09_PARAMETER_SENSITIVITY.md)
  — reviewed 2026-10-02, ready to run *later*, same gate on prompt 02 as
  above. Explicitly forbids tuning on the holdout cohort and forbids
  changing the live defaults itself.
- **[MEDIUM] Cross-asset / generalization analysis** — whether any
  demonstrated edge generalizes across the tracked universe or is
  concentrated in a handful of assets (e.g. BTC). Not yet scoped — same
  dependency on the baseline ladder existing first.
  **Implementation prompt**: [`prompts/10_CROSS_ASSET_GENERALIZATION.md`](prompts/10_CROSS_ASSET_GENERALIZATION.md)
  — reviewed 2026-10-02, ready to run *later*, same gate on prompt 02.

### Confirmed finding, not fully closed

- **Confirmed [CRITICAL][AI] LLM parametric-knowledge leakage in
  backfilled decisions.** The Aug 2024 XMR replay demonstrated 2-of-3
  assessment models citing an unsupported "regulatory delisting
  pressure" narrative that only became real after the replayed date —
  the model's own contradictory-evidence text admitted the claim wasn't
  grounded in supplied evidence, and it still materially influenced the
  outcome (drove an eventual SELL). Prompt mitigation was shipped
  (`ASSESSMENT_PROMPT_VERSION` v1→v2, `JUDGE_PROMPT_VERSION` v2→v3). The
  2022 FTX-window replay directly re-tested BTC/BNB under the new
  prompts: the same class of ungrounded historical-prior narrative
  recurred (assessment-level leakage is still present), but the Judge
  caught it every time under the new prompts and never let it drive a
  directional call (all 30 decisions landed WATCH/NO_TRADE).
  **Precisely**: assessment-level leakage remains present; Judge-level
  mitigation prevented the *tested* leakage from becoming a directional
  decision in the *tested* FTX scenario. This is evidence the mitigation
  works in the cases tested, not proof it generalizes to every future
  leakage pattern. **Do not mark this Done.** Future validation
  criterion (not yet scheduled): test several more historically
  distinctive events from different regimes and verify unsupported
  historical priors are consistently detected and blocked from becoming
  directional signals every time, not just in the one tested window.
  **Implementation prompt**: [`prompts/11_LLM_LEAKAGE_REVALIDATION.md`](prompts/11_LLM_LEAKAGE_REVALIDATION.md)
  — reviewed 2026-10-02, ready to run. Proposes genuinely new test events
  (not re-running the Aug 2024/2022 FTX windows already done). Real LLM
  cost; its own Step 0 requires explicit cost/event approval first.

---

## B. Engineering / Product / Operations backlog

Real, but not investment-validity blockers — do not let these compete
for priority with section A.

- **[HIGH][Trust/Audit] Decision-level forensic explainability — surface
  already-stored raw LLM responses, rather than only internal fields.**
  **Context (2026-10-02)**: investigating why ZEC received two different
  live Judge decisions on 2026-09-05 four minutes apart surfaced a real
  trust question. The Judge/assessment LLM calls run at nonzero
  temperature (assessment calls: 0.3, `app/llm/assessment_provider.py:
  116`; Judge synthesis call: 0.2, `app/judge/provider.py:117`) with no
  `seed` parameter anywhere in the codebase, so even identical inputs
  would not reliably reproduce an identical decision. On top of that,
  re-running the pipeline minutes apart also regenerates the inputs
  themselves (a fresh market snapshot, a fresh screening pass, and an
  entirely fresh set of `model_market_assessments` from new LLM calls) —
  "same day, same asset" never implied "same inputs." The same-day
  production *race* this produced is already closed (B1, `history.md`
  Phase 5i); the underlying non-determinism is not, and B1 was never
  meant to close it.
  **Two distinct asks here, deliberately kept separate because their
  cost/value is very different**:
  (1) **Forensic explainability** — can a specific past decision be
  reconstructed and justified after the fact? Largely already possible
  today: raw LLM responses (`model_market_assessments.raw_response`,
  `llm_analyses.response`/`token_usage`) are already persisted per
  decision, just not retrievable/visible anywhere in the UI. (Previously
  this was the "Raw LLM payloads" item under Declined, on the premise it
  was pure debug clutter — reframed here as a real audit-trail
  capability instead, now that there's a concrete reason a user would
  want to pull up exactly what a specific past Judge decision saw and
  said. See the reversal note under Declined.)
  (2) **Bit-for-bit reproducibility** (temperature=0 + a fixed seed on
  both the assessment and Judge LLM calls) — genuinely harder and only
  *partially* achievable even if implemented, since OpenRouter-routed
  models can still drift from upstream provider-side model
  version/infrastructure changes outside this system's control.
  **Recommendation**: prioritize (1) — the data is already collected,
  this is a retrieval/UI gap, not a data-collection gap, and it closes
  the real trust question directly. Treat (2) as a lower-priority,
  only-partially-achievable goal, not a blocking requirement.
  **Implementation prompt**: [`prompts/12_FORENSIC_EXPLAINABILITY.md`](prompts/12_FORENSIC_EXPLAINABILITY.md)
  — reviewed 2026-10-02, ready to run. Correctly scopes itself to (1)
  only; explicitly excludes (2), matching this item's own framing above.

- **[HIGH][Risk] `run_stress_test.py` reads the system's own TARGET
  allocation, not real holdings** — queries `PortfolioPositionRepository.
  current_allocation` instead of `compute_current_allocations`, the same
  real-vs-target ambiguity Phase 5c/5d fixed everywhere else in this
  project. Real holdings can diverge from the system's target by
  15-30+ percentage points for weeks (confirmed live for BTC/SOL
  historically), so this stress test's drawdown numbers may currently be
  computed against the wrong portfolio composition. An operational
  correctness issue affecting one diagnostic tool's output, not a
  research-validity question — fix by reading real holdings the same way
  the Risk Engine and Judge context now do.
  **Implementation prompt**: [`prompts/13_STRESS_TEST_REAL_HOLDINGS.md`](prompts/13_STRESS_TEST_REAL_HOLDINGS.md)
  — reviewed 2026-10-02, ready to run.
- **A way to correct/remove a mistaken holdings entry** — no delete
  exists (the ledger is append-only, by design). Two options discussed:
  a real hard delete (breaks the append-only guarantee, corrupts
  retroactive history, makes past Judge decisions unreproducible) vs. a
  "Remove" button posting an offsetting correcting transaction.
  Operational integrity improvement, important eventually, not central
  to establishing predictive edge. Explicitly deferred by the user
  ("address this at a later point in time").
  **Implementation prompt**: [`prompts/14_HOLDINGS_CORRECTION.md`](prompts/14_HOLDINGS_CORRECTION.md)
  — reviewed 2026-10-02, factually ready, but **this item is still
  deferred** — the prompt's own Step 0 re-asks "do you want to implement
  this now?" and stops unless the answer is a clear yes. Moved here for
  availability, not as a signal to start.
- **`evidence_observations` has no API endpoint at all** — the single
  largest block of invisible data in the system (funding rates, open
  interest, options IV, on-chain flows, DeFi TVL, stablecoin supply,
  macro series, regulatory calendar). Useful observability/product
  capability, but not a current investment-validity blocker. Needs a
  real backend design decision first (which sources, what endpoint
  shape) before any UI work.
  **Implementation prompt**: [`prompts/15_EVIDENCE_OBSERVATIONS_ENDPOINT.md`](prompts/15_EVIDENCE_OBSERVATIONS_ENDPOINT.md)
  — reviewed 2026-10-02, ready to run (Step 0 correctly leaves the
  endpoint design as an open decision for the user, not pre-picked).
- **Cosmetic / low-severity, real but minor**:
  - `POST /holdings` echoes `id: null` instead of the database-assigned
    id (handler returns the locally-constructed record instead of
    re-querying after insert). `GET /holdings`/`/holdings/history`
    correctly return the real id.
  - `/calibration/summary` does one repository call per resolved
    decision (a real N+1 pattern) — **re-measured 2026-09-27** with a
    direct in-process call at 323 resolved rows: ~29 seconds (vs. an
    original ~8.6s/179-rows-over-HTTP measurement — not directly
    comparable methodologically, but latency has grown notably faster
    than the row count). Still usable at this scale; worth
    re-prioritizing a proper join/batch method sooner rather than later.
  - `market_snapshots` and `evidence_observations` are already past
    Supabase's real ~1000-row-per-request cap (1725/4303 rows,
    re-checked 2026-10-02) — not fixed, since neither has a reachable
    "fetch everything" API endpoint today (every real consumer is
    per-asset/date-scoped). Apply the existing `_fetch_all_paginated`
    fix if a genuine "get everything" consumer is ever added for either.
  **Implementation prompt**: [`prompts/16_COSMETIC_FIXES.md`](prompts/16_COSMETIC_FIXES.md)
  — reviewed 2026-10-02, ready to run (all three sub-items verified
  accurate against current code; part (c) is verify-only, changes
  nothing if no over-cap consumer exists).

---

## Deferred / gated (not scheduled, with a stated revisit condition)

- **Deferred [MEDIUM][Portfolio] Full portfolio-optimization sizing**
  (risk parity, constrained mean-variance). **Evidence**: directional
  resolved n=46 (evidence-value's own pool) vs. the required 50; real
  net-of-costs drag averages **0.26pp/decision** (max 1.24pp) across 332
  resolved outcomes (re-checked 2026-10-02), essentially unchanged from
  the original 0.21pp/0.25pp findings — still trivial. **Do not optimize
  the allocation of a signal before establishing that the underlying
  signal contains incremental predictive/economic value** — this is
  explicitly downstream of section A's central question, not a parallel
  track. Revisit once clean evidence reaches a sufficient sample (the
  baseline-ladder/evidence-value items above), or real turnover/costs
  become economically material.
- **Phase 6 — exchange execution agent.** On hold by deliberate choice,
  no timeline. Full scope in
  [`prompts/done/PHASE6_PROMPT.md`](prompts/done/PHASE6_PROMPT.md).
- **Scheduling** (running the pipeline on a timer instead of manually).
  Explicitly decided against — the real bottleneck is elapsed calendar
  time for decisions to resolve, not run frequency. Revisit once the
  system reaches a more stable state, or a concrete cadence need emerges.
- **3j** (options gamma exposure, exchange counterparty/solvency risk,
  retail-demand proxies) **and 3k** (DeFi lending rates, staking yield/
  validator queue depth, stablecoin depeg risk) — gated on section A's
  own evidence-value/baseline-ladder work (or 3g's Judge-reasoning audit,
  or a purged-walk-forward finding — see `doc/methodology.md`) surfacing
  a specific, *named* gap one of these would close. Being used on other
  desks isn't, by itself, a reason to add a new cost-bearing, drift-prone
  input.
- **Dedicated web/financial retrieval layer (You.com / Tavily / Exa) —
  evaluate vs. the current RSS+keyword news pipeline; do not implement
  yet.** **Correction to the originating premise, verified in code
  (2026-10-02)**: OpenRouter is not currently used for web/internet
  retrieval anywhere in this system — no OpenRouter model is called with
  a `:online` suffix, a `plugins` web-search parameter, or any browsing
  tool (`app/llm/openrouter_client.py`, `app/llm/assessment_provider.py`,
  `app/judge/provider.py` send only `messages` + reasoning-tuning
  params). News/macro/regulatory evidence already comes from dedicated,
  non-LLM sources: `app/news/` pulls real RSS content from three free
  feeds (CoinDesk, CoinTelegraph, Decrypt — `app/news/rss_client.py`),
  filtered by a simple keyword/word-boundary heuristic (its own docstring
  says "not NLP" — `app/news/relevance.py`); macro/regulatory/on-chain/
  DeFi/derivatives evidence comes from real structured API clients in
  `app/market_data/` (FRED, Deribit, DeFiLlama, Etherscan/Nansen,
  SEC EDGAR, Congress.gov, etc.), each status-tagged OK/UNAVAILABLE/
  NOT_IMPLEMENTED per real connectivity. **So the actual gap this
  proposal would address is retrieval breadth/quality, not an
  LLM-web-search dependency that needs removing** — the current news
  layer is narrow (3 fixed feeds) and its relevance filter is a keyword
  heuristic, not semantic search; several evidence categories remain
  `NOT_IMPLEMENTED` for lack of any reachable API at all (spot ETF flows,
  custody/OTC flow, token unlocks, prediction markets — see the
  `NOT_IMPLEMENTED` item below), and a general-purpose retrieval API
  *might* close some of these — unconfirmed, not a given.
  **Proposed evaluation** (investigation, not an implementation task
  yet): introduce a dedicated web/financial retrieval API as a new,
  separate layer upstream of the existing news/evidence pipeline —
  current leading candidate You.com, given its finance-oriented search
  endpoints — while leaving OpenRouter's role unchanged (LLM reasoning/
  interpretation only, fed the retrieved evidence as context, exactly as
  the existing RSS/structured-API evidence is fed today). Before adopting
  any provider, run a fixed historical evaluation set comparing (1) the
  current RSS+keyword pipeline, (2) You.com, (3) Tavily, (4) Exa on
  retrieval relevance/source quality and, where feasible, downstream
  prediction impact — You.com is the current candidate, not a settled
  choice. **Revisit condition**: only worth prioritizing once section A's
  central research question has established that evidence quality is
  actually a binding constraint on predictive value, rather than model/
  weighting/architecture choices — otherwise this is new recurring
  vendor cost without a demonstrated need.
  **Implementation prompt**: [`prompts/18_RETRIEVAL_LAYER_EVALUATION.md`](prompts/18_RETRIEVAL_LAYER_EVALUATION.md)
  — reviewed 2026-10-02, ready to run, but its own gate check will very
  likely conclude the revisit condition above still isn't met (evidence-
  value n=46 vs. required 50, baseline-ladder not yet run) — expect a
  "defer" recommendation, not a green light to start vendor work.
- **Paid-tier deferrals** (real recurring-cost decisions, not technical
  failures): **Glassnode/CryptoQuant** — client built, not subscribed.
  **CoinGlass** — real documented API, no usable free tier.
  **LunarCrush** — re-confirmed 2026-09-15 with a real paid key: every
  endpoint tested returns HTTP 402, requires "Individual" tier or higher;
  user chose not to upgrade. **xAI/Grok** — API functional, no paid
  relationship established.
- **`NOT_IMPLEMENTED` sources** (genuine infeasibility, not fabricated):
  **Custody/OTC desk flow** — no reliable, independently-verifiable
  source of real custody-provider addresses exists. **Spot ETF flows** —
  Farside has no real API; SoSoValue needs an authenticated login not
  available here. **Token unlock/vesting schedules** — Messari needs a
  key not available here; TokenUnlocks.app has no discoverable public
  API. **Prediction markets** — Polymarket and Kalshi both fail DNS
  resolution from this specific development sandbox (confirmed not a
  general connectivity issue).
- **CoinGecko demo-tier rate-limit reconsideration** — a real demo key
  raises the per-asset historical endpoint from ~5 rapid calls before a
  429 to 40+ with no rate-limiting observed. Whether this is worth
  reconsidering for any other currently `UNAVAILABLE`/rate-limited use
  case is an open decision, not acted on.

---

## Declined / Not Planned (deliberate scope decisions, not forgotten TODOs)

- **`asset_status_history` dashboard exposure** — declined; current
  state is already shown live via SCREENED/JUDGED/HELD badges, this
  table is only the change-log behind them, pure audit-log clutter.
- **`prompt_templates.template_hash` exposure** — declined; internal
  dedup/versioning bookkeeping, not decision-relevant to a viewer.
- ~~Raw LLM payloads exposure~~ — **reversed 2026-10-02**, see Section B's
  "Decision-level forensic explainability" item above. No longer declined
  as pure debug clutter — reframed as a real audit-trail gap once a
  concrete trust/explainability need surfaced (the ZEC duplicate-decision
  investigation). Not yet built.
- ~~`portfolio_allocation_changes` exposure~~ — **reversed 2026-09-16**,
  see [`decisions.md`](decisions.md) and [`history.md`](history.md)'s
  Phase 5e section. No longer declined; built and live.

---

## Historical / completed findings (see `history.md` for full detail)

Not active TODOs — kept here only as pointers so they aren't mistaken for
open work. Full narrative for each lives in `doc/history.md`.

- DecisionOutcome and JudgeDecision repository pagination, and migration
  of every raw-query production consumer onto it — Phases 5m–5u.
- B1 (same-day duplicate Judge decisions) and B2 (historical duplicate
  contamination of calibration) — Phases 5i/5j.
- A1 (WATCH/NO_TRADE target-allocation cap) and A2 (cap-compliance
  corrections exempt from `MAX_WEEKLY_TURNOVER`, confirmed live-exercised
  2026-09-18) — Phases 5g/5l/5v.
- Held-symbol rescue outside the CoinGecko top-65 universe, and the
  Binance historical-fetch date-anchor/pagination bug — Phase 5f.
- Turnover-baseline redesign (the real 2026-09-14 incident) and its
  migration `0020` idempotency defect — Phase 5c.
- Stale `assets.in_asset` reconciliation — Phase 5b addendum 4.
- Judge "current allocation" was silently the stale system target, never
  real holdings — Phase 5d.
- `SCREENING_UNIVERSE_SIZE` revisit (30→50) — Phase 5b addendum 4.
- `HISTORICAL_WORST_DRAWDOWN` stress-scenario pagination fix — Phase 5b
  addendum 4.
- `portfolio_allocation_changes` surfaced as a real "Recommended
  allocation history" endpoint/table — Phase 5e.
- **The Sharpe periodicity correction — the project's single most
  important methodology finding to date, worth restating here even
  though it's "done"**: old decision-level Sharpe ≈ **1.846**; corrected,
  periodicity-matched pooled-daily Sharpe ≈ **0.295**; BTC buy-and-hold's
  own daily Sharpe over the same window ≈ **0.313**. The apparent edge
  was substantially a metric artifact, not skill — exactly the trap the
  new baseline-ladder research item above exists to catch systematically.
