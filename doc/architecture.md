# Architecture

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                              EXTERNAL DATA SOURCES                              │
└────────────────────────────────────────────────────────────────────────────────┘
        │              │              │              │              │
        ▼              ▼              ▼              ▼              ▼
   CoinGecko      CoinMarketCap   Coinbase        Binance        Deribit
   (Phase 1)      (3b)            (3b)            (3b, 3c)       (3c)
   aggregated     aggregated      exchange-       exchange-      options IV,
   price/mcap     price/mcap      native trade    native funding put/call skew,
                                  price, spread    rate, open      open interest
                                                    interest, price
        │              │              │              │              │
        │              │              │              │              ▼
        │              │              │              │         ┌─────────┐
        │              │              │              │         │  xAI /  │
        │              │              │              │         │  Grok   │──┐
        │              │              │              │         └─────────┘  │
        │              │              │              │      (3d model +     │
        │              │              │              │       3f PlanB/X)    │
        ▼              ▼                                                     │
   Etherscan      DefiLlama       RSS News        CoinAnk*      CoinGlass*   │
   (3c)           (3c)            (Phase 2)       (3f)          (3f)         │
   on-chain flow, TVL/DeFi        CoinDesk,       long/short    liquidation   │
   stablecoin     rotation,       CoinTelegraph,  ratio         heatmap       │
   supply/        stablecoin      Decrypt                                     │
   velocity/      supply                                                      │
   reserve proxy                                                              │
                                                        CryptoBubbles* (3f)    │
                                                        market-cap bubbles     │
                                                                               │
   Farside/SoSoValue (3c)               Polymarket/Kalshi (3c)                │
   spot BTC/ETH ETF net flows           prediction-market implied probabilities│
                                                                               │
   (* = fragile/unofficial, feasibility-gated in 3f)                         │
        │              │              │              │              │        │
        └──────┬───────┴──────┬───────┴──────┬───────┴──────┬───────┴────────┘
               ▼               ▼              ▼              ▼
        ┌──────────────────────────────────────────────────────────┐
        │              PROVIDER / INGESTION LAYER                  │
        │   app/market_data · app/news · per-source 3c/3f modules  │
        │   - normalizes each response to the evidence-provenance  │
        │     shape (source, scope, timestamps, decay_half_life)   │
        │   - never fabricates missing data → UNAVAILABLE/UNKNOWN  │
        └───────────────────────────┬────────────────────────────┘
                                     ▼
        ┌──────────────────────────────────────────────────────────┐
        │             EVIDENCE STORE — Supabase / Postgres          │
        ├──────────────────────────────────────────────────────────┤
        │ assets · market_snapshots · news · signal_sources ·        │
        │ model_market_assessments · market_regime_snapshots ·       │
        │ decision_outcomes · prompt_templates · llm_analyses ·      │
        │ calibration_runs                                            │
        │ (JSONB columns: payload, key_drivers, source_assessment)   │
        └───────────────────────────┬────────────────────────────┘
                                     ▼
        ┌──────────────────────────────────────────────────────────┐
        │      SCREENING, REGIME & FACTOR SCORING (3b)                │
        │      pure Python, zero LLM cost — market-regime            │
        │      classifier + composite_factor_score + anomaly flag    │
        └───────────────────────────┬────────────────────────────┘
                                     ▼
        ┌──────────────────────────────────────────────────────────┐
        │              MULTI-MODEL ASSESSMENT (3d)                   │
        └───────────────────────────┬────────────────────────────┘
                                     │
                    ┌────────────────┼────────────────┬──────────────┐
                    ▼                ▼                ▼              ▼
              OpenRouter        OpenRouter        OpenRouter    OpenRouter
              → Claude          → GPT             → Gemini      → Grok (opt.)
                    │                │                │              │
                    └────────────────┴────────────────┴──────────────┘
                                     │
                        ┌────────────┴────────────┐
                        ▼                          ▼
                   CostGuard                  Langfuse (optional)
                   (hard spend cap,            trace prompt/response/
                   checked pre-call)           cost/latency, versioned
                                                against prompt_templates
                                     │
                                     ▼
        ┌──────────────────────────────────────────────────────────┐
        │            ADVERSARIAL RESEARCH (3f)                        │
        └───────────────────────────┬────────────────────────────┘
                    │                │                │
                    ▼                ▼                ▼
              Bull research    Bear research    Scenario modeling
              (OpenRouter LLM  (OpenRouter LLM  (OpenRouter LLM,
              call, CostGuard) rebuts bull,     bull/base/bear per
                                CostGuard)       candidate, CostGuard)
                    │                │                │
                    └────────────────┼────────────────┘
                                     ▼
                              Macro evidence matrix
                              (ADP, CPI, PCE, DXY, yields —
                              manual/API feed, no LLM cost to collect)
                                     │
                                     ▼
        ┌──────────────────────────────────────────────────────────┐
        │      JUDGE (3e) — single structured OpenRouter call        │
        │      wrapped in deterministic weighing logic;              │
        │      gated by CostGuard, versioned via prompt_templates    │
        └───────────────────────────┬────────────────────────────┘
                                     ▼
        ┌──────────────────────────────────────────────────────────┐
        │      RISK ENGINE (3e) — deterministic Python, no LLM       │
        ├──────────────────────────────────────────────────────────┤
        │ env-configured caps: MAX_SINGLE_ASSET_ALLOCATION,           │
        │ MAX_NEW_POSITION_SIZE, MAX_WEEKLY_TURNOVER,                 │
        │ MIN_BUY/REBALANCE/SELL_CONFIDENCE                           │
        │        │                              │                    │
        │        ▼                              ▼                    │
        │  volatility-adjusted sizing     correlation-matrix check    │
        │  (inverse-vol / capped Kelly,   (flags concentrated,        │
        │  from 3b screening factors)     co-moving exposure)         │
        └───────────────────────────┬────────────────────────────┘
                                     ▼
        ┌──────────────────────────────────────────────────────────┐
        │       PORTFOLIO CONSTRUCTION (3e) — deterministic Python    │
        │       replacement logic vs. risk_adjusted_alpha threshold   │
        └───────────────────────────┬────────────────────────────┘
                                     ▼
        ┌──────────────────────────────────────────────────────────┐
        │   DECISION-OUTCOME LEDGER (3e/3f)                            │
        │   decision_outcomes table + scheduled/manual evaluation      │
        │   step, backfilled from market_snapshots (triple-barrier-    │
        │   style HIT_TARGET/HIT_STOP/TIMED_OUT); rows tagged with      │
        │   regime_at_decision, judge_confidence, in_holdout_window     │
        └───────────────────────────┬────────────────────────────┘
                                     ▼
        ┌──────────────────────────────────────────────────────────┐
        │   STATISTICAL VALIDATION (3g) — the accuracy gate            │
        ├──────────────────────────────────────────────────────────┤
        │ Deflated Sharpe / PBO across every 3d–3f prompt & logic      │
        │ iteration · Brier score + reliability diagrams by regime ·   │
        │ held-out-window results reported in isolation · Judge        │
        │ reasoning audit (OpenRouter LLM, CostGuard-gated) ·           │
        │ go/no-go statement for Phase 4, grounded in the above         │
        │ (reports/recommends only — does not alter upstream logic)    │
        └───────────────────────────┬────────────────────────────┘
                                     ▼
        ┌──────────────────────────────────────────────────────────┐
        │   ADAPTIVE WEIGHTING & STRESS TESTING (3h) — diagnostic only │
        ├──────────────────────────────────────────────────────────┤
        │ learned evidence-value ranking, incl. rolling-window/        │
        │ regime-sliced drift check (checked vs. Judge's implicit      │
        │ weighting, never fed back in) · portfolio stress test        │
        │ (historical/scenario drawdown, VaR/CVaR, extends Risk Engine)│
        │ (reports/flags only — no auto-adjustment without confirmation)│
        └───────────────────────────┬────────────────────────────┘
                                     ▼
        ┌──────────────────────────────────────────────────────────┐
        │   ENTITY-FLOW, CUSTODY/OTC & NETWORK FUNDAMENTALS (3i)       │
        ├──────────────────────────────────────────────────────────┤
        │ Nansen/Arkham entity-flow intelligence · custody/OTC desk    │
        │ balance tracking · active addresses/fees/dev activity ·      │
        │ wired into the Judge (3e) as new labeled inputs, same        │
        │ extend-the-input-set pattern 3f used · zero new LLM cost     │
        └───────────────────────────┬────────────────────────────┘
                                     ▼
        ┌──────────────────────────────────────────────────────────┐
        │   PAPER TRADING EXECUTION (Phase 4)                          │
        │   simulated fills, fees, slippage — no live exchange         │
        └───────────────────────────┬────────────────────────────┘
                                     ▼
        ┌──────────────────────────────────────────────────────────┐
        │   EXCHANGE EXECUTION AGENT (Phase 6, testnet only)           │
        ├──────────────────────────────────────────────────────────┤
        │   LangChain/LangGraph agent                                  │
        │        │                                                     │
        │        ▼                                                     │
        │   allow-listed tools: place_order · cancel_order ·            │
        │   check_balance  →  Testnet/Sandbox exchange API              │
        │   (Risk Engine re-checked at execution time)                  │
        └──────────────────────────────────────────────────────────┘

  Cross-cutting, reads from the Evidence Store (does not write decisions):
     FastAPI (Phase 5) ── read/query API ──▶ Dashboard (Phase 5)
