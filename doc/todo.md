# TODO / open work

Everything currently open, deferred, declined, or proposed-but-undecided,
in one place. (Replaces `open-work.md`, folded in below.) For what's
already **done**, see [`history.md`](history.md) — this file intentionally
does not repeat completed work, only points to it, so there is one
authoritative place for "what happened" and one for "what's still needed."

**Live source of truth**: the dashboard's own TODO section
(`app/api/static/dashboard.html`, `#todo-section`) is the day-to-day
working list, updated in real time as items are found/resolved. This file
is a periodically-synced summary for readers (human or agent) without
dashboard access — if the two ever disagree, the dashboard is current and
this file is stale; update this file to match, don't silently trust
whichever was read first. **Note (2026-09-27): the dashboard's own
`#todo-section` is itself a static, manually-maintained snapshot (its own
helper text says so) and was found stale relative to this file in places
(e.g. no A2 mention at all) — the stated "dashboard wins" hierarchy does
not currently hold in practice; treat both as needing an independent
live check, not either as automatically authoritative.** Last synced:
2026-09-27.

## Critical / High priority, open

- **[CRITICAL][Backtest] No embargo between the backfilled training window
  and the live holdout window.** The backfilled/live boundary is negative
  against a 45-day longest resolution horizon — 100% of live decisions
  sit within one horizon's distance of the boundary (`embargo_gap_days`,
  live-computed in Calibration summary; **re-checked 2026-09-27: now
  -17.3 days**, more negative than the "slightly negative" figure this
  item previously cited — the gap has widened as more live decisions
  accumulated, not narrowed). Price-momentum/regime persistence (present
  in both sets) is a real, unaddressed leakage channel. **Fix**: introduce
  a genuine embargo gap for the *next* holdout cohort, or continue
  treating every current/past holdout result as directionally suggestive
  only, never confirmatory.
- **[CRITICAL][Backtest] The backfill replay's candidate universe is not
  point-in-time** — `HistoricalReplayService.run()` uses TODAY's active-
  asset list for every simulated historical day, not a reconstructed
  point-in-time top-N-by-market-cap universe. A real hindsight/survivorship
  effect, not covered by the point-in-time audit (which only checked
  feature-level data, never universe selection). **Fix**: reconstruct a
  real point-in-time universe if a historical market-cap ranking source is
  reachable, or at minimum prominently disclose this wherever backfilled
  Sharpe/hit-rate numbers are shown.
- **[HIGH][AI] `source_agreement`/`confidence`/`uncertainty` are pure
  LLM self-reported numbers with no deterministic cross-check** — unlike
  `model_agreement` (a real, deterministic majority-vote fraction), these
  are the Judge's own unvalidated self-estimates, used directly as a Risk
  Engine sizing input. **Fix**: once enough live decisions resolve, run a
  reliability diagram of stated confidence vs. realized correctness
  (live-only, not blended with backfilled data).
- **[HIGH][Quant] The evidence-value logistic-regression ranking has never
  cleared its own `MIN_SAMPLE_SIZE=50`** — real n has stayed in the 16-46
  range across every run (**re-checked live 2026-09-27: n=46**, closest
  it's come yet, still below the 50 threshold). Until this clears, there
  is no real evidence any
  of the Judge's current inputs (model_agreement, source_agreement,
  confidence, risk_score, uncertainty, investment_horizon_days) predict
  outcomes better than noise. **Fix**: re-run `scripts/run_evidence_value_ranking.py`
  once n≥50 real resolved directional decisions exist; treat every current
  evidence category as unproven until then.
- **[HIGH][Backtest] `run_periodicity_fix.py`'s Sharpe comparison is scoped
  to backfilled decisions only** (found while writing [`scripts.md`](scripts.md),
  2026-09-16) — as live decisions resolve, the periodicity-matched
  system-vs-baseline comparison will not include them until this script is
  re-run or extended to cover live decisions too. Not yet actioned.
- **[HIGH][Risk] `run_stress_test.py` reads the system's own TARGET
  allocation, not real holdings, for "the current live portfolio"** (found
  while writing [`scripts.md`](scripts.md), 2026-09-16) — it queries
  `PortfolioPositionRepository` (`portfolio_positions.current_allocation`),
  exactly the real-vs-target ambiguity Phase 5c/5d fixed everywhere else in
  this project (see [`history.md`](history.md)). Given real holdings can
  diverge from the system's target by 15-30+ percentage points for weeks
  at a time (confirmed live for BTC/SOL), this stress test's drawdown
  numbers may currently be computed against the wrong portfolio
  composition. **Not yet fixed** — should read real holdings
  (`compute_current_allocations`) the same way the Risk Engine and Judge
  context now do.

## Medium/Low priority, open

- **[MEDIUM] Portfolio-optimization sizing** (risk parity, constrained
  mean-variance) — explicitly not added; revisit once either (a) enough
  live decisions resolve for evidence-value ranking to have a real sample
  (still not met, n=46 vs. 50 — see above), or (b) real turnover/fee costs
  become material (re-checked live 2026-09-27: net-of-costs drag averages
  0.26pp/decision across 312 resolved outcomes, essentially unchanged from
  the 2026-09-12 figure — still trivial).
- **[MEDIUM] `MAX_CONCURRENT_POSITIONS`/`MIN_REPLACEMENT_ALPHA_ADVANTAGE`
  sensitivity** — both are documented as a chosen convention, not fit or
  backtested. Needs enough resolved decisions across enough actual
  *replacement events* specifically (narrower than the general
  resolved-decision count) — not yet available.
