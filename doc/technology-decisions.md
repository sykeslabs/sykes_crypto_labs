# Technology stack decisions

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

