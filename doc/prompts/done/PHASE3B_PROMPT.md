# AI Crypto Portfolio — Phase 3b: CoinMarketCap, Coinbase, Binance, Screening, Regime Classification

## Context

This continues Phase 3. Sub-phase 3a is complete and live-verified: candidate
status schema, `NO_TRADE` value, evidence-provenance convention (with numeric
freshness decay), `signal_sources` registry, and empty schema groundwork for
`market_regime_snapshots`, `decision_outcomes`, and `prompt_templates`.

**Before writing any code**, inspect what 3a actually built — read the
updated `README.md` and the 3a migrations. Use what actually exists; don't
assume this document's exact table/column names are final if 3a made
different structural choices.

**This task is 3b only.** Do not begin 3c (derivatives/on-chain), 3d
(multi-model assessment), 3e (Judge/Risk/Portfolio), or 3f (adversarial
research, remaining fragile sources) — even scaffolding. Stop after 3b is
verified and wait for confirmation.

## Non-negotiables

- PAPER ONLY.
- No blended/generic sentiment score — every source stays independently
  inspectable, including where sources disagree.
- Missing data is `UNAVAILABLE`/`UNKNOWN`, never silently defaulted.
- No invented API access — verify each new source's actual documented
  capabilities at your access tier before coding against it.
- This sub-phase adds **zero new LLM calls**. Screening and regime
  classification are pure market-data arithmetic.
- Follow the evidence-provenance shape from 3a (including
  `decay_half_life_hours`) for every new stored observation.

## Task detail

**1. CoinMarketCap.**
Official/documented API only. Update `signal_sources` accordingly. Pull
what's genuinely available at your tier (market cap, rank, price, volume,
performance). Map to `assets` via a `coinmarketcap_id` column, parallel to
the existing `coingecko_id`. Keep independent from CoinGecko — do not merge —
and surface meaningful disagreement between the two (even a log line is
enough for now).

**2. Coinbase.**
Use Coinbase's official Advanced Trade / Exchange API (documented, free
tier). This is exchange-native data — real trades and order book on a
specific venue, as opposed to CoinGecko/CMC's aggregated-across-exchanges
view. Pull what's useful and available: recent trade price, 24h volume, and
— if reasonably accessible — top-of-book bid/ask spread as a liquidity proxy.
Not every asset in your universe will be listed on Coinbase; that's expected
and should show as `UNAVAILABLE` per-asset, not a source-wide failure. Note:
a new listing on Coinbase for an asset not previously listed there is a real,
historically observed demand catalyst ("Coinbase effect") — if your screening
loop runs periodically, a simple newly-listed detection (asset appears in
Coinbase's product list where it didn't before) is worth capturing as a
distinct evidence event, not inferred after the fact.

**3. Binance.**
Use Binance's public REST API (documented, no key required for market-data
endpoints). Same rationale as Coinbase — exchange-native price/volume,
independent venue, broader asset coverage than Coinbase for most alts. Keep
Binance and Coinbase as separate source rows, not merged, even though both
are "exchange data" — an asset trading tightly in sync across venues vs. one
diverging is itself informative and should stay visible.

**4. Configurable screening universe.**
Add `SCREENING_UNIVERSE_SIZE` (start at 30–50, not 100, given no LLM cost yet
but real API rate-limit and runtime considerations). Draw from
CoinGecko/CoinMarketCap's broader listings, not just the existing 16 tracked
`assets` — the point of discovery is finding assets not currently tracked.

**5. Deterministic screening factors.**
Compute, per asset, using CoinGecko + CoinMarketCap + Coinbase/Binance data
(no LLM): market cap, liquidity/volume, 7d momentum, 30d momentum,
volatility, drawdown, relative strength. Keep factor computation isolated and
testable (pure functions over input data) — reused/extended later, and needs
to be backtestable without hitting live APIs in tests.

**6. Deterministic composite factor score.**
Combine the factors from task 5 (momentum, volatility, drawdown, relative
strength, liquidity/volume) into a single, documented, deterministic
composite score per asset — a simple weighted or rank-based combination is
fine, but the weights/method must be logged, not tuned by feel. This is
**not** a sentiment score and does not replace the individual factors, which
stay independently visible per the "no blended sentiment" non-negotiable
above — it exists specifically as a distinct, purely quantitative signal
that 3e's Judge can weigh *alongside* (not merged into) the LLM/adversarial
evidence, since a system that only ever reasons narratively about numbers
has no non-LLM check on whether the narrative and the arithmetic agree.
Persist it as `composite_factor_score` on the full-screened-universe record
from task 8 below (column reserved by 3a).

**7. Basic screening-stage anomaly / wash-trading flag.**
Before an asset's factors are finalized, run a simple check for
implausible volume/price behavior relative to that asset's own recent
history (e.g. a volume or price z-score/percentage-jump threshold, similar
in spirit to 3d's later per-call sanity check but applied here at discovery
time, before an anomalous asset can even become a candidate). Flag, don't
silently exclude — a flagged asset can still surface as a `CANDIDATE`, but
the flag must be visible in its screening record and carried forward so
later stages know to treat it with extra scrutiny. This is a heuristic
guard against wash-trading/pump-and-dump patterns in the smaller-cap tier
of the universe, not a general market-manipulation detector — keep it
simple and inspectable, same rule as the regime classifier below.

**8. Deterministic market-regime classifier.**
This is new and important: compute a single, run-level market regime *once
per run* — not separately guessed per-asset later by each LLM call in 3d,
which risks inconsistent regime labels across assets in the same run. Use
deterministic inputs already available from this sub-phase's data: e.g. BTC
price relative to its own moving averages, breadth (% of the screening
universe above/below a moving average or with positive 30d momentum), and
aggregate volatility. Classify into a small number of regimes (e.g.
`RISK_ON` / `RISK_OFF` / `NEUTRAL`, or more granularity if it's cheap to
compute) and persist to the `market_regime_snapshots` table from 3a, with the
actual input values stored in `inputs` (JSONB) so the classification is
auditable, not a black box. Every later stage (3d's model assessments, 3e's
Judge) should read this one regime snapshot per run rather than each
inferring its own.

