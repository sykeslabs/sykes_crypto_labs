# Analyze: Regime robustness (todo [MEDIUM]) — GATED

## Context

Read `doc/todo.md` → "[MEDIUM] Regime robustness" first. Question: does any edge hold
across RISK_ON / RISK_OFF / NEUTRAL, or is it concentrated in one regime?

## Step 0 — gate check (required, stop if it fails)

1. Check that prompt 02 is done: `app/benchmarks/baseline_ladder.py` and
   `scripts/run_baseline_ladder.py` exist and `doc/history.md` has its results.
2. Check the ladder shows a non-trivial effect for some rung vs. the rung below
   (CI excludes zero in at least one population). If not, **stop and tell me**:
   slicing a zero effect by regime only produces noise.
3. If the gate passes, report read-only:
   - **`regime_at_decision` is not a regime label — it's a
     `market_regime_snapshots.id` UUID** (confirmed 2026-10-02, live query:
     real values look like `d1f8824c-8612-...`, never the literal
     `"RISK_ON"`/`"RISK_OFF"`/`"NEUTRAL"` string). A join to
     `market_regime_snapshots` on this id is **required** before any
     regime grouping is possible — this was missing from this prompt's
     original Context and must be the first thing implemented, not
     discovered mid-analysis.
   - `regime_at_decision` coverage per population. Known: it's NULL on old backfilled
     decisions (replay persistence gap, see `by_regime_note` in `calibration.py`);
     live decisions set it in `app/judge/service.py` (~line 262).
   - Counts per regime × population. **Known thin-data risk (2026-10-02 live
     query): `market_regime_snapshots` has only 43 rows total across the
     system's whole history** (`{RISK_ON: 17, NEUTRAL: 20, RISK_OFF: 3,
     None: 3}`) — 3 RISK_OFF observations cannot support any robustness
     claim about bear/crash behavior regardless of how the ladder itself
     performs. Report this count again live (it may have grown) and
     explicitly say whether there's enough of each regime to test anything
     at all, before proposing cells.
   - Also note the taxonomy itself (`classify_risk_regime`,
     `app/market_data/regime.py:22-36`) is a pure price-direction rule with
     no volatility dimension — it cannot distinguish "high-volatility,"
     "low-volatility," "crash," or "recovery" from each other; a sharp
     crash and a quiet grind can both land in the same bucket. State this
     limitation in the output rather than implying RISK_ON/RISK_OFF/
     NEUTRAL covers what `doc/todo.md`'s original regime list asks for.
   - For deterministic ladder rungs, regime per date can be derived from
     `market_regime_snapshots` or recomputed with replay's `_build_regime`. Propose which.
4. **Wait for my OK.**

## Implementation

- Add a `--by-regime` option to the ladder script. Same metrics, sliced by regime.
- Report n and CI per cell. Below a minimum n (propose one), print "insufficient data".
- Add a simple heterogeneity check (e.g. is the paired difference's CI overlap across
  regimes; or an interaction term). Flag if unsure which is appropriate at this n.
- Don't backfill `regime_at_decision` into old rows without asking.

## Tests

Slicing correctness on synthetic data; NULL regimes reported, not dropped silently.

## Docs (show diff first)

`doc/todo.md`, `doc/history.md`.

## Ground rules

Simplest solution. Don't touch unrelated code. Flag uncertainty. No DB writes, no LLM
calls.
