# Analyze: Cross-asset generalization (todo [MEDIUM]) — GATED

## Context

Read `doc/todo.md` → "[MEDIUM] Cross-asset / generalization analysis" first. Question:
does any edge generalize across the universe or come from a few assets (e.g. BTC)?

## Step 0 — gate check (required, stop if it fails)

1. Check that prompt 02 (baseline ladder) is done and shows a real effect for some rung.
   If not, **stop and tell me**.
2. Read-only: resolved directional decisions per asset per population; the top 5 assets'
   share of decisions.
3. **Wait for my OK.**

## Implementation

- Add a `--by-asset` option to the ladder script:
  - Per-asset contribution to the pooled daily return and to the paired difference vs.
    the rung below.
  - Concentration: share of total P&L from the top 1 / top 3 assets.
  - Leave-one-asset-out: recompute headline metrics without each of the top 3
    contributors (BTC at minimum). Report whether the effect survives.
- n per asset; "insufficient data" below a minimum you propose.
- Note universe-selection bias for backfilled (item 01): assets in the list are the ones
  that survived, which inflates generalization.

## Tests

Contribution sums match the total; leave-one-out removes exactly that asset.

## Docs (show diff first)

`doc/todo.md`, `doc/history.md`.

## Ground rules

Simplest solution. Don't touch unrelated code. Flag uncertainty. No DB writes, no LLM
calls.
