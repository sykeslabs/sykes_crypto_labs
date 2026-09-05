# AI Crypto Portfolio — Phase 3c: Derivatives (Funding, Options) & On-Chain/DeFi Sources

## Context

This continues Phase 3. Complete and live-verified so far:
- 3a: candidate/status schema, evidence provenance + freshness decay,
  `signal_sources` registry, empty schema for `market_regime_snapshots`,
  `decision_outcomes`, `prompt_templates`.
- 3b: CoinMarketCap, Coinbase, Binance market data, deterministic screening,
  `TOP_CANDIDATES`, and a deterministic market-regime classifier persisted
  per run.

**Before writing any code**, inspect what actually exists — the real schema
from 3a, the real screening/candidate output from 3b, and how the regime
classifier is stored. This sub-phase adds more *official, documented*
sources, still with zero LLM cost — it's pure data collection, feeding into
3d/3e as additional evidence.

**This task is 3c only.** Do not begin 3d (multi-model assessment), 3e
(Judge/Risk/Portfolio), or 3f (adversarial research, remaining fragile
sources). Stop after 3c is verified and wait for confirmation.

## Non-negotiables

- PAPER ONLY.
- No invented API access — every source here should be genuinely
  official/documented; if a specific field turns out to require a paid tier
  you don't have, mark that field/source `UNAVAILABLE`, don't approximate it.
- Never auto-convert a raw observation into a directional signal at the
  collector level (see per-source constraints below) — that's the Judge's job
  in 3e, using this evidence.
- Zero new LLM calls in this sub-phase.
- Follow the 3a evidence-provenance shape (including `decay_half_life_hours`)
  for every new table.

## Task detail

**1. Binance funding rates.**
Binance's public API exposes perpetual futures funding rates, documented and
free. Capture, per asset (where a perpetual exists): current funding rate,
funding interval, and recent funding-rate history if cheaply available.
**Interpretation constraint:** a strongly positive funding rate means longs
are paying shorts (crowded long positioning) — this is not automatically
bearish or bullish; it's a positioning fact. Store the raw rate; let the
Judge reason about crowding/squeeze risk in 3e. This is effectively an
official-API alternative/complement to what CoinAnk's long/short data would
provide in 3f, and should be built as an independent source, not a
replacement for CoinAnk later.

**2. Aggregate futures open interest.**
Binance and Deribit both expose open interest on their public/documented
market-data endpoints — the same venues and API keys (if any) already used
for funding rates (this section) and options data (next section), so this is
near-zero marginal integration cost. Capture current open interest and,
if cheaply available, recent OI history, per asset where a perpetual/futures
market exists. **Interpretation constraint:** open interest is a magnitude,
not a direction — rising OI with rising price and rising OI with falling
price mean very different things (fresh conviction vs. fresh short
pressure), and that pairing is the Judge's job to reason about in 3e/3f, not
this collector's. Store OI as its own field alongside price, don't derive a
combined "OI signal" here.

**3. Deribit options data.**
Deribit is the dominant BTC/ETH options venue and has a public, documented
API. Capture, for BTC and ETH at minimum (and other assets only if Deribit
actually lists options on them): implied volatility (e.g. at-the-money IV for
a near-dated expiry), and put/call ratio or skew if reasonably extractable
without heavy computation. **Interpretation constraint:** rising IV or
skewed put/call ratios reflect the options market pricing in
uncertainty/direction — this is not the same as a price prediction, and
should be stored as positioning/uncertainty evidence, not converted into a
BUY/SELL signal at the collector level.

**4. On-chain / DeFi data.**
- **DefiLlama**: fully free, documented, no key required. Capture protocol
  and chain-level TVL and meaningful TVL trend (e.g. 7d/30d change) for
  assets/ecosystems in your universe where DefiLlama has coverage. This is a
  reasonable proxy for capital rotation across chains/protocols.
- **Etherscan (or equivalent explorer API per chain actually relevant to your
  universe)**: capture what's genuinely accessible at your API tier —
  exchange inflow/outflow for a given token if reasonably derivable, or
  simpler proxies like large-transfer counts if full flow analysis isn't
  practical at this stage. If reliable exchange-flow computation isn't
  realistically achievable with a free/cheap tier, it's fine to implement a
  narrower version (e.g. just large-transfer counts) and mark the richer
  version `NOT_IMPLEMENTED` rather than approximating something you can't
  actually verify.

Do not force on-chain coverage for every asset in the universe — many small
caps won't have meaningful on-chain infrastructure to observe. Missing
coverage per-asset is `UNAVAILABLE`, not a source-wide failure.

**5. Stablecoin supply & exchange reserve flow.**
Capture two capital-rotation proxies distinct from DefiLlama's protocol-level
TVL (which measures where capital sits inside DeFi, not whether capital is
entering/leaving crypto or exchanges at all):
- **Net stablecoin supply growth** (e.g. USDT/USDC circulating supply
  change over 7d/30d) — DefiLlama's stablecoins endpoint is free and
  documented and may already cover this without a new integration; verify
  before adding a new provider.
- **Exchange reserve balances** (BTC/ETH/major-asset balances held on
  tracked exchange addresses) — check what's genuinely derivable from
  Etherscan-class explorers at your existing tier (this may be a narrower
  proxy, e.g. tracking known large exchange wallet addresses' balance
  deltas, rather than a full reserve-tracking product). If reliable
  reserve estimation isn't realistically achievable free/cheap, mark it
  `NOT_IMPLEMENTED` rather than approximating — same rule as the rest of
  this sub-phase.
**Interpretation constraint:** stablecoin supply growth and falling exchange
reserves are commonly read as bullish "dry powder"/accumulation signals, but
both have benign alternative explanations (issuance for non-trading reasons,
reserves moving to cold storage or a different venue). Store the raw
observation; this is Judge-level reasoning, not a collector-level signal.

**6. Update `signal_sources`.**
Reflect real, verified status for Binance funding, Binance/Deribit open
interest, Deribit options, DefiLlama, the on-chain explorer used, and the
stablecoin-supply/exchange-reserve source — individually, since they may have
different reliability.

**7. Tests & docs.**
`pytest` passes without live credentials (mocked responses per provider).
Update `README.md`: mark 3c complete, document what was actually achievable
per source at your API tier (especially on-chain and exchange-reserve
estimation — these are the sources most likely to need scoping down from the
original ambition).

## Exit criteria

- `signal_sources` reflects real status for Binance funding, Binance/Deribit
  open interest, Deribit options, DefiLlama, the on-chain explorer used, and
  the stablecoin-supply/exchange-reserve source.
- Funding rate, open interest, and options data captured for at least
  BTC/ETH and any other assets where genuinely available.
- On-chain/DeFi and stablecoin/reserve data captured for assets where
  genuinely available, `UNAVAILABLE` elsewhere.
- Zero new LLM calls/cost.
- `pytest` green without credentials.
- README updated with real per-source findings.

Stop here, report what was actually achievable per source (especially where
you had to scope down from the original ambition), and wait for confirmation
before starting 3d.