```

**Additional 3b/3c/3f/3g/3h/3i evidence sources and derived analytics not
redrawn into the boxes above** (same ingestion layer, same Evidence Store,
added after the diagram was first drawn — see "Technology stack decisions"
for the rationale behind each):
- **3b, derived (no new external source):** BTC dominance and an
  altcoin-season/breadth index, and BTC's halving-cycle position (days
  since/until the nearest halving), all computed from market/block data
  already collected, as additional axes on the market-regime snapshot.
- **3c, official:** Binance/Deribit dated-futures term structure (basis
  curve, alongside funding rate and OI, now also expressed as an
  annualized carry yield), the CFTC's Commitment of Traders report for CME
  BTC/ETH futures positioning, Glassnode/CryptoQuant on-chain
  valuation-cycle metrics (MVRV/SOPR/NUPL, LTH/STH cohorts) and
  BTC-specific miner metrics (hash rate, difficulty, reserves), Messari/
  TokenUnlocks token unlock & vesting schedules, and the derived
  volatility risk premium (Deribit implied volatility minus 3b's
  realized-volatility factor).
- **3f, official-but-extraction-fragile or feasibility-gated:** a
  forward-looking scheduled macro-event calendar (FOMC/CPI/PCE/NFP dates,
  official-source, low-risk); FRED-based
  global liquidity proxies and cross-asset correlation tracking (official,
  low-risk access); SEC EDGAR / congress.gov-based regulatory event
  calendar (official access, unverified per-asset extraction reliability);
  Santiment/LunarCrush-style aggregate social/narrative sentiment; CoinAnk;
  CoinGlass; CryptoBubbles; PlanB/X; and a regional exchange price premium
  (e.g. a Kimchi-premium-style Korean-venue gap), grouped here because
  reliable, ToS-compliant access to the relevant regional exchange is
  unverified going in.
- **3g, methodology check (no new evidence):** a purged/embargoed
  walk-forward audit alongside the existing point-in-time audit, checking
  whether the held-out window (and any rolling/regime-sliced split) has an
  adequate buffer against leakage from autocorrelated evidence — a finding,
  not a new signal source.
- **3h, diagnostic-only:** a learned evidence-value ranking (checked
  against, never fed back into, the live pipeline) — including a
  rolling-window/regime-sliced variant that checks whether a source's
  value has drifted over time rather than only its full-history average —
  and a portfolio stress-test module extending the Risk Engine.
- **3i, official/paid-tier, evidence-collection:** Nansen/Arkham-class
  wallet-entity-clustering and "smart money" flow intelligence, known
  custody/OTC-desk address balance tracking, and network usage (active
  addresses, fees) plus developer-activity (commit velocity) fundamentals
  — wired into the Judge as new labeled inputs, the same pattern 3f used.
- **3j, gated/optional (not scheduled by default):** options gamma
  exposure/dealer positioning, exchange counterparty/solvency risk
  (monitoring-only), and retail-demand proxies — implemented only if 3h's
  evidence-value ranking surfaces a specific named gap.
- **3k, gated/optional (not scheduled by default):** DeFi lending/borrowing
  rates, staking yield/validator queue depth (PoS assets only), and
  stablecoin depeg-risk monitoring (monitoring-only) — same gating
  discipline as 3j. Order-flow imbalance/LOB microstructure was considered
  for this list and deliberately excluded; see "Technology stack
  decisions."

### Component purposes

| Component | Introduced | Purpose |
|---|---|---|
| **Provider/ingestion layer** (`app/market_data`, `app/news`, future per-source modules) | Phase 1–3i | Talks to each external API/feed, normalizes its response into the shared evidence-provenance shape, and tags freshness/status — the only layer allowed to touch a raw external API. |
| **Evidence Store** (Supabase/Postgres) | Phase 1 | Single source of truth for every observation, model output, and decision. Relational, so backtesting and the decision-outcome ledger can join across tables by asset/time; JSONB columns give document-like flexibility for nested, source-specific fields without needing a second database. |
| **Screening, regime & factor scoring** (3b) | 3b | Deterministic, no-LLM factor computation that ranks/filters the open asset universe into candidates, classifies one shared market regime per run so every downstream stage sees the same label instead of inferring its own, combines the factors into a `composite_factor_score` the Judge can weigh as an independent, purely quantitative check against LLM narrative evidence, and flags anomalous volume/price behavior before an asset can surface as a candidate. |
| **Multi-model assessment** (`app/llm`, 3d) | Phase 2 / 3d | Sends each candidate's evidence to multiple independent LLMs (Claude, GPT, Gemini, optionally Grok) via OpenRouter, validates strict JSON output, and persists each model's standalone view plus a computed `model_agreement` — evidence, not a decision. |
| **Adversarial research** (3f) | 3f | Generates an explicitly opposing bull case and bear case per serious candidate, plus scenario modeling and a macro evidence matrix — additional evidence layers for the Judge, not decisions themselves. |
| **Judge** (`app/judge`, 3e) | 3e | Synthesizes every evidence layer above into one structured recommendation per asset, with confidence explicitly decoupled from model/source agreement, and a `NO_TRADE` outcome always available. |
| **Risk Engine** (`app/risk`, 3e) | 3e | Deterministic, non-negotiable position-sizing and exposure limits (volatility-adjusted sizing, correlation-concentration checks, hard caps) that the Judge's output cannot override. |
| **Portfolio Construction** (`app/portfolio`, 3e) | 3e | Turns Risk-Engine-adjusted Judge output plus current holdings/watchlist into concrete increase/hold/reduce/remove/initiate decisions, never forcing full capital deployment. |
| **Decision-outcome ledger** (3e/3f) | 3e | Records every decision with a resolution horizon and backfills realized returns, giving the system a continuously-updated, ground-truth accuracy measure instead of a one-off backtest. Tags every row with the market regime and Judge confidence in effect at decision time, and marks whether it falls inside the held-out window, so later accuracy claims can be sliced honestly rather than only reported in aggregate. |
| **Statistical validation** (`app/benchmarks` or a dedicated module, 3g) | 3g | The layer that decides whether an accuracy claim is real: Deflated Sharpe Ratio / probability-of-backtest-overfitting correction across every prompt/logic iteration actually tried, full Brier/reliability calibration reporting by regime, an isolated held-out-window result, and a periodic audit of whether the Judge's stated reasoning follows from its own cited evidence. Produces findings and recommendations only — it does not modify upstream evidence collection or decision logic itself. |
| **Adaptive weighting & stress testing** (3h) | 3h | Three diagnostic-only additions closing gaps identified against professional practice: a learned, sample-size-honest evidence-value ranking checked against the Judge's implicit weighting (including a rolling-window/regime-sliced drift variant, never fed back into the live pipeline), and a deterministic portfolio stress test (historical/scenario drawdown, VaR/CVaR-style estimate) extending the Risk Engine's existing sizing/correlation checks. Reports and flags only — same non-auto-adjusting standing as 3g. |
| **Entity-flow, custody/OTC & network fundamentals** (3i) | 3i | Three further evidence sources from the same gap-analysis as 3h: wallet-entity-clustering/"smart money" flow intelligence, custody/OTC desk balance tracking, and network usage/developer-activity fundamentals. Unlike 3h, this is new evidence-collection work wired into the Judge's existing input set (3e), not a diagnostic-only tool. |
| **CostGuard** (`app/llm/cost.py`) | Phase 2 | Cross-cutting spend cap checked before every LLM call from any stage; skips (not crashes) once a cap is hit. |
| **Langfuse (optional)** | 3d onward | Cross-cutting, additive tracing of LLM calls (prompt, response, cost, latency) for debugging and comparing prompt versions from `prompt_templates` against real outcomes. Never a dependency of the decision pipeline — Supabase remains authoritative. |
| **Paper Trading Execution** (`app/trading`) | Phase 4 | Simulates fills for Portfolio Construction's target changes without touching any real exchange. |
| **FastAPI + Dashboard** | Phase 5 | Read/query API over the Evidence Store (candidates, assessments, decisions, portfolio state, cost reports) for a UI; Pydantic-native, so it reuses the same schemas already defined for Phase 2/3 rather than duplicating them. |
| **Exchange Execution Agent** (LangChain/LangGraph) | Phase 6 | The only agentic component in the system. Given Portfolio Construction's already-approved target changes (not open-ended instructions) and a small, explicit, allow-listed toolset (place order, cancel order, check balance) against a **testnet** exchange API. Risk Engine constraints are re-checked at execution time; live trading remains gated behind a separate, explicit safety review per the project's development methodology. |


## Project layout

```
app/
  config/        Settings (env-driven)
  database/      Supabase client + repositories (assets, market_snapshots, news, llm_analyses, asset_status_history, signal_sources, screened_universe, market_regime_snapshots, evidence_observations); evidence_provenance.py — shared provenance shape, decay-half-life reference, "value as known at time T" helper (3a)
  market_data/   CoinGecko client, normalization, collection service; extended in 3b with CoinMarketCap/Coinbase/Binance, screening/regime classification (incl. BTC dominance/altcoin-season index and halving-cycle position), composite factor score, and anomaly flag; extended in 3c with Binance-futures/Deribit/CFTC/DefiLlama providers (funding rate, open interest, term structure + annualized carry yield, options IV/put-call, VRP, CME COT, protocol TVL, stablecoin supply growth), plus optional Etherscan (large-transfer proxy) and Glassnode (on-chain valuation/miner metrics, built but not subscribed to — see Phase 3c decisions); ETF flows, prediction markets, token unlocks, and stablecoin velocity/exchange-reserve tracking investigated in 3c and confirmed NOT_IMPLEMENTED (no accessible free API found — see Phase 3c); extended in 3f with a scheduled macro-event calendar, FRED-based global-liquidity/cross-asset-correlation, regulatory-calendar, and regional-exchange-premium providers; extended in 3i with entity-flow-intelligence, custody/OTC-flow, and network-usage/developer-activity providers; optionally extended in 3j (gated — see 3j) with options-gamma-exposure, exchange-counterparty-risk, and retail-demand-proxy providers; optionally extended in 3k (gated — see 3k) with DeFi-lending-rate, staking-yield/validator-queue, and stablecoin-depeg-risk providers
  news/          RSS collection, relevance matching, dedup (Phase 2)
  llm/           OpenRouter integration, structured output, cost guard (Phase 2); cost.py extended in 3a with COST_TRACKED_TABLES/CostLedgerRepository (multi-table cost summing, zero behavior change); extended in 3d with the current-market-assessment stage (optional Grok, optional Langfuse tracing)
  judge/         decisions.py — DecisionValue placeholder (BUY/HOLD/SELL/WATCH/NO_TRADE), 3a; Phase 3e — deterministic decision synthesis, persisted to `judge_decisions` (schema reserved in 3a); input set extended in 3f and 3i without redesign; uncertainty-aware sizing input (model/source agreement) added 3e
  portfolio/     Phase 3e — portfolio construction
  risk/          Phase 3e — deterministic risk engine, incl. uncertainty-aware position scaling; extended in 3h with a
                 deterministic portfolio tail-risk stress test
  trading/       Phase 4 — order-book-depth-aware, fee-aware paper-fill simulation (see doc/prompts/PHASE4_PROMPT.md); Phase 6 — testnet execution agent (LangChain/LangGraph)
  benchmarks/    Phase 4 — performance tracking; decision-outcome calibration (3e/3f);
                 retroactive historical replay, backfilled decisions tagged
                 `is_backfilled` and reported separately from the live
                 baseline (3e.1, optional);
                 statistical validation — Deflated Sharpe/PBO, Brier/reliability,
                 held-out-window reporting, point-in-time and purged/embargoed
                 walk-forward audits, Judge reasoning audit (3g); adaptive
                 evidence-value ranking incl. rolling-window/regime drift check,
                 diagnostic only (3h)
  api/           Phase 5 — FastAPI read/query layer (not yet created)
  main.py        Entrypoint (python -m app.main [--with-llm])
tests/
migrations/      SQL schema, applied manually or via scripts/apply_migration.py
scripts/
```

