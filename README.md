# Crypto AI Portfolio

Modular, auditable AI-driven crypto portfolio management system. **Paper trading only** —
no exchange credentials or live orders exist yet.

## Vision

The long-term goal is a full-fledged AI crypto research and advisory system: broad
market screening across an open universe (not a fixed coin list), multi-source
evidence collection (exchange-native market data, a deterministic BTC-
dominance/altcoin-season regime input, derivatives positioning — funding
rates, dated-futures term structure/basis with its annualized carry yield,
aggregate open interest, CME futures positioning via the CFTC's Commitment
of Traders report — options skew and the derived volatility risk premium,
on-chain/DeFi flows, on-chain valuation-cycle metrics (MVRV/SOPR/NUPL and
long-term/short-term holder cohorts), BTC-specific miner metrics (hash rate,
difficulty, reserves), liquidations, stablecoin supply and velocity, spot
ETF flows, prediction-market implied probabilities, scheduled token
unlock/vesting events, wallet-entity-clustering/"smart money" flow
intelligence, custody/OTC desk flow, network usage and developer-activity
fundamentals, news, macro (including global liquidity proxies and BTC's
rolling correlation to equities/gold/DXY), a dated regulatory/policy event
calendar, independent analysts, aggregate social/narrative sentiment, and a
regional exchange price premium), a deterministic market-regime
classification, a deterministic composite quant factor score computed
independently of any LLM, multi-model independent assessment (including,
optionally, xAI's Grok alongside Claude/GPT/Gemini), adversarial (bull/bear)
research, and a deterministic Judge + Risk Engine that turns all of this
into paper-only recommendations — sized with volatility/correlation
awareness and checked against a historical portfolio stress test, traced and
versioned via optional Langfuse instrumentation, tracked against realized
outcomes over time (including a learned, statistically-honest check on which
evidence sources actually earn their keep, and whether that value drifts by
regime over time), and including the ability to say "no trade" when evidence
is weak or contradictory. Further out, a read/query API (FastAPI) exposes
this to a dashboard, and — only once the recommendation pipeline is proven
out — a bounded, tool-restricted execution agent handles actual order
placement on a testnet exchange.

This is a deliberate, large expansion beyond the original Phase 1/2 scope. It
is being built **in verified sub-phases**, not as one monolithic phase,
because:
- several data sources have unknown/unofficial API availability and must be
  validated for real before any code assumes they exist — **official,
  documented sources are prioritized ahead of fragile/unofficial ones**,
- every new signal source is also a new API/LLM cost center, and costs must
  stay bounded by `CostGuard` at every step, not just at the end,
- a system that gives financial-style recommendations needs its accuracy to
  be *measurable and continuously tracked* (calibration against realized
  outcomes) from the start, not bolted on at the very end,
- the recommendation pipeline (Judge/Risk/Portfolio) is deliberately kept
  deterministic and non-agentic; agentic behavior is reserved for a later,
  clearly scoped execution layer where it's actually needed, not introduced
  wherever a task involves an LLM.

- ✅ **Phase 1 — Foundation**: project structure, configuration, Supabase schema
  (`assets`, `market_snapshots`), CoinGecko market-data collector. Complete and
  verified against a live Supabase project.
- ✅ **Phase 2 — Multi-model AI**: RSS news collection + relevance matching,
  OpenRouter integration (Claude, OpenAI, Gemini), structured/validated LLM
  output, cost tracking with daily/monthly caps. Complete and verified with
  live LLM calls against a real Supabase project.
- ⬜ **Phase 3 — Broad intelligence, discovery & judgment** (see
  `PHASE3A_PROMPT.md` through `PHASE3I_PROMPT.md`, one per sub-phase, plus
  the optional, gated `PHASE3J_PROMPT.md` and `PHASE3K_PROMPT.md` addenda),
  split into verified sub-phases:
  - ✅ **3a** (complete) — Candidate/universe status schema, evidence provenance + numeric
    freshness-decay convention (now with an explicit **point-in-time
    integrity** rule — revisable evidence fields are append-only, with an
    `is_revision_of` chain and a documented "value as known at time T"
    query convention, so later backtests can never accidentally read a
    since-revised value for a past decision), `signal_sources` registry, and
    schema groundwork for market-regime snapshots, a decision-outcome
    ledger, and prompt/template versioning (all populated in later
    sub-phases)
  - ✅ **3b** (complete) — CoinMarketCap + **Coinbase** + **Binance** exchange-native data,
    deterministic market screening, candidate discovery, a **deterministic
    market-regime classifier** computed once per run (now also tracking
    **BTC dominance and an altcoin-season/breadth index** as an orthogonal
    rotation-vs-risk-on/off axis, and BTC's **halving-cycle position** —
    days since/until the nearest halving — as a further, zero-marginal-cost
    deterministic axis reflecting the multi-year cycle-timing framing
    professional crypto research commonly uses), a **deterministic
    composite factor score** (a purely quantitative, non-LLM signal the
    Judge later weighs alongside narrative evidence rather than blends with
    it), and a basic screening-stage anomaly/wash-trading flag
  - ✅ **3c** (complete) — Official derivatives & on-chain sources: **Binance funding
    rates**, **Binance/Deribit dated-futures term structure/basis** (now
    also expressed as an **annualized basis/carry yield**),
    **Binance/Deribit aggregate open interest**, **CME futures positioning**
    via the CFTC's weekly **Commitment of Traders (COT)** report — a
    regulated-futures view of institutional positioning by trader category,
    distinct from both perpetual funding rate and spot ETF flows —
    **Deribit options** (implied volatility, put/call skew, and the derived
    **volatility risk premium** against 3b's realized-volatility factor),
    **Etherscan/DefiLlama** on-chain & DeFi TVL flows, **on-chain
    valuation-cycle metrics** (MVRV/MVRV Z-Score, SOPR, NUPL, LTH-MVRV/
    STH-MVRV cohort breakdowns, via Glassnode or CryptoQuant), **BTC miner
    metrics** (hash rate, difficulty, miner reserves and exchange flow, via
    the same on-chain analytics provider), **stablecoin supply and velocity
    / exchange reserve** flow as capital-rotation proxies distinct from
    protocol-level TVL, **spot BTC/ETH ETF net flows** (via Farside
    Investors / SoSoValue) as an institutional-capital proxy,
    **prediction-market implied probabilities** (Polymarket/Kalshi) for a
    curated set of relevant contracts, and **token unlock/vesting
    schedules** (via Messari or TokenUnlocks) as a known-in-advance calendar
    event distinct from every other inferred-from-current-data source here
    — all documented APIs (a couple may require a paid tier — a dollar
    cost, not an LLM cost), zero LLM cost
  - ✅ **3d** (complete) — Multi-model current market assessment (separate
    from `llm_analyses`), sharing one **market-regime snapshot** and one
    rendered evidence context (3b screening/regime, 3c derivatives/on-chain,
    Phase 2 news, 3a portfolio status) across every configured model per run,
    with **prompt-template versioning**, a **model-agreement** measure
    computed independently of any single model's confidence, and a data
    **sanity/bad-tick check** reusing 3b's anomaly detector. Kept to
    **Claude/OpenAI/Gemini** (Phase 2's existing three) rather than also
    adding a fourth model this round, to isolate this stage's cost/behavior
    change to the richer context alone — **Grok (xAI)** deferred to a later
    phase, addable via `OPENROUTER_ASSESSMENT_MODELS` once there's a 3-model
    baseline to compare it against. **Langfuse tracing skipped** for now
    (optional per `PHASE3D_PROMPT.md`; most useful once there's real call
    volume and multiple prompt versions to compare, from 3e onward)
  - ✅ **3e** (complete) — Deterministic Judge (weighing 3b's non-LLM
    `composite_factor_score` as a distinct input alongside 3c's derivatives/
    on-chain evidence, 3d's model assessments, and Phase 2's prior LLM
    analyses), Risk Engine (volatility-adjusted position sizing, now also
    **uncertainty-aware**: position size scales down when model/source
    agreement is weak, composed with the volatility adjustment rather than
    replacing it, plus a **correlation-concentration flag** — live-verified
    to genuinely trigger, e.g. BTC/SOL flagged at 0.93 correlation), Portfolio
    Construction (increase/hold/reduce/remove/initiate/hold-cash, plus a
    capacity-driven **replacement rule**), and a **continuous decision-outcome
    ledger** for ongoing calibration — each decision tagged with its market
    regime and Judge confidence, a **held-out decision window** reserved from
    this sub-phase's first live run (2026-09-05T17:07:49Z) onward, and a
    baseline calibration script against real Phase 1/2 data reporting **both
    hit-rate and calibration (Brier score)**, not directional accuracy alone
  - ✅ **3e.1** (complete, closed at 13/28 days) — Retroactive historical
    replay: re-runs 3e's pipeline against a past date range using only
    genuinely point-in-time-reconstructable evidence, so real calibration
    signal accumulates faster than waiting on live decisions to age. Closed
    at **13 of the intended 28 days** (2026-08-09 through 08-19, plus 2
    validation days) — cut short by the OpenRouter account's real balance
    running out mid-run, not a technical or design failure (see section
    below); resolved with a real `BACKFILL_BASELINE` calibration number
    (hit-rate 0.833, Brier 0.195 over 36 directional decisions) reported
    separately from the live forward-tracked baseline, never combined
  - ✅ **3f** (complete) — Adversarial bull → bear → scenario research cycle
    (bear demonstrably attacks the specific bull thesis, live-verified —
    see findings below), a macro matrix (CPI/PCE/claims/payrolls/yields/
    fed funds via FRED) with a **forward-looking scheduled macro-event
    calendar** (real CPI/PCE/NFP release dates — FOMC excluded, see
    decisions below), **global liquidity proxies** (M2/Fed balance sheet/
    reverse repo) and BTC's **rolling correlation to S&P 500/gold(via
    PAXG)/DXY**, the **Upbit regional exchange premium**, and a
    **regulatory event calendar** (SEC EDGAR + congress.gov, global/macro-
    scope). CryptoBubbles/CoinAnk confirmed genuinely inaccessible;
    CoinGlass/LunarCrush/PlanB(xAI) deliberately deferred (paid-tier/no-
    relationship decisions, same treatment as Glassnode in 3c); Santiment
    confirmed real but unusable for live reads (~30-day lag). Judge now
    consumes all of this (a new required `macro_sensitivity` per-asset
    reasoning field, live-verified to cite real numbers and never apply a
    blanket rule) plus 3f's bull/bear/scenarios (live-verified: the Judge's
    own `contradictory_evidence` directly quotes bear-case language
    verbatim). Recalibration attempted honestly — zero resolved decisions
    exist anywhere in the project yet (pre- or post-3f), reported as a real
    finding, not fabricated — and a live Judge-reasoning spot-check found
    the sampled theses genuinely follow from their own stated evidence
  - ✅ **3g** (complete) — Statistical validation of the Judge/Risk/Portfolio
    configuration's real track record. Honest trial count reconstructed
    (**1** real calibrated configuration — `judge_decision` v2, backfill-only;
    v1 was superseded before any resolved data ever used it). Deflated Sharpe
    Ratio computed on the 36 directional resolved backfilled decisions
    (Sharpe 1.82, DSR≈0.9998 at n_trials=1 — no multiple-comparisons
    deflation applies, correctly, since there was no genuine selection among
    alternatives); PBO **not computable** (needs ≥2 tried configurations).
    Full Brier/reliability report by confidence bucket and by model/source-
    agreement bucket; **by-regime breakdown blocked by a real persistence
    gap** (3e.1's replay computes a regime per simulated day but never
    persists it as a queryable row, so `regime_at_decision` is NULL for
    every one of the 109 resolved backfilled outcomes — same root cause
    later found to also block task 6's `composite_factor_score` comparison).
    Point-in-time audit: **CLEAN**, verified at the code level across every
    evidence pathway replay actually uses. Purged/embargo check: **gap
    absent** — the training/holdout boundary has zero (slightly negative)
    separation against a 45-day longest horizon, so 100% of the holdout
    sample sits within one resolution-horizon of the boundary; this is the
    primary reason no go/no-go claim can be made yet (see below), not merely
    small sample size. Held-out window: 50 live decisions, all
    `in_holdout_window=true`, **zero resolved** — insufficient data.
    Formalized Judge-reasoning audit (new `judge_reasoning_audits` table,
    8 real audited decisions, real cost **$0.026838** total): 1 of 8 showed
    a genuine unsupported claim (a SELL thesis that never addressed its own
    cited contradicting evidence). Source-disabling recommendations: **no
    source can currently be evaluated** — every 3c/3f source named in the
    task is either `NOT_IMPLEMENTED`, was deliberately excluded from replay
    (zero resolved-decision exposure), or was only ever used post-3f in
    still-unresolved live decisions. **Go/no-go for Phase 4: not yet** — see
    findings below for the full reasoning, led by the embargo/generalization
    problem, not sample size alone.
  - **3h** — A later addendum, added after a gap-analysis against
    professional crypto-advisory practice: a **learned evidence-value
    ranking** (a simple, inspectable supervised model checked against
    `decision_outcomes`, reported alongside — never blended into — the
    Judge's own implicit evidence weighting, including a **rolling-window/
    regime-sliced drift variant** that catches a source whose predictive
    value shifts over time rather than only its full-history average) and a
    deterministic **portfolio tail-risk stress test** (historical/
    scenario-based drawdown and VaR/CVaR-style estimates under a
    correlated-crash scenario). Reporting-only, same standing as 3g's
    findings — neither auto-adjusts Judge, Risk Engine, or `signal_sources`
    without explicit confirmation
  - **3i** — A second later addendum from the same gap-analysis pass: three
    further evidence sources closing gaps against institutional on-chain
    research practice — **wallet-entity-clustering/"smart money" flow
    intelligence** (Nansen/Arkham-class, resolving 3c's documented
    unclustered-large-transfer limitation), **custody/OTC desk flow
    tracking** (institutional accumulation that happens off public exchange
    order books and outside the spot-ETF wrapper entirely), and **network
    usage & developer-activity fundamentals** (active addresses, fee
    revenue, GitHub commit velocity) as a slower-moving, more
    fundamentals-oriented evidence type. Unlike 3h, this is new
    evidence-collection work wired into the existing Judge, not a
    diagnostic-only tool — the same "extend the input set" pattern 3f used.
    Now the last **required** sub-phase of Phase 3.
  - **3j** *(optional, gated backlog — not scheduled by default)* — A third
    gap-analysis addendum identifying **options gamma exposure/dealer
    positioning** (distinct from 3c's IV/skew), **exchange counterparty/
    solvency risk** (proof-of-reserves and insurance-fund monitoring), and
    **retail-demand proxies** (Google Trends/exchange-app-store rank,
    complementary to 3f's social/narrative sentiment). Unlike every other
    Phase 3 sub-phase, 3j is explicitly **not** implemented until 3h's
    evidence-value ranking, run against real decision history, surfaces a
    specific named gap one of these three would plausibly close — adding
    them speculatively would mean shipping more cost-bearing, drift-prone
    inputs with no evidence the existing 3a–3i evidence set is actually the
    bottleneck. See `PHASE3J_PROMPT.md` for the exact gating condition.
  - **3k** *(optional, gated backlog — not scheduled by default)* — A
    fourth gap-analysis addendum identifying **DeFi lending/borrowing
    rates** (Aave/Compound-style supply/borrow APYs and utilization, a
    leverage/carry proxy distinct from 3c's TVL flows and funding rates),
    **staking yield/validator queue depth** for proof-of-stake assets
    (supply-side lockup dynamics distinct from 3c's valuation-cycle
    cohorts), and **stablecoin depeg-risk monitoring** (distinct from 3c's
    supply/velocity tracking — a tail-risk flag, not a directional input).
    A fourth candidate, order-flow imbalance/LOB microstructure, was
    considered and explicitly **not** added to this backlog — it was
    already deliberately rejected earlier (see "Technology stack
    decisions") as out of scope for this project's multi-day-to-multi-month
    Judge horizon, and that reasoning stands. Same gating discipline as
    3j — not implemented until 3h's evidence-value ranking (or 3g's
    Judge-reasoning audit or purged-walk-forward finding) surfaces a
    specific named gap one of these three would plausibly close. See
    `PHASE3K_PROMPT.md` for the exact gating condition.
- ⬜ Phase 4 — Paper trading execution, benchmarks, ongoing accuracy tracking
  (see `PHASE4_PROMPT.md`). Simulated fills must be **order-book-depth-aware**
  (volume-weighted execution price against real bid/ask depth, with a
  labeled volatility-scaled fallback where depth data is unavailable) and
  fee-aware, not mark-to-mid — every 3g/3h calibration and stress-test
  number produced so far assumes costless, instant fills, so this phase
  re-runs those numbers net of realistic execution costs as an explicit,
  separately-reported comparison, not a silent replacement, since 3g's
  accuracy claims are only as meaningful as the fill assumptions behind
  them. Portfolio Construction's
  current inverse-vol/capped-Kelly sizing (3e) is deliberately simple for a
  paper system, and whether a fuller portfolio-optimization approach
  (e.g. risk parity or a constrained mean-variance step) is worth the added
  complexity is a decision for Phase 4's own scoping prompt, not assumed
  here
- ⬜ Phase 5 — Dashboard, scheduling, and a **FastAPI** read/query layer over
  the Evidence Store (candidates, assessments, Judge decisions, portfolio
  state, cost reports)
- ⬜ Phase 6 — Exchange integration (testnet only): a bounded **execution
  agent** (LangChain/LangGraph) that turns Portfolio Construction's approved
  target changes into actual (testnet) orders — the only agentic component
  in the system, scoped to an explicit, allow-listed toolset, with Risk
  Engine constraints re-checked at execution time

Each sub-phase is implemented, verified against the live Supabase project, and
reviewed before the next begins — same methodology as Phase 1 and 2 (see
"Development methodology" below). `pytest` must keep passing without live
credentials at every step; any source that turns out to have no reliable
programmatic access is recorded as `UNAVAILABLE`/`NOT_IMPLEMENTED` in
`signal_sources` rather than silently skipped or faked.

## Architecture

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

## Technology stack decisions

Recorded here so the reasoning behind each choice — including the ones
deliberately *not* adopted — doesn't get lost as the project grows.

- **FastAPI — adopted, Phase 5 only.** Pydantic-native, which matches this
  project's validation-heavy style throughout Phase 2/3 (strict schemas for
  LLM output, Judge output, etc.), so a future API layer can reuse those
  models almost directly. Not introduced earlier because nothing outside the
  CLI run needs to call this system until there's a dashboard to serve.
- **xAI (Grok) — adopted, in two places.** (1) As an optional fourth model in
  `OPENROUTER_ASSESSMENT_MODELS` for 3d, routed through OpenRouter like the
  other three, under the same `CostGuard`/schema rules — no special-cased
  integration. (2) As the access mechanism for the PlanB/X source in 3f,
  since Grok has native X/Twitter search and that's a more realistic path
  than unofficial scraping. Both uses still require the same real
  feasibility/cost verification as any other source before being relied on.
- **MongoDB — not adopted.** The evidence-provenance design already gets
  document-like flexibility from Postgres/Supabase's JSONB columns
  (`payload`, `key_drivers`, `source_assessment`, etc.) without giving up
  relational integrity — and that relational integrity is exactly what the
  decision-outcome ledger and calibration backtests depend on (joining
  `market_snapshots` ⋈ `model_market_assessments` ⋈ `decision_outcomes` ⋈
  `assets` by timestamp and asset). A second database would mean a second
  source of truth and duplicated infra/auth for no corresponding benefit
  here.
- **LangChain/LangGraph — adopted, Phase 6 only.** Every stage through
  Phase 3/4/5 is a fixed, deterministic pipeline with structured JSON in and
  out — there's no agent decision-making involved, so an agent framework
  would mean rewriting working code to fit someone else's abstraction for no
  benefit. Phase 6 is different: interacting with a live/testnet exchange API
  to place, monitor, and potentially adjust orders is exactly the bounded,
  tool-using loop an agent framework is built for. When that phase starts,
  the agent's toolset is explicitly allow-listed (place order, cancel order,
  check balance — not arbitrary API access), its task input is Portfolio
  Construction's already-approved target change (not an open-ended
  instruction), and Risk Engine constraints are re-checked at execution
  time, not just at recommendation time.
- **Deflated Sharpe Ratio / Probability of Backtest Overfitting — adopted,
  3g.** A raw hit-rate or Sharpe ratio computed after several rounds of
  prompt/logic iteration (3d–3f each version bumps, plus repeated
  calibration re-runs) is a classic multiple-comparisons setup: enough
  attempts against the same historical data will eventually produce a
  good-looking number by chance alone, independent of whether the system
  actually has an edge. Deflated Sharpe / PBO exist specifically to correct
  for this, and this project has the bookkeeping to do it properly
  (`prompt_templates`, `calibration_runs`) because that bookkeeping was
  designed in from 3a rather than reconstructed after the fact.
- **Brier score / reliability diagrams — adopted, 3e onward.** The Judge and
  every model assessment emit an explicit `confidence` value that the Risk
  Engine uses directly for position sizing — so whether that confidence is
  *calibrated* (a 70%-confidence call actually resolving positively ~70% of
  the time) is a separate, and arguably more actionable, question than
  whether calls are directionally right on average. Computed per regime, not
  just in aggregate, since a system calibrated in one regime and
  overconfident in another is a materially different (and more dangerous)
  system than one that's uniformly miscalibrated.
- **Held-out decision window — adopted, 3e onward.** Every sub-phase from
  3e forward tags decisions as inside or outside a window that's never used
  to tune prompts or logic, so the 3f/3g "did accuracy improve" comparison
  has at least one slice of results that wasn't iterated against. Cheap to
  add (one boolean column, decided once), and the alternative — discovering
  after months of iteration that there was never a genuinely untouched
  sample — is much more expensive.
- **Order-book / limit-order-book microstructure features (order-flow
  imbalance, spread, price-impact, toxicity) — considered, not adopted.**
  Current research shows these features have real, portable short-horizon
  predictive value on official, already-integrated venues (Binance/Deribit),
  so this isn't a source-availability rejection like CoinAnk/CryptoBubbles —
  it's a scope rejection. This project's Judge operates on multi-day to
  multi-month horizons via structured LLM reasoning; LOB features are
  validated for sub-minute to intraday statistical/ML models with their own
  walk-forward and leakage-control methodology, not for the Judge's evidence
  format. Revisit explicitly (as its own scoped phase, with its own
  validation approach) rather than folding it into an existing sub-phase if
  a shorter-horizon component is ever wanted. Re-examined during the 3k
  gap-analysis pass and reaffirmed unchanged — the horizon-mismatch
  reasoning above doesn't depend on which other evidence sources exist, so
  it wasn't reopened just because 3k was looking at nearby data (order-book
  depth) for other purposes.
- **Aggregate open interest, stablecoin supply/velocity, and exchange-reserve
  flow — adopted, 3c.** All are official/documented-API-accessible from
  venues already integrated by 3c (Binance, Deribit, DefiLlama, the existing
  on-chain explorer), so they're near-zero marginal cost, and each captures
  a distinct fact — position magnitude (OI), capital entering the crypto
  ecosystem (stablecoin supply), whether that capital is actually moving
  (velocity), and capital sitting on exchanges specifically (reserves) —
  that the funding-rate and TVL sources already in scope don't capture on
  their own.
- **Spot ETF flows — adopted, 3c.** Institutional-desk practice increasingly
  treats spot BTC/ETH ETF net flows as the primary medium/long-horizon
  proxy for institutional positioning, read *alongside* (not instead of)
  derivatives leverage data to distinguish capital-driven demand from
  leveraged speculation. Accessed via a documented aggregator (Farside
  Investors / SoSoValue) rather than per-issuer scraping, so it fits the
  same "official/documented source" bar as everything else in 3c. Not
  adopted earlier (3b) because it's a capital-flow fact, not a screening
  input over the open universe — most assets in the universe don't have a
  spot ETF at all.
- **Prediction markets — adopted, 3c, narrowly scoped.** Polymarket/Kalshi
  implied probabilities are a genuinely distinct evidence *type* — a
  market-priced probability for a specific, well-defined outcome, unlike
  options IV (which prices uncertainty magnitude, not a specific outcome) or
  LLM-stated confidence (which isn't backed by capital at risk). Scoped
  narrowly to a curated, liquid contract set rather than broad coverage,
  since thin-liquidity implied probabilities are noise, not signal — this is
  a "verify real access and real liquidity before relying on it" source like
  everything else in 3c, not an assumed-reliable one.
- **Deterministic composite factor score — adopted, 3b.** The Judge's
  primary evidence (3d model assessments, 3f adversarial research) is all
  LLM-narrative-derived, even when it's reasoning over real numbers. A
  simple, deterministic, non-LLM combination of the screening factors
  already computed in 3b (momentum, volatility, drawdown, relative
  strength) gives the Judge — and later, 3g's validation — a purely
  quantitative reference point to check the narrative against, at zero
  marginal LLM cost. Deliberately kept simple and inspectable (documented
  weights, not a trained model) rather than a fitted quant model, consistent
  with this project's "simple and auditable over sophisticated and opaque"
  approach to every other deterministic component (Risk Engine sizing,
  regime classifier).
- **On-chain valuation-cycle metrics (MVRV/SOPR/NUPL/LTH-STH cohorts) —
  adopted, 3c.** Professional on-chain research treats these as the
  foundational metric set for cycle-position valuation — distinct from both
  the transfer-flow/TVL data already in 3c (which measures capital
  movement, not where the holder base sits relative to cost basis) and from
  the LLM-narrative evidence in 3d/3f. Accessed via a documented provider
  (Glassnode or CryptoQuant); a paid tier may be required for full
  coverage, which is a dollar cost to weigh against project budget, not an
  LLM cost, so it doesn't touch `CostGuard`. Coverage is expected to be
  BTC/ETH-strong and thin-to-absent for most smaller-cap assets in the
  universe, consistent with how every other 3c source handles uneven
  per-asset coverage.
- **Futures term structure / basis — adopted, 3c.** The perpetual funding
  rate (already in 3c) captures perpetual-specific positioning and open
  interest captures magnitude, but neither captures how futures desks price
  forward expectations across concrete expiries the way a dated-futures
  contango/backwardation curve does — a materially different signal, at
  near-zero marginal integration cost since it's the same Binance/Deribit
  venues already integrated for funding and options.
- **Token unlock/vesting schedule — adopted, 3c.** Structurally unlike every
  other source in this project: it's a calendar-dated *known future event*
  rather than a read of current market/on-chain state. Particularly
  relevant to this project's altcoin-heavy `in_asset = true` universe
  (ONDO, ENA, JASMY, S, STORJ, JTO, etc.), where scheduled unlocks are a
  real, foreseeable supply-side catalyst that price/volume/on-chain data
  alone won't surface in advance. A natural input to the Judge's
  `invalidation_conditions` (3e) rather than just another risk factor,
  since the event date is known rather than inferred.
- **Social/narrative sentiment — adopted, 3f, fragile.** Aggregate social
  volume / trending-narrative tracking (Santiment/LunarCrush-style) is a
  genuinely distinct evidence type from both Phase 2's RSS news (editorial
  coverage) and 3f's PlanB/X source (one named analyst's stated opinion) —
  it's an aggregate attention signal across many unnamed accounts. Placed
  in 3f rather than 3c because reliable, reasonably priced programmatic
  access is unverified going in, unlike the documented-API sources in 3c;
  a low-effort/`UNAVAILABLE` outcome here is an acceptable result, same as
  CoinAnk or CryptoBubbles.
