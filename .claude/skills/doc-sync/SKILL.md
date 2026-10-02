---
name: doc-sync
description: Update this repo's documentation after any substantial change so each fact lives in exactly one doc/ file. Use at the end of every code or design task, or when the user asks to "update the docs" / "reconcile docs".
---

# Doc sync

## Routing table: put each fact in ONE place, link from others
| Change | Goes to |
|---|---|
| New/changed component, data flow, `app/` layout | `doc/architecture.md` |
| Why something was chosen or declined (dated) | `doc/decisions.md`. Separate **observed fact** from **inferred rationale**, and never invent past reasoning |
| What was built, real live numbers, incidents | `doc/history.md`, **append-only** new dated section |
| Open / deferred / declined work | `doc/todo.md`. Remove done items, keep revisit conditions |
| Env var, migration, run sequence, cost per run | `doc/operations.md` |
| Script added/changed, its cost & schedule | `doc/scripts.md` |
| Process rule | `doc/methodology.md` |
| High-level status only | `README.md` (no duplicated detail) |

## Procedure
1. `git diff --stat` and read the diff to list what changed.
2. For each change, update only the routed file; replace duplicates elsewhere with a link.
3. Grep `doc/` and `README.md` for now-stale names (renamed functions, env vars, migration ranges like "0001 through 00NN").
4. Final question: *If another agent started tomorrow, would the docs describe the system correctly?* If not, keep going.
5. For a substantial change, delegate to the `doc-consistency-checker` agent.
