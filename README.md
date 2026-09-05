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
  - **3a** — Candidate/universe status schema, evidence provenance + numeric
    freshness-decay convention (now with an explicit **point-in-time
    integrity** rule — revisable evidence fields are append-only, with an
    `is_revision_of` chain and a documented "value as known at time T"
    query convention, so later backtests can never accidentally read a
    since-revised value for a past decision), `signal_sources` registry, and
    schema groundwork for market-regime snapshots, a decision-outcome
    ledger, and prompt/template versioning (all populated in later
    sub-phases)
  - **3b** — CoinMarketCap + **Coinbase** + **Binance** exchange-native data,
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
  - **3c** — Official derivatives & on-chain sources: **Binance funding
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
  - **3d** — Multi-model current market assessment (separate from
    `llm_analyses`), now with consistent regime/derivatives/on-chain context,
    prompt-template versioning, an optional **Grok (xAI)** model in the
    OpenRouter model set, and optional **Langfuse** call tracing
  - **3e** — Deterministic Judge (now also weighing 3b's non-LLM
    `composite_factor_score` as a distinct input alongside model/adversarial
    evidence), Risk Engine (volatility/correlation-aware sizing, now also
    **uncertainty-aware**: position size scales down when model/source
    agreement is weak, composed with the existing volatility adjustment
    rather than replacing it), Portfolio Construction, and a **continuous
    decision-outcome ledger** for ongoing calibration — each decision tagged
    with its market regime and Judge confidence, a **held-out decision
    window** reserved and respected from this point forward, and a baseline
    backtest against existing Phase 1/2 data reporting **both hit-rate and
    calibration (Brier score)**, not directional accuracy alone
  - **3f** — Adversarial bull/bear research, scenario modeling, a macro
    matrix extended with a **forward-looking scheduled macro-event
    calendar** (known-in-advance FOMC/CPI/PCE/NFP release dates, distinct
    from the after-the-fact print observations already in the matrix),
    **global liquidity proxies** (M2, Fed balance
    sheet, via FRED) and BTC's **rolling correlation to equities/gold/DXY**,
    and the remaining exploratory/fragile-to-extract sources (CoinAnk,
    CoinGlass liquidation heatmap, CryptoBubbles, PlanB/X — the latter
    accessed via **xAI's API**, which has native X/Twitter search —
    aggregate **social/narrative sentiment** via Santiment or LunarCrush-
    style tracking, a **regulatory/policy event calendar** via SEC
    EDGAR and congress.gov, official sources where the extraction of a
    dated, asset-specific event is the unverified part, and a **regional
    exchange price premium** — e.g. the historically-documented "Kimchi
    premium" on Korean venues — as a proxy for regionally concentrated
    retail speculative intensity, distinct from the ordinary cross-venue
    aggregation noise already logged in 3b) — each gated on a real
    access-feasibility check; re-run calibration afterward (by regime, not
    just in aggregate) and spot-check whether the Judge's own stated
    reasoning actually follows from its cited evidence
  - **3g** — Statistical validation: a **Deflated Sharpe Ratio /
    probability-of-backtest-overfitting** correction across every
    prompt/logic iteration made in 3d–3f (so "it got better" claims account
    for how many times the system was tried, not just the final number), a
    full calibration/reliability report broken down by regime **and by
    model/source-agreement bucket** (so disagreement functions as a genuine,
    checked uncertainty signal rather than an unverified assumption), a
    report on the held-out window in isolation, a **point-in-time/
    look-ahead-bias audit** re-deriving revisable evidence (on-chain
    valuation metrics, ETF flow figures, regulatory-event extraction) as it
    would have appeared at decision time and confirming no since-revised
    value leaked into training/calibration, a **purged/embargoed
    walk-forward check** — a distinct leakage risk from point-in-time
    correctness, since autocorrelated evidence (on-chain metrics, funding
    rates, open interest) can leak across a held-out boundary even when
    every individual value is correctly dated, so this task quantifies
    whether the held-out window has an adequate embargo gap and flags it as
    a finding if not — and a Judge-reasoning audit — the gate this project
    treats as the actual determinant of whether Phase 3 improved prediction
    accuracy, rather than a raw before/after delta
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

3. Apply the database schema — both migrations, in order. Either:
   - **Recommended**: open the Supabase SQL Editor and paste the contents of
     `migrations/0001_init.sql`, run it, then do the same for
     `migrations/0002_llm_and_news.sql`. Both are idempotent — safe to re-run
     any time they change.
   - Or, with `DATABASE_URL` set:
     ```
     python scripts/apply_migration.py migrations/0001_init.sql
     python scripts/apply_migration.py migrations/0002_llm_and_news.sql
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

**Cost control**: `CostGuard` checks cumulative spend (summed from
`llm_analyses.estimated_cost`) against `MAX_DAILY_LLM_COST` /
`MAX_MONTHLY_LLM_COST` before every provider call, skipping (not crashing)
once a cap is hit. The pricing table in `app/llm/cost.py` is a point-in-time
snapshot of OpenRouter pricing — re-check https://openrouter.ai/models
periodically, especially after changing `CLAUDE_MODEL`/`OPENAI_MODEL`/`GEMINI_MODEL`.

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

## Project layout

```
app/
  config/        Settings (env-driven)
  database/      Supabase client + repositories (assets, market_snapshots, news, llm_analyses, and Phase 3 tables)
  market_data/   CoinGecko client, normalization, collection service; extended in 3b with CoinMarketCap/Coinbase/Binance, screening/regime classification (incl. BTC dominance/altcoin-season index and halving-cycle position), composite factor score, and anomaly flag; extended in 3c with ETF-flow/prediction-market/stablecoin-velocity/CME-COT/miner-metrics providers and the derived volatility-risk-premium/annualized-carry-yield fields; extended in 3f with a scheduled macro-event calendar, FRED-based global-liquidity/cross-asset-correlation, regulatory-calendar, and regional-exchange-premium providers; extended in 3i with entity-flow-intelligence, custody/OTC-flow, and network-usage/developer-activity providers; optionally extended in 3j (gated — see 3j) with options-gamma-exposure, exchange-counterparty-risk, and retail-demand-proxy providers; optionally extended in 3k (gated — see 3k) with DeFi-lending-rate, staking-yield/validator-queue, and stablecoin-depeg-risk providers
  news/          RSS collection, relevance matching, dedup (Phase 2)
  llm/           OpenRouter integration, structured output, cost guard (Phase 2); extended in 3d with the current-market-assessment stage (optional Grok, optional Langfuse tracing)
  judge/         Phase 3e — deterministic decision synthesis, persisted to `judge_decisions` (schema reserved in 3a); input set extended in 3f and 3i without redesign; uncertainty-aware sizing input (model/source agreement) added 3e
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