Add **BTC dominance and an altcoin-season/breadth index** as additional
inputs alongside the risk-on/risk-off inputs above — this is a distinct axis
from "is crypto broadly risk-on," namely "is capital currently rotating from
BTC into alts or the reverse." Compute BTC's share of total screened-universe
market cap (dominance) and its trend, plus the standard altcoin-season
formulation (e.g. % of the top N non-stablecoin assets in the universe that
have outperformed BTC over a trailing 90d window, a widely-used
CoinMarketCap-style definition) from data this sub-phase already collects —
no new external source needed. Store both as their own labeled fields in
`market_regime_snapshots.inputs`, distinct from the risk-on/risk-off
classification itself: a `RISK_ON` + `BTC_DOMINANT` regime and a `RISK_ON` +
`ALTCOIN_SEASON` regime call for different candidate-tilt reasoning
downstream, and collapsing the two axes into one label would lose that
distinction. This does not change the small risk-on/off/neutral enum itself
— it adds an orthogonal, equally auditable field alongside it.

Add **BTC's position in the halving cycle** as a further, orthogonal regime
input, using the same "cheap, deterministic, zero-marginal-cost" reasoning as
BTC dominance above: the four-year block-subsidy halving is a fixed, publicly
known schedule (not inferred from market data), so compute BTC's current
block height against the known/estimated schedule of past and next halving
dates and store both **days since the most recent halving** and **days until
the next estimated halving** (estimated from recent average block time if the
next halving hasn't occurred yet) in `market_regime_snapshots.inputs`,
alongside — not blended into — the risk-on/off and BTC-dominance/altcoin-
season fields. This is a distinct axis from both: cycle-timing frameworks
(pre-halving accumulation, post-halving markup, cycle-peak, bear) are widely
referenced in professional crypto research as a multi-month-to-multi-year
backdrop, separate from both the current risk-on/off regime and the
BTC-vs-alts rotation question. Do not hard-code a "N days post-halving =
bullish" rule at the collector level — store the raw day-counts only; any
cycle-phase interpretation belongs to the Judge (3e) or later research
(3f's scenario modeling), consistent with the "no blended sentiment,
no editorializing at the collector level" rule used everywhere else in this
sub-phase. No new external source or table needed — block height is already
retrievable from data sources this sub-phase collects (or, if not already
available, a single call to any of the already-integrated providers that
expose it); if none of the existing sources expose block height cleanly,
mark this specific field `NOT_IMPLEMENTED` rather than adding a new provider
just for it, and revisit in 3c/3f where new providers are already being
added anyway.

**9. Candidate output.**
Produce a ranked `TOP_CANDIDATES` list. Assets already `HELD` remain
distinguishable from newly surfaced candidates. Tag genuinely new discoveries
with the 3a `CANDIDATE` status.

Also persist a compact record of the **full screened universe** for the run
(asset id + its screening factor values + rank + `composite_factor_score` +
the anomaly flag from task 7), not just the assets that made
`TOP_CANDIDATES` — a lightweight row per screened asset is enough, no need to
store full evidence for assets that don't surface. This exists specifically
so that later validation work (3g) can check for survivorship bias in
discovery: if only assets that later performed well are ever visible in the
historical record, any calibration or accuracy check built on "what got
surfaced" is silently biased, because it never sees what got correctly or
incorrectly screened out.

**10. Tests & docs.**
`pytest` passes without live credentials (mock CoinMarketCap/Coinbase/Binance
responses, plus a fixture case that should trip the anomaly flag). Update
`README.md`: mark 3b complete, document actual field availability/rate
limits found at each provider's tier, and record the regime classifier's and
composite factor score's chosen inputs/weights/thresholds as a "known
limitations / decisions" note (like the existing Phase 2 section does for
news coverage).

## Exit criteria

- `signal_sources` rows for CoinMarketCap, Coinbase, Binance reflect real,
  verified status.
- Live run produces a ranked `TOP_CANDIDATES` list from a configurable
  universe size.
- Cross-source disagreement (CoinGecko vs. CoinMarketCap vs.
  Coinbase/Binance) is visible in output/logs for overlapping assets.
- A `market_regime_snapshots` row is written each run with auditable inputs,
  including BTC dominance and the altcoin-season/breadth index alongside the
  risk-on/off inputs, and BTC's halving-cycle day-counts (or an explicit
  `NOT_IMPLEMENTED` note if block height genuinely isn't available from any
  in-scope source yet).
- A `composite_factor_score` is computed per screened asset with the
  weighting/method documented, and stays visibly distinct from the
  individual factors and from any later LLM/Judge confidence value.
- The screening-stage anomaly/wash-trading flag demonstrably triggers on a
  synthetic bad-volume/price-jump test case without excluding the asset
  outright.
- The full screened universe for each run is persisted (not just
  `TOP_CANDIDATES`), enabling a future survivorship-bias check.
- Zero new LLM calls/cost.
- `pytest` green without credentials.
- README updated with real tier/rate-limit findings.

Stop here, report what was built, tier/rate-limit findings, the regime
classifier's behavior (including the observed BTC dominance trend,
altcoin-season/breadth reading, and halving-cycle day-counts, or why the
latter was marked `NOT_IMPLEMENTED`), the composite factor score's chosen
weighting, and any anomaly flags observed on the live universe, and wait for
confirmation before starting 3c.
