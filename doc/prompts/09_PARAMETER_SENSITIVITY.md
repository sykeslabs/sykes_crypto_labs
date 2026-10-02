# Analyze: Parameter sensitivity of MAX_CONCURRENT_POSITIONS / MIN_REPLACEMENT_ALPHA_ADVANTAGE (todo [MEDIUM]) — GATED

## Context

Read `doc/todo.md` → "[MEDIUM] Parameter sensitivity" first.

Verified 2026-10-02:

- `max_concurrent_positions = 8` and `min_replacement_alpha_advantage = 0.03` in
  `app/config/settings.py` (~lines 195–202). Chosen, not fit.
- Used in `app/portfolio/construction.py` (~lines 168–206): overflow above the cap
  triggers replacing the weakest holding if the newcomer's alpha beats it by the margin.
- `app/benchmarks/replay_fakes.py` has in-memory position/allocation repos, so portfolio
  construction can be re-simulated deterministically over persisted Judge decisions,
  **no LLM cost**.

## Step 0 — gate check (required, stop if it fails)

1. Check that prompt 02 (baseline ladder) is done and shows a real effect for the full
   system. If the full system shows no edge, **stop and tell me**: tuning position limits
   on a signal with no edge is pointless.
2. Count real **replacement events** (cap overflow cases) in history, read-only. Use
   `portfolio_allocation_changes` (`change_reason`, migration 0021) and logs/fields that
   identify replacements. Report how many exist per population.
3. If replacement events are very few (propose a threshold, e.g. < 20), stop and report.
4. **Wait for my OK.**

## Implementation

- A script that replays `PortfolioConstructionService` + `RiskEngine` over the
  persisted Judge decisions in time order, with the in-memory fakes, for a small grid:
  `max_concurrent_positions ∈ {6, 8, 10}`, `min_replacement_alpha_advantage ∈
  {0.01, 0.03, 0.05}` (confirm grid with me).
- Pass parameters via a settings copy; **don't change the defaults**.
- Output per grid cell: pooled-daily Sharpe and return (ladder methodology), turnover,
  cost drag, number of replacements. Report n and say whether differences exceed
  bootstrap noise.
- Note in output: picking the best cell from this grid and reporting it would be
  overfitting. The grid shows sensitivity only.

## Tests

Re-simulation with default params reproduces the recorded allocations on a small fixture
(or explain why it can't exactly); grid parameters actually take effect.

## Docs (show diff first)

`doc/todo.md`, `doc/history.md`, `doc/scripts.md`.

## Ground rules

Simplest solution. Don't touch unrelated code. Flag uncertainty. No DB writes, no LLM
calls. Never use the holdout cohort to choose parameters.
