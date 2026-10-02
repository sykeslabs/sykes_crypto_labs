# Fix: capacity-blocked BUYs are misclassified as strategy turnover, not risk-control (todo [HIGH][Portfolio/Risk])

## Context

Read `doc/todo.md` → "B. Engineering / Product / Operations backlog" →
"[HIGH][Portfolio/Risk] Capacity-blocked decisions misclassified as
`change_reason=\"strategy\"`" first, and
`doc/reviews/2026-10-02_INVESTMENT_VALIDITY_REVIEW.md` (finding F.3) for
the full writeup. This is a confirmed, active production bug, not a
research-design question — found while tracing portfolio-construction
validity, not assumed.

Verified 2026-10-02, read-only, exact mechanism:

- `PortfolioConstructionService.apply()` (`app/portfolio/construction.py:
  63-70`) calls `self._apply_replacement_capacity_limit(sized_decisions,
  decisions_by_asset)` **first**, then loops over the same
  `sized_decisions` list to build each `PortfolioAction` and classify
  `change_reason` (lines 72-128).
- `_apply_replacement_capacity_limit` (lines 149-207): when a brand-new
  candidate (`previous_system_target == 0`) can't be added because
  `MAX_CONCURRENT_POSITIONS` is full **and** no existing holding clears
  `MIN_REPLACEMENT_ALPHA_ADVANTAGE`, it does `newest.final_allocation =
  0.0` (line 201) and logs "blocked: no capacity" — but never touches
  `newest.decision` (still whatever the Judge said, e.g. `"BUY"`), and
  there is no field anywhere recording that this specific zeroing came
  from the capacity limiter rather than from the Judge/Risk Engine's own
  confidence gate.
- `change_reason` classification (lines 121-126) is:
  `"risk_control" if d.decision in ("WATCH", "NO_TRADE") or
  is_cap_compliance_correction(d, max_single_asset_allocation) else
  "strategy"`. For a capacity-blocked BUY: `d.decision` is still `"BUY"`
  (not WATCH/NO_TRADE), and `is_cap_compliance_correction`
  (`app/risk/engine.py:35-64`) requires `d.previous_system_target >
  max_single_asset_allocation` — **false for a brand-new candidate, whose
  `previous_system_target` is 0 by definition** (confirmed: that's exactly
  the filter `_apply_replacement_capacity_limit` uses to find "new
  candidates," line 178). Neither condition fires, so the row is persisted
  with **`change_reason="strategy"`**.
- `change_reason="strategy"` is not cosmetic — it is the one field
  `get_turnover_since` (`app/database/repository.py:1147-1163`,
  `.eq("change_reason", "strategy")`) uses to compute the real,
  live-enforced `MAX_WEEKLY_TURNOVER` budget. **A capacity-blocked decision
  (final_allocation forced to 0 for a portfolio-construction reason having
  nothing to do with the asset's own merits) is therefore currently
  counted against the strategy turnover budget it should be exempt from**
  — the same class of bug A1/A2 (`doc/decisions.md`) already fixed for
  WATCH/NO_TRADE and cap-compliance corrections, just a third case those
  fixes didn't cover.
- **A pre-existing, never-wired field already anticipates part of this
  fix**: `PortfolioAction.blocked_no_capacity: bool = False`
  (`app/portfolio/construction.py:45`) is declared but **never set to
  `True` anywhere** in this file (confirmed via grep) — dead field. It is
  not currently usable for the `change_reason` fix as-is because
  `PortfolioAction` is constructed per-decision inside the main loop
  (line 76), **after** `_apply_replacement_capacity_limit` has already run
  and mutated the `SizedDecision` objects — the information needs to flow
  from the capacity limiter into the classification, which happens on
  `SizedDecision`, not `PortfolioAction`.

## Step 0 — required, then stop

1. Confirm the exact fix shape and **wait for my OK** before editing:
   add a new field to `SizedDecision` (`app/risk/engine.py`), e.g.
   `capacity_blocked: bool = False`, set to `True` at
   `construction.py:201` (the "blocked: no capacity" branch only — **not**
   the replacement branch at line 192, where an existing holding is
   legitimately out-competed by a stronger new candidate; that is real
   strategy turnover, not a bug) — then use it in the `change_reason`
   classification alongside the existing two conditions. State clearly
   whether `PortfolioAction.blocked_no_capacity` should finally get wired
   up too (set from the same flag, for the dead field's own sake) or
   removed if genuinely redundant — don't leave it dead either way.
2. Report: live, how many resolved `portfolio_allocation_changes` rows
   historically fall into this exact pattern (candidate's `previous_
   allocation == 0` and `new_allocation == 0` with `change_reason=
   "strategy"`, i.e. a persisted no-op that was almost certainly a
   capacity block, not a genuine strategy "do nothing" row) — this
   quantifies how much historical turnover-budget accounting has actually
   been affected, not just whether the bug is theoretically possible.
3. Ask explicitly: should the fix apply retroactively (a one-off script
   recomputing historical `change_reason` for past capacity-blocked rows,
   using the same detection heuristic from point 2) or only prospectively
   (correct going forward, leave history as-recorded, matching this
   project's general "don't rewrite history" convention, e.g.
   `doc/history.md` being append-only)? Default assumption if you don't
   hear back: prospective-only, consistent with how A1/A2 themselves were
   NOT retroactively reclassified (confirmed: `doc/decisions.md`'s A2
   entry explicitly left prior rows as originally recorded) — but confirm
   before assuming.

## Implementation (after Step 0)

1. Add the agreed field to `SizedDecision`, set it in
   `_apply_replacement_capacity_limit`'s capacity-blocked branch only.
2. Extend the `change_reason` ternary (lines 121-126) to also treat
   `d.capacity_blocked` (or whatever name was agreed) as `"risk_control"`,
   with a comment matching this file's existing style (dated, cites the
   real mechanism, references this prompt).
3. If `PortfolioAction.blocked_no_capacity` is kept: set it from the same
   source at `construction.py:76-81` (same loop, same data already in
   scope) rather than leaving it permanently `False`.
4. Do not touch `is_cap_compliance_correction`, A1/A2's own logic, or
   `_strategy_turnover_delta` — this fix is additive (a third, previously
   missing condition), not a change to the existing two.

## Tests

A capacity-blocked new candidate (set up `MAX_CONCURRENT_POSITIONS` at
capacity, a new BUY candidate that doesn't clear
`MIN_REPLACEMENT_ALPHA_ADVANTAGE` over any existing holding) now persists
`change_reason="risk_control"`, not `"strategy"`. A genuine replacement
(existing holding correctly bumped by a stronger candidate) still persists
`"strategy"` — prove the fix doesn't over-broaden and swallow real strategy
turnover too. Existing A1/A2 tests (`tests/test_portfolio.py` or
equivalent) continue to pass unchanged.

## Docs (show diff first)

`doc/todo.md` (close this item once fixed and verified against real data),
`doc/history.md`, `doc/decisions.md` (record this as a real incident, same
convention as A1/A2 — dated, forensic, "real bug fixed" style comment in
code).

## Ground rules

Simplest solution. Don't touch unrelated code — this prompt changes
`change_reason` classification only, not sizing, not the capacity/
replacement logic itself, not turnover-cap enforcement's own math. Flag
uncertainty. No DB writes beyond whatever Step 0 agrees for the
retroactive-vs-prospective question. This is a real correctness fix to
already-shipped code, not a research experiment — prioritize accuracy over
speed, verify against real historical data before closing.
