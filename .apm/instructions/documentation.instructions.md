---

description: Documentation consistency and source-of-truth policy for sykes_crypto_labs
applyTo: "**"
-------------

# Documentation Policy

A task is not complete until the relevant documentation has been updated.

Follow this flow:

**Understand → Implement → Test → Update docs → Verify consistency**

Each fact has exactly one authoritative location:

| File                  | Source of truth                                        |
| --------------------- | ------------------------------------------------------ |
| code                  | Implementation                                         |
| `doc/architecture.md` | Current architecture                                   |
| `doc/methodology.md`  | Process                                                |
| `doc/decisions.md`    | Rationale, dated                                       |
| `doc/history.md`      | What happened — append-only, never rewrite             |
| `doc/todo.md`         | What's open; no completed work                         |
| `doc/operations.md`   | Setup, environment variables, migrations, run sequence |
| `doc/scripts.md`      | Scripts, cost, and schedule                            |

Implementation prompts live in:

`doc/prompts/NN_*.md`

The index is:

`doc/prompts/00_INDEX.md`

Completed prompts move to:

`doc/prompts/done/`.
