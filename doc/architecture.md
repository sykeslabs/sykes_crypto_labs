# Architecture

What the system looks like today. For *why* it got this way, see
[`history.md`](history.md) (build log) and [`decisions.md`](decisions.md)
(ADR-style rationale). For what's still open or deliberately deferred, see
[`todo.md`](todo.md). For the script catalog, see [`scripts.md`](scripts.md).

## Data flow (built and live today)

```
EXTERNAL SOURCES
  CoinGecko · CoinMarketCap · Coinbase · Binance (spot+futures) · Deribit
  Etherscan · DefiLlama · CFTC (COT) · Upbit · FRED · SEC EDGAR · congress.gov
  Nansen · GitHub · OpenRouter (Claude/OpenAI/Gemini) · RSS news feeds
        │
        ▼
PROVIDER / INGESTION LAYER  (app/market_data, app/news)
  one client module per source; normalizes into the shared evidence-
  provenance shape; never fabricates missing data -> records OK /
  UNAVAILABLE / NOT_IMPLEMENTED in `signal_sources`, never silently omits
        │
        ▼
EVIDENCE STORE  (Supabase / Postgres, 20 migrations, see below)
        │
        ▼
SCREENING & FACTOR SCORING  (app/market_data/screening_service.py, regime.py,
  factors.py, anomaly.py) -- deterministic, zero LLM cost. Ranks the open
  universe, classifies one shared market regime per run, computes
  composite_factor_score, flags anomalies, auto-promotes new candidates
  into `assets` (real display name fixed 2026-09-16, see history.md). A
  held asset that falls outside the top-N-by-market-cap fetch is retrieved
  directly by coingecko_id (fixed 2026-09-16, see history.md) so the
  held-symbol Judge-coverage override always has a row to act on
        │
        ▼
MULTI-MODEL ASSESSMENT  (app/llm/assessment_*.py) -- Claude + OpenAI +
  Gemini via OpenRouter, one call per model per candidate, computes
  model_agreement (real, deterministic majority-vote fraction)
        │
        ▼
ADVERSARIAL RESEARCH  (app/llm/adversarial_*.py) -- bull -> bear -> scenario
  cycle per candidate, plus macro evidence matrix (app/market_data/
  macro_service.py, fred.py, sec_edgar.py, congress_gov.py, upbit.py)
        │
        ▼
JUDGE  (app/judge/) -- one structured OpenRouter call per asset, synthesizes
  every evidence layer above into BUY/SELL/HOLD/WATCH/NO_TRADE. Given TWO
  distinct allocation numbers per asset (Phase 5d, 2026-09-15):
  actual_allocation (real holdings, ground truth) and previous_system_target
  (the system's own last recommended target) -- see context.py's
  AssetJudgeContext and render_prompt(). Production Judge decisions are
  idempotent per asset and UTC decision day (Phase 5i, 2026-09-16): before
  the LLM call, any candidate that already has a live (is_backfilled=false)
  decision for today is excluded and logged, never re-decided -- a second
  same-day attempt for an asset never creates a new judge_decisions/
  decision_outcomes row and never alters portfolio state. Scoped to live
  decisions only; replay/backfilled decisions (is_backfilled=true) are
  structurally unaffected, since 3e.1's replay never calls JudgeService at
  all (see app/benchmarks/replay.py's own separate persistence path)
        │
        ▼
RISK ENGINE  (app/risk/engine.py) -- deterministic Python, no LLM.
  size_one() computes final_allocation from current_allocation (real
  holdings) + previous_system_target (system's own last target), applying
  MAX_SINGLE_ASSET_ALLOCATION / MAX_NEW_POSITION_SIZE / MIN_*_CONFIDENCE
  gates and volatility/agreement scalars. MAX_SINGLE_ASSET_ALLOCATION
  constrains the DESIRED TARGET final_allocation expresses in every branch,
  including WATCH/NO_TRADE (fixed 2026-09-16, see history.md's Phase 5g
  section) -- WATCH/NO_TRADE cannot re-adopt real holdings sitting above
  the cap as a compliant-looking target for free. This never modifies real
  holdings (current_allocation) itself, and actual holdings can remain
  above the cap for a real stretch of time regardless, since turnover/
  execution constraints still govern how fast the portfolio actually moves
  toward that target. remaining_turnover_budget() and
  _strategy_turnover_delta() measure weekly turnover against
  previous_system_target, not real holdings (Phase 5c fix, 2026-09-14 --
  see history.md; real backtest evidence: 318.30% -> 104.18% apparent
  turnover). _strategy_turnover_delta() treats WATCH/NO_TRADE as zero
  strategy turnover, and that exemption is now persisted, not just applied
  in memory (Phase 5k fix, 2026-09-17, see history.md): every
  `portfolio_allocation_changes` row carries `change_reason`
  ("strategy"/"risk_control"), set from the already-gated
  `SizedDecision.decision` at Portfolio Construction time -- never
  reconstructed later from `judge_decisions.decision` (the raw, pre-
  confidence-gate value). `get_turnover_since()` sums `change_reason=
  "strategy"` rows only.

  **A1 vs A2 (Phase 5l, 2026-09-17 -- see decisions.md/history.md)**:
  two independent, mutually-exclusive conditions both map to the same
  `change_reason="risk_control"` exemption. **A1** = `decision in
  ("WATCH", "NO_TRADE")` -- these are never sizing decisions at all
  (Phase 5g). **A2** = `is_cap_compliance_correction()` (module-level
  function, `app/risk/engine.py`) -- a BUY/HOLD/SELL decision (never
  WATCH/NO_TRADE, that's already A1) whose `final_allocation` brings a
  genuinely oversized `previous_system_target` (above
  MAX_SINGLE_ASSET_ALLOCATION, with TURNOVER_EPSILON tolerance -- no new
  epsilon constant) down to, or below, the cap. Real motivating incident:
  Risk Engine repeatedly computed a fully cap-compliant HOLD target for
  BTC (0.15, real live history 2026-09-16/09-17) only for the ordinary
  turnover-cap mechanism to block or scale it back above cap every time,
  with no guaranteed convergence -- see decisions.md's A2 entry for the
  full reasoning (in short: MAX_WEEKLY_TURNOVER is documented, in
  settings.py, as a circuit breaker against discretionary STRATEGY
  CHURN -- a forced reduction toward an already-enforced hard cap is not
  churn). SELL-to-zero from an oversized target is deliberately included
  (no distinct "exit" category exists anywhere in this project). A2
  operates on `previous_system_target`/`final_allocation` only -- it never
  reads `current_allocation` (real holdings), so it cannot be, and does
  not attempt to be, an execution-engine fix for a separately-oversized
  real holding whose target is already compliant (e.g. SOL, whose target
  has been 0.0 since 2026-09-15 while real holdings independently sit
  above the cap -- an unrelated, already-documented no-execution-engine
  gap). Both `PortfolioConstructionService` and `RiskEngine` call the
  exact same `is_cap_compliance_correction()` function, so the two layers
  cannot silently classify a decision differently (regression-tested in
  `tests/test_portfolio.py`). No new `change_reason` value, no new
  turnover budget, no ordering/priority mechanism between simultaneously-
  qualifying assets -- each is independently exempt.
  app/risk/correlation.py flags concentrated/co-moving exposure;
  app/risk/stress_test.py runs two deterministic drawdown scenarios
  (known gap: reads target allocation, not real holdings -- see todo.md)
        │
        ▼
PORTFOLIO CONSTRUCTION  (app/portfolio/construction.py, holdings.py) --
  turns Risk-Engine output into concrete decisions against real
  `holdings_ledger`/`holdings_transactions` ground truth (Phase 5a/5b).
  Every real change to the system's own target is recorded to
  `portfolio_allocation_changes` (previous_allocation/new_allocation =
  target, actual_allocation_before = real holdings at that moment, audit
  only, change_reason = strategy/risk_control per Phase 5k) -- surfaced on
  the dashboard since 2026-09-16 (Phase 5e)
        │
        ▼
DECISION-OUTCOME LEDGER  (app/benchmarks/evaluation_service.py,
  triple_barrier.py) -- backfills realized returns via triple-barrier
  (HIT_TARGET/HIT_STOP/TIMED_OUT), tags regime/confidence/is_backfilled
        │
        ▼
STATISTICAL VALIDATION  (app/benchmarks/statistical_validation.py,
  reasoning_audit.py, baseline_comparison.py) -- Deflated Sharpe/PBO, Brier/
  reliability, held-out-window reporting, Judge reasoning audits. Reports
  only -- never alters upstream logic. Same-UTC-day duplicate LIVE Judge
  decisions (is_backfilled=false, >1 per asset/day -- B1 prevents new ones,
  see Phase 5i) are excluded ENTIRELY (no canonical row chosen) from every
  directional/calibration statistic here and in
  scripts/run_composite_weights_validation.py and
  scripts/calibration_baseline.py's --source live branch
  (app/database/repository.py's compute_duplicate_group_decision_ids, B2,
  Phase 5j) -- a pure, query-level classification, computed from
  judge_decisions alone (never outcome resolution status), so it's stable
  as outcomes resolve. Raw judge_decisions/decision_outcomes rows,
  portfolio state, and LLM cost accounting are all untouched by this;
  resolved/unresolved audit counts remain a deliberately separate,
  unfiltered statistic (see doc/decisions.md)
        │
        ▼
ADAPTIVE WEIGHTING  (app/benchmarks/evidence_value.py) -- learned evidence-
  value ranking, diagnostic only, gated on n>=50 resolved decisions
  (real n has stayed 16-42 -- see todo.md, not yet actionable)

Cross-cutting: FastAPI (app/api/) reads the Evidence Store for the
dashboard (app/api/static/dashboard.html); CostGuard (app/llm/cost.py)
checks a hard spend cap before every LLM call from any stage.
```

