# Implementation prompts for doc/todo.md (sections A + B, excluding the embargo item)

One file per open todo item. Each file is a standalone prompt for the Claude Code CLI.
Verified read-only against the repo on 2026-10-02 (HEAD `62013f6` + the uncommitted
embargo work in the working tree).

## Before running any of these

The embargo work (`TRAINING_WINDOW_END`, `HOLDOUT_COHORT_START`, `holdout_cohort_*`
fields, replay guard) is **uncommitted** in the working tree. Several prompts below
build on it. Commit it first.

## Suggested order (dependencies)

| # | File | Todo item | Depends on | LLM cost |
|---|------|-----------|------------|----------|
| 01 | `01_PIT_CANDIDATE_UNIVERSE.md` | [CRITICAL] Replay universe not point-in-time | – | none |
| 02 | `02_BASELINE_LADDER.md` | [HIGH] Simple-baseline / incremental-value ladder | 01 (label at minimum) | none |
| 03 | `03_LLM_ABLATION.md` | [HIGH] LLM incremental-value / ablation | 02 | optional |
| 04 | `04_COMPOSITE_WEIGHTS_VALIDATION.md` | [HIGH] Composite factor weights | 01 | none |
| 05 | `05_EVIDENCE_VALUE_RANKING.md` | [HIGH] Evidence-value LR ranking | decision in Step 0 | optional |
| 06 | `06_LLM_SELF_REPORTED_CALIBRATION.md` | [HIGH] LLM self-reported confidence etc. | 05 (shared code) | none |
| 07 | `07_ADVERSARIAL_INCREMENTAL_VALUE.md` | [HIGH] Adversarial (3f) incremental value | 02/03 harness | yes (paired replay) |
| 08 | `08_REGIME_ROBUSTNESS.md` | [MEDIUM] Regime robustness | **gated on 02** | none |
| 09 | `09_PARAMETER_SENSITIVITY.md` | [MEDIUM] Parameter sensitivity | **gated on 02** | none |
| 10 | `10_CROSS_ASSET_GENERALIZATION.md` | [MEDIUM] Cross-asset generalization | **gated on 02** | none |
| 11 | `11_LLM_LEAKAGE_REVALIDATION.md` | Confirmed [CRITICAL] LLM leakage, not closed | – | yes (replays) |
| 12 | `12_FORENSIC_EXPLAINABILITY.md` | [HIGH] Decision-level forensic explainability | – | none |
| 13 | `13_STRESS_TEST_REAL_HOLDINGS.md` | [HIGH] Stress test reads target, not holdings | – | none |
| 14 | `14_HOLDINGS_CORRECTION.md` | Correct/remove mistaken holdings entry | **gated: you deferred it** | none |
| 15 | `15_EVIDENCE_OBSERVATIONS_ENDPOINT.md` | `evidence_observations` has no endpoint | design decision in Step 0 | none |
| 16 | `16_COSMETIC_FIXES.md` | POST /holdings id, calibration N+1, pagination | – | none |

Quick, low-risk wins you can run any time: 13, 16, 12.

## Cross-cutting risks I found (each prompt repeats the relevant one)

- **New replays now land in the backfilled population.** Any replay (05, 07, 11) adds
  `is_backfilled=true` rows that change the backfilled hit-rate/Sharpe, the
  evidence-value pool and the reasoning-audit pool. There is no tag today that
  separates "experiment replay" rows from the main backfill. Prompts 05, 07 and 11 ask
  you to decide this before any replay runs.
- **Replays must end on or before `TRAINING_WINDOW_END` (2026-09-23)** or they
  contaminate the clean holdout cohort.
- **The holdout cohort must stay untouched as a test set.** No prompt may tune,
  select, or fit anything on decisions with `decision_timestamp >= HOLDOUT_COHORT_START`.
- **Every new replay inherits the survivorship bias from item 01** until that's fixed.
