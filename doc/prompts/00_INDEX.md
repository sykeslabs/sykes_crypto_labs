# Implementation prompts for doc/todo.md's open items

One file per open `doc/todo.md` item (sections A, B, and one in
Deferred/gated), each a standalone prompt for the Claude Code CLI — with one
exception: `17` introduces a genuinely new todo item rather than
implementing an existing one (see the revision log below). The table below
mirrors `doc/todo.md`'s own document order exactly — read top to bottom in
either file and you're looking at the same sequence, `17` included.

**`done/`** holds completed work, not open prompts: the original
phase-by-phase build prompts (`PHASE1-2_PROMPT.md` through
`PHASE6_PROMPT.md`) plus any numbered prompt below once actually
implemented (so far: `EMBARGO_HOLDOUT_COHORT_PROMPT.md`). Nothing in `done/`
is tracked in the table below.

## Revision log

- **2026-10-02, batch review**: all 16 files (01–16) independently
  re-verified read-only against the current repo (every factual/code claim
  checked file:line, not assumed; live-data claims re-queried where
  feasible) and confirmed **READY** — no factual errors, no stale
  references, no silently-assumed uncertain decisions found in any of
  them. Moved here from `Claude outputs/` as a result; `doc/todo.md`'s own
  items each link their corresponding file directly. Two carry an extra
  caveat beyond "ready": `14_HOLDINGS_CORRECTION.md` covers a todo item
  the user has explicitly deferred — ready to run, but still requires the
  user to say so, which its own Step 0 re-confirms; `05`/`06` had their
  Docs sections extended to also record findings in `doc/decisions.md`,
  matching this project's usual convention.
- **2026-10-02, +17**: `17_FAISS_SIMILARITY_RETRIEVAL.md` added from a
  user-supplied generic proposal (local FAISS historical-news-similarity
  retrieval), regrounded against this repo's actual `news` schema, config
  conventions, and existing no-lookahead/evaluation patterns before being
  written. Unlike every other file here, it introduces a **new**
  `doc/todo.md` item rather than implementing one that already existed.
  Slotted right after 07 (same paired-replay/contamination/cost-approval
  shape for its phase 2).
- **2026-10-02, +18**: `18_RETRIEVAL_LAYER_EVALUATION.md` added for the
  existing Deferred/gated "Dedicated web/financial retrieval layer
  (You.com/Tavily/Exa)" item, from a detailed user-supplied template,
  regrounded the same way. Its own gate check (the todo item's stated
  revisit condition) is checked live in its Context section: **not yet
  met today** (evidence-value n=46 vs. required 50, baseline-ladder not
  yet run) — expect a "defer" recommendation from running it, not vendor
  integration work.
- **2026-10-02, reconciliation**: `doc/prompts/` reorganized into active
  (this folder, top level) vs. completed (`done/`) — `EMBARGO_HOLDOUT_
  COHORT_PROMPT.md` and every `PHASE*_PROMPT.md` moved to `done/`. This
  index and every cross-reference elsewhere in `doc/` updated to match.

## Before running any of these

The embargo work (`TRAINING_WINDOW_END`, `HOLDOUT_COHORT_START`,
`holdout_cohort_*` fields, replay guard) is **uncommitted** in the working
tree. Several prompts below build on it. Commit it first.

## Suggested order (mirrors doc/todo.md exactly)

| # | File | `doc/todo.md` section | Todo item | Depends on | LLM cost |
|---|------|------------------------|-----------|------------|----------|
| 01 | `01_PIT_CANDIDATE_UNIVERSE.md` | A — CRITICAL | Replay universe not point-in-time | – | none |
| 02 | `02_BASELINE_LADDER.md` | A — HIGH | Simple-baseline / incremental-value ladder | 01 (label at minimum) | none |
| 03 | `03_LLM_ABLATION.md` | A — HIGH | LLM incremental-value / ablation | 02 | optional |
| 04 | `04_COMPOSITE_WEIGHTS_VALIDATION.md` | A — HIGH | Composite factor weights | 01 | none |
| 05 | `05_EVIDENCE_VALUE_RANKING.md` | A — HIGH | Evidence-value LR ranking | decision in Step 0 | optional |
| 06 | `06_LLM_SELF_REPORTED_CALIBRATION.md` | A — HIGH | LLM self-reported confidence etc. | 05 (shared code) | none |
| 07 | `07_ADVERSARIAL_INCREMENTAL_VALUE.md` | A — HIGH | Adversarial (3f) incremental value | 02/03 harness | yes (paired replay) |
| 17 | `17_FAISS_SIMILARITY_RETRIEVAL.md` | A — HIGH | FAISS historical-similarity retrieval | phase 1: none; phase 2: 07's contamination solution | phase 1: none; phase 2: yes (paired replay) |
| 08 | `08_REGIME_ROBUSTNESS.md` | A — MEDIUM | Regime robustness | **gated on 02** | none |
| 09 | `09_PARAMETER_SENSITIVITY.md` | A — MEDIUM | Parameter sensitivity | **gated on 02** | none |
| 10 | `10_CROSS_ASSET_GENERALIZATION.md` | A — MEDIUM | Cross-asset generalization | **gated on 02** | none |
| 11 | `11_LLM_LEAKAGE_REVALIDATION.md` | A — Confirmed finding, not fully closed | LLM parametric-knowledge leakage re-validation | – | yes (replays) |
| 12 | `12_FORENSIC_EXPLAINABILITY.md` | B | Decision-level forensic explainability | – | none |
| 13 | `13_STRESS_TEST_REAL_HOLDINGS.md` | B | Stress test reads target, not holdings | – | none |
| 14 | `14_HOLDINGS_CORRECTION.md` | B | Correct/remove mistaken holdings entry | **gated: you deferred it** | none |
| 15 | `15_EVIDENCE_OBSERVATIONS_ENDPOINT.md` | B | `evidence_observations` has no endpoint | design decision in Step 0 | none |
| 16 | `16_COSMETIC_FIXES.md` | B | POST /holdings id, calibration N+1, pagination | – | none |
| 18 | `18_RETRIEVAL_LAYER_EVALUATION.md` | Deferred/gated | Retrieval layer (You.com/Tavily/Exa) | **gated: evidence-quality finding not yet established (02/03/05)** | phase 1: optional (grading); phase 2: yes (paired replay) |

Quick, low-risk wins you can run any time: 13, 16, 12, and 17's **phase 1
only** (the retrieval infrastructure itself — local, free,
`FAISS_ENABLED=False` by default, no prompt/decision-path change).

## Cross-cutting risks I found (each prompt repeats the relevant one)

- **New replays now land in the backfilled population.** Any replay (05,
  07, 11, 17 phase 2, 18 phase 2) adds `is_backfilled=true` rows that
  change the backfilled hit-rate/Sharpe, the evidence-value pool and the
  reasoning-audit pool. There is no tag today that separates "experiment
  replay" rows from the main backfill. Each of those prompts asks you to
  decide this before any replay runs.
- **Replays must end on or before `TRAINING_WINDOW_END` (2026-09-23)** or
  they contaminate the clean holdout cohort.
- **The holdout cohort must stay untouched as a test set.** No prompt may
  tune, select, or fit anything on decisions with
  `decision_timestamp >= HOLDOUT_COHORT_START`.
- **Every new replay inherits the survivorship bias from item 01** until
  that's fixed.
