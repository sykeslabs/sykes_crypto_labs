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

**2. Deribit options data.**
Deribit is the dominant BTC/ETH options venue and has a public, documented
API. Capture, for BTC and ETH at minimum (and other assets only if Deribit
actually lists options on them): implied volatility (e.g. at-the-money IV for
a near-dated expiry), and put/call ratio or skew if reasonably extractable
without heavy computation. **Interpretation constraint:** rising IV or
skewed put/call ratios reflect the options market pricing in
uncertainty/direction — this is not the same as a price prediction, and
should be stored as positioning/uncertainty evidence, not converted into a
BUY/SELL signal at the collector level.

**3. On-chain / DeFi data.**
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

**4. Update `signal_sources`.**
Reflect real, verified status for Binance funding, Deribit options,
DefiLlama, and whatever on-chain explorer you used — individually, since they
may have different reliability.

**5. Tests & docs.**
`pytest` passes without live credentials (mocked responses per provider).
Update `README.md`: mark 3c complete, document what was actually achievable
per source at your API tier (especially on-chain — this is the source most
likely to need scoping down from the original ambition).

## Exit criteria

- `signal_sources` reflects real status for Binance funding, Deribit options,
  DefiLlama, and the on-chain explorer used.
- Funding rate and options data captured for at least BTC/ETH and any other
  assets where genuinely available.
- On-chain/DeFi data captured for assets where genuinely available, `UNAVAILABLE`
  elsewhere.
- Zero new LLM calls/cost.
- `pytest` green without credentials.
- README updated with real per-source findings.

Stop here, report what was actually achievable per source (especially where
you had to scope down from the original ambition), and wait for confirmation
before starting 3d.
