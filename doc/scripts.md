# Scripts

Every script in `scripts/`, what it does, its real cost, and whether it
should run periodically or stays a deliberate one-off/manual tool. See
[`operations.md`](operations.md) for the main `python -m app.main` flag
reference and the recommended daily sequence these scripts sit alongside.

## Already integrated into `scripts/run_daily.py`

`run_daily.py` runs the full recommended sequence in one command: the news
step, the combined screening/derivatives/macro/assessment/adversarial/
judge/evaluate-outcomes invocation, then these two, every day, unconditionally:

| Script | What it does | Cost | Why it's in the daily sequence |
|---|---|---|---|
| `apply_execution_costs.py` | Backfills `realized_return_net_of_costs`/`assumed_fill_method` on every resolved `decision_outcomes` row still missing one. | Zero — deterministic OHLCV fetch + arithmetic. | Needs to run every time new decisions resolve (via that day's `--evaluate-outcomes`), so it belongs right after that step, every day. |
| `apply_benchmark_alpha.py` | Backfills `benchmark_return`/`effective_alpha` (real return vs. BTC's own buy-and-hold return over the same window) for the same newly-resolved decisions. | Zero. | Same reasoning as above — a fixed, small amount of work per day, worth doing immediately rather than batching. |

**Fixed 2026-09-16**: both scripts used to fetch a flat 1000-day OHLCV window anchored to *today* (`fetch_daily_ohlcv_with_timestamps`) — the same bug class already found and fixed in `run_replay.py`/`run_stress_test.py` (see [`history.md`](history.md)). Any decision older than ~2.7 years before the real current date silently fell out of reach. Both now call `BinanceClient.fetch_daily_ohlcv_paginated` with a depth computed from the oldest resolved decision still needing the calculation (never less than 1000 days), so the boundary no longer moves against live decisions over time. This does **not** retroactively resolve the 2022/2024 ablation-era rows (still blocked, pending a separate, not-yet-decided entry-price/permanently-unresolvable evaluation design) or assets with no Binance/Coinbase pair at all (e.g. BTW).

...and, **only on Sundays**:

| Script | What it does | Cost | Why weekly, not daily |
|---|---|---|---|
| `run_reasoning_audit.py --sample-size 8` | Samples resolved **backfilled** decisions (weighted toward `requires_review=true`, low agreement, outcome-contradicted cases) and asks one LLM call per sample whether the decision's own thesis follows from its own cited evidence. Now genuinely safe to re-run — excludes already-audited decisions, so repeated runs only ever expand coverage, never re-bill for the same decision twice. | Real but tiny (~$0.003/decision). | Samples from a **fixed, non-growing pool** (backfilled decisions only, never live) — there's nothing new to audit day over day, so running more than about once a week gains nothing. |

## Recommended for periodic (not necessarily daily) re-runs, not yet wired into `run_daily.py`

These are all zero-LLM-cost, deterministic, and their *inputs* genuinely
change over time as more decisions resolve — but none is currently run on
any schedule. Each is cheap enough to add to a weekly cadence (e.g.
alongside the Sunday reasoning-audit step) once you're comfortable with
that; none needs to be daily, since none of their real findings change
meaningfully within a single day.

| Script | What it does | Cost | Recommended cadence | Why not daily |
|---|---|---|---|---|
| `run_evidence_value_ranking.py` | Fits a from-scratch logistic regression over resolved decisions' structured fields (model/source agreement, confidence, risk_score, uncertainty, horizon) to rank which inputs actually predict outcomes — diagnostic only, never fed back into sizing. | Zero. | Weekly. | Requires ≥50 resolved directional decisions to produce anything (`MIN_SAMPLE_SIZE`); currently short of that. Re-running daily wouldn't change the result until enough new decisions resolve — check weekly, or trigger it manually once you know a batch of decisions just resolved. |
| `run_composite_weights_validation.py` | Checks whether `COMPOSITE_FACTOR_WEIGHTS`' real momentum-tilted weighting selects better-performing assets than an equal-weight or momentum-only alternative, using every directional decision joinable back to its own `screened_universe` peer group. | Zero. | Weekly. | Same reasoning — small, slowly-growing sample (n=2 at last count); a fixed daily job would just report "still not enough data" on most days. |
| `run_periodicity_fix.py` | Recomputes the system-vs-BTC/equal-weight Sharpe comparison using per-day pooled returns (the periodicity-matched fix — see [`history.md`](history.md)'s Phase 5b-addendum-4 section for why the original decision-level comparison was misleading). | Zero. | Weekly, or after any batch of backfilled decisions resolves. | Currently scoped to **backfilled** decisions only — re-running it doesn't pick up newly-resolved *live* decisions at all yet. Worth extending to include live decisions before making this a routine job (see [`todo.md`](todo.md)). |
| `run_benchmark_comparison.py` | System vs. real BTC buy-and-hold vs. real equal-weight-universe buy-and-hold, same fee/slippage cost treatment, over the calendar window the system's own resolved decisions span. | Zero. | Weekly, or whenever you want a fresh read. | A structural comparison over a slowly-growing decision history — nothing meaningfully changes hour to hour or even day to day. |
| `run_stress_test.py` | Two deterministic portfolio tail-risk scenarios (`HISTORICAL_WORST_DRAWDOWN` — each held asset's own real historical peak-to-trough drawdown, now paginated back to each asset's real listing date; `ALTCOIN_CONTAGION_LUNA_FTX_STYLE` — a stated contagion assumption) against the **current** portfolio. | Zero — real OHLCV fetches + arithmetic. | Weekly, or whenever the real portfolio allocation changes materially. | **Known gap, worth fixing before making this routine**: it currently reads `PortfolioPositionRepository` (the system's own *target*, not real holdings) for "the current live portfolio" — the same real-vs-target ambiguity Phase 5c/5d fixed everywhere else in this project. Given real holdings can now diverge from the system's target by 15-30+ percentage points for weeks at a time (see [`history.md`](history.md)'s Phase 5d section), this script's stress-test numbers may currently be computed against the wrong portfolio composition. Recorded as a real, not-yet-actioned finding — see [`todo.md`](todo.md). |

## Genuinely one-time / already run, not periodic

| Script | What it did | Status |
|---|---|---|
| `reconcile_in_asset.py` | One-time retroactive fix for `assets.in_asset` going stale (11 of 25 assets were wrong). `POST /holdings` now keeps this field in sync going forward — this script has nothing left to do unless that forward-sync logic itself regresses. | Done, 2026-09-13. Safe to re-run (idempotent — reports 0 corrections if nothing is stale), but no ongoing need. |
| `reconcile_asset_names.py` | One-time retroactive fix for `assets.name` falling back to the bare symbol instead of CoinGecko's real display name (12 of 29 assets were wrong). The root cause in `ScreeningService._promote_new_candidates` is fixed going forward. | Done, 2026-09-16. Safe to re-run (idempotent — only touches rows where `name == symbol`), but no ongoing need unless the forward fix regresses. |
| `apply_migration.py <path>` | Applies one migration SQL file directly via `psycopg2`/`DATABASE_URL`. | **Currently broken** in this environment — `DATABASE_URL` connections have failed with "password authentication failed for user postgres" for every migration attempted since 0011. The real, working path is pasting the SQL directly into the Supabase SQL Editor, then verifying via the Python `supabase` client (never via `psycopg2`) — see [`operations.md`](operations.md). |

## Manual, cost-gated, run on demand only — never automate

| Script | What it does | Why it must stay manual |
|---|---|---|
| `run_replay.py` | Re-runs the full assessment → Judge → Risk Engine → Portfolio Construction pipeline against a past date range, using only genuinely point-in-time-reconstructable evidence, to build up calibration signal faster than waiting on live decisions to resolve. `--with-adversarial` also runs 3f's real bull/bear/scenario cycle per replayed day. **Since 2026-10-02**: refuses any `--end` date after the frozen `TRAINING_WINDOW_END` (`app/benchmarks/schemas.py`) — fails fast with a clear message before even estimating cost — unless `--allow-post-training-cutoff` is passed, which permanently marks the embargoed holdout cohort `contaminated` (see `EMBARGO_HOLDOUT_COHORT_PROMPT.md`). | **Makes real, billed LLM calls** (model-assessment + Judge per replayed day; +3f cost with `--with-adversarial`). Prints a cost estimate and requires confirmation before running (`--yes` to skip). Running this on any schedule would silently accumulate real spend and pollute the backfilled decision history with duplicate `run_id`s if pointed at an already-replayed date range. Always choose a fresh, never-replayed date window, and never use `--allow-post-training-cutoff` without understanding it's a one-way contamination of the clean holdout cohort. |
| `calibration_baseline.py` | Registers one calibration "trial" (`--source phase2/backfill/live`) against `calibration_runs` — the honest trial-count bookkeeping 3g's Deflated Sharpe/PBO correction depends on. | Not periodic by design — a "trial" should mean a genuinely new configuration being calibrated (a prompt version bump, a new logic change), not a recurring re-check. `/calibration/summary` already live-computes the current hit-rate/Brier/Sharpe/DSR picture on every dashboard load without needing a new trial row for that. Run this only when you've actually changed something worth counting as a new trial. |

## Not a script — the FastAPI dashboard itself

`uvicorn app.api.main:app` (see [`operations.md`](operations.md)) is the
one long-running process in this project; everything above is a one-shot
CLI invocation, run manually or via `run_daily.py`.
