# Build: API endpoint for evidence_observations (todo B)

## Context

Read `doc/todo.md` → "`evidence_observations` has no API endpoint at all" first. The item
says a backend design decision is needed before any UI work.

Verified 2026-10-02:

- `EvidenceObservationRepository` (`app/database/repository.py` ~line 546) already has
  `get_latest_by_asset(asset_id, limit=150)`, `get_latest_global(source, limit=10)`,
  `get_latest_global_all(limit=100)`.
- The table is past Supabase's ~1000-rows-per-request cap (3714 rows on 2026-09-27).
  `_fetch_all_paginated` exists (~line 36) if a full fetch is ever needed.
- Sources include funding rates, open interest, options IV, on-chain flows, DeFi TVL,
  stablecoin supply, macro series, regulatory calendar, each with status
  OK / UNAVAILABLE / NOT_IMPLEMENTED.

## Step 0 — design decision, then stop (required)

1. Read-only: row count per `source` (and per asset vs. global), latest timestamp per
   source, and the model's fields (`app/market_data/evidence_schemas.py`).
2. Propose endpoints that map directly onto the existing repo methods, e.g.:
   - `GET /evidence/asset/{asset_id}?limit=` → latest per asset
   - `GET /evidence/global?source=&limit=` → latest global (macro/regulatory)
   - optionally `GET /evidence/sources` → per-source status/count/latest
   No "get everything" endpoint unless I ask (it would need `_fetch_all_paginated`).
3. UI: ask whether you should add a dashboard section now or backend only.
4. **Wait for my decision.**

## Implementation

- New router `app/api/routers/evidence.py`, registered like the others, same auth.
- Response models in `app/api/schemas.py` (reuse the existing evidence model if it's
  already API-safe).
- Cap `limit` at a sane maximum below 1000.

## Tests

Follow `tests/test_api_endpoints.py`: each endpoint returns data, respects limit,
unknown asset → empty list (or 404 — ask), auth enforced.

## Docs (show diff first)

`doc/todo.md`, `doc/history.md`, `doc/architecture.md` endpoint list.

## Ground rules

Simplest solution. Don't touch unrelated code. Flag uncertainty. No schema changes.
