# AI Crypto Portfolio — Phase 3c: Derivatives (Funding, Term Structure, Options, CME Positioning), On-Chain/DeFi, Valuation & Miner Sources

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
- A couple of sources added in this sub-phase (on-chain valuation metrics,
  token unlock schedules) may require a paid API tier. That's a dollar cost
  to note in the README's cost section, not an LLM cost — it does not touch
  `CostGuard` or `MAX_DAILY_LLM_COST`/`MAX_MONTHLY_LLM_COST`, but it should
  still be a deliberate, documented decision, not an unexamined recurring
  charge.

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

**2a. Futures term structure / basis.**
Binance and Deribit both list dated (expiry-based) futures alongside
perpetuals, and their basis relative to spot across expiries (the
contango/backwardation curve) is a distinct signal from both the perpetual
funding rate (task 1) and open interest (task 2): funding rate reflects
perpetual-specific positioning, OI reflects magnitude, but the dated-futures
curve reflects where futures desks are pricing forward expectations over
concrete time horizons — closer in spirit to a fixed-income yield curve than
to either of the other two. Capture, for BTC/ETH at minimum (and other
assets only where dated futures actually exist and have meaningful open
interest): basis at the nearest few listed expiries. Alongside the raw basis
at each expiry, also compute and store the **annualized basis/carry yield**
(the basis expressed as an annualized percentage, comparable across expiries
and assets, the same way a bond desk annualizes a cash-and-carry trade) —
this is a straightforward derived transformation of data already captured,
not a new source, but it makes the curve directly comparable across assets
and against a risk-free-rate benchmark in a way the raw basis numbers alone
don't. Store both the raw curve and the annualized figure. **Interpretation
constraint:** steep contango is commonly read as bullish positioning/carry
demand and backwardation as bearish/stress, but both have benign
alternative explanations (e.g. contango can simply reflect a stable
risk-free-rate carry trade rather than directional conviction) — store the
raw curve, don't convert it into a signal at the collector level.

**2b. CME futures positioning (CFTC Commitment of Traders report).**
The CFTC publishes a free, official, weekly Commitment of Traders (COT)
report for CME BTC and ETH futures, breaking open interest down by trader
category (typically leveraged funds, asset managers/institutional, dealers,
and other reportables). This is a genuinely distinct evidence type from
everything else in this sub-phase: funding rate (task 1) and OI (task 2)
describe perpetual/aggregate futures activity on crypto-native exchanges,
while COT describes *regulated*, CME-specific futures positioning broken out
by the kind of institution holding it — closer to how equity/commodity
analysts read institutional positioning than to any crypto-native metric
already in scope. Capture, per available category: net position (long minus
short), open interest, and week-over-week change, for BTC and ETH (COT
coverage for altcoin futures is essentially nonexistent — that's expected,
not a gap to chase). Verify actual access before building: CFTC publishes
COT data as free downloadable reports/APIs (e.g. via cftc.gov or a
documented aggregator such as The Block or Barchart) — use the CFTC's own
published data as the source of truth, not a scraped third-party chart, and
confirm the real publication cadence (weekly, released Fridays, reflecting
the prior Tuesday's close — meaning this data is inherently several days
stale by design, not a collector bug; record this in `decay_half_life_hours`
accordingly). **Interpretation constraint:** do not assume the traditional
"commercials are smart money" reading transfers to Bitcoin — multiple
independent analyses of BTC's COT data find the relationship inverted
(commercial/dealer positioning behaves more like standard risk-hedging of
the categorizing institutions' own custody/OTC books than a directional
call, and non-commercial speculative positioning has at times tracked price
direction better). Store the raw category breakdown; do not pre-label either
category as bullish/bearish smart money at the collector level — that
category-specific interpretation, and its exceptions, is Judge-level
reasoning in 3e/3f, not something to encode here.

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

