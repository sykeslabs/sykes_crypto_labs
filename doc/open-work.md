# Open / deferred work

Everything currently deferred-but-not-abandoned, consolidated in one place
so it's discoverable without scanning every phase section in
[`phases.md`](phases.md). An item here was deliberately not built, or not
yet built, for a stated reason — not silently skipped. Nothing here is
abandoned; each has a stated revisit condition.

## Phase 6 — exchange execution agent

**On hold by deliberate choice, not started, no timeline.** The
recommendation pipeline (screening → assessment → adversarial research →
Judge → Risk Engine → Portfolio Construction) is built and live-verified
through Phase 5a; Phase 6 would add a bounded, testnet-only **execution
agent** (LangChain/LangGraph) that turns Portfolio Construction's approved
target changes into actual (testnet) orders — the only agentic component
planned for this system, scoped to an explicit allow-listed toolset with
Risk Engine constraints re-checked at execution time. Full scope already
defined in [`doc/prompts/PHASE6_PROMPT.md`](prompts/PHASE6_PROMPT.md)
whenever it's picked back up.

## Scheduling

**Explicitly decided against for now, in favor of manual daily runs**
(Phase 5 task 3). This project's real bottleneck is elapsed time for
decisions to resolve, not run frequency, so scheduling infrastructure
wasn't judged worth building yet. Full reasoning and the concrete
revisit trigger (what changes — TLS, real auth, rate limiting — if this
system is ever exposed beyond a single local machine, and what would
make scheduling worth adding) already live in
[`phases.md`](phases.md)'s Phase 5 section — not duplicated here. See also
[`operations.md`](operations.md)'s "Daily operation" chapter for the
current manual command sequence this deferral implies.

## 3j / 3k — gamma exposure, counterparty risk, retail-demand proxies, DeFi lending rates, staking yield, stablecoin depeg risk

**Gate not met.** Both addenda are intentionally not implemented until 3h's
evidence-value ranking (or 3g's Judge-reasoning audit / purged-walk-forward
finding) surfaces a specific, named gap one of these sources would close —
being used elsewhere on professional desks isn't, by itself, a reason to
add a new cost-bearing, drift-prone input. The concrete blocker: 3h's
evidence-value ranking requires `MIN_SAMPLE_SIZE=50` resolved directional
decisions and found only **n=36** — insufficient data, not a null result.
Revisit once enough `decision_outcomes` rows accumulate to clear that
threshold and evidence-value ranking can actually run.

## CoinGecko demo-tier rate limit — open reconsideration

New finding from this documentation pass, not yet acted on. A demo API key
was added and live-verified: it raises CoinGecko's per-asset historical
endpoint from ~5 rapid calls before a `429` (unauthenticated) to at least
40 rapid calls across distinct coins with no rate-limiting observed, at a
measured throughput (10 calls in 2.41s) comparable to Binance's own
14-calls-in-3.7s figure. This was the exact constraint Binance's
primary-source-for-volatility/drawdown decision (Phase 3b) was based on.
**Open decision, not acted on**: whether this is now worth reconsidering
for volatility/drawdown sourcing, or for any other currently
`UNAVAILABLE`/rate-limited use case — deliberately not switched over
automatically, same gating discipline as 3j/3k. See
[`phases.md`](phases.md)'s Phase 3b section for the full live-verification
detail. Two caveats on the finding itself: CoinGecko exposes no
rate-limit-remaining headers, and the demo tier's monthly call cap was not
tested live (would mean burning real quota with no operational benefit) —
so burst-rate-limiting is confirmed resolved, monthly-cap behavior is not.

## Paid-tier deferrals (real recurring-cost decisions, not technical failures)

- **Glassnode / CryptoQuant** (on-chain valuation-cycle metrics — MVRV/
  SOPR/NUPL, LTH/STH cohorts, BTC miner metrics) — built against, but not
  subscribed to; see `phases.md`'s Phase 3c section.
- **CoinGlass** (liquidation heatmap data) — real, documented API exists
  but is tiered-paid with no usable free tier; see `phases.md`'s Phase 3f
  section.
- **LunarCrush** (social/narrative sentiment) — even its "public" v4
  endpoint requires an auth token; deferred alongside CoinGlass; see
  `phases.md`'s Phase 3f section.
- **xAI / Grok** (as a fourth assessment/research model) — xAI's API is
  live and functional (verified), but no paid API relationship was
  established; see `phases.md`'s Phase 3d section.

## `NOT_IMPLEMENTED` sources (genuine infeasibility or no accessible free API, not fabricated)

- **Custody / OTC desk flow** — no reliable, independently-verifiable
  source of real custody-provider wallet addresses exists (unlike the
  exchange hot-wallet proxy used elsewhere); building this would mean
  guessing addresses, which this project does not do. Revisit only if a
  real, citable source of custody-provider addresses is identified. See
  `phases.md`'s Phase 3i section.
- **Spot ETF flows** — Farside has no real API (Cloudflare-protected
  webpage only); SoSoValue's API requires an authenticated login not
  available here. Revisit if SoSoValue API access is obtained. See
  `phases.md`'s Phase 3c section.
- **Token unlock / vesting schedules** — Messari requires an API key not
  available here (and its tier's unlock-data coverage is unconfirmed);
  TokenUnlocks.app has no discoverable public API. Revisit if a Messari
  key is obtained. See `phases.md`'s Phase 3c section.
- **Prediction markets** — both Polymarket and Kalshi failed DNS
  resolution from this development sandbox specifically (general
  connectivity was otherwise confirmed fine). Revisit from an environment
  that can reach them. See `phases.md`'s Phase 3c section.

## Other documented open items

- **CoinMarketCap's response shape is implemented per its documented API
  but not live-verified end-to-end** — no key was available while
  building it. Verify once `COINMARKETCAP_API_KEY` is set. See
  `phases.md`'s Phase 3b section.
- **`/calibration/summary` does one repository call per resolved
  decision** (a real N+1 query pattern), measured at ~8.6 real seconds
  over HTTP at 179 `decision_outcomes` rows. Usable today at this scale;
  first thing to fix (a proper join/batch method) if called more
  frequently or history grows materially. See `phases.md`'s Phase 5
  section.
- **`POST /holdings` echoes `id: null`** in its response instead of the
  database-assigned id (the handler returns the locally-constructed
  record rather than re-querying after insert); `GET /holdings` and
  `GET /holdings/history` return the real id correctly. Cosmetic only —
  not a correctness issue. See `phases.md`'s Phase 5a section.
