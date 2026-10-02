---
name: write-implementation-prompt
description: Turn an idea, todo.md item, or user-supplied generic proposal into a new grounded implementation prompt in doc/prompts/NN_*.md, verified read-only against the repo. Use when the user asks to "write a prompt for", "regound this proposal", or "add a prompt for todo item X".
---

# Write a grounded implementation prompt

Work **read-only** on code. The only files you write are the new prompt and its index/todo links.

## Steps
1. **Locate**: find the matching `doc/todo.md` item. If none exists, say so; the prompt will introduce a new item (note this explicitly, as `17` did).
2. **Ground**: for every claim about the code, cite `path:line` that you actually opened. Re-query live numbers only if the user OKs it, and date them ("verified YYYY-MM-DD, read-only").
3. **Next number**: highest `NN_` in `doc/prompts/` and `doc/prompts/done/`, plus 1.
4. **Write** `doc/prompts/NN_UPPER_SNAKE_TITLE.md` with exactly these sections:
   - `## 0. What this is — and is not` (deliverable + binding **Out of scope** list)
   - `## Context — verified <date>, read-only` (cited facts only)
   - `## Step 0 — gate check` (the todo item's revisit condition, checked; stop conditions)
   - `## Steps` (numbered, smallest viable change; migrations, tests, cost estimate if LLM)
   - `## Validation` (pytest + any live check, marked "ask user first")
   - `## Docs` (which of history/decisions/todo/operations/scripts/architecture change)
   - `## Open questions for the user` (never silently decide these)
5. **Index**: add a row to `00_INDEX.md` in the same order as `doc/todo.md`, plus a dated revision-log bullet; link the prompt from the todo item.
6. **Verify**: delegate to the `prompt-verifier` agent; fix or flag every finding before calling it READY.