**3a. Volatility risk premium (VRP).**
Implied volatility on its own (task 3) tells you how much uncertainty
options are pricing in, but professional options desks read it *relative to*
realized volatility — the spread between the two (implied minus realized,
over a matched window) is a distinct, well-documented signal from either
value alone: persistently positive VRP reflects a structural premium options
sellers earn for bearing risk, and a collapsing or negative VRP is itself
informative about market stress/complacency. This is a derived computation,
not a new external source: pair task 3's Deribit at-the-money IV with the
realized-volatility factor 3b's screening already computes for the same
asset over a matched lookback window, and store the spread as its own
labeled field (e.g. `vrp = implied_vol - realized_vol`) alongside — not
instead of — the two raw inputs. Only compute it where both inputs are
genuinely available for the same asset/window; otherwise `UNAVAILABLE`.
**Interpretation constraint:** VRP is a positioning/pricing-efficiency
signal, not a price-direction signal — a wide VRP says options are
"expensive" relative to recent realized movement, not which way the
underlying will move. Store it raw; the Judge reasons about what a
stretched or compressed VRP implies alongside everything else.

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
  actually verify. **Known limitation to document, not solve here:** a raw
  large-transfer count conflates genuine whale accumulation/distribution
  with routine exchange-internal or protocol traffic, since it has no
  entity-clustering behind it (grouping multiple addresses controlled by the
  same actor, the way Glassnode/Nansen-class platforms do). If your access
  tier doesn't include entity-adjusted clustering, ship the raw count anyway
  but record this conflation explicitly in `signal_sources.notes` and the
  README's known-limitations section, so it isn't later mistaken for a
  clean whale signal — this is exactly the kind of caveat 3g's source
  review should be able to find without re-deriving it from scratch.

Do not force on-chain coverage for every asset in the universe — many small
caps won't have meaningful on-chain infrastructure to observe. Missing
coverage per-asset is `UNAVAILABLE`, not a source-wide failure.

**5. Stablecoin supply, velocity & exchange reserve flow.**
Capture three capital-rotation proxies distinct from DefiLlama's
protocol-level TVL (which measures where capital sits inside DeFi, not
whether capital is entering/leaving crypto or exchanges at all):
- **Net stablecoin supply growth** (e.g. USDT/USDC circulating supply
  change over 7d/30d) — DefiLlama's stablecoins endpoint is free and
  documented and may already cover this without a new integration; verify
  before adding a new provider.
- **Stablecoin supply velocity** (aggregate stablecoin transaction/transfer
  volume relative to circulating supply, over a consistent window such as
  7d) — a distinct signal from raw supply growth: growth measures whether
  capital is entering the stablecoin base at all, velocity measures whether
  that capital is actively moving (usage) versus sitting still (hoarding).
  Check whether DefiLlama or an on-chain explorer already exposes the
  transfer-volume input needed to compute this before building a new
  aggregation path.
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
reserves moving to cold storage or a different venue). Velocity has its own
ambiguity — rising velocity can mean genuine on-chain usage or just
exchange-internal shuffling. Store the raw observations; this is Judge-level
reasoning, not a collector-level signal.

**5a. On-chain valuation-cycle metrics (MVRV, SOPR, NUPL, LTH/STH cohorts).**
The Etherscan/DefiLlama sources above capture flow and TVL, but not the
valuation-cycle metrics that professional on-chain research treats as
foundational: **MVRV** (and MVRV Z-Score) comparing market price to the
average price at which coins last moved, **SOPR** (spent-output profit
ratio — whether coins moving on-chain are being sold at a profit or loss),
**NUPL** (net unrealized profit/loss across the holder base), and a
**long-term-holder vs. short-term-holder cohort breakdown** (LTH-MVRV,
STH-MVRV) distinguishing distribution-phase behavior from fresh-buyer
capitulation. These are a genuinely distinct evidence type from
transfer-flow/TVL data — they describe where the *holder base as a whole*
sits relative to cost basis, not capital movement or protocol-level
liquidity.
Capture via a documented on-chain analytics API — e.g. Glassnode or
CryptoQuant — for BTC and ETH at minimum (coverage for smaller-cap assets
in your universe will likely be much thinner; that's expected and should
show as `UNAVAILABLE` per-asset, not a source-wide failure). These
providers' free tiers are limited and the fuller metric set often sits
behind a paid tier — verify actual access, rate limits, and real dollar
cost at your account tier before committing, same rule as every other
source in this sub-phase; a paid data subscription is a dollar cost to
weigh against project budget, not an LLM cost, so it does not run through
`CostGuard`, but it should still be noted in the README's cost section.
**Interpretation constraint:** these are cycle-position/valuation signals,
not short-term timing signals, and are most informative in **confluence**
with each other (e.g. high MVRV plus declining SOPR plus rising exchange
inflow reads differently than any one of those alone) — store each metric
raw and separately; combining them into a single "cycle score" is Judge-level
reasoning in 3e, not a collector-level computation here.

