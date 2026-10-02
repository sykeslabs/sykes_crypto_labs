# Fix: Historical replay candidate universe is not point-in-time (todo [CRITICAL][Backtest])

## Context

Read `doc/todo.md` → "[CRITICAL][Backtest] The historical replay's candidate universe is
not point-in-time" first.

Verified 2026-10-02:

- `HistoricalReplayService.run()` (`app/benchmarks/replay.py` ~line 283) calls
  `self._asset_repo.get_active_assets()` once and reuses that list for every replayed day.
  `get_active_assets()` is simply `assets where active = true` *today*.
- `_build_day_universe()` (~line 660) then ranks only those assets by
  `compute_composite_factor_scores`.
- Live screening (`app/market_data/screening_service.py` ~line 231) instead takes the
  CoinGecko top `screening_universe_size + 15` (= 65) **by market cap at run time**.
- So replay picks from "assets that turned out to matter enough to be in our table",
  live picks from "today's top-N by market cap". That's survivorship/hindsight bias.
- This is **not** the Binance date-anchor/pagination bug (history.md Phase 5f/5m). Don't
  close this item on the strength of that fix.

## Goal

Either (A) make replay select each day's candidates from a genuine point-in-time top-N
by market cap, or (B) if that isn't feasible, label every backfilled Sharpe/hit-rate as
subject to universe-selection bias. Which one is decided in Step 0.

## Step 0 — feasibility check, then stop and ask (required)

1. Find out whether a **historical** market-cap ranking is reachable with the keys in
   `.env` (don't print key values). Candidates:
   - CoinGecko `/coins/{id}/market_chart` (has `market_caps`) — only works for coins you
     already know, so it can't find coins that were top-N then but aren't in our table
     now. That is still partial survivorship. Say so.
   - CoinGecko historical snapshot / `/coins/{id}/history` — check what the demo/free
     tier allows (history depth limits, rate limits).
   - CoinMarketCap historical listings (`app/market_data/coinmarketcap.py` exists) —
     check whether our plan tier allows it.
   Make at most a handful of read-only API calls to confirm. No bulk fetching.
2. Report: which source works, how far back, rate-limit cost for a 28-day replay and
   for a 1-year replay, and the remaining bias it can't remove.
3. Recommend A or B. **Wait for my decision.**

## If A (point-in-time universe)

- Add one function that, given a cutoff date, returns the top
  `screening_universe_size` assets by market cap *as of that date*. Mirror live
  screening's rules (same size, same stablecoin/exclusion filters — find them in
  `screening_service.py` and reuse, don't duplicate).
- Coins not in our `assets` table: ask me how to handle (insert as inactive assets vs.
  keep in-memory only for the replay). Don't decide silently.
- `run()` uses that per-day universe instead of the one-off `get_active_assets()` list.
  OHLCV fetch per asset stays as is, but now over the union of all daily universes.
- Persist which universe source was used per replay run (reuse an existing field if
  there is one; ask before adding a column).
- Existing backfilled rows are not recomputed. They stay biased; label them (see B).

## If B (labeling only), and also for existing rows under A

- Reuse the "directional only — not confirmatory" mechanism from the embargo work.
  Add one short line wherever backfilled hit-rate/Sharpe/DSR is shown:
  `held_out_window_note`-style text in `/calibration/summary`, the dashboard Calibration
  rows, and stdout of `run_periodicity_fix.py` / `run_evidence_value_ranking.py` /
  `calibration_baseline.py --source backfill`. List the exact spots for my OK first.
- No new API field unless needed; prefer extending the existing note text.

## Tests

- A: universe function returns the right top-N for a mocked historical response;
  replay uses a different universe on two different days; missing data for a day is
  reported, never silently falls back to today's list.
- B: label appears in the calibration summary output.
- Full `pytest` suite passes.

## Docs (show diff first)

`doc/todo.md` item (close only if A is done and remaining bias is documented),
`doc/history.md` entry, mirror the dashboard todo item.

## Ground rules

- Simplest solution. Don't touch unrelated code. Flag uncertainty instead of guessing.
- Don't run `run_replay.py`, migrations, or anything that writes to the DB without my
  explicit OK. Replays must end on or before `TRAINING_WINDOW_END`.
- Never blend backfilled and live figures.
