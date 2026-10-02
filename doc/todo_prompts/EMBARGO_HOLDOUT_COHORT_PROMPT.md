# Fix: Genuine temporal embargo + non-confirmatory labeling (todo [CRITICAL][Backtest])

## Context

`doc/todo.md` → "A. Active research — investment validity" → **[CRITICAL][Backtest] No
genuine temporal embargo between the backfilled training window and the live holdout
window.** Read that entry and `doc/history.md` → "Task 3b: purged/embargoed walk-forward
check" before starting.

Current state (verified read-only on 2026-10-02):

- `app/api/routers/calibration.py::_compute_embargo_stats` computes
  `embargo_gap_days = min(live.decision_timestamp) - max(backfilled.decision_timestamp)`.
  Live value today: **-17.3 days** (windows overlap). Phase 3g measured ≈ -2 days.
- **Root cause of the gap getting worse:** `app/benchmarks/replay.py` sets a backfilled
  row's `decision_timestamp = cutoff` (the replayed date), and `scripts/run_replay.py`
  defaults `--end` to *today*. Each replay over recent dates pushes `training_end`
  further into the live window. As long as this is possible, no holdout cohort can stay
  clean.
- Live decisions get `in_holdout_window=IN_HOLDOUT_WINDOW` (constant `True`,
  `app/judge/service.py:39`). Backfilled rows get `in_holdout_window=False`.
- The longest resolution horizon in use is 45 days.
- The project's point-in-time audit (history.md "Task 3a") found **no feature-level
  look-ahead**. This task is about statistical independence of the two samples, not
  about a leak. Do not describe it as a leak anywhere.

## Goal

1. **(a) Clean holdout cohort:** define a new live holdout cohort that starts a full
   45-day embargo after a *frozen* training-window end, and report its stats separately.
2. **Replay guard:** stop `run_replay.py` from producing backfilled decisions after the
   frozen training-window end (hard block, explicit override flag).
3. **(b) Labeling:** everywhere a backfilled/live/combined Sharpe or hit-rate is shown,
   mark it as **directional evidence only, not confirmatory**, until the clean cohort
   meets the confirmatory criterion below.

## Design (decided — do not change without asking)

- **Fixed date constants, no DB migration, no new column.**
  - `TRAINING_WINDOW_END`: a frozen UTC datetime = the current
    `max(decision_timestamp)` over `decision_outcomes` where `is_backfilled = true`.
  - `HOLDOUT_EMBARGO_DAYS = 45` (longest resolution horizon).
  - `HOLDOUT_COHORT_START = TRAINING_WINDOW_END + HOLDOUT_EMBARGO_DAYS`.
  - A decision belongs to the clean cohort iff `is_backfilled = false` AND
    `decision_timestamp >= HOLDOUT_COHORT_START`. Computed at read time only.
- **Replay hard block:** `run_replay.py` / `HistoricalReplayService` refuse any cutoff
  `> TRAINING_WINDOW_END` and exit non-zero with a clear message, unless an explicit
  `--allow-post-training-cutoff` flag is passed. The override prints a loud warning that
  it contaminates the clean cohort.
- **Contamination check:** if any backfilled row has
  `decision_timestamp > TRAINING_WINDOW_END` (i.e. the override was used), the clean
  cohort is flagged contaminated and can never be reported as confirmatory.
- **Confirmatory criterion:** `holdout_cohort_confirmatory = true` only when the clean
  cohort is not contaminated AND its resolved directional sample (after the existing
  B2 same-day duplicate exclusion) is ≥ 50 (the project's existing "sufficient sample"
  bar). Otherwise `false`.

## Step 0 — before writing any code (required)

**Do not start Step 0, or any code/query, until the user explicitly says "go."**
This prompt has been pre-assessed (2026-10-02) against the current codebase and found
clear/implementable; it is parked here until that explicit signal.

1. Run a **read-only** query to get the exact current `max(decision_timestamp)` for
   backfilled `decision_outcomes`, and `min(decision_timestamp)` for live ones. Show me
   both values and the resulting `HOLDOUT_COHORT_START`. **Wait for my confirmation
   before hardcoding them.**
2. Tell me where you intend to put the constants (`app/config/settings.py` vs. a module
   constant next to `IN_HOLDOUT_WINDOW`) and why. Follow the existing pattern there.
3. List every place you found that displays a Sharpe or hit-rate figure (API fields,
   dashboard rows, script stdout). Confirm the list with me before editing.
   Known so far: Calibration summary in `app/api/static/dashboard.html` (Hit rate,
   Brier, Sharpe, DSR rows ~2093–2117) and `held_out_window_note` in `calibration.py`.
   Check also `scripts/run_periodicity_fix.py` and `scripts/run_benchmark_comparison.py`.
   Note that BTC buy-and-hold / basket benchmarks are not system decisions, so they may
   not need the label. Ask me if unsure.