### Current dashboard sections (`app/api/static/dashboard.html`)

TODO · Screened tokens · Market regime · Judge Decisions · Calibration
summary · LLM prompts & answers · **Portfolio** (merged 2026-09-16: two
donuts side by side — AI target left, real holdings right, mirrored
legends — an "AI Portfolio" table and a "My Portfolio" table sharing
column widths with no-wrap+horizontal-scroll, a turnover-cap banner, a
holdings entry form + collapsible full transaction history, a Comparison
table (My vs AI %/USD + deltas), and a collapsible recommended-allocation-
history table backed by `portfolio_allocation_changes`) · Recent news ·
Cost / spend · Signal sources.

## What's deliberately not built (see `todo.md`/`decisions.md` for full reasoning)

Live-queried 2026-09-16: of 29 rows in `signal_sources`, 18 are `OK`, 2 are
`UNAVAILABLE`, 9 are `NOT_IMPLEMENTED`. Real reasons, not silent gaps:

- **Paid-tier deferrals** (client built or a working key exists, not
  subscribed/upgraded): Glassnode/CryptoQuant on-chain valuation metrics,
  CoinGlass liquidation heatmap, LunarCrush social sentiment (a real paid
  key returns HTTP 402 on every endpoint — Individual tier or higher
  required), xAI/Grok as a 4th assessment model.