- **CME futures positioning (CFTC COT) — adopted, 3c.** A free, official,
  weekly government report giving a regulated-futures view of institutional
  positioning by trader category — distinct in kind from spot ETF flows
  (fund-level capital movement) and perpetual funding rate (crypto-native
  leverage), both already in 3c. Deliberately does not hard-code the
  traditional "commercials are smart money" reading, since independent
  analysis of BTC's COT data finds that relationship doesn't reliably
  transfer from other commodities — the raw category breakdown is stored,
  and any smart-money inference is left to the Judge.
- **BTC miner metrics — adopted, 3c.** Hash rate, difficulty, and miner
  reserve/exchange-flow data are a standard on-chain research category
  (miner capitulation/recovery signals) sitting alongside the MVRV/SOPR/
  NUPL metrics already scoped for 3c, typically from the same vendor
  (Glassnode/CryptoQuant), so the marginal integration cost is low.
  BTC-specific only — the mining security-budget dynamic doesn't transfer
  to most of the rest of the universe.
- **Global liquidity & cross-asset correlation (FRED) — adopted, 3f.** M2
  growth, Fed balance sheet, and reverse-repo levels are widely treated in
  crypto-macro research as a more informative multi-month driver than any
  single data print, and BTC's rolling correlation to equities/gold/DXY
  speaks directly to whether crypto is currently trading as a macro risk
  asset. FRED is free, official, and documented, which keeps this to the
  same reliability bar as everything else — placed in 3f because that's
  where the macro-evidence-matrix logic already lives, not because the
  access itself is fragile.
- **Regulatory/policy event calendar — adopted, 3f, feasibility-gated.**
  SEC EDGAR and congress.gov are both free, official, documented government
  APIs — the access itself is not the risky part. What's unverified is
  reliably extracting a dated, asset-specific, investment-relevant event
  from raw filings/bills without an unacceptable false-positive/negative
  rate, which is a similar risk profile to PlanB/X's post-parsing. Grouped
  with 3f's feasibility-gated sources for that reason; a global/macro-scope
  version (not attributed to a specific asset) is an acceptable fallback if
  per-asset attribution isn't reliably achievable.
