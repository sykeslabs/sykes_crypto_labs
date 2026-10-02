# Investment Validity Review — 2026-10-02

Run from `prompt_INVESTMENT_VALIDITY_REVIEW_PROMPT.md` (full prompt text
preserved at `doc/prompts/done/` — see note at end of this file). Read-only
investigation: no prompt in `doc/prompts/` was executed, no replay was run,
no LLM call was made as part of producing this review. Repo state at time
of review: HEAD `5593e6d`, working tree clean except `CLAUDE.md` (modified,
unrelated to this review) and a deleted scratch copy of the review prompt
itself. Test suite: 712 passed (one pre-existing, unrelated failure fixed
as a side effect of this session — see `doc/history.md`'s corresponding
entry).

Method: one specialized statistical/backtest-methodology audit + five
parallel general investigations, each covering a cluster of the review's
32 sections and auditing a subset of `doc/prompts/`'s 18 open
implementation prompts. Findings below are synthesized from all six.

Evidence classification used throughout: **VERIFIED** (directly
demonstrated by code/data/tests) / **STRONGLY SUPPORTED** (multiple
corroborating pieces, some uncertainty remains) / **PLAUSIBLE** (reasonable
but not demonstrated) / **UNVALIDATED** (insufficient evidence exists) /
**CONTRADICTED** (evidence argues against). A prompt that has not been run
yields no result — every such case is marked "Evidence unavailable in
current project state," never estimated.

---

## A. Executive conclusion