- **A way to correct/remove a mistaken holdings entry** — no delete exists
  (the ledger is append-only, by design). Two options discussed: a real
  hard delete (breaks the append-only guarantee, corrupts retroactive
  history, makes past Judge decisions unreproducible) vs. a "Remove"
  button posting an offsetting correcting transaction. Explicitly deferred
  by the user ("address this at a later point in time").
- **`evidence_observations` has no API endpoint at all** — the single
  largest block of invisible data in the system (funding rates, open
  interest, options IV, on-chain flows, DeFi TVL, stablecoin supply, macro
  series, regulatory calendar). Needs a real backend design decision first
  (which sources, what endpoint shape) before any UI work — proposed, not
  scoped.

## Declined (with reasoning, so these aren't re-proposed blind)

- **`asset_status_history` dashboard exposure** — declined; current state
  is already shown live via SCREENED/JUDGED/HELD badges, this table is
  only the change-log behind them, pure audit-log clutter.
- **`prompt_templates.template_hash` exposure** — declined; internal
  dedup/versioning bookkeeping, not decision-relevant to a viewer.
- **Raw LLM payloads** (`model_market_assessments.raw_response`,
  `llm_analyses.response`/`token_usage`) — declined; debug-only, real cost
  is already reported in dollar terms via Cost/spend.
- ~~`portfolio_allocation_changes` exposure~~ — **reversed 2026-09-16**,
  see [`decisions.md`](decisions.md) and [`history.md`](history.md)'s
  Phase 5e section. No longer declined.

## Deferred / gated (not scheduled, with a stated revisit condition)

- **Phase 6 — exchange execution agent.** On hold by deliberate choice, no
  timeline. Full scope in [`prompts/PHASE6_PROMPT.md`](prompts/PHASE6_PROMPT.md).
- **Scheduling** (running the pipeline on a timer instead of manually).
  Explicitly decided against — the real bottleneck is elapsed calendar
  time for decisions to resolve, not run frequency; running more often
  wouldn't accelerate that. Revisit once the system reaches a more stable
  state, or a concrete cadence need emerges that manual triggering can't
  keep up with.
- **3j** (options gamma exposure, exchange counterparty/solvency risk,
  retail-demand proxies) **and 3k** (DeFi lending rates, staking yield/
  validator queue depth, stablecoin depeg risk) — gate not met. Both
  wait on 3h's evidence-value ranking (or 3g's Judge-reasoning audit /
  purged-walk-forward finding) surfacing a specific, *named* gap one of
  these would close — being used on other desks isn't, by itself, a
  reason to add a new cost-bearing, drift-prone input. Blocked on the
  same n≥50 sample-size gate as the evidence-value item above.
- **Paid-tier deferrals** (real recurring-cost decisions, not technical
  failures): **Glassnode/CryptoQuant** (on-chain valuation metrics) —
  client built, not subscribed. **CoinGlass** (liquidation heatmap) — real
  documented API, no usable free tier. **LunarCrush** (social sentiment) —
  re-confirmed 2026-09-15 with a real paid key: every endpoint tested
  returns HTTP 402, requires "Individual" tier or higher; user chose not
  to upgrade. **xAI/Grok** (4th assessment/research model) — API
  functional, no paid relationship established.
- **`NOT_IMPLEMENTED` sources** (genuine infeasibility, not fabricated):
  **Custody/OTC desk flow** — no reliable, independently-verifiable source
  of real custody-provider addresses exists. **Spot ETF flows** — Farside
  has no real API; SoSoValue needs an authenticated login not available
  here. **Token unlock/vesting schedules** — Messari needs a key not
  available here; TokenUnlocks.app has no discoverable public API.
  **Prediction markets** — Polymarket and Kalshi both fail DNS resolution
  from this specific development sandbox (confirmed not a general
  connectivity issue) — revisit from an environment that can reach them.
- **CoinGecko demo-tier rate-limit reconsideration** — a real demo key
  raises the per-asset historical endpoint from ~5 rapid calls before a
  429 to 40+ with no rate-limiting observed. Whether this is worth
  reconsidering for any other currently `UNAVAILABLE`/rate-limited use
  case is an open decision, not acted on (the burst-limit finding is
  confirmed; the demo tier's real monthly cap was never tested live, to
  avoid burning quota for no benefit).

## Other tracked (cosmetic / low-severity, real but minor)

- **`POST /holdings` echoes `id: null`** in its response instead of the
  database-assigned id (the handler returns the locally-constructed record
  rather than re-querying after insert). `GET /holdings`/`/holdings/history`
  correctly return the real id. Cosmetic only.
- **`/calibration/summary` does one repository call per resolved
  decision** (a real N+1 pattern) — originally measured at ~8.6 real
  seconds over HTTP at 179 rows; **re-measured 2026-09-27 with a direct
  in-process call (not over HTTP, so not directly comparable) at the
  current 323 resolved rows: ~29 seconds** — history has grown ~1.8x
  since the original measurement but latency grew notably more than
  proportionally. Still usable at this scale, but the "first thing to
  fix if history grows materially" condition is closer to being met than
  it was — worth re-prioritizing a proper join/batch method sooner rather
  than later.
- **`market_snapshots` (1725 rows, re-checked 2026-09-27) and
  `evidence_observations` (3714 rows, re-checked 2026-09-27) are already
  past Supabase's real ~1000-row-per-request cap** (see
  [`history.md`](history.md)'s Phase 5m section for the fix applied to
  `llm_analyses`/`judge_decisions`) — not fixed here, since neither has a
  reachable "fetch everything" API endpoint today (every real consumer is
  per-asset/date-scoped, not a "get all history" read), so they aren't
  currently exhibiting silent truncation. Apply the same
  `_fetch_all_paginated` fix if a genuine "get everything" consumer is
  ever added for either.