- **Adaptive evidence-value ranking — adopted, 3h, diagnostic only.**
  3f/3g's before/after calibration comparisons and manual
  `signal_sources.enabled` toggling answer "did this source help" only in
  aggregate and only when a human explicitly re-runs the comparison. A
  simple, inspectable supervised model trained on `decision_outcomes`
  produces a learned importance ranking across all structured evidence
  fields at once, checked against — never blended into — the Judge's own
  implicit weighting. Kept strictly diagnostic (same rule as
  `composite_factor_score`'s relationship to the Judge) because turning a
  small-sample learned model into a live re-weighting mechanism risks
  exactly the overfitting-to-noise failure mode 3g's Deflated Sharpe/PBO
  correction exists to catch.
- **Evidence-value drift detection (rolling-window/regime-sliced) —
  adopted, 3h.** A single full-history importance ranking (above) can hide
  a source whose predictive value has genuinely shifted — crypto regimes
  turn over fast enough (pre-ETF vs. post-ETF, a deleveraging year vs. a
  quieter one) that a source informative in one stretch and inert in
  another can average out to "mediocre" rather than surface as the more
  actionable finding, "this source's value is regime-dependent." Re-running
  task 1's method over rolling windows and regime slices, with the same
  minimum-sample-size gating, catches that distinction at negligible extra
  cost since it reuses the same modeling approach and data.
- **Portfolio tail-risk stress testing — adopted, 3h.** The Risk Engine's
  per-asset caps, volatility-adjusted sizing, and correlation-concentration
  flag (3e) are all real-time/forward-looking checks; none of them asks
  "what would this portfolio's drawdown have been in a historical
  correlated-crash scenario," which is standard practice at institutional
  risk desks before sizing is trusted. Kept simple and inspectable
  (documented scenario templates, not a fitted tail-risk model), consistent
  with every other deterministic component in this project, and explicitly
  labels any cross-asset historical-data assumption as an assumption rather
  than measured history.
- **Screening-stage anomaly/wash-trading flag — adopted, 3b.** The smaller-
  cap tier of an open, discovery-driven universe is exactly where wash
  trading and pump-and-dump volume patterns are most likely to surface as
  a "candidate" on raw momentum/volume factors alone. A cheap z-score/
  percentage-jump check at screening time, before any evidence collection
  or LLM cost is spent on an asset, is a proportionate response — flagging
  rather than excluding, so the anomaly stays visible rather than silently
  filtering the universe.
- **BTC dominance / altcoin-season index — adopted, 3b.** The risk-on/
  risk-off regime classification answers "is crypto broadly attracting or
  shedding capital," but not the orthogonal, equally-watched professional
  question of whether capital is rotating *within* crypto, from BTC into
  alts or back. A derived, zero-marginal-cost computation from data 3b
  already collects (BTC's share of screened-universe market cap and its
  trend, plus the standard "% of the universe outperforming BTC over a
  trailing window" formulation) gives the regime snapshot that second axis
  without a new external source or a new table.
- **Volatility risk premium (VRP) — adopted, 3c.** Deribit's implied
  volatility (already captured) says how much uncertainty options are
  pricing in, but professional options desks read that relative to
  realized volatility — the spread between the two is what actually prices
  the risk premium options sellers earn, and it behaves differently from
  either input alone. A derived field pairing task 3's IV with 3b's
  already-computed realized-volatility factor, at zero marginal cost.
- **Annualized futures basis/carry yield — adopted, 3c.** The raw
  dated-futures basis curve (already captured) is comparable within an
  asset across expiries but awkward to compare across assets or against a
  risk-free-rate benchmark. Annualizing it — a straightforward
  transformation of data already collected — makes the term-structure
  signal directly usable the way a fixed-income desk reads a carry trade,
  without adding a new source or an interpretation judgment at the
  collector level.
- **Regional exchange premium — adopted, 3f, fragile.** A structural,
  region-specific price gap (historically documented as the Korean "Kimchi
  premium") reflects a genuinely different economic mechanism — capital
  controls and regionally concentrated retail speculative intensity — than
  the ordinary cross-venue aggregation noise 3b already logs between
  globally arbitraged venues. Grouped with 3f's fragile sources because
  reliable, ToS-compliant programmatic access to the relevant regional
  exchange is unverified going in; a low-effort/`UNAVAILABLE` outcome is an
  acceptable result, same as CoinAnk or CryptoBubbles.
- **Entity-flow intelligence (Nansen/Arkham-class) — adopted, 3i.** 3c's
  Etherscan-based on-chain source explicitly documents a known limitation:
  a raw large-transfer count has no entity clustering behind it, so it
  conflates genuine whale accumulation with routine exchange-internal
  traffic. A paid, documented wallet-entity-clustering provider closes that
  specific gap by labeling *who* is moving funds, not just that a transfer
  occurred — a materially higher-confidence fact, though still not a
  directional signal on its own (a labeled "smart money" cohort can be
  wrong same as anyone). Scoped to 3i, after 3h, since it's genuinely new
  evidence-collection work identified in the same gap-analysis pass that
  produced 3h, not a diagnostic addition.
- **Custody/OTC desk flow tracking — adopted, 3i.** A growing share of
  institutional crypto activity, especially post-spot-ETF, happens through
  custody providers or OTC desks and never touches a public exchange order
  book — meaning it's invisible to both 3c's exchange-reserve proxy and
  its spot-ETF-flow source. Tracking known custody-provider address
  balances (e.g. Coinbase Custody, Fidelity Digital Assets) closes that
  visibility gap at near-zero marginal cost, reusing the on-chain explorer
  relationship already established in 3c.
- **Network usage & developer-activity fundamentals — adopted, 3i.**
  Distinct from both price-derived screening factors (3b) and on-chain
  valuation-cycle metrics (3c, which describe where the holder base sits
  relative to cost basis): active addresses, transaction throughput, and
  fee revenue measure raw usage, and developer/commit activity measures
  building activity — both slower-moving, more fundamentals-oriented
  evidence types that professional long-horizon research treats as
  differentiated inputs, fitting the Judge's existing 90-day-and-longer
  horizon reasoning.
- **Langfuse — adopted, optional starting 3d.** Complements, not replaces,
  the manual prompt-versioning (`prompt_templates`) and cost tracking
  (`CostGuard`, `estimated_cost` columns) already designed into Phase 3 —
  it adds a UI for tracing individual calls and comparing prompt versions
  once there's enough call volume and outcome data (from 3e's
  decision-outcome ledger) to make that comparison meaningful. Strictly
  additive instrumentation: the decision pipeline must run identically
  whether or not Langfuse is configured.

## Setup

1. Create a virtual environment and install dependencies:

   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and fill in:
   - `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` — from your Supabase project's
     Settings -> API page. **Required.**
   - `COINGECKO_API_KEY` — optional; leave blank to use CoinGecko's public
     (rate-limited) endpoint.
   - `DATABASE_URL` — optional, only needed if you want to apply migrations via
     `scripts/apply_migration.py` instead of the Supabase SQL Editor.
   - `OPENROUTER_API_KEY`, `CLAUDE_MODEL`, `OPENAI_MODEL`, `GEMINI_MODEL` — only
     required if you want to run `--with-llm` (see Phase 2 below). Not needed
     for plain market-data collection.
   - (From Phase 3d onward, optional) `OPENROUTER_ASSESSMENT_MODELS` — the
     model set for the current-market-assessment stage; may include Grok if
     you choose to enable it.
   - (Optional, Phase 3d onward) `LANGFUSE_*` credentials — only needed if you
     choose to enable call tracing; the pipeline runs identically without
     them.
   - (Optional, Phase 3c onward) `GLASSNODE_API_KEY` / `CRYPTOQUANT_API_KEY`
     — only needed to enable on-chain valuation-cycle metrics
     (MVRV/SOPR/NUPL/LTH-STH cohorts); a paid tier may be required for full
     coverage. Leave blank to have that source recorded as
     `NOT_IMPLEMENTED`/`UNAVAILABLE` in `signal_sources` rather than
     approximated.
   - (Optional, Phase 3c onward) `TOKEN_UNLOCK_SOURCE_API_KEY` (Messari or
     TokenUnlocks) — only needed to enable token unlock/vesting schedule
     data for the altcoin tier of the universe.
   - (Optional, Phase 3c onward) `CME_COT_SOURCE` config — the CFTC
     publishes Commitment of Traders data for free with no key required;
     this setting only exists if you choose to point at a documented
     aggregator instead of the CFTC's own published data directly. Leave
     unset to have `CME_COT_POSITIONING` recorded as `NOT_IMPLEMENTED`
     rather than approximated.
   - (Optional, Phase 3f onward) `FRED_API_KEY` — free, required by FRED for
     the global-liquidity/cross-asset-correlation macro extension (M2, Fed
     balance sheet, S&P 500/dollar-index series). Leave blank to have
     `GLOBAL_LIQUIDITY_MACRO` recorded as `NOT_IMPLEMENTED`.
   - (Optional, Phase 3f onward) `SEC_EDGAR_USER_AGENT` /
     `CONGRESS_GOV_API_KEY` — only needed to enable the regulatory/policy
     event calendar. Both underlying APIs are free; leave blank to have
     `REGULATORY_EVENT_CALENDAR` recorded as `NOT_IMPLEMENTED`.
   - (Optional, Phase 3f onward) `REGIONAL_EXCHANGE_API_KEY` / endpoint
     config (e.g. Upbit/Bithumb) — only needed to enable the regional
     exchange price-premium source. Leave unset to have
     `REGIONAL_EXCHANGE_PREMIUM` recorded as `NOT_IMPLEMENTED`.
   - (Optional, Phase 3i onward) `NANSEN_API_KEY` / `ARKHAM_API_KEY` — only
     needed to enable wallet-entity-clustering/"smart money" flow
     intelligence; a paid tier is required. Leave blank to have
     `ENTITY_FLOW_INTELLIGENCE` recorded as `NOT_IMPLEMENTED`.
   - (Optional, Phase 3i onward) `DEV_ACTIVITY_SOURCE_API_KEY` (e.g. an
     Electric Capital Developer Report-style aggregator, or a direct
     GitHub API token) — only needed to enable the developer-activity half
     of `NETWORK_FUNDAMENTALS_DEV_ACTIVITY`; the network-usage half (active
     addresses, fees) reuses the on-chain explorer credentials already
     configured for 3c. Leave blank to have the developer-activity field
     recorded as `NOT_IMPLEMENTED`.
   - (Optional, Phase 3i onward) `CUSTODY_WATCH_ADDRESSES` config — a
     documented list of known custody-provider addresses to track balance
     deltas for; no paid API required if using publicly known addresses via
     the existing on-chain explorer. Leave unset to have `CUSTODY_OTC_FLOW`
     recorded as `NOT_IMPLEMENTED`.

3. Apply the database schema — all five migrations, in order. Either:
   - **Recommended**: open the Supabase SQL Editor and paste the contents of
     `migrations/0001_init.sql`, run it, then do the same for
     `migrations/0002_llm_and_news.sql`,
     `migrations/0003_phase3a_universe_provenance.sql`,
     `migrations/0004_phase3b_screening_regime.sql`, and
     `migrations/0005_phase3c_derivatives_onchain.sql`. All are idempotent —
     safe to re-run any time they change.
   - Or, with `DATABASE_URL` set:
     ```
     python scripts/apply_migration.py migrations/0001_init.sql
     python scripts/apply_migration.py migrations/0002_llm_and_news.sql
     python scripts/apply_migration.py migrations/0003_phase3a_universe_provenance.sql
     python scripts/apply_migration.py migrations/0004_phase3b_screening_regime.sql
     python scripts/apply_migration.py migrations/0005_phase3c_derivatives_onchain.sql
     ```

4. Run the collector:

   ```
   python -m app.main
   ```

   This fetches current market data for all active assets from CoinGecko and stores
   one normalized snapshot per asset in `market_snapshots`, skipping any asset whose
   most recent snapshot is younger than `MIN_SNAPSHOT_INTERVAL_MINUTES` (default 5)
   to avoid redundant writes.

5. Optionally, also run news collection + multi-model LLM research:

   ```
   python -m app.main --with-llm
   ```

   **This makes real, billed calls to Claude/OpenAI/Gemini via OpenRouter** — see
   the Phase 2 section below before running it.

6. Optionally, also run 3b's screening + market-regime classification (zero
   LLM cost — CoinGecko/CoinMarketCap/Coinbase/Binance market data only):

   ```
   python -m app.main --with-screening
   ```

   Combine with `--with-llm` if you want both in one run. See the Phase 3b
   section below for what this does.

7. Optionally, also run 3c's derivatives/on-chain collection (zero LLM cost —
   Binance Futures/Deribit/CFTC/DefiLlama market data, no key required for
   any of those four):

   ```
   python -m app.main --with-derivatives
   ```

   Combine with `--with-llm`/`--with-screening` as needed. See the Phase 3c
   section below for what this does.

## Verifying it worked

- Console output logs a `run_id` (e.g. `RUN-20260903-141623`, unique to the second) and a per-run summary:
  `inserted=N skipped_duplicate=N failed=N`, plus which symbols were stored.
- In the Supabase Table Editor, check `market_snapshots` — you should see one row
  per active asset with a recent `timestamp`, `price`, `market_cap`, etc.
- Run `python -m app.main` again immediately — assets should show up in
  `skipped_duplicate` rather than being re-inserted (dedup working).
- Run `pytest` — all tests should pass without needing any credentials (they use
  fakes/mocks, no live network or database calls).

For `--with-llm`: check `news` and `llm_analyses` in the Supabase Table Editor.
`llm_analyses` should have up to one row per (provider, asset) — 3 providers ×
however many `active` assets. Console output logs `stored_by_provider`,
`failed`, and `skipped_cost_cap` per provider so failures are visible without
digging through the database.

## Asset universe

The asset universe is **not hard-coded** in the application. It lives in the `assets`
table (seeded by the migration) and is read fresh on every run. To add or disable an
asset, edit the `assets` table directly (e.g. set `active = false`, or insert a new
row with its CoinGecko id) — no code changes required.

Two independent flags per asset:
- `active` — whether the market-data collector tracks this asset at all.
- `in_asset` — whether it's currently held in the live portfolio, vs. tracked for
  research/watchlist purposes only. Purely informational in Phase 1; later phases
  (Portfolio Manager, Risk Engine) will read it.

Seeded assets:

| symbol | name | coingecko_id | in_asset |
|---|---|---|---|
| BTC | Bitcoin | `bitcoin` | true |
| ETH | Ethereum | `ethereum` | true |
| SOL | Solana | `solana` | false |
| XRP | XRP | `ripple` | false |
| BNB | BNB | `binancecoin` | false |
| HYPE | Hyperliquid | `hyperliquid` | false |
| LINK | Chainlink | `chainlink` | true |
| ONDO | Ondo | `ondo-finance` | true |
| JASMY | JasmyCoin | `jasmycoin` | true |
| ENA | Ethena | `ethena` | true |
| S | Sonic | `sonic-3` | true |
| STORJ | Storj | `storj` | true |
| ZRX | 0x Protocol | `0x` | true |
| XTZ | Tezos | `tezos` | true |
| BONK | Bonk | `bonk` | true |
| JTO | Jito | `jito-governance-token` | true |

All 16 are `active`, so the collector currently tracks all of them regardless of
`in_asset`.

## Phase 2 — Multi-model AI research (`--with-llm`)

Running `python -m app.main --with-llm` adds two steps after market data
collection:

1. **News collection** (`app/news/`): pulls RSS from CoinDesk, CoinTelegraph,
   and Decrypt (free, no API key), matches each article against the asset
   universe by name/ticker (word-bounded; ticker matching is case-sensitive
   to avoid e.g. "LINK" matching the ordinary word "link"), dedupes on
   `content_hash`, and stores only articles relevant to at least one asset.
2. **LLM research** (`app/llm/`): builds one shared market-data-plus-news
   context, sends it to Claude, OpenAI, and Gemini via OpenRouter (one
   batched call per provider covering every asset, not one call per asset,
   to keep cost down), validates each response against a strict Pydantic
   schema (retrying once in-conversation if the model returns invalid JSON),
   and persists one row per (provider, asset) to `llm_analyses`. One provider
   failing never blocks the other two.

**Cost control**: `CostGuard` checks cumulative spend against
`MAX_DAILY_LLM_COST`/`MAX_MONTHLY_LLM_COST` before every provider call,
skipping (not crashing) once a cap is hit. As of Phase 3a, the sum is computed
by `CostLedgerRepository` across every table registered in
`COST_TRACKED_TABLES` (`app/llm/cost.py`) — today just `llm_analyses`, but any
future sub-phase adding a new LLM-call-persisting table (3d, 3e, 3f, 3g)
registers it there rather than CostGuard silently missing that spend. The
pricing table in `app/llm/cost.py` is a point-in-time snapshot of OpenRouter
pricing — re-check https://openrouter.ai/models periodically, especially
after changing `CLAUDE_MODEL`/`OPENAI_MODEL`/`GEMINI_MODEL`.

**Known limitations** (accepted tradeoffs, not bugs):
- `sentiment` on `news` rows is always `NULL` — computing it reliably needs
  either an extra LLM call (cost) or a real sentiment model; deferred.
- News relevance matching is a keyword heuristic, not NLP — it will
  occasionally miss context or produce a coincidental match. It's a cheap
  pre-filter feeding models that can apply their own judgment, not a source
  of ground truth.
- Coverage is uneven across the asset universe: general crypto news outlets
  cover BTC/ETH/SOL/XRP/BNB/HYPE far more than smaller caps like STORJ or
  JTO. When no news is found, the LLMs correctly fall back to price-momentum
  reasoning rather than inventing a catalyst.

`run_id` is time-based to the second (`RUN-YYYYMMDD-HHMMSS`), generated fresh
per process — each `python -m app.main` invocation gets its own unique id.

## Phase 3a — Universe/candidate schema, evidence provenance, registries

`migrations/0003_phase3a_universe_provenance.sql` adds, empty and ready for
later sub-phases (no new external API calls, no new LLM calls, no behavior
change to any Phase 1/2 code path):

- **`asset_status_history`** — an append-only record of `HELD`/`WATCHLIST`/
  `CANDIDATE`/`REJECTED` transitions per asset, independent of
  `assets.active`/`assets.in_asset`. Seeded from the current `in_asset` flag
  (`true` → `HELD`, `false` → `WATCHLIST`) so it isn't empty for existing
  assets. Read/write via `AssetStatusRepository`
  (`app/database/repository.py`).
- **`signal_sources`** — a registry of every evidence source in the Phase 3
  vision (`app/database/models.py`'s `SignalSource`, read via
  `SignalSourceRepository`). CoinGecko and News are seeded `OK` (already
  implemented); everything else — CoinMarketCap, Coinbase, Binance, Deribit,
  Etherscan, DefiLlama, CoinAnk, CoinGlass, CryptoBubbles, PlanB, Macro, and
  the longer list of 3c/3f/3i-specific sources — is seeded `NOT_IMPLEMENTED`.