**No.** Current evidence does not demonstrate a genuine investment edge.
The strongest historical signal the project had (decision-level Sharpe
≈1.846) was already shown by the project's own work to be substantially a
periodicity-measurement artifact (corrected ≈0.295, statistically
indistinguishable from BTC buy-and-hold's ≈0.313). No baseline comparison,
LLM ablation, or out-of-sample test has actually been *run* since — every
one of prompts 02/03/05/06/07/17 is a well-designed but unexecuted plan.
The holdout cohort that would eventually produce a confirmatory result
currently has **zero rows** (starts 2026-11-07). This review also
surfaced that the apparatus meant to produce that confirmatory number
(`/calibration/summary`'s Sharpe/DSR) still uses the same flawed
non-periodicity-matched methodology the project already debunked once —
so even when the holdout cohort fills, today's code would repeat the
error. **STRONGLY SUPPORTED → UNVALIDATED** is the honest status: the
system may have some edge, but nothing currently in the project
demonstrates one, and one real production bug plus one methodological gap
need fixing before the first trustworthy confirmatory number could even
be produced.

---

## B. Current system (factual)

Flag-gated pipeline (`app/main.py`): market-data snapshot (unconditional)
→ screening (live top-65 by market cap, deterministic
`composite_factor_score`) → optional derivatives/macro/asset-intelligence
evidence → 3-model LLM assessment (stochastic, temp 0.3, no seed) →
optional sequential adversarial bull→bear→scenario → Judge (single
synthesizing LLM call, temp 0.2, no seed) → Risk Engine (confidence gate +
vol/agreement scalars, hard thresholds) → correlation flagging (advisory
only) → turnover cap (proportional scale-back) → Portfolio Construction
(replacement-capacity logic) → optional outcome evaluation against a
**self-referential** triple-barrier target (target/stop/horizon all
chosen by the same Judge call being graded). No single stage is identified
anywhere as "the" edge source — this itself is a finding.

---

## C. Where the potential edge could come from

| Mechanism | Evidence | Uncertainty | Prompt that tests it |
|---|---|---|---|
| Deterministic composite factor score (momentum/vol/RS/drawdown/volume) | Infrastructure built, empirical validation n=2 (far below usable) | Untested at adequate N | `04_COMPOSITE_WEIGHTS_VALIDATION.md` |
| LLM assessment interpreting news/evidence beyond deterministic factors | None — no ablation run | UNVALIDATED | `03_LLM_ABLATION.md` |
| Adversarial (3f) dissent/stress-testing | One prior run shows 20/30 theses *referenced* 3f output — referencing ≠ changing the decision, explicitly unmeasured | UNVALIDATED | `07_ADVERSARIAL_INCREMENTAL_VALUE.md` |
| Judge synthesis adding value over a deterministic rule | None | UNVALIDATED | `03` Level 1 |
| Risk-sizing/turnover discipline improving risk-adjusted return | Net-of-costs drag is small (0.26pp/decision avg) but no decomposition of alpha vs. risk-control vs. beta exists | UNVALIDATED | New prompt `22` |

---

## D. What is actually validated

- **No lookahead at the feature/news level** in replay (`since`/`until`
  bounds genuinely enforced, `EVIDENCE_UNAVAILABLE_FOR_REPLAY` explicitly
  disclosed rather than faked). **VERIFIED.**
- **Prompt versioning, model/provider recording** for reconstructing which
  config produced which decision. **VERIFIED.**
- **The embargo/holdout-cohort guard mechanics** (boundary math, replay
  refusal, no-tuning-on-holdout) are correctly implemented and tested.
  **VERIFIED** — note this is "the guard works," not "the guard's 45-day
  length is correct" (see F.4).
- **CostGuard discipline**: production LLM spend is small and capped
  ($5/day, $50/month). **VERIFIED.**
- **The project's own honesty about its small-N problem**: every current
  hit-rate/Sharpe figure is already labeled directional-only, not
  confirmatory, in the actual API responses. **VERIFIED.**

---

## E. What remains unvalidated (critical section)

1. Whether *any* layer of the pipeline (factors, assessment, adversarial,
   Judge) adds incremental predictive value over the layer beneath it —
   **nothing has been run** (02/03/07 all unexecuted).
2. Whether the corrected 0.295 Sharpe is statistically distinguishable
   from BTC's 0.313 — never tested, and the underlying N (166 daily
   points from 38 decisions) is a row count, not an independent-observation
   count (no dependence adjustment exists anywhere in the codebase).
3. Whether the Judge/Risk Engine/Portfolio Construction chain is
   dominated by prediction or by deterministic risk rules — **no
   attribution exists**, and prompt 12 (forensic explainability) does not
   cover this; it's per-decision tracing, not aggregate attribution.
4. Whether the LLM layers survive a replay-reliability objection:
   replaying pre-cutoff historical windows with **current-generation
   models whose training data includes those windows' real outcomes**
   tests "can leakage be blocked from becoming directional," not "can the
   model predict the future from period-available evidence." This is a
   third, independent reason (beyond no-embargo and universe survivorship)
   that **all backfilled results are at best directional**.
5. Whether the 45-day embargo is actually long enough — contradicted by
   the project's own code (`investment_horizon_days` is uncapped;
   `calibration_baseline.py` states real horizons span "14-90+ days").
6. Whether the project's reported Sharpe/DSR figures — including the one
   that will eventually gate `holdout_cohort_confirmatory` — are computed
   correctly at all (see F.1, a newly-found bug in the production
   endpoint, not just an unresolved research question).

---

## F. Top 10 weaknesses (ranked by research/investment importance)

