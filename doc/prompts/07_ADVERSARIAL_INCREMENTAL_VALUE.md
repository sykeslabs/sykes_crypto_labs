# Test: Adversarial (3f) chain incremental value (todo [HIGH][AI])

## Context

Read `doc/todo.md` → "[HIGH][AI] Adversarial (3f) chain — incremental value, not
infrastructure" first.

Verified 2026-10-02:

- 3f is sequential (bear sees bull, scenario sees both). Infrastructure is done:
  `HistoricalReplayService(adversarial_provider=..., adversarial_repo=...)`,
  `scripts/run_replay.py --with-adversarial` (~$0.30/day extra). Its docstring already
  mentions enabling a "genuine with-vs-without-3f ablation".
- One prior run: 2026-08-20..22 with 3f, 30/30 decisions got adversarial research,
  20/30 theses referenced it. **Referencing ≠ changing the decision.**
- Live: `macro_sensitivity IS NULL` marks pre-3f decisions (see
  `calibration_baseline.py --source live`). A pre/post-3f live comparison is confounded
  by time and market regime, so it's weak evidence.

## Goal

Measure whether 3f changes and improves Judge decisions, using **paired** observations
(same day, same asset, same inputs except 3f).

## Step 0 — required, then stop

1. Read-only: list replay days that already exist **with** 3f and **without** 3f, and
   whether any day exists in both. Report counts.
2. Propose a paired design: replay window(s) on or before `TRAINING_WINDOW_END`, run
   each day once with and once without 3f. Give number of days, decisions expected,
   and cost.
3. **Where do the paired rows go?** Both runs land as `is_backfilled=true` rows, so the
   same day would be counted twice in backfilled stats, the evidence-value pool and
   B2 duplicate logic. Propose how to tag and exclude them from those (ask before any
   migration). This must be solved before running anything.
4. Note that with non-zero temperature (Judge 0.2, assessments 0.3, no seed), two runs
   differ even without the 3f change. Propose a noise baseline: e.g. a few days run
   twice *without* 3f to measure run-to-run disagreement.
5. **Pre-specify the success criterion now** (added 2026-10-02 per
   `doc/reviews/2026-10-02_INVESTMENT_VALIDITY_REVIEW.md`): state what
   decision-change rate, measured against the no-3f noise baseline from
   point 4, would count as "3f adds value" — fix this before any replay
   runs, not after. `11_LLM_LEAKAGE_REVALIDATION.md`'s "must be 0 to pass"
   framing is the template.
6. **Design the general experiment-row-tagging solution here, not just for
   3f.** This project has no tag distinguishing "experiment replay" rows
   from the main backfilled population anywhere (`is_backfilled` is
   binary only) — prompts `05`, `11`, `17` (phase 2), `18` (phase 2) all
   independently re-raise this identical open question rather than
   duplicating a fix. Since this is the first HIGH-tier prompt in
   dependency order that actually needs to run a new replay, **design the
   general tagging convention here** (e.g. a `replay_batch_id`/`experiment_
   tag` column, or whatever you propose) so later prompts can point back
   to this one's solution instead of re-deciding it. Flag this explicitly
   to the other prompts' implementers via a one-line note in each (see
   Docs below).
7. **Wait for my decision and cost approval.**

## Implementation (after approval)

- Analysis script (zero LLM cost) over the paired rows:
  - Decision change rate with vs. without 3f, compared to the no-3f noise baseline.
  - On changed decisions: outcome comparison (hit rate, return) with/without 3f.
  - Paired difference via the ladder metrics from prompt 02 if available.
  - n per cell; "insufficient data" where appropriate.
- Reuse existing replay code; only add the tagging agreed in Step 0.

## Tests

Pairing logic (same day/asset matched, unmatched reported), tagged rows excluded from
calibration and evidence-value populations.

## Docs (show diff first)

`doc/todo.md`, `doc/history.md`, `doc/scripts.md`.

## Ground rules

Simplest solution. Don't touch unrelated code. Flag uncertainty. **No replay without
explicit cost approval.** Replays end on or before `TRAINING_WINDOW_END`.
