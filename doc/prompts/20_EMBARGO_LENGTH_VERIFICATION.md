# Verify: does the 45-day embargo actually cover the longest resolution horizon in use? (todo [HIGH][Backtest])

## Context

Read `doc/todo.md` → "A. Active research" → "[HIGH][Backtest] Verify
`HOLDOUT_EMBARGO_DAYS` against the real max `investment_horizon_days`"
first, and `doc/reviews/2026-10-02_INVESTMENT_VALIDITY_REVIEW.md` (finding
F.4) for the full writeup.

Verified 2026-10-02, read-only:

- `HOLDOUT_EMBARGO_DAYS = 45  # longest resolution horizon in use`
  (`app/benchmarks/schemas.py:18`) — a comment asserting a fact, not a
  value derived from a query at the time it was written
  (`EMBARGO_HOLDOUT_COHORT_PROMPT.md`, `doc/prompts/done/`, did not
  itself verify the real max horizon before choosing 45).
- `investment_horizon_days` is **unconstrained**: the Judge's own prompt
  schema asks for a plain `"investment_horizon_days": <int>`
  (`app/judge/context.py:348`) with no stated bound; `JudgeDecisionItem.
  investment_horizon_days: int` (`app/judge/schemas.py:35`) has no
  `Field(ge=.., le=..)`, unlike `confidence`/`target_allocation`/etc.,
  which do; `decision_outcomes.horizon_days` is set verbatim from it with
  no clamp anywhere (`app/judge/service.py:258`,
  `app/benchmarks/replay.py:518`, both `horizon_days=item.
  investment_horizon_days`). No code path caps this value.
- `scripts/calibration_baseline.py:21,341` states outright, in its own
  comments: real decision horizons span **"14-90+ days."** If this is
  accurate, a 45-day embargo does not satisfy "embargo ≥ longest
  resolution horizon from anything used in training/backfill" — the
  CRITICAL embargo item's own stated requirement
  (`doc/todo.md`'s "no genuine temporal embargo" item, "Fix" bullet).

## Step 0 — required, then stop

1. Run a **read-only** query: `max(horizon_days)` over `decision_outcomes`
   (all rows, both `is_backfilled=true` and `false`), and separately the
   max over just the backfilled population (the one the embargo actually
   needs to be measured against, per the embargo item's own wording
   "longest resolution horizon from anything used in training/backfill").
   Also report the distribution (e.g. count above 45 days, above 90 days)
   — a single outlier matters less than a repeated tail.
2. **Show me both numbers and wait for my decision** before changing
   anything. Three possible outcomes, don't pick one silently:
   - Real max ≤ 45 days: the comment was accidentally conservative-but-
     correct; no change needed, just correct the comment to cite the
     real verified number and date instead of an unverified assertion.
   - Real max > 45 days: `HOLDOUT_EMBARGO_DAYS` needs to be widened to the
     real max (or a deliberately chosen buffer above it) — this moves
     `HOLDOUT_COHORT_START` later, which also pushes back the earliest
     possible `holdout_cohort_confirmatory` date; recompute and report
     the new date.
   - The real distribution has a long, thin tail of extreme outliers
     (e.g. one 400-day horizon): ask whether capping
     `investment_horizon_days` itself going forward (a Judge-prompt/schema
     change) is preferable to embargoing against an extreme outlier
     forever — this is a real design trade-off, not something to decide
     here.

## Implementation (after Step 0)

Whichever outcome Step 0 confirms:

1. If `HOLDOUT_EMBARGO_DAYS` changes: update the constant and its comment
   in `app/benchmarks/schemas.py`, citing the real verified max and the
   date verified (matching this file's own citation style). Recompute
   `HOLDOUT_COHORT_START` (pure arithmetic, already correct given the
   constant).
2. **Do not touch `TRAINING_WINDOW_END`** — that's a separately-frozen,
   already-correct constant (the real `max(decision_timestamp)` over
   backfilled `decision_outcomes` at the time the embargo work shipped);
   this prompt only concerns the embargo *length*, not the training-window
   boundary itself.
3. If a cap on `investment_horizon_days` is agreed in Step 0: add the
   bound to `JudgeDecisionItem` (`app/judge/schemas.py`) the same way
   `confidence`/`target_allocation` already do it, and to the Judge's own
   prompt instructions (`app/judge/context.py`) so the model is told the
   real constraint, not just validated against it after the fact.
4. If nothing needs to change (max ≤ 45 days confirmed): only the comment
   changes, from an assertion to a verified citation.

## Tests

If the constant changes: a test asserting `HOLDOUT_COHORT_START ==
TRAINING_WINDOW_END + timedelta(days=HOLDOUT_EMBARGO_DAYS)` still holds
(same invariant, new value) — extend the existing boundary tests in
`tests/test_api_endpoints.py` (the `test_holdout_cohort_*` tests added this
session) rather than duplicating them; they already parametrize on these
two constants, so most should need no change beyond re-running. If a
horizon cap is added: a test that a Judge decision with
`investment_horizon_days` above the cap is rejected/clamped, per whatever
Step 0 agreed.

## Docs (show diff first)

`doc/todo.md` (this item, plus a note on the CRITICAL embargo item if the
constant changed — cross-reference, don't duplicate), `doc/history.md`,
`doc/decisions.md` (record the real verified max and which outcome was
chosen).

## Ground rules

Simplest solution. Don't touch unrelated code. Flag uncertainty. No DB
writes beyond the read-only Step 0 query. Do not widen or narrow the
embargo without the live number in hand — this is exactly the kind of
"assumed fact in a comment" this prompt exists to stop propagating.