| # | Issue | Evidence | Consequence | Confidence | Prompt |
|---|---|---|---|---|---|
| 1 | **`/calibration/summary`'s Sharpe/DSR uses the exact non-periodicity-matched methodology already shown to inflate Sharpe 1.846→0.295** — including the field (`sharpe_decision_level_holdout_cohort`) that will eventually gate whether the system is declared to have an edge | VERIFIED, `app/api/routers/calibration.py:69-104` vs. `scripts/run_periodicity_fix.py` | The future "confirmatory" number would repeat a known, already-caught bug | High | New prompt `19` |
| 2 | **Nothing has been run yet** — 02 (baseline ladder) is the single highest-priority unrun experiment; everything downstream (03, 05 partially, 08, 09, 10) is gated on or weaker without it | VERIFIED by 3 independent workstreams | No confirmatory claim is possible until this exists | High | `02_BASELINE_LADDER.md` |
| 3 | **Real production bug**: capacity-blocked BUYs (`_apply_replacement_capacity_limit`) get `change_reason="strategy"` instead of a risk-control reason, so they're wrongly counted against the strategy turnover budget, live, today | VERIFIED, `app/portfolio/construction.py:149-207` vs. `:70,121-126` | Active correctness bug, not just an attribution gap | High | New prompt `21` |
| 4 | **The 45-day embargo's own justification is contradicted elsewhere in the code** (uncapped horizons, documented 14-90+ day range) | VERIFIED (code contradiction); real max horizon unconfirmed | `holdout_cohort_confirmatory` may not mean what it claims | Medium | New prompt `20` |
| 5 | **Backfilled replay has two independent, compounding integrity problems**: survivorship bias and LLM parametric-knowledge leakage risk | VERIFIED (both) | Most of the project's evidence base (232 backfilled rows) is directional at best, for two separate reasons | High | `01`, `11` |
| 6 | **No portfolio-performance attribution** (alpha/beta/risk-control/timing) exists anywhere | VERIFIED (absence) | Can't tell whether observed behavior is prediction or deterministic rules | Medium | New prompt `22` |
| 7 | **Momentum double-counting**: price momentum reaches the Judge via both the deterministic composite score and independent LLM interpretation of the same OHLCV | VERIFIED (channel exists); magnitude UNVALIDATED | May look like multiple independent signals while being one, re-expressed | Medium | Revise `03`/`05` |
| 8 | **No dependence/autocorrelation adjustment** anywhere in `statistical_validation.py` | VERIFIED (absence) | Reported sample sizes are an upper bound on true independent evidence | Medium | Revise `02` |
| 9 | **`regime_at_decision` stores a UUID, not a regime label**; also only 43 regime snapshots exist total (3 RISK_OFF) | VERIFIED | `08` would silently need debugging before producing anything; data too thin regardless | Medium | Revise `08` |
| 10 | **Experiment-row-tagging problem solved independently by 4+ prompts** (05/07/11/17-phase-2/18-phase-2) rather than once | VERIFIED | Wasted effort, risk of inconsistent solutions | Low-Medium | Revise `07` |

---

## G. Components to KEEP / MODIFY / QUESTION / REMOVE

| Component | Classification | Basis |
|---|---|---|
| No-lookahead data plumbing | **KEEP** | Verified sound, disclosed honestly |
| CostGuard / spend discipline | **KEEP** | Small, capped, working |
| Embargo/holdout-cohort mechanism (the guard itself) | **KEEP**, length **MODIFY** pending check | Mechanically correct; length unverified |
| `/calibration/summary` Sharpe/DSR computation | **MODIFY (urgent)** | Known-flawed methodology in production |
| `_apply_replacement_capacity_limit`/`change_reason` | **MODIFY (bug fix)** | Active misclassification |
| Deterministic composite factor score | **QUESTION** | Built, untested at adequate N |
| LLM assessment layer | **QUESTION** | No ablation run; real leakage risk in backfilled context |
| Adversarial (3f) layer | **QUESTION** | No incremental-value test run |
| "Ensemble logic" / "multi-agent" framing | **MODIFY (terminology)** | Real mechanism is simpler than the terms imply |
| Judge's `source_agreement` self-estimate | **QUESTION** | Not independent of inputs it already saw once |
| Portfolio attribution reporting | **Build (new)** | Doesn't exist |

---

## H. Strongest components

- The embargo/holdout-cohort infrastructure — well-built, tested, honest
  about what it hasn't yet produced.
- The project's own documentation discipline (`doc/history.md`/
  `doc/decisions.md`) — made the periodicity-fix and leakage-mitigation
  history fully reconstructable, which is how this review verified prior
  findings precisely.
- Status-tagging convention (OK/UNAVAILABLE/NOT_IMPLEMENTED) — no silent
  faking found anywhere.
- Prompt-version/model/provider tracking.

---

## I. Simplification opportunities

- No RAG, no tool-calling, no genuine multi-agent negotiation currently
  exists — "sophisticated architecture" framing outpaces what's built.
  Simplify the language, not necessarily the code.
