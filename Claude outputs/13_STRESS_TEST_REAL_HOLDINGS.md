# Fix: run_stress_test.py uses target allocation, not real holdings (todo B [HIGH][Risk])

## Context

Read `doc/todo.md` → "[HIGH][Risk] `run_stress_test.py` reads the system's own TARGET
allocation" and `doc/history.md` Phase 5c/5d first.

Verified 2026-10-02:

- `scripts/run_stress_test.py` (~lines 74–81) builds the allocation from
  `PortfolioPositionRepository(client)` → `p.current_allocation` (the system's target).
- Real holdings are computed by `compute_current_allocations` in
  `app/portfolio/holdings.py` (~line 158), which Phase 5c/5d switched the Risk Engine and
  Judge context to.
- `app.risk.stress_test` functions accept any allocation dict, so only the input changes.

## Step 0 — required, then stop

1. Find exactly how the Judge context / daily runner call `compute_current_allocations`
   (arguments, price source, `min_material_holding_usd`, cash handling). Show me the call
   you'll copy.
2. Ask: print the target allocation as well, for comparison, or real holdings only?
   (Default suggestion: real holdings as the stress-tested portfolio, plus one line
   per asset showing target vs. real.)
3. **Wait for my OK.**

## Implementation

- Replace the input in `run_stress_test.py` with the same `compute_current_allocations`
  call the Risk Engine path uses. No new helper unless the call is non-trivial to copy.
- Cash: treat exactly as the Risk Engine does (state which).
- Header line in output: "Stress-tested portfolio: real holdings as of <timestamp>".

## Tests

Script's allocation builder uses holdings, not positions (mock both with different values
and assert); empty holdings handled.

## Docs (show diff first)

`doc/todo.md` (close), `doc/history.md`, mirror dashboard todo item.

## Ground rules

Simplest solution. Don't touch unrelated code. Flag uncertainty. No DB writes.