**5b. BTC miner metrics.**
Hash rate, difficulty (and its scheduled adjustment), miner reserve balances,
and miner-to-exchange transfer flow are a standard on-chain category
("hash ribbons"-style miner capitulation/recovery signals) used alongside
MVRV/SOPR/NUPL in professional on-chain research, and are BTC-specific — the
mining security-budget dynamic doesn't transfer to most other assets in the
universe, so don't force coverage elsewhere. Capture via the same on-chain
analytics provider already used for task 5a (Glassnode or CryptoQuant
typically expose this in the same tier/API surface, so check there first
before evaluating a separate vendor) — this may be near-zero marginal cost
if that vendor relationship already covers it, or may require a higher tier;
verify actual access and real cost before committing, same rule as every
other source here. **Interpretation constraint:** falling hash rate/
difficulty can reflect miner capitulation (a bearish stress signal) or
simply a routine efficiency-driven fleet transition; rising miner-to-exchange
flow can reflect distribution or just routine operational treasury
management — store the raw metrics, don't pre-convert either into a
directional signal at the collector level. If reliable access isn't
achievable at a reasonable tier, mark `ON_CHAIN_MINER_METRICS`
`UNAVAILABLE` rather than approximating.

**6. Spot ETF flows (BTC/ETH).**
Capture daily net flows for spot BTC and ETH ETFs. Use an aggregator with a
documented, free/cheap API (e.g. Farside Investors or SoSoValue) rather than
scraping or polling each issuer (BlackRock, Fidelity, etc.) individually —
verify the aggregator's actual access terms and rate limits before building
against it. Capture daily net flow (USD) per tracked fund set and, if cheaply
available, a rolling cumulative-flow figure, since a single day's flow is
noisy and the trend is what's actually informative. **Interpretation
constraint:** ETF flows are a medium/long-horizon institutional-capital
proxy, not a short-term trading signal, and are most informative *paired*
with the funding-rate/open-interest data from tasks 1–2 (steady ETF inflows
alongside flat leverage suggests capital-driven demand; ETF inflows alongside
rapidly rising OI suggests leveraged speculation is doing the work instead).
Store both series raw and separately; that pairing is Judge-level reasoning,
not something to pre-compute into a combined signal here. If no
asset in your universe beyond BTC/ETH has a spot ETF, that's expected —
don't force coverage.