- Evidence-based minimal system today: composite factor score →
  deterministic rule → Risk Engine → Portfolio Construction → real
  execution-cost model → forward evaluation. Every LLM-involving stage is
  currently an *unvalidated addition* on top of this.
- Do not add 17/18 (FAISS, external retrieval API) before 03 shows the
  existing news/LLM layer carries signal worth improving — both prompts
  already self-flag this; confirmed, not overridden.

---

## J. Highest-value experiments (before adding complexity)

1. `02_BASELINE_LADDER.md` — run it.
2. New prompt `19` — fix `/calibration/summary`'s Sharpe/DSR methodology.
3. `03_LLM_ABLATION.md` (revised) — the mandatory LLM-value test.
4. New prompt `20` — verify/correct the embargo length.
5. `01_PIT_CANDIDATE_UNIVERSE.md` — resolve or label survivorship bias.
6. `11_LLM_LEAKAGE_REVALIDATION.md` (revised) — fix the detector rule now.
7. New prompt `21` — fix the `change_reason` misclassification bug.
8. `04_COMPOSITE_WEIGHTS_VALIDATION.md` — cheap, decoupled from Judge-N.
9. `07_ADVERSARIAL_INCREMENTAL_VALUE.md` — conditional on #3.
10. New prompt `22` — portfolio-performance attribution.

---

## K. Recommended research architecture

Evolve toward: one shared, periodicity-matched, dependence-aware
evaluation harness (fixing F.1 and F.8 once, centrally) that every prompt
calls into rather than each computing its own Sharpe. One shared
experiment-row-tagging convention (fixing F.10 once, in 07). No new
information source (17, 18, 3j/3k) until 03 demonstrates the existing
LLM/news layer earns its complexity. No portfolio-optimization
sophistication until an edge is shown at all.

---

## L. TODO and prompt verification

New TODOs added (2026-10-02, this review): 1 CRITICAL, 2 HIGH, 1 MEDIUM
(see `doc/todo.md`). No TODO removed. No previously-closed infrastructure
reopened (A1/A2, B1/B2, pagination all re-confirmed closed, not
re-litigated). New prompts added: `19`, `20`, `21`, `22`. Prompts revised:
`03`, `04`, `07`, `08`, `10`, `11`, `12`, `17`. `doc/prompts/00_INDEX.md`
updated to match.

---

## M. Evidence matrix

| Claim | Evidence | Status | What would prove/disprove it | Prompt |
|---|---|---|---|---|
| The strategy predicts returns | Decision-level Sharpe ≈1.846, corrected to ≈0.295 ≈ BTC's 0.313 | **CONTRADICTED** (as currently measured) | Re-run on 02 with 19's fix applied | 02, 19 |
| LLMs add value | No ablation run | **UNVALIDATED** | 03 (revised) | 03 |
| News adds value | No ablation run; 3 fixed RSS feeds + keyword match | **UNVALIDATED** | 03 variant E | 03 |
| The Judge adds value over a deterministic rule | No isolated test | **UNVALIDATED** | 03 Level 1 | 03 |
| Ensemble logic adds value | Majority-vote arithmetic, real but simple; untested | **UNVALIDATED**, terminology overstates it | 03 | 03 |
| Risk controls improve risk-adjusted returns | No attribution exists | **UNVALIDATED** | 22 | 22 |
| Portfolio construction adds value | Confounded by an active misclassification bug | **UNVALIDATED**, confound confirmed | 21, then 22 | 21, 22 |
| The strategy beats simple baselines | Only computed via the known-flawed Sharpe methodology | **UNVALIDATED** | 02 with 19's fix | 02, 19 |
| The strategy survives transaction costs | Net drag small (0.26pp avg); no 2×/3× sensitivity tested | **PLAUSIBLE**, not demonstrated | Revise 02 | 02 |
| The strategy generalizes to unseen periods/assets | Survivorship bias confirmed present; cross-asset testing unrun | **UNVALIDATED** | 01, 10 | 01, 10 |
| The strategy is robust across regimes | Only 43 regime snapshots exist, 3 RISK_OFF | **Evidence unavailable** | 08 (after UUID-join fix) | 08 |

