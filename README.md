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

- ✅ **Phase 1 — Foundation**: project structure, configuration, Supabase schema,
  CoinGecko market-data collector.
- ✅ **Phase 2 — Multi-model AI**: RSS news collection, OpenRouter integration
  (Claude, OpenAI, Gemini), structured/validated LLM output, cost tracking.
- ✅ **Phase 3 — Broad intelligence, discovery & judgment**, built as verified
  sub-phases 3a through 3i (screening/regime classification, derivatives &
  on-chain evidence, multi-model assessment, the Judge/Risk Engine/Portfolio
  Construction core, historical replay, adversarial research & macro,
  statistical validation, evidence-value ranking & stress testing,
  entity-flow/network/developer-activity intelligence). **3j/3k** (options
  gamma/counterparty risk/retail-demand proxies; DeFi lending/staking/
  stablecoin-depeg monitoring) remain a **deliberately gated backlog** — not
  built until evidence-value ranking or the Judge-reasoning audit names a
  specific gap they'd close (needs ≥50 resolved decisions first; see
  [`doc/todo.md`](doc/todo.md)).
- ✅ **Phase 4 — Paper trading execution**: order-book-depth-aware fill
  simulation, execution-cost-adjusted outcomes, benchmark comparison vs.
  real BTC/equal-weight buy-and-hold.
- ✅ **Phase 5 — FastAPI + dashboard** (localhost/personal-machine scope, one
  API-key header), plus **5a** (real `holdings_ledger` ground truth,
  replacing `portfolio_positions` as the pipeline's real-allocation input),
  **5b** (live pricing, transactional holdings entry, full transaction
  history, P&L), **5c** (a real incident: the turnover-cap baseline was
  computed against real holdings instead of the system's own prior target,
  overstating turnover by ~3-4x in one live run — fixed, migration 0020),
  **5d** (the Judge's prompt was silently blending "real holdings" and "the
  system's own last target" into one ambiguous "current allocation" number —
  fixed to show both, distinctly labeled), and **5e** (dashboard's AI/My
  Portfolio sections merged into one, LunarCrush re-confirmed paid-tier-only,
  an asset-display-name bug fixed and 12 live records corrected). Full
  detail, real numbers, and every live-verified finding for every phase live
  in [`doc/history.md`](doc/history.md) — this README intentionally doesn't
  duplicate it.
- ⬜ **Phase 6 — Exchange integration** (testnet only): on hold by deliberate
  choice, no timeline (see [`doc/todo.md`](doc/todo.md)).

Each phase is implemented, verified against the live Supabase project, and
reviewed before the next begins (see [`doc/methodology.md`](doc/methodology.md)
for the cross-phase principles, and the standing documentation-maintenance
policy it now also carries). `pytest` must keep passing without live
credentials at every step; any source with no reliable programmatic access
is recorded as `UNAVAILABLE`/`NOT_IMPLEMENTED` in `signal_sources` rather
than silently skipped or faked.

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

- **[`doc/operations.md`](doc/operations.md)** — setup, every env var and
  what it gates, migrations, asset-universe configuration, the recommended
  `scripts/run_daily.py` entrypoint and the manual flag-by-flag pipeline
  sequence with real per-run costs, running the API & dashboard, and how to
  verify a run worked.
- **[`doc/architecture.md`](doc/architecture.md)** — the system's *current*
  real data-flow diagram, component table, and codebase (`app/`) layout —
  what's built and live today, not the original plan.
- **[`doc/decisions.md`](doc/decisions.md)** — why each piece of the stack
  (FastAPI, xAI, LangChain/LangGraph, Langfuse, things deliberately *not*
  adopted like MongoDB) was chosen, plus later dated decisions (turnover
  baseline, Judge-context design, dashboard scope) as they were made.
- **[`doc/history.md`](doc/history.md)** — the full build history: what was
  built, real live-verified findings, and known limitations for every phase
  from Phase 2 through the present, append-only, never rewritten.
- **[`doc/scripts.md`](doc/scripts.md)** — every script in `scripts/`, what
  it does, its real cost, and whether it's already wired into
  `run_daily.py`, recommended for periodic runs, or manual/one-time only.
- **[`doc/todo.md`](doc/todo.md)** — everything currently open, deferred, or
  declined, each with its stated reasoning/revisit condition: Phase 6,
  scheduling, 3j/3k, paid-tier deferrals, `NOT_IMPLEMENTED` sources, and
  other real open items. Deliberately does not repeat "done" work — that's
  `history.md`'s job.
- **[`doc/methodology.md`](doc/methodology.md)** — the development
  methodology and cross-phase principles this project holds itself to,
  including the standing documentation-maintenance policy.
- **[`doc/prompts/`](doc/prompts/)** — two things, kept separate:
  ready-to-run implementation prompts for `doc/todo.md`'s still-open items
  (`01_...md` through `18_...md`, each independently verified against the
  live codebase before being written — `01`-`16` and `18` each implement an
  item that already existed in `doc/todo.md`; `17` is the one exception,
  introducing a genuinely new item of its own; see
  [`00_INDEX.md`](doc/prompts/00_INDEX.md) for suggested order and
  cross-cutting risks), and, in **`doc/prompts/done/`**, the historical
  phase-by-phase prompts (`PHASE1-2_PROMPT.md` through `PHASE6_PROMPT.md`)
  that drove this project's original build, plus any numbered prompt above
  whose work is now actually complete (e.g.
  `EMBARGO_HOLDOUT_COHORT_PROMPT.md`) — historical input specs, not living
  documentation; not kept in sync with later renames elsewhere in `doc/`.
