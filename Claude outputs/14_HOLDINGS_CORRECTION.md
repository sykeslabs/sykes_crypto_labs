# Build: Correct a mistaken holdings entry (todo B) — GATED (you deferred this)

## Context

Read `doc/todo.md` → "A way to correct/remove a mistaken holdings entry" first.

**You explicitly deferred this ("address this at a later point in time").**

## Step 0 — gate check (required)

Ask me: "This item is marked deferred by you. Do you want to implement it now?"
**If not a clear yes, stop.**

## Context (verified 2026-10-02)

- `holdings_ledger` is append-only. `transaction_type` check constraint allows only
  `'BUY'`, `'SELL'` (migration 0015). `platform` added in 0022.
- `POST /holdings` (`app/api/routers/holdings.py` `record_holding`, ~line 100) inserts a
  transaction; SELL is validated against the aggregated quantity per asset + platform;
  `in_asset` is updated afterwards.
- Hard delete was rejected: it breaks the append-only guarantee and makes past Judge
  decisions (which saw the mistaken holding) unreproducible.

## Step 1 — design decision, then stop

Present and ask:

1. **Reuse SELL** for the full remaining quantity with a correction note. Simple, no
   migration, but a correction then looks like a real sale (cost basis, any turnover or
   realized P&L logic). Check whether anything treats SELL as a real trade.
2. **New `transaction_type = 'CORRECTION'`** (signed quantity offsets the mistaken
   entry). Needs a migration for the check constraint and updates to
   `aggregate_current_holdings` and every consumer of `transaction_type`. List them.
3. Also: should a correction reference the entry it corrects (`corrects_entry_id`)?
   Adds traceability, needs a column.

Recommend one. **Wait for my decision.**

## Implementation (after decision)

- Backend: smallest change for the chosen option. Correction must never rewrite or
  delete existing rows.
- Dashboard: a "Remove / Correct" button on a holdings row that posts the offsetting
  entry, with a confirm step showing what will be posted.
- `GET /holdings/history` shows corrections visibly as corrections.
- Migration (if any): write it idempotent (see 0020's defect in history.md Phase 5c),
  **don't apply it**. I'll apply it.

## Tests

Correction brings the aggregated quantity to the intended value; history keeps both rows;
`in_asset` updated; over-correction rejected.

## Docs (show diff first)

`doc/todo.md`, `doc/history.md`, `doc/decisions.md` (the design choice).

## Ground rules

Simplest solution. Don't touch unrelated code. Flag uncertainty. Don't apply migrations
or write to the DB.
