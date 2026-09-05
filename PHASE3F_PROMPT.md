# AI Crypto Portfolio — Phase 3f: Adversarial Research, Scenario Modeling, Macro Matrix, Remaining Fragile Sources

## Context

This is the last **evidence/decision-pipeline** sub-phase of Phase 3 — 3g
(statistical validation) follows this one before Phase 4. Complete and
live-verified so far: 3a (schema/provenance/registries), 3b (CoinMarketCap/
Coinbase/Binance, screening, regime classifier), 3c (funding/open interest/
options/on-chain/stablecoin-reserve sources), 3d (multi-model assessment),
3e (Judge, Risk Engine, Portfolio Construction, decision-outcome ledger with
regime tagging and a held-out window, baseline hit-rate + Brier calibration).

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
- The held-out decision window established in 3e (`in_holdout_window = true`
  rows) is not used to tune any bull/bear/scenario prompt, Judge logic, or
  Risk Engine formula introduced here. New decisions made during 3f continue
  the same tagging convention (`regime_at_decision`, `judge_confidence`,
  `in_holdout_window`) established in 3e — this sub-phase does not get its
  own separate bookkeeping.

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
  objective market data. **Use xAI's API (Grok has native access to X/Twitter
  search) as the primary access mechanism** rather than unofficial scraping
  of X directly — verify what it actually returns for a specific account's
  recent post history, real rate limits, and real pricing before committing
  to it, the same as any other source in this feasibility check. If xAI's
  API doesn't reliably return what's needed for this specific account, fall
  back to `status = UNAVAILABLE` rather than approximating.

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
calibration script (now reporting hit-rate **and** Brier score, per 3e) and
the `decision_outcomes` ledger going forward, and persist this run to
`calibration_runs` like every other calibration attempt — this one included
in whatever trial count 3g later corrects for. Report the comparison broken
down **by regime** (`regime_at_decision`), not only in aggregate. Record
whether the added evidence sources changed accuracy or just added cost and
complexity, and note it plainly in the README even if the answer is "no
measurable improvement yet." Treat any raw before/after delta at this stage
as a candidate finding, not a conclusion — a single before/after comparison
cannot distinguish real improvement from noise or from having iterated the
prompts against the same data multiple times; 3g's deflated-Sharpe/PBO pass
is what actually adjudicates that, and this sub-phase should say so rather
than declare victory early. If a source shows no measurable value after a
reasonable sample of decisions, consider disabling it via
`signal_sources.enabled` rather than leaving it on by default indefinitely.

**9. Judge reasoning spot-check.**
Sample a handful of resolved decisions from this sub-phase's live runs —
weighted toward `requires_review = true`, low-confidence, and
low-model-agreement cases, since that's where synthesis errors are most
likely — and check whether the Judge's stored `thesis` actually follows from
its own `key_evidence`/`contradictory_evidence`, rather than sounding
plausible while quietly ignoring evidence that was fed to it. A second LLM
call (fed the same evidence + the Judge's output, asked to identify
unsupported leaps) or a manual read-through are both acceptable at this
sample size — this is a spot-check, not a new automated stage. Log findings;
do not auto-correct the Judge from this feedback in this sub-phase.

**10. Tests & docs.**
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
- Calibration before/after comparison recorded (hit-rate and Brier score,
  broken down by regime), persisted to `calibration_runs`, explicitly framed
  as provisional pending 3g's statistical correction — whatever the result.
- Judge reasoning spot-check completed and findings logged.
- `pytest` green without credentials.
- README updated.

This completes the evidence-collection and decision-pipeline portion of
Phase 3. Report the full before/after calibration comparison, the real
availability results across all sources, and the Judge reasoning spot-check
findings. Do not present the before/after delta as a confirmed accuracy
improvement — that determination belongs to 3g (statistical validation:
deflated Sharpe / probability of backtest overfitting, full calibration
reporting, and held-out-window results), which runs next, before Phase 4
(paper trading execution, benchmarks, and ongoing accuracy tracking via the
decision-outcomes ledger).
