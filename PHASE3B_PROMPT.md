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

**6. Deterministic market-regime classifier.**
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

**7. Candidate output.**
Produce a ranked `TOP_CANDIDATES` list. Assets already `HELD` remain
distinguishable from newly surfaced candidates. Tag genuinely new discoveries
with the 3a `CANDIDATE` status.

**8. Tests & docs.**
`pytest` passes without live credentials (mock CoinMarketCap/Coinbase/Binance
responses). Update `README.md`: mark 3b complete, document actual field
availability/rate limits found at each provider's tier, and record the
regime classifier's chosen inputs/thresholds as a "known limitations /
decisions" note (like the existing Phase 2 section does for news coverage).

## Exit criteria

- `signal_sources` rows for CoinMarketCap, Coinbase, Binance reflect real,
  verified status.
- Live run produces a ranked `TOP_CANDIDATES` list from a configurable
  universe size.
- Cross-source disagreement (CoinGecko vs. CoinMarketCap vs.
  Coinbase/Binance) is visible in output/logs for overlapping assets.
- A `market_regime_snapshots` row is written each run with auditable inputs.
- Zero new LLM calls/cost.
- `pytest` green without credentials.
- README updated with real tier/rate-limit findings.

Stop here, report what was built, tier/rate-limit findings, and the regime
classifier's behavior, and wait for confirmation before starting 3c.
