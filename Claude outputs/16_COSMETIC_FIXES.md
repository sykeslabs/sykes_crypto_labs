# Fix: Cosmetic / low-severity items (todo B) — three independent sub-tasks

Read `doc/todo.md` → "Cosmetic / low-severity, real but minor" first. Do the three
sub-tasks one at a time; show me the diff after each.

---

## (a) `POST /holdings` returns `id: null`

Verified 2026-10-02:

- `record_holding` (`app/api/routers/holdings.py` ~line 100) builds `record`, calls
  `ledger_repo.insert(record)`, then returns `HoldingsEntryView(id=record.id, ...)`.
- `HoldingsLedgerRepository.insert` (`app/database/repository.py` ~line 1218) is
  `self._client.table("holdings_ledger").insert(entry.to_row()).execute()` and returns
  nothing, so `record.id` stays `None`.

**Step 0:** list every caller of `HoldingsLedgerRepository.insert`. Ask before changing
its return type if other callers exist.

**Fix (simplest):** have `insert` return the DB-assigned id from the insert response's
`data` (Supabase returns the inserted row), and use it in the response.

**Test:** `POST /holdings` response has a non-null id matching the stored row
(`tests/test_api_holdings.py` style).

---

## (b) `/calibration/summary` N+1 query

Verified 2026-10-02:

- `get_calibration_summary` (`app/api/routers/calibration.py`) builds
  `decision_by_outcome_id = {o.decision_id: judge_repo.get_by_id(o.decision_id) for o in resolved}`:
  one DB call per resolved outcome (~29 s at 323 rows on 2026-09-27).
- The same function already fetches `judge_repo.get_recent(limit=None, is_backfilled=False)`.

**Step 0:** measure the current latency with a direct in-process call (read-only).

**Fix (simplest):** fetch all decisions once with `judge_repo.get_recent(limit=None)`
(both populations; check that `is_backfilled=None` returns both and is paginated via
`_fetch_all_paginated`), build `{d.id: d}`, look up from it. Reuse that list for the
live-duplicate computation instead of a second fetch if the result is identical.
No new repo method unless this doesn't work.

**Tests:** existing calibration tests pass unchanged; assert `get_by_id` isn't called per
outcome. Report latency before/after.

---

## (c) `market_snapshots` / `evidence_observations` beyond the 1000-row cap

The todo says: not fixed on purpose, because no "fetch everything" consumer exists.

**Task: verification only.** Grep for any consumer that reads either table without an
asset/date scope or with a limit ≥ 1000. If none, change nothing and say so. If one
exists, show it and ask before applying `_fetch_all_paginated`.

Note: if prompt 15 adds an evidence endpoint, re-check it.

---

## Docs (show diff first)

`doc/todo.md`: remove/close (a) and (b), update (c)'s check date.
`doc/history.md`: one short entry.

## Ground rules

Simplest solution. Don't touch unrelated code. Flag uncertainty. No DB writes.
