---
name: new-migration
description: Create a new Supabase/Postgres migration in migrations/ following this repo's numbering, idempotency, and documentation rules. Use whenever a task needs a schema change (new table, column, constraint, index).
---

# New migration

1. **Number**: highest `migrations/NNNN_*.sql` plus 1, zero-padded to 4. Name: `NNNN_short_snake_description.sql`.
2. **Header comment** (match existing files): phase/date, *why* the change exists, what it backfills (or why nothing needs backfilling), and the line `-- Idempotent -- safe to re-run.`
3. **Idempotent SQL only**: `create table if not exists`, `add column if not exists`, `create index if not exists`, guarded `do $$ ... $$` blocks for constraints. Never `drop` data without explicit user approval.
4. **Invariants**:
   - Persists an LLM result? Add an `estimated_cost numeric` column AND register the table + timestamp column in `COST_TRACKED_TABLES` (`app/llm/cost.py`).
   - Revisable evidence? Append-only with `is_revision_of`, no update-in-place.
   - Required dimensions are `not null` with no silent default (see 0022's `platform`).
5. **Code**: update `app/database/models.py` / `repository.py` and add a test with a mocked client.
6. **Docs**: add the row to the migrations table in `doc/operations.md` and bump "`0001` through `NNNN`".
7. **Applying**: the user pastes it in the Supabase SQL Editor. Don't rely on `scripts/apply_migration.py` (auth currently broken). Verify by querying the new table/column, with the read-only Supabase MCP if it's connected, or a `python -c` client snippet the user runs.