- **Genuinely `NOT_IMPLEMENTED`** (no reachable/reliable source found):
  custody/OTC desk flow, spot ETF flows (Farside has no API, SoSoValue
  needs an unavailable login), token unlock/vesting schedules (Messari
  needs a key, TokenUnlocks.app has no public API), prediction markets
  (Polymarket/Kalshi fail DNS from this sandbox).
- **Gated on sample size, not infeasibility**: options gamma exposure,
  exchange counterparty risk, retail-demand proxies, DeFi lending/staking/
  depeg monitoring — all wait on the evidence-value ranking (or a Judge-
  reasoning-audit finding) naming a specific gap, which itself is gated on
  n>=50 resolved decisions (currently 16-42).
- **Explicitly decided against**: a paper-trading/live-exchange execution
  agent (Phase 6) — on hold, no timeline; scheduling the pipeline on a
  timer — the real bottleneck is decision-resolution time, not run
  frequency.

## Database

20 migrations (`migrations/0001`-`0020`), applied in order via the
Supabase SQL Editor (see [`operations.md`](operations.md) — the
`psycopg2`/`apply_migration.py` path is currently broken in this
environment). Broad eras: `0001`-`0002` core schema + news/LLM;
`0003`-`0005` universe provenance, screening/regime, derivatives/on-chain
(Phase 3a-3c); `0006`-`0012` multi-model assessment, portfolio/decision
state, adversarial research, reasoning audits, evidence-value reports
(Phase 3d-3h); `0013` execution-cost backfill (Phase 4); `0014`-`0015`
real holdings ledger + transactions (Phase 5a-5b); `0016`-`0020` dashboard/
accuracy cleanup and the turnover-baseline redesign (Phase 5c, see
history.md).

## Project layout

```
app/
  api/           FastAPI app (main.py), auth.py (X-API-Key gate), routers/
                 (assessments, calibration, cost, holdings, judge, news,
                 portfolio, screening, signal_sources), static/dashboard.html
  benchmarks/    replay/backfill, evaluation_service, triple_barrier,
                 statistical_validation, reasoning_audit, evidence_value,
                 baseline_comparison, historical_factors
  config/        Settings (env-driven)
  database/      Supabase client + repositories, evidence_provenance.py
  judge/         context.py (AssetJudgeContext, build_judge_context),
                 service.py, provider.py, schemas.py, decisions.py
  llm/           OpenRouter client, structured output, cost guard,
                 assessment_* (3d), adversarial_* (3f)
  market_data/   one client module per external source (coingecko,
                 coinmarketcap, coinbase, binance, deribit, etherscan,
                 defillama, cftc, upbit, fred, sec_edgar, congress_gov,
                 nansen, github_activity, glassnode), screening_service,
                 regime, factors, anomaly, macro_service
  news/          RSS collection, relevance matching, dedup
  portfolio/     construction.py, holdings.py, schemas.py
  risk/          engine.py (RiskEngine, SizedDecision), correlation.py,
                 stress_test.py
  trading/       fill_simulator.py (paper-trading fills; no live exchange —
                 Phase 6 execution agent not built)
  main.py        Entrypoint (python -m app.main [flags] — see operations.md)
tests/
migrations/      SQL schema, 0001-0020
scripts/         see scripts.md
```
