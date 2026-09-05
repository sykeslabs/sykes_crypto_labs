# AI Crypto Portfolio — Phase 3f: Adversarial Research, Scenario Modeling, Macro Matrix, Remaining Fragile Sources

## Context

This is the final sub-phase of Phase 3. Complete and live-verified so far:
3a (schema/provenance/registries), 3b (CoinMarketCap/Coinbase/Binance,
screening, regime classifier), 3c (funding/options/on-chain), 3d (multi-model
assessment), 3e (Judge, Risk Engine, Portfolio Construction, decision-outcome
ledger, baseline calibration).

**Before writing any code**, inspect what actually exists across 3a–3e,
especially the Judge's current input shape (3e) and the `signal_sources`
registry (3a) — this sub-phase's job is to add new evidence *inputs* to an
already-working Judge, not to redesign it.

This is the highest-effort, highest-risk-of-wasted-work sub-phase, and
deliberately last — the sources here (CryptoBubbles, CoinAnk, CoinGlass,
PlanB/X) are less reliably accessible than everything built in 3b/3c. Do the
feasibility checks in step 1 before writing any provider code. Expect some or
most to end up `UNAVAILABLE` — that's a fine, expected outcome, not a
failure, especially since 3b/3c already cover funding-rate positioning
(Binance) and options/volatility (Deribit) through official APIs.

## Non-negotiables

- PAPER ONLY.
- No invented API access, no undocumented scraping presented as a supported
  integration. If access isn't real and reliable, the source stays
  `UNAVAILABLE` in `signal_sources`.
- Every source keeps its original interpretation constraints (below) — none
  of these get auto-converted into a directional signal by the collector
  itself. Interpretation belongs to the Judge.
- Every new LLM call (bull research, bear research, scenario modeling) goes
  through `CostGuard`, tracked as its own stage in the cost report, and uses
  the `prompt_templates` versioning convention from 3d.
- No hard-coded macro-sensitivity assumptions without the system showing its
  per-asset reasoning.

## Task detail

**1. Feasibility check, for each of CryptoBubbles, CoinAnk, CoinGlass,
PlanB/X — before writing provider code:**
- CryptoBubbles (cryptobubbles.net): determine if reliable programmatic
  access exists at all.
- CoinAnk (coinank.com/longshort/realtime): determine actual programmatic
  access; do not invent endpoints. Note: Binance funding rates (3c) already
  give an official-API view of positioning crowding — CoinAnk is additive,
  not the only source of this signal type, so a low-effort/`UNAVAILABLE`
  outcome here is genuinely fine.
- CoinGlass (liquidation heatmap): use official/documented API only if
  available.
- PlanB / X (@100trillionUSD): determine what's actually extractable
  programmatically from X; treat as an external analyst opinion, never
  objective market data.

For each: if reliable access exists, build a provider following the 3a
evidence-provenance shape. If not, implement the provider abstraction
returning `status = UNAVAILABLE` and stop there for that source. Update
`signal_sources` accordingly either way.

**2. Source-specific interpretation constraints (preserve exactly):**
- CoinAnk long/short ratio: not automatically bullish/bearish — crowded longs
  can mean conviction, liquidation vulnerability, or contrarian bearish risk.
  Store the raw ratio; the Judge reasons about it alongside Binance's
  official funding-rate data from 3c.
- CoinGlass liquidation data: never turn liquidation clusters into an
  automatic BUY/SELL signal. Store levels/concentration/distance-to-price;
  the Judge reasons about cascade risk and liquidity magnets.
- PlanB posts: only capture a signal if the post contains an explicit
  prediction, asset, and direction (confidence only if explicitly stated). A
  BTC-specific post must never auto-propagate to other assets. If no
  investment-relevant signal can be extracted, `signal = NONE`.

**3. Bull/Bear adversarial research.**
Make this genuinely adversarial, not two independent generations from the
same context:
- Bull research builds the strongest evidence-based case (valuation,
  adoption, ecosystem growth, catalysts).
- Bear research receives the bull thesis and is explicitly instructed to
  attack it: tokenomics/unlocks, dilution, competition, leverage, regulatory
  risk, technical deterioration, narrative exhaustion.
- Where practical, let bull research see and rebut the bear case in a second
  pass.

**4. Scenario modeling.**
For serious candidates, bull/base/bear scenarios, each with: probability,
expected return, price target (if appropriate), timeframe, assumptions,
catalysts, failure conditions. Use 7d/30d/90d/180d/365d horizons where
meaningful.

**5. Macro evidence matrix.**
Track macro observations (ADP, initial claims, payrolls, CPI, PCE, Fed
expectations, Treasury yields, DXY, etc.) with source, publication timestamp,
observation date, actual/previous/consensus, surprise (if calculable),
direction, confidence, data quality. Never reduce this to a simple vote.
Require an explicit `macro_sensitivity` reasoning output per candidate asset
— "how does this macro development affect this specific asset" — rather than
a blanket assumption applied uniformly.

**6. Feed into the existing Judge from 3e.**
Add bull/bear research, scenario models, and macro evidence as additional
Judge inputs — extend the input set and prompt/logic, don't replace 3e's
decision-making approach.

**7. Cost sizing before merging.**
Bull, bear, and scenario modeling are each additional LLM calls per serious
candidate. Estimate total calls/day and cost/day, compare against
`MAX_DAILY_LLM_COST`, and reduce candidate count or batch more aggressively
rather than raising the cap by default.

**8. Re-run calibration and check the outcome ledger.**
Compare the 3e baseline against post-3f results using both the one-off
calibration script and the `decision_outcomes` ledger going forward. This
comparison is the actual point of building 3f — record whether the added
evidence sources changed accuracy or just added cost and complexity, and note
it plainly in the README even if the answer is "no measurable improvement
yet." If a source shows no measurable value after a reasonable sample of
decisions, consider disabling it via `signal_sources.enabled` rather than
leaving it on by default indefinitely.

**9. Tests & docs.**
`pytest` passes without live credentials for every new provider and stage
(mocked responses, fixed fixtures for bull/bear/scenario/macro logic). Update
`README.md`: mark 3f complete, document real availability findings for each
exploratory source, and record the calibration before/after comparison.

## Exit criteria

- `signal_sources` reflects the real, verified status of every source in the
  original vision.
- Bull/bear research is demonstrably adversarial (bear output references and
  attacks the specific bull thesis, not a generic list of risks).
- Scenario modeling and macro matrix are populated for real candidates and
  visible as distinct Judge inputs.
- Cost report includes bull/bear/scenario as their own line items.
- Calibration before/after comparison recorded, whatever the result.
- `pytest` green without credentials.
- README updated.

This completes Phase 3. Report the full before/after calibration comparison
and the real availability results across all sources before considering
Phase 4 (paper trading execution, benchmarks, and ongoing accuracy tracking
via the decision-outcomes ledger built in 3e).
