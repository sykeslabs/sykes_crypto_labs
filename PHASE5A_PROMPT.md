# AI Crypto Portfolio — Phase 5a: Current-Holdings Input

## Context

Phase 5 is a deliberately **read-only** layer over existing state — no
endpoint may write anything that influences a Judge/Risk Engine/Portfolio
Construction decision. This sub-phase adds exactly one, narrow exception:
a way to tell the system what you **actually hold right now**, so
Portfolio Construction's increase/hold/reduce/remove/initiate logic reasons
against your real position, not stale or manually-edited database rows.

This is a factual data-entry capability, not a decision-making one. It does
not let you influence *what* the Judge recommends — it lets you correct
*what the system believes you currently own*, which the Judge/Portfolio
Construction pipeline has depended on as an input since 3e.

**Before writing any code**, inspect what actually exists: find and
document exactly how "current portfolio status" is presently read by
Portfolio Construction (3e's task 3 lists it as a real input) — a table, a
config file, or something else. **Do not introduce a second, parallel
source of truth for holdings.** If a holdings table already exists, this
sub-phase extends/replaces how it's written to; it does not create a
competing one.

**This task is Phase 5a only.** It does not change Judge, Risk Engine, or
Portfolio Construction decision logic — only what real-world state they're
given to reason about.

## Non-negotiables

- **Ground truth only, never a decision override.** This endpoint/form lets
  you state what you hold (asset, quantity, and optionally cost basis) — it
  must never accept or influence a `decision`, `target_allocation`, or any
  other Judge/Risk Engine/Portfolio Construction output field. If the
  underlying table or form has any field that could be mistaken for
  steering a recommendation, remove it before shipping.
- **Point-in-time integrity applies here too.** Holdings changes over time
  matter for any future backtest or Judge input replay — an edit must be
  **append-only** (a new row with `recorded_at`/effective timestamp), never
  an in-place overwrite of a prior holdings row, same convention 3a already
  established for revisable evidence. "What did I hold as of date T" must
  remain answerable later.
- **Validation, not silent acceptance.** An entered asset must already exist
  in the `assets` table (tracked, even if only `CANDIDATE` status);
  quantities must be non-negative. Reject anything else with a clear error
  — don't silently create a new untracked asset row as a side effect of a
  holdings entry, and don't silently clamp/round an invalid value.
- **Full audit trail**, same standard as every write this project has
  introduced: every holdings change is timestamped and attributable (even
  if there's only one real user), queryable after the fact.
- **No scope creep into Phase 6.** This sub-phase does not place orders,
  does not read a real or testnet exchange balance automatically, and does
  not reconcile your stated holdings against any external source — it is
  purely "tell the system what you have," entered by hand.
- **Never expose secrets** — same standard as Phase 5 (this endpoint touches
  the same API surface and auth).
- **Live verification required.** Before this sub-phase is reported
  complete, enter a real holdings state via the dashboard/API against the
  live Supabase project, run the existing pipeline through
  Portfolio Construction, and confirm the entered holdings are genuinely
  what Portfolio Construction reasoned against — not fixture tests alone.

## Task detail

**1. Locate and document the existing holdings mechanism.**
Before building anything, find exactly how Portfolio Construction currently
sources "current holdings" and document it in the README. If it's a manual
Supabase table, name the table/columns. If it's something else, describe it
precisely.

**2. Holdings write endpoint (`app/api/`, extending Phase 5's FastAPI app).**
A single, narrowly-scoped endpoint (e.g. `POST /holdings`) accepting asset +
quantity (+ optional cost basis), validated per the non-negotiables above,
writing an append-only row to the real holdings-source-of-truth table
identified in task 1 (or a new table if none exists yet, in which case wire
Portfolio Construction to read from it going forward — document that
change explicitly).

**3. Dashboard form.**
A simple form in Phase 5's dashboard: list current holdings (latest
effective row per asset), allow adding/editing/removing a position, calling
the endpoint from task 2. No other write capability is added to the
dashboard beyond this.

**4. Tests & docs.**
`pytest` passes without live credentials: validation-rejection tests
(untracked asset, negative quantity), an append-only-history test (editing
a holding doesn't overwrite the prior row), and a secrets-leak test on this
new endpoint's error paths. Update `README.md`: document the holdings
mechanism found in task 1, the new/changed table, and confirm Portfolio
Construction reads from it correctly.

## Exit criteria

- The pre-existing holdings mechanism is documented, and no duplicate
  source of truth was introduced.
- Holdings entries are append-only and queryable as of any past effective
  date.
- Invalid entries (untracked asset, negative quantity) are rejected with a
  clear error, not silently accepted or corrected.
- A real holdings entry made via the dashboard, against the live Supabase
  project, is confirmed to be what Portfolio Construction actually reasons
  against in a real pipeline run — not just written to the table.
- No secret ever appears in this endpoint's response, log, or error path.
- `pytest` green without live credentials.
- README updated with real findings, not placeholders.

Report the holdings mechanism found, what was built or changed, and the
live-verification result, then this sub-phase is done — no further
confirmation gate needed before resuming normal daily use of the system.