## Implementation

1. **Constants** as decided in Step 0.
2. **Replay guard** in the replay entry point (CLI arg check + service-level check, so
   a direct `HistoricalReplayService.run()` call is also blocked). Add the
   `--allow-post-training-cutoff` flag to `scripts/run_replay.py`.
3. **Calibration summary** (`calibration.py` + `CalibrationSummary` in
   `app/api/schemas.py`): add only these fields:
   - `holdout_cohort_start` (datetime)
   - `holdout_cohort_decision_count` (int, all clean-cohort live decisions)
   - `directional_sample_size_holdout_cohort`, `hit_rate_holdout_cohort`,
     `brier_score_holdout_cohort`, `sharpe_decision_level_holdout_cohort`,
     `deflated_sharpe_ratio_holdout_cohort` — computed with the existing
     `_directional_stats(pairs_for(...))`, so the B2 duplicate exclusion applies.
   - `holdout_cohort_contaminated` (bool)
   - `holdout_cohort_confirmatory` (bool)
   Keep every existing field and its meaning unchanged (backward compatibility).
   Leave `_compute_embargo_stats` as is: it is still the correct measure for the
   *existing* live window.
4. **`held_out_window_note`:** keep the existing text. Append one sentence that says
   whether the clean cohort exists yet, its start date, its resolved n, and that until
   `holdout_cohort_confirmatory` is true, all hit-rate/Sharpe figures are directional
   only.
5. **Dashboard:** add a visible "Directional only — not confirmatory" badge on the
   Hit rate / Brier / Sharpe / DSR rows, driven by `holdout_cohort_confirmatory`. Add one
   row for the clean cohort (start date, n, and its hit rate/Sharpe when they're
   computable). Reuse existing badge/row styles; no new components.
6. **Scripts** (only those confirmed in Step 0.3): print one line next to the system
   Sharpe/hit-rate output saying it is directional only, not confirmatory.

## Tests (pytest, follow `tests/test_api_endpoints.py` style)

- Cohort membership boundary: decision exactly at `HOLDOUT_COHORT_START` is in;
  1 second before is out; backfilled rows are never in.
- Empty cohort → cohort stats are `None`/0, `confirmatory = false`, no crash.
- Contamination: a backfilled row after `TRAINING_WINDOW_END` → `contaminated = true`,
  `confirmatory = false` even with n ≥ 50.
- Confirmatory flips to `true` only at resolved directional n ≥ 50, not contaminated.
- Duplicate-group decisions (B2) are excluded from cohort stats.
- Replay guard: cutoff > `TRAINING_WINDOW_END` raises/exits non-zero; passes with the
  override flag; cutoff ≤ `TRAINING_WINDOW_END` unaffected.
- Existing embargo tests (`test_get_calibration_summary_computes_negative_embargo_gap_...`
  etc.) still pass unchanged.

Run the full test suite and report results.

## Docs (last step, show me the diff first)

- `doc/todo.md` entry: keep it **Open**. Add that the clean cohort is defined (start
  date) and the replay guard exists; the item closes only when
  `holdout_cohort_confirmatory` becomes true. Mirror the same change in the hardcoded
  todo item in `dashboard.html` (~line 207).
- `doc/decisions.md`: one dated entry recording the constants, the 45-day embargo, the
  n ≥ 50 criterion, and the no-migration choice.

## Constraints (from CLAUDE.md)

- Ask, don't assume. If anything above conflicts with what you find in the code, stop
  and ask.
- Simplest solution. No new abstractions, config systems, or DB columns.
- Don't touch unrelated code, even if it looks improvable.
- Don't run `run_replay.py`, migrations, or anything that writes to the database.

## Uncertainties to flag back to me (don't resolve silently)

- With this design the cohort starts ≈ 45 days after `TRAINING_WINDOW_END` and needs
  up to another 45 days to resolve. That means no confirmatory result for roughly
  3 months. **User accepted this multi-month no-op window (2026-10-02).** Still
  estimate the realistic confirmatory date at the current live decision rate and
  surface it in Step 0 output, for the record.
- ~~Live features use trailing windows... A 45-day embargo past decision time may not
  cover feature-window overlap if those windows are longer than 45 days.~~ **Resolved
  during pre-assessment (2026-10-02), read-only, no code changed:** `TRAILING_WINDOW_DAYS
  = 31` (`app/benchmarks/historical_factors.py:17`, also used by `app/benchmarks/
  replay.py`) — 31 days < the 45-day embargo, so the embargo already fully covers the
  trailing-feature-window overlap. No embargo-length change needed. Still worth a quick
  re-confirm at implementation time in case this constant moved since the assessment.
- "Training" is a loose term here: backfilled decisions are used for calibration and
  evaluation, not model fitting. If you find code that actually tunes on them, tell me.
