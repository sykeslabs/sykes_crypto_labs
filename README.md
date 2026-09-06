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
  `doc/prompts/PHASE3A_PROMPT.md` through `doc/prompts/PHASE3I_PROMPT.md`,
  one per sub-phase, plus the optional, gated `doc/prompts/PHASE3J_PROMPT.md`
  and `doc/prompts/PHASE3K_PROMPT.md` addenda),
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
    (optional per `doc/prompts/PHASE3D_PROMPT.md`; most useful once there's real call
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
    running out mid-run, not a technical or design failure (see
    `doc/phases.md`'s Phase 3e.1 section); resolved with a real
    `BACKFILL_BASELINE` calibration number
    (hit-rate 0.833, Brier 0.195 over 36 directional decisions) reported
    separately from the live forward-tracked baseline, never combined
  - ✅ **3f** (complete) — Adversarial bull → bear → scenario research cycle
    (bear demonstrably attacks the specific bull thesis, live-verified —
    see `doc/phases.md`'s Phase 3f section), a macro matrix (CPI/PCE/claims/
    payrolls/yields/fed funds via FRED) with a **forward-looking scheduled
    macro-event calendar** (real CPI/PCE/NFP release dates — FOMC excluded,
    see `doc/phases.md`'s Phase 3f section), **global liquidity proxies**
    (M2/Fed balance sheet/
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
    primary reason no go/no-go claim can be made yet (see `doc/phases.md`'s
    Phase 3g section), not merely small sample size. Held-out window: 50 live decisions, all
    `in_holdout_window=true`, **zero resolved** — insufficient data.
    Formalized Judge-reasoning audit (new `judge_reasoning_audits` table,
    8 real audited decisions, real cost **$0.026838** total): 1 of 8 showed
    a genuine unsupported claim (a SELL thesis that never addressed its own
    cited contradicting evidence). Source-disabling recommendations: **no
    source can currently be evaluated** — every 3c/3f source named in the
    task is either `NOT_IMPLEMENTED`, was deliberately excluded from replay
    (zero resolved-decision exposure), or was only ever used post-3f in
    still-unresolved live decisions. **Go/no-go for Phase 4: not yet** — see
    `doc/phases.md`'s Phase 3g section for the full reasoning, led by the
    embargo/generalization problem, not sample size alone.
  - ✅ **3h** (complete) — A later addendum, added after a gap-analysis
    against professional crypto-advisory practice. **Evidence-value ranking**:
    a from-scratch, inspectable logistic regression (no new ML dependency —
    pure Python gradient descent, matching this project's "new tooling
    earns its place" discipline), verified against engineered synthetic
    fixtures with a known relationship (both a plain perfect-predictor-vs-
    noise case and a regime-dependent case) before running on real data.
    **Real result: insufficient data** — n=36 real directional resolved
    decisions, below the documented minimum of 50 (~10 observations/feature,
    Peduzzi et al. 1996) — reported honestly, not fabricated; rolling-window
    variants (n=20, n=16) are smaller still. A further real limitation
    found: `source_assessment` and `composite_factor_score` are not usable
    at all — neither is joinable to any resolved backfilled decision (same
    root persistence gap 3g found for `regime_at_decision` — see
    `doc/phases.md`'s Phase 3g/3h sections). Regime-sliced drift: **not
    computable**, same reason. Deterministic
    **portfolio tail-risk stress testing** (`app/risk/stress_test.py`, zero
    LLM cost): two scenarios — `HISTORICAL_WORST_DRAWDOWN` (each asset's own
    REAL historical peak-to-trough drawdown, fetched live from Binance/
    Coinbase) and `ALTCOIN_CONTAGION_LUNA_FTX_STYLE` (a stated, documented
    assumption) — run against the real live portfolio (see `doc/phases.md`'s
    Phase 3h section).
    Reporting-only throughout — neither capability altered Judge prompts,
    Risk Engine formulas, Portfolio Construction, or `signal_sources`.
    **Headline stress-test caveat**: neither scenario flags at the current
    ~21%-allocated portfolio, but that reflects low current *deployment*,
    not low underlying asset risk (real per-asset drawdowns are severe,
    -53% to -76%) — see `doc/phases.md`'s Phase 3h section (task 2) for the
    scaled-to-full-allocation figures.
  - ✅ **3i** (complete) — A second later addendum from the same gap-analysis
    pass. **Entity-flow intelligence**: Nansen's real smart-money/netflow API
    (live-verified — real auth, real per-token data, EVM/Solana chains only,
    free tier: 100 one-time credits + 10/day refill). Arkham confirmed
    genuinely inaccessible (Cloudflare bot-challenge-gated, same standard as
    CoinAnk in 3f). **Custody/OTC flow: `NOT_IMPLEMENTED`** — no reliable,
    independently-verifiable source of real custody-provider addresses
    exists; building it would mean fabricating addresses, which this
    project does not do. **Network usage**: a per-token active-address/
    transfer-count proxy via Etherscan's free `tokentx` (the network-wide
    `dailytx` stat genuinely requires Etherscan's separate paid Pro tier,
    confirmed live) — and a real bug caught during live verification: busy
    tokens' fetched transfers covered mere **hours**, not the nominal 7-day
    window, now disclosed via an honest `possibly_truncated` flag rather
    than silently mislabeled. **Developer activity**: real GitHub commit/
    contributor counts for assets with an unambiguous primary repo (10 of
    22), everything else marked `UNAVAILABLE` per the task's own
    instruction, never guessed. All three sources verified live to appear
    in the Judge's actual rendered prompt with **zero Judge code changes** —
    the existing generic per-asset evidence architecture from 3c already
    surfaces any new `evidence_observations` source automatically. Zero new
    LLM cost throughout. Calibration re-run, honestly persisted as a new
    trial: still 0 resolved live decisions (real horizons haven't elapsed
    yet), reported as such, not fabricated. Now the last **required**
    sub-phase of Phase 3.
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
    bottleneck. See `doc/prompts/PHASE3J_PROMPT.md` for the exact gating condition.
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
    `doc/prompts/PHASE3K_PROMPT.md` for the exact gating condition.
- ✅ **Phase 4** (complete) — Paper trading execution, benchmarks, ongoing
  accuracy tracking (see `doc/prompts/PHASE4_PROMPT.md`). Built a real, live-verified
  **order-book-depth-aware fill simulator** (`app/trading/fill_simulator.py`)
  — a multi-level book walk producing a genuine VWAP and (when the order
  exceeds fetched depth) a real partial fill, backed by real public Binance/
  Coinbase order-book endpoints — plus a documented, clearly-labeled
  **volatility-scaled fallback** for when no real depth data exists (true
  for every currently-resolved decision, since order books aren't stored
  historically anywhere in this project). `decision_outcomes` now carries
  `realized_return_net_of_costs`/`assumed_fill_method` alongside the
  original mark-to-mid `realized_return`, never instead of it. **Real
  finding**: execution costs are small relative to this sample's realized
  returns (avg. drag ≈0.21 percentage points/decision) — hit-rate and Brier
  are **unchanged**, Sharpe drops modestly (~3.5% relative). Benchmark
  tracking (`app/benchmarks/baseline_comparison.py`) compared the system
  against real BTC and equal-weight-universe buy-and-hold over the same
  real 28-day window, identically costed — with an explicit, disclosed
  caveat that the system's decision-level Sharpe and the baselines'
  daily-return Sharpe are not directly comparable in magnitude (different
  return periodicities), so no "system beats market" claim is made from
  this alone. Portfolio-optimization sizing review (task 4): **decided
  against adding complexity now** — costs are demonstrably small and 3g/3h
  already found the bigger open problem is a lack of resolved, out-of-
  sample data to validate even the current simple sizing scheme; added
  optimization machinery would introduce new overfitting risk before that
  gap closes, same philosophy as 3j's own gating.
- ✅ **Phase 5** (complete) — A **FastAPI** read/query layer (20 endpoints)
  over the Evidence Store (candidates, assessments, Judge decisions,
  portfolio state, cost reports) plus a minimal read-only dashboard.
  Deployment scope decided up front (see `doc/phases.md`'s Phase 5 section):
  **localhost/personal-machine only**, not a public deployment — every
  prior phase has been operated entirely via local CLI by a single user,
  no hosting infrastructure exists anywhere in this project, and nothing
  about this phase's stated purpose (replacing manual Supabase queries with
  a local view) requires remote access. A single API-key header is
  therefore a genuinely sufficient minimum bar for this scope, not a
  deliberately under-scoped one — if this
  is ever exposed beyond localhost, the security posture (TLS, stronger
  auth, rate limiting) must be revisited before that happens, not after.
  Scheduling was explicitly considered and **deferred** (reasoning in the
  Phase 5 section) — this project's real bottleneck is elapsed time for
  decisions to resolve, not run frequency. Live-verification (required, not
  optional, per this phase's own non-negotiable) found and fixed two real
  bugs: a nullability mismatch that crashed the calibration endpoint on
  real pre-3f data, and a dashboard JS syntax error that would have broken
  every panel in a real browser.
- ✅ **Phase 5a** (complete) — Real current-holdings ground truth (see
  `doc/prompts/PHASE5A_PROMPT.md`): a narrow, append-only `POST /holdings`
  write endpoint extending Phase 5's otherwise read-only API, structurally
  kept separate from any Judge/Risk Engine/Portfolio Construction output.
  Replaces `portfolio_positions` as the live pipeline's actual
  `current_allocation` input (confirmed live, not just wired to the
  dashboard) — `portfolio_positions` itself is retired as an input and kept
  only as Portfolio Construction's own derived bookkeeping.
- ⬜ Phase 6 — Exchange integration (testnet only): a bounded **execution
  agent** (LangChain/LangGraph) that turns Portfolio Construction's approved
  target changes into actual (testnet) orders — the only agentic component
  in the system, scoped to an explicit, allow-listed toolset, with Risk
  Engine constraints re-checked at execution time

Each sub-phase is implemented, verified against the live Supabase project, and
reviewed before the next begins — same methodology as Phase 1 and 2 (see
[`doc/methodology.md`](doc/methodology.md)). `pytest` must keep passing without live
credentials at every step; any source that turns out to have no reliable
programmatic access is recorded as `UNAVAILABLE`/`NOT_IMPLEMENTED` in
`signal_sources` rather than silently skipped or faked.

## Quickstart

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY`
(required) — every other variable is optional and gates a specific evidence
source or LLM stage (see [`doc/operations.md`](doc/operations.md) for the
full list). Apply the migrations in `migrations/` in order via the Supabase
SQL Editor, then run the collector:

```
python -m app.main
```

For everything else — the full env-var reference, the daily manual command
sequence for the whole advisory pipeline and its real per-run costs,
running the FastAPI dashboard, and how to verify a run worked — see
[`doc/operations.md`](doc/operations.md).

## Documentation

This README stays a concise overview. Everything else lives in `doc/`:

- **[`doc/operations.md`](doc/operations.md)** — setup, asset-universe
  configuration, the daily manual pipeline command sequence with real
  per-run costs and ordering dependencies, running the API & dashboard,
  and how to verify a run worked.
- **[`doc/architecture.md`](doc/architecture.md)** — the system's data-flow
  diagram, component table, and codebase (`app/`) layout.
- **[`doc/technology-decisions.md`](doc/technology-decisions.md)** — why
  each piece of the stack (FastAPI, xAI, LangChain/LangGraph, Langfuse,
  and things deliberately *not* adopted like MongoDB) was chosen, and when.
- **[`doc/phases.md`](doc/phases.md)** — the full build history: what was
  built, real live-verified findings, and known limitations/decisions for
  every phase from Phase 2 through Phase 5a.
- **[`doc/open-work.md`](doc/open-work.md)** — everything currently
  deferred-but-not-abandoned in one place: Phase 6, scheduling, 3j/3k,
  paid-tier deferrals, `NOT_IMPLEMENTED` sources, and other open items —
  each with its stated revisit condition.
- **[`doc/methodology.md`](doc/methodology.md)** — the development
  methodology and cross-phase principles this project holds itself to.
- **[`doc/prompts/`](doc/prompts/)** — the phase-by-phase prompts
  (`PHASE1-2_PROMPT.md` through `PHASE6_PROMPT.md`) that drove this
  project's build, one per (sub-)phase.