- **`market_regime_snapshots`**, **`judge_decisions`**, **`decision_outcomes`**,
  **`prompt_templates`**, **`calibration_runs`** — schema only, populated
  starting in 3b (regime snapshots), 3d (prompt templates), and 3e (Judge
  decisions, decision outcomes, calibration runs).
- **Evidence provenance convention** (`app/database/evidence_provenance.py`):
  the shared column shape (`source`, `scope`, three timestamps, `timeframe`,
  `freshness` + numeric `decay_half_life_hours`, `status`, `payload`) every
  future evidence-source table composes, plus `is_revision_of` for
  point-in-time integrity — a correction is a new linked row, never an
  `UPDATE` overwriting what was originally retrieved — and a
  `latest_value_as_of()` helper implementing the "value as known at time T"
  query convention so 3b/3c/3f don't each invent their own.
- **`DecisionValue`** (`app/judge/decisions.py`): `BUY`/`HOLD`/`SELL`/`WATCH`/
  `NO_TRADE` as a forward-looking placeholder for 3e's Judge — no
  decision-making logic yet. Deliberately separate from Phase 2's live
  `Action` type (`app/llm/schemas.py`, `BUY`/`HOLD`/`SELL` only), which stays
  untouched. `judge_decisions.decision` enforces this same vocabulary at the
  database level via a `CHECK` constraint.