---

## N. Per-prompt audit

| # | Still correct? | Success criterion | Statistical adequacy | Gate correct? | Contamination handling | Priority | Verdict |
|---|---|---|---|---|---|---|---|
| 01 | Yes, re-verified exactly | Yes (Step-0 decision gate) | N/A (infra fix) | None needed | N/A | Highest — everything inherits this | KEEP |
| 02 | Yes | No — add one | Unknown pending Step 0 | None needed | N/A, zero cost | Highest unrun experiment | KEEP + revise |
| 03 | Yes | No — add one | Unknown, likely class-imbalanced | Correctly gated on 02 | Correctly raised | High | REVISE |
| 04 | Yes | Partial | Good — decoupled from small Judge-N | Correctly notes 01 inheritance | N/A | Subordinate to 02 | KEEP (minor revision) |
| 05 | Yes, incl. per-source non-joinability | Implicit | Thin (n=46 vs. 50 required) | N/A | Explicit | High, blocks 06 | KEEP |
| 06 | Yes | Yes | Currently starved — holdout n=0 | Correctly depends on 05 | Correct | High design, low near-term output | KEEP |
| 07 | Yes | No — add one | Weakest-N of the set | None beyond its own cost gate | Best-specified of the three replay prompts | Moderate, conditional on 03 | KEEP + revise |
| 08 | Yes, gate confirmed unmet | Yes | Correctly gated; needs UUID-join fix added | Correctly gated on 02 | N/A | Low until 02 | KEEP + revise |
| 09 | Yes, all values exact | Yes | Correctly gated | Correctly gated on 02 | N/A | Low until 02 | KEEP |
| 10 | Yes | Partial | Depends on 02 | Correctly gated on 02 | Notes 01 inheritance | Low until 02 | KEEP + revise |
| 11 | Yes | Half | Adequate for its narrow claim only | None needed | Best in the set | High, independent of 02 | REVISE |
| 12 | Yes | N/A | N/A | Correctly stops at Step 0 | N/A | Useful, not a validity blocker | KEEP |
| 13 | Yes, bug confirmed | N/A | N/A | N/A | N/A | Materially relevant if cited as risk evidence | KEEP |
| 14-16 | — | — | — | — | — | — | Out of scope — unchanged |
| 17 | Yes | Phase 2 only | Same small-N problem as 07 | Phase 1 ungated, phase 2 correctly gated | Correct | Textbook complexity-before-edge | REPRIORITIZE |
| 18 | Yes, gate confirmed unmet | Yes at gate level | Appropriately deferred | Correctly gated, self-aware | Correct | Correctly low | KEEP |

---

## O. REAL-MONEY DECISION

**Would current evidence justify allocating CHF 100,000 of real capital to
this system today? No.**

Not because the architecture looks unsophisticated — because nothing has
actually been measured yet. The one number that looked like evidence of an
edge (Sharpe ≈1.846) was already shown by the project's own work to be
substantially a measurement artifact, and this review found the production
endpoint that will eventually report a "confirmatory" result still uses
that same flawed methodology. The minimum evidence needed before this
question could be answered differently: (1) run `02_BASELINE_LADDER.md`,
(2) apply prompt 19's Sharpe-methodology fix everywhere calibration is
reported, (3) run `03_LLM_ABLATION.md` (revised), (4) resolve or honestly
label the survivorship bias (`01`) and re-test leakage mitigation
generalization (`11`, revised), (5) wait for the holdout cohort to reach
n≥50 under the corrected methodology. None of this requires large spend
(realistic total LLM cost to clear the HIGH-tier program is well under
$50) — it requires calendar time and running the plans that already
exist.

---

## Note on the review prompt itself

The full `prompt_INVESTMENT_VALIDITY_REVIEW_PROMPT.md` that drove this
review was a user-supplied, project-agnostic 32-section audit template
(not itself a `doc/prompts/NN_*.md`-convention file). It is not moved into
`doc/prompts/done/` since it isn't part of that numbered sequence; this
review file is its permanent record.