**7. Prediction market implied probabilities.**
Capture implied probabilities for a small, curated set of relevant
macro/crypto event contracts (e.g. Fed rate decisions, CPI prints, a
specific asset's ETF-approval or listing events, if actively trading) from a
documented API such as Polymarket or Kalshi. Verify actual programmatic
access, contract coverage, and rate limits before committing — if reliable
access to a specific venue doesn't exist at your tier, mark
`PREDICTION_MARKETS` `UNAVAILABLE` rather than approximating, same rule as
every other source here. Capture, per contract: implied probability,
contract description, resolution date, and volume/liquidity (as a rough
confidence-in-the-price proxy — a thinly traded contract's implied
probability is much noisier than a liquid one's). **Interpretation
constraint:** this is a market-priced probability, not a directional trading
signal and not the same kind of evidence as options-implied volatility
(which prices uncertainty magnitude, not a specific outcome's likelihood) —
store the raw probability and let the Judge weigh it; never auto-convert it
into BUY/SELL at the collector level. Do not force contract coverage for
every asset; most won't have a relevant, sufficiently liquid contract, and
that's `UNAVAILABLE`, not a failure.

**7a. Token unlock / vesting schedule.**
Unlike every other source in this sub-phase, this one is a **known future
event**, not an inferred-from-current-data observation — a scheduled
vesting cliff or emission unlock is a calendar fact, dated in advance,
rather than a signal read off live market/on-chain data. Capture, for
assets in your universe with meaningful vesting schedules (mainly the
smaller-cap/altcoin tier — ONDO, ENA, JASMY, S, STORJ, JTO, and similar are
far more likely to have active unlock schedules than BTC/ETH), the next
scheduled unlock date, the unlock size (as a percentage of circulating
supply, which matters more than the raw token count), and the unlock
category if available (e.g. team/investor cliff vs. staking/ecosystem
emission — a team unlock and a staking-rewards emission carry different
sell-pressure implications). Use a documented aggregator such as Messari or
TokenUnlocks rather than per-project tokenomics-page scraping; verify actual
API access and coverage for your specific universe before committing —
expect uneven coverage, same as on-chain data, and mark per-asset
`UNAVAILABLE` rather than a source-wide failure. **Interpretation
constraint:** an upcoming unlock is a known supply-side event, not
automatically bearish — whether it moves price depends on float already
priced in, recipient behavior, and market conditions at unlock time — so
store the calendar fact (date, size, category) raw; the Judge is
responsible for weighing it, and it is a natural candidate for
`invalidation_conditions` in 3e's Judge output ("thesis invalidated if a
material unlock occurs before horizon X").

**8. Update `signal_sources`.**
Reflect real, verified status for Binance funding, the futures term-structure
source, Binance/Deribit open interest, Deribit options, DefiLlama, the
on-chain explorer used, the on-chain valuation-metrics provider
(Glassnode/CryptoQuant), BTC miner metrics (`ON_CHAIN_MINER_METRICS`), the
stablecoin-supply-velocity/exchange-reserve source, the spot-ETF-flow
aggregator, CME futures positioning (`CME_COT_POSITIONING`), the
prediction-market source, and the token-unlock-schedule source —
individually, since they may have different reliability.

**9. Tests & docs.**
`pytest` passes without live credentials (mocked responses per provider).
Update `README.md`: mark 3c complete, document what was actually achievable
per source at your API tier (especially on-chain/exchange-reserve
estimation, stablecoin velocity, and prediction-market contract coverage —
these are the sources most likely to need scoping down from the original
ambition).

## Exit criteria

- `signal_sources` reflects real status for Binance funding, the futures
  term-structure source, Binance/Deribit open interest, Deribit options,
  DefiLlama, the on-chain explorer used, the on-chain valuation-metrics
  provider (MVRV/SOPR/NUPL/cohort data), BTC miner metrics, the
  stablecoin-supply-velocity/exchange-reserve source, the spot-ETF-flow
  aggregator, CME futures positioning (CFTC COT), the prediction-market
  source, and the token-unlock-schedule source.
- Funding rate, futures basis (raw and annualized carry yield), open
  interest, and options data (including the derived volatility risk
  premium, where both IV and realized volatility are available) captured
  for at least BTC/ETH and any other assets where genuinely available.
- CME COT positioning captured for BTC/ETH by trader category, with the
  report's inherent multi-day publication lag documented in
  `decay_half_life_hours`/`publication_timestamp`, `UNAVAILABLE` if real
  access can't be verified.
- On-chain/DeFi, on-chain valuation metrics (MVRV/SOPR/NUPL/cohorts), BTC
  miner metrics (hash rate/difficulty/reserves/exchange flow), stablecoin
  supply/velocity, and reserve data captured for assets where genuinely
  available, `UNAVAILABLE` elsewhere.
- Spot ETF net flow data captured daily for BTC/ETH at minimum, stored raw
  and separately from funding-rate/OI data (not pre-combined).
- Prediction-market data captured for whatever curated contract set is
  genuinely accessible and liquid enough to be meaningful; `UNAVAILABLE`
  elsewhere.
- Token unlock/vesting schedule data captured for the altcoin tier of the
  universe where genuinely available, stored as dated calendar facts
  (date, size, category), `UNAVAILABLE` elsewhere.
- Zero new LLM calls/cost. (Paid on-chain-analytics or unlock-schedule API
  subscriptions, if used, are a documented dollar cost, separate from and
  not routed through `CostGuard`.)
- `pytest` green without credentials.
- README updated with real per-source findings.

Stop here, report what was actually achievable per source — including ETF
flows, stablecoin velocity, prediction markets, on-chain valuation metrics,
BTC miner metrics, futures term structure (and its annualized carry yield),
the volatility risk premium, CME COT positioning, and token unlock
schedules, and especially where you had to scope down from the original
ambition — and wait for confirmation before starting 3d.