- **`COST_TRACKED_TABLES`** (`app/llm/cost.py`): the CostGuard-extension
  registry — every LLM-call-persisting table gets an `estimated_cost` column
  and an entry here (table name → its timestamp column, since they aren't
  all named the same — `llm_analyses.timestamp` vs. `judge_decisions.created_at`).
  `CostLedgerRepository` sums across every registered table; `CostGuard`
  itself is unchanged (still just calls `.get_cost_sum_since(...)` on
  whatever it's given), so this was a zero-behavior-change refactor verified
  by the full pre-existing Phase 2 test suite passing unmodified.

**Known limitations / decisions** (locked before implementation — see
`PHASE3_LOCKED_DECISIONS.md` for the full reasoning):
- **History table over a status column** — chosen so status transitions
  stay auditable once 3b's candidate discovery starts moving assets between
  states; cheap to add now, expensive to retrofit once 3b–3g are writing
  against a fixed schema.
- **`judge_decisions` named now, in 3a** — `decision_outcomes.decision_id`
  needed a real FK target; without this, 3e would have had to invent (and
  migrate for) the table mid-implementation.
- **Initial `decay_half_life_hours` values** are starting estimates, not
  measured: `coingecko_price` ≈ 2h, `news` ≈ 18h, `macro` ≈ 720h (~30 days,
  "until superseded"). Refine per-source as 3b/3c/3f actually build against
  real data behavior.
- **`market_regime_snapshots.regime` and `calibration_runs.method`** are left
  as free text, not `CHECK`-constrained enums — 3b/3g define the actual
  label/method sets and may need to refine them without another migration.
- **Smart-contract/scam-safety screening** (honeypot/rug-pull checks on
  newly-discovered 3b candidates) was identified as a real gap against
  professional screening practice, flagged for an explicit decision once 3b
  started. Resolved: **out of scope for 3b** — `PHASE3B_PROMPT.md`'s actual
  task list doesn't call for it, and it wasn't invented back in as scope
  creep. Still a real gap; a natural fit for 3c (already adding new
  providers) or a dedicated future check, not built here.

## Phase 3b — CoinMarketCap, Coinbase, Binance, screening, regime classification

`python -m app.main --with-screening` adds, after market data collection:

1. **CoinMarketCap** (optional, gated behind `COINMARKETCAP_API_KEY`) —
   aggregated market data, kept fully independent from CoinGecko (never
   merged), used both as a cross-check and as the source for 90d
   percent-change (needed for the altcoin-season index below — CoinGecko
   doesn't offer a 90d window). Endpoint/auth shape verified live (a 401
   with CMC's documented error code); the response shape itself has **not**
   been end-to-end verified against a real key as of this writing — verify
   once you add one.
2. **Coinbase** (`app/market_data/coinbase.py`) — public Exchange API, no key
   needed. Verified live: covers all 16 assets in the current universe
   (837 total USD products) with 200+ days of daily history.
3. **Binance** (`app/market_data/binance.py`) — public REST API, no key
   needed. Verified live: 14 sequential historical-data calls completed in
   3.7s with zero rate-limiting — this is why it's the **primary** source
   for volatility/drawdown (which need a real return series, not just a
   point-in-time percent change), not CoinGecko. Two of the current 16
   assets (HYPE, STORJ) have no Binance USDT pair — Coinbase is the
   **fallback** for those; `UNAVAILABLE` only if neither venue lists the
   asset.
4. **Screening universe** (`SCREENING_UNIVERSE_SIZE`, default 30) — the top
   N assets by CoinGecko market cap (stablecoins excluded via a documented
   symbol denylist, `app/market_data/stablecoins.py`), not just the 16
   currently tracked — this is where genuinely new candidates get
   discovered.
5. **Deterministic factors** (`app/market_data/factors.py`, pure functions,
   fully unit-tested without live APIs): momentum (7d/30d, direct from
   CoinGecko/CMC point returns), volatility (stdev of daily returns) and max
   drawdown (both from Binance/Coinbase daily closes), relative strength
   (vs. BTC's own 30d momentum), and liquidity (24h volume).
6. **Composite factor score** — a documented, rank-based (not raw-value)
   combination, so factors with very different natural scales (% vs.
   dollars) combine safely: `momentum_30d` 30%, `momentum_7d` 15%,
   `relative_strength_30d` 20%, `volatility_30d` 15% (inverted — lower
   ranks higher), `drawdown_30d` 10% (inverted — shallower ranks higher),
   `volume_24h` 10%. A missing factor for one asset has its weight
   redistributed across that asset's other factors rather than being
   treated as zero/neutral. Purely quantitative — stays visible alongside,
   never blended into, LLM/Judge evidence later.
7. **Anomaly/wash-trading flag** (`app/market_data/anomaly.py`) — flags (never
   excludes) an asset whose latest-day price move exceeds 50% or whose
   latest-day volume is a >3σ outlier vs. its own trailing history.
8. **Market-regime classification** (`app/market_data/regime.py`) — one
   `market_regime_snapshots` row per run: `RISK_ON`/`RISK_OFF`/`NEUTRAL` from
   BTC's price vs. its own 7d/30d moving averages plus universe breadth (%
   with positive 30d momentum); **BTC dominance** (BTC's share of screened
   market cap); an **altcoin-season index** (% of non-stablecoin assets
   outperforming BTC over 90d — `UNAVAILABLE` without a CoinMarketCap key);
   and **halving-cycle day-counts** (days since/until the nearest halving).

**Known limitations / decisions:**
- **Halving cycle is a calendar-based approximation, not live block
  height.** None of CoinGecko/CoinMarketCap/Coinbase/Binance expose current
  BTC block height (verified live — they're trading/aggregation APIs, not
  block explorers). The past halving date (2024-04-20) is a public,
  unchanging historical fact; the next is estimated as +1458 days (~210,000
  blocks at Bitcoin's ~10-minute target). Raw day-counts only, no
  cycle-phase interpretation — that's for the Judge (3e) or later scenario
  research (3f).
- **`signal_sources.enabled` is informational only for CoinMarketCap/
  Coinbase/Binance** — the screening service doesn't yet gate on it before
  attempting a source (only `status`/`last_checked_at` get updated per run).
  An operator toggle here would need real gating logic added later.
- **`SCREENING_UNIVERSE_SIZE` defaults to 30, not 50** — a directly verified
  constraint (CoinGecko's per-asset historical endpoint rate-limits after
  ~5 rapid calls on the free tier), not a guess. This only matters for
  historical calls the service *doesn't* make from CoinGecko (it uses
  Binance/Coinbase for those instead) — the constraint is about overall
  per-run call volume and runtime across every source combined.
- **CoinMarketCap's response shape is implemented per its documented API
  but not live-verified end-to-end** — no key was available while building
  this. Verify once `COINMARKETCAP_API_KEY` is set.

## Phase 3c — Derivatives, CME positioning, on-chain/DeFi, stablecoin supply

`python -m app.main --with-derivatives` collects, into one shared
`evidence_observations` table (see below), zero LLM cost:

1. **Binance funding rate + open interest** (`app/market_data/binance.py`,
   extended) — for every tracked asset with a Binance perpetual (18 of 21
   currently tracked; missing STORJ, BONK, WBT — verified live).
2. **Futures term structure / annualized carry yield** — Binance's and
   Deribit's dated (quarterly) futures vs. spot, for **BTC/ETH only**:
   verified live that neither venue lists dated futures for any other
   currently tracked asset (SOL, XRP, BNB, LINK, etc. all show zero dated
   contracts despite having perpetuals). Raw basis and the annualized
   carry-yield transformation are both stored.
3. **CME Commitment of Traders (COT) positioning** (`app/market_data/cftc.py`)
   — the CFTC's free, official "Traders in Financial Futures" report via
   their public Socrata API, for BTC and ETH (as `MICRO ETHER` — CME's actual
   contract name; there's no plain "ETHEREUM" listing). Categorized by
   Dealer/Asset Manager/Leveraged Money/Other Reportables, exactly as
   professional COT analysis expects. Stored with `freshness=STALE` by
   design — the report reflects the prior Tuesday's close, published
   Fridays; `decay_half_life_hours=84` (half the ~7-day publication cycle).
4. **Deribit options** (`app/market_data/deribit.py`) — implied volatility
   (near-dated, near-the-money) and aggregate put/call open-interest ratio,
   **BTC/ETH only** (verified live: every other currency shows zero option
   instruments on Deribit, despite some listing perpetuals there).
5. **Volatility risk premium (VRP)** (`app/market_data/derivatives_factors.py`)
   — Deribit's annualized implied vol minus 3b's realized 30d volatility
   (itself annualized to match scale) for the same asset. Only computed
   when both sides are genuinely available; a documented, testable pure
   function, not a new external source.
6. **DefiLlama TVL** (`app/market_data/defillama.py`) — protocol TVL +
   1d/7d change, matched to tracked assets by governance-token symbol
   (best-effort; ties broken by highest TVL). Fully free, no key.
7. **Stablecoin supply growth** — DefiLlama's dedicated stablecoins API
   directly exposes `circulating`/`circulatingPrevWeek`/`circulatingPrevMonth`,
   so 7d/30d growth needed no derived computation or new provider. Captured
   for the top 5 stablecoins by circulating supply, as `GLOBAL_CRYPTO`-scope
   evidence (`asset_id = null`) — a market-wide capital-flow proxy, not
   asset-specific.
8. **Etherscan large-transfer proxy** (`app/market_data/etherscan.py`,
   optional, gated behind `ETHERSCAN_API_KEY`) — counts native ETH transfers
   above a threshold to/from a small set of known exchange addresses in the
   last 24h, attributed to ETH's own evidence record.
9. **Glassnode** (`app/market_data/glassnode.py`, optional, gated behind
   `GLASSNODE_API_KEY`) — on-chain valuation-cycle metrics (MVRV/SOPR/NUPL/
   cohorts) and BTC miner metrics. Client built and ready; **not
   subscribed to** (see decisions below), reports `NOT_IMPLEMENTED`.

Every raw observation is stored as-is — funding rate, open interest, the
futures curve, IV, put/call ratio, VRP, and COT positioning are all
positioning/pricing facts, not directional signals; no BUY/SELL inference
happens at the collector level anywhere in this sub-phase (that's the
Judge's job in 3e, per every per-source interpretation constraint in
`PHASE3C_PROMPT.md`).

**Signal sources confirmed genuinely inaccessible this round** (investigated
live, not guessed): **Spot ETF flows** — Farside has no real API, just a
Cloudflare-protected webpage; SoSoValue's API requires an authenticated
login not available here. **Token unlock schedules** — Messari requires a
key not available here (and its tier's unlock-data coverage is unconfirmed);
TokenUnlocks.app has no discoverable public API. **Prediction markets** —
Polymarket and Kalshi both fail DNS resolution from this specific
development sandbox (confirmed it's not a general connectivity issue), so
neither could be verified at all; both are `NOT_IMPLEMENTED` pending
verification from a network that can reach them. All three remain seeded
`NOT_IMPLEMENTED` from 3a — this sub-phase confirmed why, rather than
leaving it unexamined.

**Known limitations / decisions:**
- **One shared `evidence_observations` table, not one table per source.**
  3a's evidence-provenance shape was designed as a generic, reusable shape;
  with 7+ structurally similar new sources this sub-phase, one table with a
  `source` column and a `payload` JSONB is the generalization that shape was
  built for — `market_snapshots`/`news`/`screened_universe` stay dedicated
  tables because their columns are stable and well-known in advance, which
  isn't true of most of 3c's smaller, heterogeneous observations.
- **Glassnode/CryptoQuant deliberately not subscribed to.** MVRV/SOPR/NUPL/
  cohort data and BTC miner metrics are very likely behind a paid tier at
  either provider (confirmed both require an API key; free tiers are
  typically limited to basic price data) — a real recurring-dollar-cost
  decision, not a quick free signup like Etherscan/CoinMarketCap. Deferred
  rather than committed to without deliberate consideration.
- **Etherscan's large-transfer proxy is a narrower scope than full
  exchange-reserve tracking** — it counts transfers to/from two well-known
  public exchange addresses, not a comprehensive reserve-balance product,
  and has no entity-clustering behind it (conflates genuine whale activity
  with routine exchange-internal/protocol traffic — the same caveat
  `PHASE3C_PROMPT.md` itself calls out). Recorded in the observation's own
  payload, not just this doc.
- **Stablecoin supply *velocity*** (transaction volume relative to
  circulating supply) **was not built** — DefiLlama's stablecoins endpoint
  exposes supply figures but no transfer-volume field, and computing it
  properly needs on-chain transfer aggregation beyond this sub-phase's
  scope. Supply *growth* (7d/30d) is captured; velocity is not.
- **Exchange reserve balances were not built** — same reasoning: a real
  reserve-tracking product needs a curated, maintained set of known
  exchange wallet addresses per asset, which is its own research effort
  beyond what a free/cheap tier reasonably supports right now.

## Phase 3d — Multi-model current market assessment (`--with-assessment`)

`python -m app.main --with-assessment` runs, on top of the latest
`--with-screening` run's `TOP_CANDIDATES` (requires at least one prior
screening run; warns and does nothing if none exists — no silent fallback to
a stale or arbitrary universe):

1. **One shared context per run** (`app/llm/assessment_context.py`) — every
   candidate's prompt carries the **same** `market_regime_snapshots` row (3b),
   so models reason from one consistent regime label rather than each
   inferring their own. Per-asset context adds: current price/volume/change
   (Phase 1), the deterministic `composite_factor_score` and any screening
   anomaly flag (3b), every derivatives/on-chain observation on record for
   that asset (3c), recent relevant news (Phase 2), and current portfolio
   status (3a).
2. **Sanity/bad-tick check** (task 6) — before context is built, each asset's
   recent stored snapshots are run through 3b's existing `detect_anomaly()`
   (reused, not reimplemented); a flagged asset gets an explicit "possible bad
   tick, treat with caution" warning injected into its prompt rather than
   being silently excluded or handed to the model uncaveated. Covered by
   dedicated unit tests (a synthetic price-spike case, an ordinary-data case,
   and an insufficient-history case) since real live data is not guaranteed
   to contain a bad tick on any given run.
3. **Three independent models via OpenRouter** (`app/llm/assessment_provider.py`)
   — Claude, OpenAI, and Gemini (Phase 2's existing three; see decisions
   below), one batched call per provider covering every candidate in the run,
   validated against a strict Pydantic schema
   (`app/llm/assessment_schemas.py`) with the same retry-once-on-invalid-JSON
   pattern as Phase 2. One provider failing never blocks the others.
4. **Model agreement** (`app/llm/assessment_agreement.py`) — the fraction of
   models agreeing with the majority `overall_assessment` direction, computed
   once per asset per run across all configured models, then denormalized
   onto every model's row for that asset/run. Verified live to be genuinely
   distinct from — and not derived from — any individual model's confidence:
   in the run below, BTC/BNB/SOL/HYPE/LINK/NEAR/XRP show `model_agreement=1.0`
   (unanimous), while ZEC/XMR/UNI show `model_agreement=0.667` (2-of-3 split),
   with each model's own confidence values still varying independently
   underneath (e.g. BTC's three models returned short-term confidence 0.5,
   0.6, and 0.62 despite unanimous agreement).
5. **Prompt-template versioning** (`app/database/repository.py`'s
   `PromptTemplateRepository`, `prompt_templates` table from 3a) — the
   rendered system prompt's hash and version are inserted (or reused, keyed
   on name+stage+version+hash) once per run, and every
   `model_market_assessments` row stores that row's id, not a copy of the
   prompt text.
6. **New table** `model_market_assessments` (migration `0006`) — one row per
   (run, asset, provider): short/medium/long-term direction + confidence,
   expected return at 7d/30d/90d, risk score/level, the shared market regime,
   model agreement, thesis, key drivers/risks, per-source assessment,
   invalidation conditions, and the raw response — **this asset's own slice**
   of the batch response, not the full multi-asset payload (same
   cost-hygiene fix applied to Phase 2's `LLMResearchService`).

**Live-verified** (queried Supabase directly, not just a passing test —
per the standing lesson from 3c that a clean-looking report can still hide a
real gap): a combined `--with-screening --with-derivatives --with-assessment`
run against the 10 real `TOP_CANDIDATES` of that run produced exactly 30
`model_market_assessments` rows (10 assets × 3 models), one shared
`prompt_templates` row referenced by every one of them, one shared
`market_regime` (`RISK_ON`) and `data_cutoff_timestamp` across all three
providers per asset, and the model-agreement split described above. Total
cost for that run: **$0.4115** (claude $0.1313, openai $0.1292, gemini
$0.1510) — confirmed via `CostGuard`'s cumulative-spend sum, which correctly
included both `llm_analyses` and `model_market_assessments` in the same 24h
window ($0.7207 combined that day). At 10 `TOP_CANDIDATES` and 3 models, this
stage costs ~$0.41/run regardless of candidate count changes within reason
(one batched call per provider, not per asset) — comfortably inside
`MAX_DAILY_LLM_COST=5.00` even at several runs/day; no schedule/cadence is
built yet (each `python -m app.main` invocation is a manual/on-demand run).

**Known limitations / decisions:**
- **Grok (xAI) deferred, not built.** `PHASE3D_PROMPT.md` offered it as an
  optional fourth model; the explicit choice here was to keep this
  sub-phase's change isolated to the richer context (regime + 3c evidence +
  sanity check) rather than also changing the model set, so any behavior
  shift this round has one cause, not two confounded ones. Addable later via
  `OPENROUTER_ASSESSMENT_MODELS=claude:...,openai:...,gemini:...,grok:...`
  with zero code changes, once Claude/OpenAI/Gemini have a baseline to
  compare a fourth model against.
- **Langfuse tracing skipped.** Optional per the prompt; most valuable once
  there's real call volume and multiple prompt versions to A/B, which starts
  mattering from 3e's decision-outcome ledger onward, not now.
- **A parallel `OpenRouterAssessmentProvider`/`AssessmentProviderResult`
  class, not a generalized Phase 2 `OpenRouterProvider`.** Phase 2's provider
  is hardcoded to validate `AnalysisBatch`; generalizing it to also handle
  `AssessmentBatch` would mean changing an already-shipped, live-verified
  class's signature across every existing call site and test. Duplicating
  the retry/content-extraction/token-summing logic costs some repetition but
  carries zero regression risk to Phase 2 — a deliberate trade-off, not an
  oversight.
- **Assessment target is exactly 3b's latest `TOP_CANDIDATES`, nothing wider
  or narrower.** No silent fallback: if `--with-screening` has never been
  run, `--with-assessment` logs a warning and does nothing, rather than
  guessing a universe.

## Phase 3e — Judge, Risk Engine, Portfolio Construction, calibration (`--with-judge`, `--evaluate-outcomes`)

`python -m app.main --with-judge` runs, over the same latest `TOP_CANDIDATES`
3d assessed (requires a prior `--with-assessment` run; warns and does nothing
otherwise):

1. **Judge** (`app/judge/`) — one LLM call per run (single synthesizing
   model, not an ensemble — the ensemble already happened in 3d) reasoning
   over: 3b's screening factors + `composite_factor_score` + regime
   (including BTC dominance/altseason/halving-cycle position), 3c's
   derivatives/on-chain evidence (with `freshness`/`decay_half_life_hours`
   shown explicitly per source), 3d's model assessments + its computed
   `model_agreement`, Phase 2's prior `llm_analyses`, recent news, and
   current portfolio status/allocation. Outputs one structured decision per
   asset (`BUY`/`HOLD`/`SELL`/`WATCH`/`NO_TRADE`), persisted in full to
   `judge_decisions` (thesis, key/contradictory evidence, key risks,
   invalidation conditions, `estimated_cost`) — a new, parallel evidence
   type again duplicating Phase 2/3d's provider-class pattern
   (`OpenRouterJudgeProvider`) rather than generalizing either shipped class,
   same deliberate zero-regression trade-off as 3d's.
2. **Risk Engine** (`app/risk/`) — deterministic, AI-uninfluenced, over the
   Judge's *unconstrained* `target_allocation`:
   - A confidence gate (`MIN_BUY_CONFIDENCE`/`MIN_SELL_CONFIDENCE`/
     `MIN_REBALANCE_CONFIDENCE`) that can downgrade a low-confidence BUY to
     WATCH or a low-confidence SELL to HOLD before any sizing happens.
   - **Volatility-adjusted sizing**: an inverse-volatility scalar
     (`RISK_TARGET_VOLATILITY / asset_volatility`, capped at 1.0 — this only
     ever de-risks, never levers up) composed with an **agreement-aware**
     scalar (average of `model_agreement`/`source_agreement`, floored at
     0.3) — the two compose multiplicatively, neither alone determines size.
   - Hard caps: `MAX_SINGLE_ASSET_ALLOCATION`, `MAX_NEW_POSITION_SIZE` (new
     positions only), and `MAX_WEEKLY_TURNOVER` (scales every proposed
     change down proportionally, fairly, if the trailing 7-day budget would
     be exceeded — never picks winners).
   - A **correlation-concentration flag** (`app/risk/correlation.py`): a
     pairwise Pearson correlation matrix over held/candidate assets' actual
     stored `market_snapshots` returns, flagging (not blocking) pairs at/
     above `CORRELATION_FLAG_THRESHOLD` that are both being increased.
3. **Portfolio Construction** (`app/portfolio/`) — classifies each
   Risk-Engine-adjusted decision into INITIATE/INCREASE/HOLD/REDUCE/REMOVE/
   HOLD_CASH against the paper book's actual current state (new
   `portfolio_positions`/`portfolio_allocation_changes` tables — see
   decisions below), and applies a capacity-driven **replacement rule**:
   above `MAX_CONCURRENT_POSITIONS`, a new candidate may only bump an
   existing holding when its `risk_adjusted_alpha` (`expected_alpha /
   max(risk_score, 0.05)`) clears the incumbent's by
   `MIN_REPLACEMENT_ALPHA_ADVANTAGE`; otherwise the new candidate is simply
   blocked (stays at 0 allocation) rather than exceeding capacity.
4. **Continuous decision-outcome ledger** — every Judge decision opens one
   `decision_outcomes` row (3a schema) with a lightweight triple-barrier
   target/stop (`app/benchmarks/triple_barrier.py`: derived from the Judge's
   own `expected_return`/`risk_score`, a floor of ±5% so a near-zero
   `expected_return` still gets a workable barrier), `regime_at_decision`,
   `judge_confidence`, and `in_holdout_window = true` — see the held-out
   window note below. `python -m app.main --evaluate-outcomes` (independent
   of every other flag, zero LLM cost) walks forward through real subsequent
   `market_snapshots` and backfills `HIT_TARGET`/`HIT_STOP`/`TIMED_OUT`,
   leaving genuinely-too-recent decisions `UNRESOLVED`.
5. **Baseline calibration script** (`scripts/calibration_baseline.py`) —
   checks Phase 1/2's existing `llm_analyses` directional calls against
   actual subsequent `market_snapshots` price movement, reporting
   directional hit-rate AND a Brier score + confidence-bucket reliability
   breakdown (two different claims — see findings below). Persists every
   invocation to `calibration_runs` as a countable attempt, per task 5.

**Live-verified** (queried Supabase directly and cross-checked against the
real deterministic formulas, not just passing tests or clean-looking logs —
per the standing lesson from 3c):
- A combined `--with-screening --with-derivatives --with-assessment
  --with-judge` run persisted exactly 10 `judge_decisions` rows (one per
  `TOP_CANDIDATE`) and 10 matching `decision_outcomes` rows, each correctly
  referencing its `judge_decisions.id`, `regime_at_decision`, and
  `judge_confidence`, all with `in_holdout_window = true`.
- Reachable decisions confirmed live: `BUY`, `HOLD`, and `WATCH` all occurred
  across three runs (e.g. ZEC/XMR got WATCH with a genuinely coherent "wait
  for X to resolve" thesis, not a default), and `requires_review = true`
  fired on 19 of 30 live decisions, correlated sensibly with lower
  confidence. `NO_TRADE` did not occur within 3b's screening-filtered
  `TOP_CANDIDATES` across those three runs — investigated directly rather
  than assumed: a genuine adversarial test (a real tracked asset deliberately
  outside `TOP_CANDIDATES`, given a maximally split 3-model ensemble,
  0.08 composite score, a screening anomaly flag, and stale/thin derivatives
  evidence) produced a real, live `NO_TRADE` from the actual model on the
  first attempt (`confidence=0.15`, thesis: *"Evidence is too thin, stale,
  and internally contradictory to support any actionable thesis... This is a
  case for NO_TRADE rather than manufacturing a directional or watch thesis
  from noise."*) — confirming `NO_TRADE` is genuinely reachable by the real
  model when warranted, not just in a unit fixture, and supporting the
  explanation below (TOP_CANDIDATES are pre-filtered for quality) over a
  residual action-bias theory.
- Recomputed the Risk Engine's exact sizing formula against the real stored
  `volatility_30d`/`model_agreement`/`source_agreement` values and confirmed
  it matches the persisted `portfolio_positions` allocations exactly — e.g.
  HYPE (`volatility_30d=0.045`) got `vol_scalar=0.663` vs. BTC's
  (`volatility_30d=0.024`) `vol_scalar=1.0` at the same target allocation
  ask, and BTC's `agreement_scalar=0.775` (model_agreement=1.0 but
  source_agreement=only 0.55) visibly shrank its position relative to a
  unanimous-agreement asset — proving the mechanism runs for real in the
  live path, not only in isolated unit tests.
- The correlation flag fired live and unprompted: `Correlated with SOL at
  0.93 (both being increased)` on BTC/SOL in a real run (only surfaced after
  a fix — see decisions below).
- `--evaluate-outcomes` ran against real data: correctly found entry prices
  for all 30 open decisions and correctly left all 30 `UNRESOLVED` (every
  decision's horizon — 21 to 90 days — is still far in the future relative
  to this project's ~2-day-old history); the `HIT_TARGET`/`HIT_STOP`/
  `TIMED_OUT` resolution paths themselves are covered by dedicated unit
  tests with synthetic past-horizon data, since no real decision has aged
  into resolution yet.
- `scripts/calibration_baseline.py --horizon-days 1` (shortened from the
  default 7 — see decisions below) against 144 real `llm_analyses` rows
  produced a genuine baseline: **hit_rate = 0.706, brier_score = 0.229** over
  51 scored BUY/SELL rows (45 HOLD rows excluded, no directional claim to
  score), with a real reliability-by-bucket breakdown showing the
  confidence~0.8 bucket hitting only 62.5% versus confidence~0.6 hitting
  87% — a genuine, useful overconfidence-at-the-top finding, not a clean
  number. Both this run and the null 7-day attempt are persisted to
  `calibration_runs` as separate, countable attempts.
- `judge_decisions` confirmed registered in `COST_TRACKED_TABLES`
  (`app/llm/cost.py`), with a test proving `CostGuard`'s cumulative sum
  reflects an inserted row, and live cost was $0.0155/asset ($0.155 for the
  10-candidate run).
- Full `pytest` suite green (226 tests) throughout.

**Known limitations / decisions:**
- **`NO_TRADE` did not occur within 3 organic live runs against real
  `TOP_CANDIDATES` — confirmed genuinely reachable, not a latent bug, via a
  targeted adversarial test.** Investigated in two stages, not left as an
  assumption: (1) the first prompt draft used the same phrase ("genuinely
  conflicting evidence") to describe both `WATCH` and `NO_TRADE`, which the
  live model resolved by always picking `WATCH` — a real prompt-clarity bug,
  fixed by sharpening `WATCH` ("a real thesis, waiting on a specific
  condition") vs. `NO_TRADE` ("no actionable view at all") and bumping
  `JUDGE_PROMPT_VERSION` to `v2`; (2) after the fix, still zero live
  `NO_TRADE`s on organic `TOP_CANDIDATES`, so a real tracked asset deliberately
  outside `TOP_CANDIDATES` was fed a maximally split 3-model ensemble, a weak
  composite score, a screening anomaly flag, and stale/thin derivatives
  evidence, through the real `OpenRouterJudgeProvider` — the live model
  returned `NO_TRADE` on the first attempt. This confirms `TOP_CANDIDATES`
  being pre-filtered for quality (not residual action bias) explains why it
  hasn't surfaced organically yet — worth re-checking once the tracked
  universe or a weaker market regime surfaces a genuinely marginal
  `TOP_CANDIDATE`.
- **New `portfolio_positions`/`portfolio_allocation_changes` tables
  (migration `0007`), not anticipated by 3a.** 3a reserved `judge_decisions`/
  `decision_outcomes`/`calibration_runs` empty for this sub-phase, but never
  anticipated that Portfolio Construction would need a real *numeric*
  current-allocation-per-asset state — `assets.in_asset` is a plain boolean
  with no size. No seed data: every asset starts at allocation 0 until the
  first live run assigns one, since Phase 1/2's `in_asset` flag was never a
  sized position.
- **Calibration baseline horizon shortened to 1 day (from a 7-day
  default).** This project's actual historical data (both `llm_analyses` and
  `market_snapshots`) only spans about 2 days so far — a 7-day horizon
  genuinely resolves zero rows right now, which the script correctly
  reported (persisted as its own null-valued countable attempt) rather than
  silently falling back to a shorter window. Re-run at the default (or a
  properly chosen) 7-day horizon once more calendar time has passed.
- **Held-out window boundary: 2026-09-05T17:07:49Z** — the `decision_timestamp`
  of this sub-phase's first live Judge decision. Every `decision_outcomes`
  row is stamped `in_holdout_window = true` unconditionally from this
  sub-phase onward (not a random subset) — the commitment is to never tune
  Judge prompts/Risk Engine formulas/Portfolio Construction logic against
  live decisions from this point forward, so 3f/3g's "did accuracy actually
  improve" comparisons mean something.
- **Replacement logic is scoped to assets judged in the SAME run only** — a
  new candidate can only displace an existing holding that also has a fresh
  `risk_adjusted_alpha` from this run's Judge output; an idle holding outside
  today's `TOP_CANDIDATES` is never displaced without fresh evidence.
- **A third parallel `OpenRouterJudgeProvider`** — same deliberate
  duplicate-over-shared-abstraction-risk trade-off as 3d's, applied again
  rather than generalizing either of the two already-shipped, live-verified
  provider classes.

## Phase 3e.1 — Retroactive historical replay (`scripts/run_replay.py`)

Re-runs 3e's exact model-assessment → Judge → Risk Engine → Portfolio
Construction pipeline, unmodified, against a past date range — so real
calibration signal starts accumulating immediately instead of waiting weeks
for live decisions to age into resolution. A diagnostic supplement, never a
substitute for the live, continuously-accumulating baseline: reported as a
completely separate number, never blended into one figure.

**Evidence-feasibility classification** (task 1, `app/benchmarks/replay.py`'s
`EVIDENCE_UNAVAILABLE_FOR_REPLAY`) — decided before writing the replay
runner, not worked out after the fact:
- **Backfillable, and used:** price/volume/OHLCV (Binance primary, Coinbase
  fallback — same source order as 3b's live screening, new
  `fetch_daily_ohlcv_with_timestamps` methods added to both clients since the
  existing live methods discard the date), and **Binance's genuinely
  historical funding-rate series** (`/fapi/v1/fundingRate` — verified live to
  return real past observations timestamped by `fundingTime`, not today's
  rate backdated). News (Phase 2's real stored articles, filtered by their
  own real `published_at` against the replay's `until` cutoff — already
  point-in-time-safe with no changes needed) and portfolio/LLM-analysis
  history (via two new as-of-safe repository methods,
  `get_latest_status_as_of`/`get_latest_by_asset_as_of`).
- **Not reliably backfillable, marked UNAVAILABLE, disclosed every replayed
  day, never fabricated:** everything else 3c supplies — dated-futures term
  structure/carry, aggregate open interest, Deribit options/VRP, CME COT,
  DefiLlama TVL, stablecoin supply/velocity, Etherscan transfers, on-chain
  valuation/miner metrics, spot ETF flows, prediction markets, token unlocks
  — plus regime-level BTC dominance and the altcoin-season index (both need
  either universe-wide historical market cap or CoinMarketCap's 90d field,
  neither a fixed reconstructable value for a past date with this system's
  sources).
- The screening/regime universe itself is scoped to the 21 **currently
  active tracked assets**, not 3b's wider 30-asset CoinGecko-discovered
  universe — CoinGecko's top-markets endpoint only exposes today's ranking,
  not a historical one, so re-deriving which assets would have ranked as
  `TOP_CANDIDATES` on a past date isn't reconstructable. A documented scoping
  decision, not an oversight.

**Safety design:** Risk Engine and Portfolio Construction run completely
unmodified, but against a fully isolated, in-memory-only simulated portfolio
state (`app/benchmarks/replay_fakes.py`) — a backfill run never reads or
writes the live `portfolio_positions`/`portfolio_allocation_changes` tables.
`judge_decisions`/`decision_outcomes` rows ARE persisted for real (migration
`0008` adds `is_backfilled`), always tagged `is_backfilled = true` and
`in_holdout_window = false` — backfilled rows are never forward-tracked
evidence, per the sub-phase's own non-negotiable.

**Live-verified, closed at 13 of the intended 28 days** (2026-08-09 through
08-19, plus the 2 validation days 09-04/09-05 run first to confirm
correctness on a short window before scaling up, per the sub-phase's own
guidance) — cut short by the OpenRouter account's real balance running out
mid-run (confirmed directly via OpenRouter's `/api/v1/credits` and `/api/v1/key`
endpoints: the account had ~$0.36 of its $105 total left, and the API key in
use had its own separate $20 sub-limit with ~$7 remaining — a real-money
constraint, not a bug in this system), not any technical or design failure:
- 129 `judge_decisions` rows and 129 matching `decision_outcomes` rows
  persisted across the 13 days, all confirmed `is_backfilled = true` and
  `in_holdout_window = false` by direct query — zero mistagging in either
  direction (no backfilled row missing the tag, no live row incorrectly
  tagged), checked against all 159 `judge_decisions` rows in the database.
- Every reachable decision value genuinely occurred: `WATCH`=47, `BUY`=42,
  `NO_TRADE`=21, `HOLD`=14, `SELL`=5 — including real `SELL` and far more
  `NO_TRADE` than any live run has produced, consistent with replay's
  genuinely thinner reconstructed evidence set surfacing more low-conviction
  cases. `requires_review = true` on 85 of 129 (66%).
- **The triple-barrier outcome resolution genuinely works on real
  backfilled data**, not just synthetic unit fixtures: 109 of 129 outcomes
  already resolved (103 `HIT_TARGET`, 6 `HIT_STOP`), immediately upon
  creation, by walking forward through the same fetched historical series
  used for reconstruction (not the live `market_snapshots` table, which only
  has ~2 days of real history and would have silently under-resolved almost
  everything — a deliberate scoping choice, see decisions below). Only the
  20 most recent decisions (from 09-04/09-05) remain genuinely `UNRESOLVED`,
  correctly, since not enough real time has passed for their horizons yet.
- `scripts/calibration_baseline.py --source backfill` produced a real,
  separate baseline: **hit-rate 0.833, Brier score 0.195** over 36 scored
  BUY/SELL decisions (93 HOLD/WATCH/NO_TRADE rows correctly excluded — no
  directional claim to score), persisted to `calibration_runs` with
  `method=BACKFILL_BASELINE`, distinct from and never combined with the
  live/Phase-2 forward-tracked baseline.
- `pytest` green throughout (242 tests, including a dedicated combined
  regression test for the incident below).

**A real incident during this sub-phase, not glossed over — the CostGuard
blind spot:** live-verifying the first larger continuation chunk revealed
that `CostGuard`'s daily/monthly cap check never actually saw the replay's
own spend for any date not coinciding with the real calendar day. Root
cause: `judge_decisions.created_at` was set to the *simulated historical
date* being replayed rather than the row's real insertion time, and since
`CostGuard` sums cost by `created_at >= today's midnight`, every
August-dated backfilled row was permanently invisible to the cap check — it
could have run indefinitely without ever tripping the daily/monthly cap.
A second, related gap compounded it: the assessment stage's cost is never
persisted to any table at all (by design, to avoid writing backfilled rows
into the live `model_market_assessments` table), so even a corrected ledger
could only ever see the Judge-stage third of the replay's true spend.
Fixed with two changes, not one: (1) `created_at` is now always
`datetime.now(UTC)` — the row's real insertion time; the simulated date
remains fully recoverable from `run_id` (e.g. `BACKFILL-2026-08-09`); (2)
`HistoricalReplayService` now snapshots the real remaining budget once via
a new `CostGuard.remaining_budget()` method, then tracks its own spend
in-process against that snapshot for the rest of the run — so it self-gates
correctly regardless of what does or doesn't get persisted to any table.
Verified with a combined regression test (`test_regression_incident_both_
bugs_covered_together`) that reproduces both mechanisms together — a
realistic ledger reading only `judge_decisions` (mirroring production
exactly) is shown to structurally under-count true spend, and the run is
confirmed to still be correctly bounded by the true total via local
tracking regardless. A related, lower-confidence finding from the same
incident: every HTTP client in this codebase set an explicit timeout except
the Supabase client (silently defaulting to supabase-py's 120s) — hardened
to 30s defensively, though this couldn't be conclusively proven as the
cause of the specific multi-minute hangs observed (no crash logs survive a
killed process); those hangs turned out to be intermittent, not
reproducible on demand, and are the reason later chunks were run as
small, background-launched, explicitly-verified-killable windows rather
than one long unattended invocation.

**Known limitations / decisions:**
- **Closed at 13/28 days by a real budget constraint, not a technical
  ceiling.** The remaining 15 days (2026-08-20 through 09-03) were not
  replayed. This is a deliberate, explicit stopping point — resuming later
  requires only re-running `scripts/run_replay.py --start 2026-08-20 --end
  2026-09-03` once the OpenRouter account has real balance again; nothing
  about the 13-day result needs redoing.
- **Outcome resolution reuses `evaluate_triple_barrier` directly but reads
  from the replay's own fetched historical series, not the live
  `OutcomeEvaluationService`/`market_snapshots` table** — deliberately, since
  this project's real snapshot history is only ~2 days deep and would have
  left nearly every backfilled decision perpetually `UNRESOLVED` for no
  genuine reason.
- **The `Bash` tool's `timeout` parameter does not kill a hung process** —
  discovered empirically (not assumed) with a deliberate `time.sleep(999)`
  test: the process was still verifiably alive after its timeout elapsed.
  `timeout` only bounds how long the tool waits synchronously before handing
  back a background task id; an actual kill requires an explicit stop call,
  confirmed to work via the same empirical test.
- **Each real invocation of the replay's simulated portfolio state starts
  fresh at zero allocations** — splitting the window across multiple
  process invocations (unavoidable given the real per-day/per-month cost
  caps) means Portfolio Construction's replacement/turnover dynamics are
  continuous only *within* one invocation's chunk, not across the whole
  13-day result. This doesn't affect the core calibration signal
  (`judge_decisions`' direction/confidence, `decision_outcomes`'
  resolution), which is 3e.1's actual payoff — only the simulated sizing
  narrative is chunk-local.

## Phase 3f — Adversarial research, macro matrix, remaining fragile sources (`--with-adversarial`, `--with-macro`)

The last evidence/decision-pipeline sub-phase of Phase 3 (3g, statistical
validation, follows next). Two new zero-and-non-zero-LLM-cost collection
stages plus a Judge extension, built and live-verified in that order.

### Feasibility findings (task 1) — decided before writing any provider code

**Confirmed working, built:**
- **Upbit** (regional exchange premium) — free, public, no key; verified
  live with real KRW-BTC ticker data.
- **SEC EDGAR full-text search** (regulatory calendar, US side) — free,
  official, no key (just a descriptive `User-Agent` per SEC's fair-access
  policy); verified live with real 8-K filing hits.
- **congress.gov** (regulatory calendar, legislative side) — free, official,
  key-gated (a quick signup, not a paid relationship); verified live with
  real bill data. No server-side full-text/keyword search on the bill-list
  endpoint (verified live: date-range filtering works, keyword filtering
  does not) — titles are keyword-matched client-side instead.
- **FRED** (Federal Reserve Economic Data) — free, official, key-gated (a
  quick signup); verified live against every series this project uses
  (`M2SL`, `WALCL`, `RRPONTSYD`, `SP500`, `DTWEXBGS`, `DEXKOUS`, plus the
  release-date endpoints for CPI/PCE/NFP). FRED's own historical gold-price
  series (`GOLDAMGBD228NLBM`) has been discontinued (verified live: "the
  series does not exist") — gold correlation instead uses **PAXG**
  (tokenized gold) via the already-integrated Binance/Coinbase clients, a
  real live-verified price (~$4432/oz, matching within cents across both
  venues) — no new vendor dependency.

**Confirmed genuinely infeasible:**
- **CryptoBubbles** — no documented API found (a guessed data endpoint
  returned 404); `robots.txt` explicitly disallows `ClaudeBot` site-wide.
- **CoinAnk** — the site is behind a BytePlus WAF bot-challenge (a JS
  challenge page, no accessible endpoint or `robots.txt`) — no legitimate
  API surface exists to build against.

**Confirmed real, deliberately deferred:**
- **CoinGlass** (liquidation heatmap) — a real, official, documented API
  exists, but is API-key-gated with tiered paid plans (Startup/Standard/
  Professional); no usable free tier confirmed. Same category as
  Glassnode in 3c — a real recurring-cost decision, deferred, not a
  technical failure.
- **LunarCrush** — even the "public" v4 endpoint requires an auth token; no
  anonymous access at all. Deferred alongside CoinGlass.
- **PlanB/X (via xAI)** — xAI's API is live and functional (verified a real
  auth-challenge response confirming the endpoint works), but no paid API
  relationship was established for this source — a deliberate choice, not
  an access failure.
- **Santiment** (social/narrative sentiment) — genuinely accessible with NO
  key for a real anonymous free tier (verified live: real
  `social_volume_total` time-series data returned), but restricted to data
  at least ~30 days old — unusable for this system's actual use case
  (current-sentiment reads for live decisions), so recorded `NOT_IMPLEMENTED`
  rather than wired in for a purpose it can't serve.

All nine of the above sources are reaffirmed live every `--with-macro` run
with real investigation notes — the exact discipline a 3c live-verification
incident established (a status never actually re-checked by code looks
identical, in a clean report, to one genuinely reaffirmed).

### What was built

1. **Macro matrix** (`app/market_data/macro_service.py`) — CPI, PCE, initial
   claims, payrolls, 10Y Treasury yield, and the effective fed funds rate,
   each reporting `actual` vs. `previous` (no free source for economist-
   **consensus** estimates was found — `surprise`/`consensus` are honestly
   `null`, never fabricated).
2. **Forward-looking macro-event calendar** — real, discrete CPI/PCE/NFP
   release dates via FRED's `release/dates` endpoint. **FOMC excluded**:
   FRED's "FOMC Press Release" release id (101) does not behave as a
   discrete meeting calendar — verified live it returns a release date for
   *every single day*, not ~8 meetings/year — so it's left out rather than
   silently faked as a real calendar.
3. **Global liquidity** (M2, Fed balance sheet, reverse repo) and **BTC's
   rolling 30d/90d correlation** to S&P 500, gold (PAXG), and DXY — computed
   deterministically from real stored/fetched price series, never
   editorialized into a signal at the collector level.
4. **Regional exchange premium** — Upbit KRW-BTC vs. the global USD price,
   converted via FRED's real KRW/USD rate (`DEXKOUS`).
5. **Regulatory event calendar** — SEC EDGAR (crypto-keyword full-text
   search) + congress.gov (keyword-matched bill titles), both **global/
   macro-scope only**: reliable per-asset attribution isn't achievable at an
   acceptable false-positive rate from a title/filing match alone, per the
   sub-phase's own explicit allowance for a narrower version.
6. **Adversarial research cycle** (`app/llm/adversarial_service.py`) — one
   model, three sequential batched calls covering every `TOP_CANDIDATE`:
   bull case → bear case (explicitly attacks the specific bull thesis,
   required to name which bull catalyst/evidence item each attack point
   rebuts) → bull/base/bear scenarios. Persisted to a new `adversarial_research`
   table (migration `0009`), registered in `COST_TRACKED_TABLES`. Uses a new,
   genuinely generic `OpenRouterStructuredProvider` (`app/llm/structured_provider.py`)
   parameterized by response schema — unlike Phase 2/3d/3e's provider
   classes, this one has no existing call sites to risk regressing, so a
   real generalization was the right call here, not a shortcut.
7. **Judge extension** (`app/judge/context.py`, migration `0010`) — the
   Judge now receives the shared macro/liquidity backdrop
   (`JudgeContext.macro_evidence`, one latest reading per single-value
   source), the forward-looking macro-event calendar and regulatory-event
   calendar as their own distinct multi-entry lists
   (`JudgeContext.scheduled_events`/`regulatory_events` — see the bug fixed
   below), and each candidate's bull/bear/scenarios
   (`AssetJudgeContext.adversarial`), and must produce a new required
   `macro_sensitivity` field — explicit, per-asset reasoning about how the
   shared macro backdrop affects *that specific asset*, never a blanket
   "liquidity up = bullish" rule. Both new inputs degrade gracefully to
   empty/`None` when unavailable (e.g. 3e.1's replay, which never collected
   macro/adversarial evidence) rather than requiring changes to
   already-shipped code.

### Live-verified findings

- **Cost, real per-stage breakdown** (not just a summed total, per explicit
  request): bull **$0.0515**, bear **$0.0911**, scenario **$0.0940** — total
  **$0.2366** for 10 candidates. All three came in well under the
  pre-verification estimate (~$0.48 total, anchored to Judge/assessment's
  real per-call costs) — and notably, the scenario call (carrying the most
  accumulated context: bull + bear + its own reasoning) did **not** cost
  noticeably more than bear, meaning input-token accumulation mattered less
  here than the estimate assumed. Full pipeline (assessment + adversarial +
  Judge) ≈ **$0.80/run**, comfortably inside `MAX_DAILY_LLM_COST` even at
  several runs/day — no candidate-count reduction needed.
- **Bull/bear is demonstrably adversarial, not generic**: UNI's live bear
  case directly quotes the bull thesis's own language ("Claude's own thesis
  states the price move has 'vastly outpaced' fundamental TVL growth...")
  and argues the TVL figure can't justify the composite-score claim; HYPE's
  bear case turns a data-quality flag from the bull thesis itself into an
  attack point and raises unlock/dilution risk the bull case never
  mentioned. `attacks_bull_point` correctly names the specific bull
  catalysts verbatim in both cases.
- **The Judge genuinely uses both new inputs, not just has them in
  context**: `macro_sensitivity` reasoning is real and per-asset, citing
  actual numbers (e.g. BNB: "...elevated 10Y yields (4.77%) and a
  near-zero reverse repo balance suggest limited fresh liquidity impulse
  feeding through to BNB specifically") and correctly differentiating asset
  classes (privacy coins reasoned as "idiosyncratic regulatory/narrative
  dynamics... limited direct read-through" vs. high-beta L1s reasoned as
  "benefits at the margin from RISK_ON" vs. XRP explicitly noting "no
  XRP-specific macro catalyst is present") — never one rule applied
  uniformly. Separately, UNI's `contradictory_evidence` directly quotes the
  bear case's exact phrasing, and both UNI's and HYPE's final confidence/
  decision were visibly tempered by the specific bear attack points, not
  just decoratively mentioning them.
- **Recalibration attempted honestly, not fabricated**: extended
  `scripts/calibration_baseline.py` with a `--source live` mode (splits real
  live Judge decisions into pre-3f/post-3f eras via `macro_sensitivity IS
  NOT NULL`, with a by-regime breakdown). Real result: **zero resolved
  decisions exist anywhere in the project yet** — all 40 live Judge
  decisions (30 pre-3f, 10 post-3f) are `UNRESOLVED` (real horizons of
  14–90+ days haven't elapsed), and only one regime (`RISK_ON`) has ever
  occurred in this project's real history. Persisted as two honest null
  attempts (`LIVE_PRE_3F_BASELINE`, `LIVE_POST_3F_BASELINE`, both
  `sample_size=0`) rather than a fabricated comparison.
- **Judge reasoning spot-check** (task 9): sampled 6 live decisions weighted
  toward `requires_review=true`/low-confidence/low-agreement. 5 of 6 showed
  the thesis directly and traceably following from `key_evidence`/
  `contradictory_evidence`, correctly reflecting genuine tension rather than
  glossing over it (e.g. ZEC's WATCH thesis correctly weighs the bull-side
  quant strength against negative funding, a bearish model outlier, and
  unaddressed regulatory tail risk). One minor wording ambiguity found, not
  a synthesis error — see decisions below. Findings logged, not used to
  auto-correct the Judge this sub-phase, per the prompt's own instruction.
- `pytest` green throughout (287 tests).

**A real incident during this sub-phase — two FRED bugs, found and fixed
live:**
1. `FredClient.fetch_recent_observations` used `sort_order=asc` + `limit`,
   which FRED interprets as "the *oldest* N observations from the series'
   entire history" (e.g. SP500 from 2016, DTWEXBGS from 2006), not the most
   recent N — this silently produced **zero** shared trading days between
   BTC and SP500/DXY, so correlation for those two references was silently
   never computed. Fixed by requesting `sort_order=desc` (genuinely the most
   recent) then reversing to the oldest-first contract callers expect.
2. `FredClient.fetch_release_dates` needs `include_release_dates_with_no_data=true`
   — without it, FRED silently excludes exactly the future/not-yet-published
   dates this method exists to find (verified live: omitting it returned
   `count: 0` for a real, known upcoming CPI release date). Both were caught
   by live-verifying the actual returned data against expectations, not by
   the code merely running without error — the same discipline the 3c and
   3e.1 incidents established.
3. A smaller, related bug: gold-PAXG correlation was initially gated behind
   `FRED_API_KEY` being configured, even though it needs no FRED data at
   all (it's Binance-sourced) — caught by a test that legitimately expected
   it to work without a FRED key.
4. **A fourth bug, found during this task's own final self-check (task 10),
   after the Judge extension had already been reported as working**:
   `build_judge_context`'s macro-evidence collection used
   `macro_evidence.setdefault(obs.source, ...)` — correct for a genuine
   single-value "latest reading" source (e.g. `macro_cpi`), but silently
   wrong for a source name shared by many distinct real observations. Two
   sources hit this: `scheduled_macro_event` (22 real rows, spanning 11
   distinct CPI/PCE/NFP dates through December 2026 — only 1 survived) and
   `regulatory_event_sec_edgar`/`regulatory_event_congress` (45 real rows —
   only 1 survived). The forward-looking calendar and regulatory calendar
   both genuinely existed in the database exactly as designed, but the
   Judge only ever saw one arbitrary entry from each — a gap invisible from
   a passing test suite or a clean run log, only caught by directly
   querying `EvidenceObservationRepository.get_latest_global_all()` and
   counting real rows per source. Fixed by routing these two source
   families into their own deduped-by-content lists
   (`JudgeContext.scheduled_events`, `JudgeContext.regulatory_events`,
   the latter capped at `MAX_REGULATORY_EVENTS_SHOWN=10`) instead of the
   single-value `macro_evidence` dict, and rendering both as their own
   labeled sections in the Judge prompt. Live re-verified with zero LLM
   cost (pure context-building, no model call involved): rebuilding the
   real Judge context against live Supabase data now surfaces all 11 real
   distinct scheduled dates and 10 (of 20 real, capped) distinct regulatory
   filings in the actual rendered prompt text, not just one of each. Three
   regression tests added directly targeting this bug class.

   **Both the task 9 reasoning spot-check and the earlier live `--with-judge`
   run predate this fix** — their persisted decisions were built against the
   buggy single-entry context, so a fresh live decision was pulled
   post-fix (run `RUN-20260906-080647`, real cost **$0.2407** across 10
   decisions) to confirm the Judge's *reasoning*, not just the prompt text,
   genuinely engages with more than one scheduled-event entry. Confirmed:
   SOL's and DOGE's `invalidation_conditions` both name two distinct real
   dates from the calendar by role — "a macro risk-off shock around the
   2026-09-11 CPI or 2026-10-02 NFP prints before horizon" (SOL) and "watch
   macro prints: CPI 2026-09-11, NFP 2026-10-02" (DOGE) — not a single
   generic date or a copy-pasted line, and consistent with the two distinct
   real release dates nearest the decision horizon. This is a genuine
   reasoning-level confirmation, not merely a prompt-rendering check.

### Known limitations / decisions

- **FOMC meeting dates are not in the forward-looking calendar** — FRED's
  only plausible release id for this doesn't behave as a real meeting
  calendar (see above); no other free, documented, official source was
  found within reasonable effort. CPI/PCE/NFP dates are real and populated.
- **No macro "surprise" (actual vs. consensus)** — FRED only publishes
  actual released values, never economist-consensus estimates; no free
  source for the latter was found. `actual`/`previous` are real; `surprise`/
  `consensus` are honestly `null`.
- **The regulatory event calendar is global/macro-scope only, never
  per-asset attributed** — a title/filing keyword match can't reliably
  distinguish "this SEC filing/bill concerns crypto broadly" from "this
  specifically affects asset X," per the sub-phase's own explicit
  allowance for a narrower version over an unacceptable false-positive
  rate.
- **congress.gov coverage is keyword-matched titles only** — the API has no
  server-side full-text/keyword search on its bill-list endpoint (verified
  live), so this is a naive keyword filter with the same false-positive/
  false-negative risk explicitly called out for this kind of extraction,
  not a claimed complete legislative feed.
- **CoinGlass, LunarCrush, and PlanB(xAI) deliberately deferred** — real,
  working access paths exist for all three, but each requires a new paid
  relationship (a subscription tier, or an xAI API account) that wasn't
  committed to this round. Binance funding rates (3c) and Santiment's
  lagged data already cover a meaningful slice of the underlying signal
  types.
- **The bull-rebuts-bear second pass was not built** — task 3's own
  language framed it as optional ("where practical"); kept to 3 calls to
  control cost, the same trade-off logic 3d used to defer Grok.
- **A minor prompt-clarity item, not a synthesis error**: one spot-checked
  decision (XRP, a live run on 2026-09-06) had `key_evidence` say "claude
  and openai cite strong medium-term momentum as the core bullish anchor"
  while `contradictory_evidence` said "all three models rate XRP NEUTRAL,
  not bullish" — these aren't strictly contradictory (a model can cite a
  bullish factor while still landing NEUTRAL overall) but read confusingly
  side-by-side. Didn't change the well-justified WATCH conclusion or invent
  anything; noted for future prompt wording, not acted on this sub-phase.
- **Recalibration (task 8) could not produce a real before/after number**
  — not a gap in the mechanism, a real fact about this project's age: zero
  live Judge decisions (pre- or post-3f) have had enough real time pass to
  resolve, and only one market regime has ever occurred. The `--source
  live` mode is built and ready to report a genuine comparison the moment
  real resolved data exists.
- **A third parallel provider-style class rationale, but genuinely
  different this time**: `OpenRouterStructuredProvider` generalizes over
  response schema rather than duplicating per-schema, unlike Phase 2/3d/3e's
  deliberately-separate provider classes — because it has no existing
  shipped call sites to risk regressing. Both trade-offs (duplicate vs.
  generalize) are deliberate, evaluated case-by-case, not a fixed rule.

## Phase 3g — Statistical validation & robustness

The last sub-phase before 3h (adaptive weighting/stress testing) and 3i
(a further evidence-collection addendum), and the gate this project treats as
the actual determinant of whether Phase 3's pipeline improved decision
quality, rather than a raw before/after delta. Changes no evidence
collection and no decision logic — produces findings and recommendations
only, per its own non-negotiable, even where a finding clearly warrants a
follow-up change.

### Task 1: trial-count reconstruction

Walked `prompt_templates` (4 rows: `market_assessment` v1, `judge_decision`
v1 and v2, `adversarial_research` v1) and `calibration_runs` (5 rows) to
reconstruct an honest count of real calibration attempts. Finding:
**`judge_decision` v1 was never calibrated at all** — the 10 decision_outcomes
rows referencing it are all from one early live run
(`RUN-20260905-165829`), all still `UNRESOLVED`; v2 superseded it before any
resolved data ever existed to score it against. Of the 5 `calibration_runs`
rows, 2 (`phase2_llm_analyses_directional_baseline`) used an entirely
different mechanism (Phase 2's `llm_analyses` table directly, not
`judge_decisions`/`decision_outcomes` at all) and aren't comparable Judge
"trials"; 2 (`LIVE_PRE_3F_BASELINE`/`LIVE_POST_3F_BASELINE`) are honest null
attempts (sample_size=0); only 1 (`BACKFILL_BASELINE`) reflects a real
calibration against resolved outcomes, and it used only `judge_decision` v2.
**Honest trial count: 1** real configuration ever calibrated against
resolved data. `signal_sources.enabled` was checked as a possible second
counting dimension per the task's own wording — found to be a static value
seeded once in migrations and never toggled by any app code (`update_status`
only ever writes `status`, never `enabled`), so there is no real toggle
history to reconstruct; this dimension contributes nothing to the trial
count, reported as such rather than fabricated.

### Task 2: Deflated Sharpe Ratio / PBO

Implemented in `app/benchmarks/statistical_validation.py`: Probabilistic
Sharpe Ratio (Bailey & Lopez de Prado, 2012) built on Lo (2002)'s closed-form
Sharpe-ratio standard error, and Deflated Sharpe Ratio (Bailey & Lopez de
Prado, 2014) on top of that. Verified against known-correct outputs, not
just "plausible-looking code": PSR at `sharpe_ratio == benchmark_sharpe`
must equal exactly 0.5 for any n/skew/kurtosis (an exact mathematical
identity — tested); PSR independently cross-checked against Lo (2002)'s
formula recomputed a second, separate way in the test itself (not calling
the module's own helper) — matches to 1e-12; DSR at `n_trials=1` (this
project's real trial count) must reduce exactly to `PSR(0)`, since with only
one configuration ever tried there is no selection bias to correct for —
`n_trials=1` returning `expected_max_sharpe_under_null=0.0` is a genuine
degenerate case, not an approximation (the formula's own
`Φ⁻¹(1 - 1/1) = Φ⁻¹(0) = -∞` is undefined at n=1).

On the 36 directional (BUY/SELL) resolved backfilled decisions: **Sharpe
1.82** (skew −0.25, kurtosis 7.26 — noticeably fat-tailed), n=36. **DSR ≈
0.9998** at the real trial count of 1. **Caveat, load-bearing**: this is the
backfilled/simulated return series (11 replayed historical days), not live
paper-trading results, and applies zero multiple-comparisons correction
(correctly, for n_trials=1) — it says "distinguishable from zero on this
backfilled sample," not "expect this Sharpe going forward."

**PBO: not computable.** Requires ≥2 independently-tried configurations to
compare in-sample vs. out-of-sample rank (Bailey, Borwein, Lopez de Prado,
Zhu, 2014); this project has only ever calibrated 1. The CSCV method is
implemented and tested against the one case provable by hand construction
(two configurations, one a constant-shift-up of the other in every period —
proven by hand to always win in-sample AND out-of-sample, so PBO must be
exactly 0.0) plus a second hand-provable case (two literally identical
configurations tie on every split, so by the tie convention PBO must be
exactly 0.5) — **not** cross-checked against a published numeric worked
example, disclosed honestly rather than overclaimed, per the sub-phase's own
non-negotiable.

### Task 3: full calibration reporting

Brier score **0.195** (reliability 0.073, resolution 0.015, uncertainty
0.139). The classical 3-term Murphy (1973) decomposition
(`BS = Reliability - Resolution + Uncertainty`) is only an *exact* identity
when every point's forecast equals its bucket's mean — true for discrete
forecast values, false for continuous confidence values grouped into
ranges. Found this the hard way: an initial test asserting exact
reconstruction failed at the 3rd decimal (0.067 vs. 0.068) on real
continuous test data. Fixed by adding and reporting a fourth term,
`within_bucket_dispersion` — the information lost by substituting each
point's forecast with its bucket mean — making
`reliability - resolution + uncertainty + within_bucket_dispersion` an exact
identity for any bucketing, verified across several synthetic datasets. A
second real bug found the same way: `int(f / bucket_size)` misclassifies
exact bucket boundaries under float error (`0.3 / 0.1 == 2.9999999999999996`
truncates into the wrong bucket) — fixed with a small epsilon before
truncation, with a regression test targeting this exact float-boundary case.

Reliability by confidence bucket (all n small): 0.4–0.5 (n=4, 50% hit-rate),
0.5–0.6 (n=16, 87.5%), 0.6–0.7 (n=13, 84.6%), 0.7–0.8 (n=3, 100%) — hit-rates
run *above* stated confidence at every bucket (underconfidence, not
overconfidence), though n is small everywhere. By `model_agreement`: MED
n=19 (84.2%) vs. HIGH n=17 (82.4%) — **no evidence high agreement resolves
better than medium** at this sample size. By `source_agreement`: MED n=28
(78.6%) vs. HIGH n=7 (100%) vs. LOW n=1 — directionally consistent with
`source_agreement` earning its keep as a sizing input, but n=7/n=1 are too
small to call real.

**By-regime breakdown: not computable — a real persistence gap, not a
sample-size problem.** Every one of the 109 resolved backfilled outcomes has
`regime_at_decision = NULL`. 3e.1's replay computes a real
`MarketRegimeSnapshot` per simulated day and uses it live in the Judge's
prompt, but that snapshot is constructed with `id=None` and never persisted
to `market_regime_snapshots` — so `decision_outcomes.regime_at_decision`
(a real FK) has nothing to link to, for any backfilled row. The regime
string itself is not recoverable from the database for any backfilled
decision. Reported as a finding, not fixed — changing `replay.py` is outside
3g's scope (no new evidence collection or decision logic).

### Task 3a: point-in-time / look-ahead audit — CLEAN

Verified at the code level, not by re-trusting the design intent:
`HistoricalSeries.as_of` correctly slices to `date <= cutoff`; the funding-
rate evidence builder filters `funding_time <= cutoff` before selecting the
latest; Phase 2 LLM analyses and asset-status both route through genuine
`get_latest_by_asset_as_of`/`get_latest_status_as_of` point-in-time methods;
news correctly bounds `published_at <= until`. Every other revisable 3c/3f
source (on-chain valuation metrics, ETF flow figures, regulatory-event
extraction, ETF/CFTC positioning) was deliberately marked
`EVIDENCE_UNAVAILABLE_FOR_REPLAY` rather than reconstructed — exactly
avoiding the lookahead risk those sources pose. No contamination found in
any pathway replay actually uses.

### Task 3b: purged/embargoed walk-forward check — gap absent, primary blocker for task 7

**No embargo exists between the training (backfilled, `in_holdout_window=
false`) and holdout (live, `in_holdout_window=true`) samples.** The
backfilled decisions run 2026-08-09 through 2026-09-05; the live decisions
start 2026-09-05 — **the gap is negative** (≈ −1d23h; they overlap slightly
in wall-clock terms) against a **45-day** longest resolution horizon.
**100% of the 50 holdout decisions sit within one resolution-horizon's
distance of the training boundary.** Mitigating factor: the specific
slow-moving/sticky evidence types that pose the worst autocorrelation risk
(derivatives, on-chain) were excluded from replay entirely (see 3a above) —
but price-momentum/regime persistence (used in both sets) remains a real,
unaddressed leakage channel. This is not a defect in tasks 2–3's numbers
themselves (which are honest in-sample descriptions of the backfilled data);
it means a *future* "the holdout period confirms it" claim, once holdout
decisions resolve, would not constitute a clean, independent test without
first adding an embargo — the reason task 7 cannot issue a go/no-go on
sample-size grounds alone, even once more time passes.

### Task 4: held-out window — insufficient data

50 live decisions, all `in_holdout_window=true`, **zero resolved**. Horizons
present: 14/21/30/45 days; only ~1 day of real calendar time has elapsed
since the first live decision. Nothing to report yet beyond "wait" — and per
task 3b, even the eventual result will need the embargo caveat attached.

### Task 5: Judge reasoning audit

Formalized 3f's manual spot-check into a persisted, repeatable check — new
`judge_reasoning_audits` table (migration `0011`), registered in
`COST_TRACKED_TABLES` (tested). A single structured LLM call per sampled
decision, given ONLY that decision's own stored `thesis`/`key_evidence`/
`contradictory_evidence` (never live evidence, which may have since decayed
or resolved differently) — a pure internal-consistency check: does the
thesis actually follow from its own cited evidence.

Sampling (`app/benchmarks/reasoning_audit.py::select_audit_sample`) is
weighted, in priority order: outcome-contradicted-decision (rarest, most
diagnostic — all 6 real cases in this project's history), `requires_review=
true` (70 of 109 resolved), then low model/source agreement (<0.6, 59 of
109). Real cost, exact: a single test call **$0.002268** (confirmed real,
below even the low end of the pre-run estimate — this call's input is much
smaller than assessment/adversarial calls, just one decision's evidence text
plus a short instruction), then the remaining sample for **$0.024570**;
**$0.026838 total** across 9 calls (8 distinct decisions — one duplicate
occurred, see below).

**Real finding: 1 of 8 audited decisions (12.5%) shows a genuine
unsupported claim.** A SELL decision (`requires_review=true`,
model_agreement=1.0 but source_agreement=0.65, outcome contradicted the
call) recommended trimming exposure but never addressed its own cited
contradicting evidence (a slightly positive funding rate, flat-to-positive
90-day returns) and only nominally acknowledged a "still-decent composite
score" without reconciling it with the bearish conclusion. The other 7
(including 5 of the 6 contradicted-outcome cases) showed internally
consistent reasoning — e.g. one decision's thesis was confirmed to
genuinely weigh cited bullish evidence against cited bearish signals rather
than ignoring either side. n=8 is small — a real, useful signal, not a
generalizable rate.

**A real script gap, disclosed rather than hidden**: `select_audit_sample`
has no memory of prior audit runs, so re-running the script reselected an
already-audited decision, producing 2 audit rows for it (both agreeing
`supported=true`, so no impact on the finding above, but wasted real spend).
Noted as a known limitation below, not silently fixed after the fact.

### Task 6: source-disabling recommendations

**No source named in the task can currently be evaluated for measurable
value** — every one is blocked by a different reason, not a weak effect
size: `SPOT_ETF_FLOWS`, `PREDICTION_MARKETS`, and `ON_CHAIN_MINER_METRICS`
are `NOT_IMPLEMENTED` (nothing to evaluate). `STABLECOIN_SUPPLY_VELOCITY_
AND_EXCHANGE_RESERVES` and `CME_COT_POSITIONING` are genuinely operational
(`status=OK`) but were deliberately excluded from 3e.1's replay
(`EVIDENCE_UNAVAILABLE_FOR_REPLAY`, per 3a's audit above) — zero resolved
decisions have ever used them. `GLOBAL_LIQUIDITY_MACRO` and
`REGULATORY_EVENT_CALENDAR` (3f) are operational but postdate replay
entirely — only used in the 50 still-unresolved live decisions. For
`composite_factor_score`: the intended "agreed vs. diverged" hit-rate
comparison hit the **same persistence gap as task 3's regime finding** —
`screened_universe` (which holds the real, joinable score) only has rows
for live `RUN-*` run_ids, never replay's `BACKFILL-*` run_ids, so no
backfilled decision has a joinable composite_factor_score on record. The
score IS narratively embedded in `key_evidence` free text (e.g. "Composite
score 0.637..."), but a regex extraction from inconsistently-phrased
narrative text was deliberately rejected as too misparse-prone for a
statistical comparison — reported as not computable rather than risking a
silently-wrong number. **No `signal_sources` row is recommended for
disabling; none can be, on real evidence, yet.**

### Task 7: go/no-go statement for Phase 4

**Not yet — and the primary reason is the missing embargo (task 3b), not
sample size alone.** Even once the 50 live holdout decisions resolve (the
earliest possible in ~13 more days, at the 14-day horizon), that result
would not constitute a clean, independent out-of-sample test without an
embargo gap first: 100% of those decisions sit within one resolution-horizon
of the training boundary, and price-momentum/regime persistence — present
in both the training and holdout data — is a real, unaddressed
autocorrelation channel. Sample size compounds this (zero holdout
resolutions exist right now at all) but is not the deeper problem; a larger
unembargoed holdout sample would still not license a go/no-go claim on its
own. Getting to a real answer needs, in order: (1) let holdout decisions
resolve to have *any* out-of-sample number, then (2) either introduce a
genuine embargo gap for the *next* holdout cohort, or treat any earlier
non-embargoed holdout result as directionally suggestive only, never
confirmatory. This is a statement about what's missing, not a negative
verdict on the system — the backfilled Sharpe/Brier numbers (tasks 2–3) are
a positive signal, just not yet one that has cleared the bar this sub-phase
exists to apply.

### Tests

327 tests passing (`pytest`, no live credentials needed):
`tests/test_statistical_validation.py` (20 tests — PSR/DSR against known-
correct degenerate cases and an independent cross-check, PBO against the two
hand-provable constructions, Brier decomposition's exact-reconstruction
identity including the float-boundary regression), `tests/
test_reasoning_audit.py` (13 tests — sampling priority/dedup/cap, prompt
rendering, schema validation, `CostGuard` registration, a mocked-LLM call).

### Known limitations / decisions

- **By-regime and composite-factor-score breakdowns are blocked by the same
  underlying gap**: 3e.1's replay computes real regime/score values
  in-memory for context-building but never persists them as clean,
  joinable rows for backfilled decisions — only their narrative embedding
  in free text survives. A real, reportable structural gap in replay's
  bookkeeping, not fixed here (out of 3g's scope).
- **DSR/PBO's honest ceiling is this project's youth, not a flaw in the
  method**: with only 1 real calibrated configuration and 0 resolved live
  decisions, there's genuinely little for deflation/overfitting-correction
  machinery to correct yet — both are built, tested, and ready the moment
  there's more than one trial or a resolved holdout to check.
- **PBO's implementation is verified only against 2 hand-provable
  degenerate cases**, not a published numeric worked example — disclosed
  plainly rather than overclaimed, consistent with the sub-phase's own
  non-negotiable on unverified formula implementations.
- **The reasoning-audit script has no run-to-run memory** — a repeat
  invocation can reselect and re-audit an already-audited decision (real,
  wasted spend observed this run). Not fixed here; a natural task-5
  follow-up if the audit becomes a recurring, repeated process.
- **`DATABASE_URL` (used only by `scripts/apply_migration.py`) had a stale
  password this sub-phase** — migration `0011` was applied manually via the
  Supabase SQL Editor instead (the script's own documented fallback).
  `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY` (used by the real app/tests)
  were unaffected.
- **A fourth evidence-pipeline bug of the same class as 3f's macro-evidence
  dedup was found and fixed this sub-phase, before 3g's own tasks began**:
  `binance_futures_term_structure`/`deribit_futures_term_structure` are
  collected per dated-futures instrument (up to 12 distinct BTC instruments
  per run on Deribit alone), but all three per-asset evidence-context
  builders (Judge, 3d assessment, 3f adversarial research) deduped by
  source name, silently collapsing the whole term-structure curve to one
  arbitrary point — worse than 3f's bug, since ties in `retrieval_timestamp`
  make "which point survives" non-deterministic, not even reliably
  "nearest expiry." Fixed via one shared, tested helper
  (`group_observations_by_multi_entry_source` in
  `app/database/evidence_provenance.py`) reused by all three consumers
  rather than tripling the fix; also bumped
  `EvidenceObservationRepository.get_latest_by_asset`'s default query limit
  50→150, since multi-entry sources alone were nearing that ceiling and
  risked crowding out single-value sources' latest readings. Live-verified
  using BTC's real evidence data through all three real `render_prompt`
  functions: all 12 real Deribit instruments and 2 real Binance instruments
  now render as the full curve. **3 real, still-`UNRESOLVED` live
  `judge_decisions` (all BTC) reasoned from the pre-fix single collapsed
  point** — flagged here as a caveat on those specific decisions rather than
  rerun; none of the 109 resolved backfilled outcomes ever cited term
  structure, so no calibration number is affected.

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
  trading/       Phase 4 — order-book-depth-aware, fee-aware paper-fill simulation (see PHASE4_PROMPT.md); Phase 6 — testnet execution agent (LangChain/LangGraph)
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

## Development methodology

This project is built and verified one phase at a time (see Status above) — each
phase is implemented, tested against a live Supabase project, and reviewed before
the next begins. Live trading is only ever activated after a separate, explicit
safety review; the default and current mode is PAPER.

Starting with Phase 3, this also applies *within* a phase: Phase 3 is large
enough that it is split into sub-phases (3a–3i, plus the optional, gated 3j
and 3k addenda — see their own gating rules below), each with its own live
verification and cost check, rather than implemented as one block. Rules that
carry across every sub-phase:

- **Official, documented sources come before fragile/unofficial ones.**
  Coinbase, Binance, Deribit, Etherscan, and DefiLlama all have real,
  documented, free-or-cheap APIs and are built in 3b/3c. CryptoBubbles,
  CoinAnk, and PlanB/X have unclear or unofficial access and are deliberately
  built last (3f), gated on a real feasibility check each time.
- **No new external source is assumed reliable until checked.** Programmatic
  access is verified for real before code is written against it; sources that
  turn out to be unavailable are recorded as such (`signal_sources` table),
  not faked or silently dropped.
- **No new evidence source ships without a cost estimate** against
  `MAX_DAILY_LLM_COST` / `MAX_MONTHLY_LLM_COST`. Any sub-phase that adds LLM
  calls (3d, 3f) estimates calls/day and cost/day before merging. Market-data
  sources (3b, 3c) have no LLM cost but should still be checked against
  provider rate limits. A small number of 3c/3f/3i sources (on-chain
  valuation metrics, token unlock schedules, social/narrative sentiment,
  entity-flow intelligence, developer-activity aggregation) may require a
  paid data-API subscription — a dollar cost against project budget, tracked
  and documented separately from `CostGuard`, which exists specifically to
  cap LLM spend, not general data-vendor spend.
- **Two schema/convention decisions were locked before 3a started**, since
  schema is cheap to decide up front and expensive to retrofit once 3b–3g
  are writing against it (see `PHASE3_LOCKED_DECISIONS.md` for the full
  writeup):
  - The full Judge decision record (thesis, key/contradictory evidence,
    invalidation conditions) lives in a dedicated `judge_decisions` table,
    reserved empty in 3a and populated in 3e — not folded into the slimmer
    `decision_outcomes` ledger, which only tracks resolution against
    realized returns. `decision_outcomes.decision_id` FKs to it.
  - Every table that persists an LLM call's result must have an
    `estimated_cost` column and be registered in a documented
    `COST_TRACKED_TABLES` list in `app/llm/cost.py` that CostGuard sums
    across — so a later sub-phase adding a new LLM-call table
    (`model_market_assessments` in 3d, `judge_decisions` in 3e, bull/bear/
    scenario tables in 3f, reasoning-audit calls in 3g) can't silently
    under-report real spend against `MAX_DAILY_LLM_COST`/
    `MAX_MONTHLY_LLM_COST` by forgetting to wire it in.
- **Predictions are tracked against reality, continuously.** Starting in 3e,
  every Judge decision is recorded in a decision-outcome ledger and later
  backfilled with realized returns, so the system's own accuracy — not just
  its internal model agreement — is measurable and improves the design over
  time rather than being assessed once at the end.
- **An accuracy claim isn't accepted until it survives multiple-testing and
  calibration checks, not just a hit-rate.** Every prompt or logic change
  followed by a calibration re-run is a "trial" in the statistical sense —
  enough trials against the same historical data will eventually produce a
  good-looking number by chance. From 3e onward this project tracks that
  trial count (`calibration_runs`, `prompt_templates`) and, in 3g, applies
  Deflated Sharpe / probability-of-backtest-overfitting correction before
  treating any before/after comparison as a real improvement. Directional
  hit-rate alone is also insufficient — confidence values feed position
  sizing directly, so calibration (Brier score / reliability by regime)
  is tracked as a separate, equally-required metric, and a held-out decision
  window is reserved from 3e onward specifically so at least one result
  hasn't been iterated against.
- **New tooling earns its place by matching a real need, not by being
  available.** FastAPI, xAI, LangChain/LangGraph, and Langfuse are each
  adopted for a specific, scoped reason (see "Technology stack decisions"
  above) and introduced only in the phase where that reason applies —
  MongoDB was considered and deliberately not adopted, for the same kind of
  reasoning; order-flow imbalance/LOB microstructure features were
  considered and deliberately not adopted for the same reason, on a
  horizon-mismatch basis rather than an availability basis (see "Technology
  stack decisions"). **3j and 3k apply this rule to evidence sources, not
  just infrastructure**: options gamma exposure, exchange counterparty/
  solvency risk, and retail-demand proxies (3j), and DeFi lending rates,
  staking yield/validator queue depth, and stablecoin depeg-risk monitoring
  (3k), were all identified as things professional crypto desks track, but
  none is scheduled for implementation until 3h's evidence-value ranking
  (or 3g's Judge-reasoning audit or purged-walk-forward finding) shows a
  specific, named gap one of them would close — being used elsewhere is
  not, by itself, a reason to add a new cost-bearing, drift-prone input to
  this system.
- **A learned model is a checking tool until proven otherwise, never a
  silent decision-maker.** 3h's evidence-value ranking exists specifically
  to catch cases where the Judge's narrative weighting and a
  statistically-learned weighting disagree — but a small-sample learned
  model is exactly as vulnerable to the multiple-comparisons/overfitting
  problem 3g exists to correct for, so it stays diagnostic-only (reported
  alongside `composite_factor_score`, never blended into the Judge or used
  to auto-adjust `signal_sources`) until it has survived the same kind of
  scrutiny 3g applies to the Judge itself.
- **Point-in-time integrity is checked, not assumed.** Several evidence
  types (on-chain valuation metrics, ETF flow figures, regulatory-event
  extraction) get revised by their own provider after the fact. From 3a
  onward, revisable fields are append-only (`is_revision_of`, never an
  overwrite) so a "value as known at time T" query is always available, and
  3g explicitly audits a sample of resolved decisions to confirm no
  since-revised value leaked into a historical evaluation. An accuracy
  number that turns out to be quietly using hindsight is worse than an
  honestly-reported low accuracy number, because it fails silently.
- **Model/source disagreement is a risk-sizing input, checked for whether it
  actually earns that role.** 3d/3e compute `model_agreement`/
  `source_agreement` as evidence distinct from any single model's
  confidence, and 3e's Risk Engine scales position size down when
  agreement is weak, composed with (not instead of) volatility-based
  sizing. 3g then checks — via a reliability breakdown by agreement bucket,
  the same discipline already applied by regime — whether low-agreement
  decisions genuinely resolve less reliably than high-agreement ones at the
  same stated confidence, rather than assuming disagreement is informative
  just because it's intuitive that it should be.
- **Execution realism is part of the accuracy claim, not a separate
  concern.** Every calibration/stress-test number produced through 3g/3h is
  computed against mark-to-mid `market_snapshots` prices, which assumes
  costless, instant fills. Phase 4 does not treat this as good enough to
  call "paper trading" — it adds order-book-depth-aware, fee-aware fill
  simulation and re-reports calibration net of realistic execution costs,
  specifically because a system's real-world accuracy is only as
  trustworthy as the fill assumptions behind the numbers describing it.
