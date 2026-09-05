# AI Crypto Portfolio — Phase 3f: Adversarial Research, Scenario Modeling, Macro Matrix (incl. Global Liquidity), Remaining Fragile Sources (incl. Social/Narrative Sentiment, Regulatory Calendar, Regional Exchange Premium)

## Context

This is the last **evidence/decision-pipeline** sub-phase of Phase 3 — 3g
(statistical validation) follows this one before Phase 4. Complete and
live-verified so far: 3a (schema/provenance/registries), 3b (CoinMarketCap/
Coinbase/Binance, screening, regime classifier, composite factor score,
anomaly flag), 3c (funding/open interest/options/on-chain/stablecoin-supply-
velocity/exchange-reserve/spot-ETF-flow/prediction-market sources), 3d
(multi-model assessment),
3e (Judge, Risk Engine, Portfolio Construction, decision-outcome ledger with
regime tagging and a held-out window, baseline hit-rate + Brier calibration).

**Before writing any code**, inspect what actually exists across 3a–3e,
especially the Judge's current input shape (3e) and the `signal_sources`
registry (3a) — this sub-phase's job is to add new evidence *inputs* to an
already-working Judge, not to redesign it.

This is the highest-effort, highest-risk-of-wasted-work sub-phase, and
deliberately last — the sources here (CryptoBubbles, CoinAnk, CoinGlass,
PlanB/X, and social/narrative sentiment) are less reliably accessible than
everything built in 3b/3c. Do the feasibility checks in step 1 before
writing any provider code. Expect some or most to end up `UNAVAILABLE` —
that's a fine, expected outcome, not a failure, especially since 3b/3c
already cover funding-rate positioning (Binance), futures term structure
(Binance/Deribit), options/volatility (Deribit), on-chain valuation cycle
metrics (MVRV/SOPR/NUPL), institutional capital rotation (spot ETF flows,
stablecoin supply/velocity), known-event supply calendars (token unlocks),
and market-priced event probabilities (prediction markets) through official
or documented-paid-tier APIs — the fragile sources here are additive color,
not the only source of any given signal type.

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
- Social/narrative sentiment (e.g. Santiment or LunarCrush-style aggregate
  social volume / trending-narrative tracking): determine actual
  programmatic access and real pricing at a usable tier — most of these
  platforms gate their fuller data behind paid plans, so verify what the
  free/cheap tier actually returns before assuming coverage. This is
  distinct from PlanB/X (one analyst's stated opinion) and from Phase 2's
  RSS news (editorial coverage) — it's an aggregate attention/narrative-
  rotation signal across many unnamed accounts, which is a different
  evidence type than either. If reliable coverage isn't achievable at a
  reasonable cost, `status = UNAVAILABLE` — this is genuinely optional
  color, not a source the Judge depends on.
- Regional exchange premium (e.g. the historically-documented "Kimchi
  premium" — the price gap between Korean exchanges such as Upbit/Bithumb
  and global venues): determine whether reliable, ToS-compliant
  programmatic access to a relevant regional exchange's public price feed
  exists. This is a genuinely distinct evidence type from the cross-source
  disagreement 3b already logs between CoinGecko/CoinMarketCap/Coinbase/
  Binance — that disagreement is aggregation/venue noise across globally
  arbitraged venues, whereas a structural regional premium reflects capital
  controls and regionally concentrated retail speculative intensity, a
  different economic mechanism. Treat this as genuinely optional color, same
  standing as CryptoBubbles or CoinAnk — a low-effort/`UNAVAILABLE` outcome
  is a fine result if the exchange's public API terms or rate limits make
  reliable access impractical; do not scrape around API restrictions to get
  it.
- Regulatory/policy event calendar: unlike the other sources in this list,
  the underlying access here is genuinely official — SEC EDGAR's full-text
  search API (enforcement actions, filings) and congress.gov's API
  (legislative tracking) are both free, documented, government sources, not
  scraped or unofficial. What's unverified is the *extraction*: reliably
  turning a raw filing or bill into a dated, asset-specific,
  investment-relevant event (e.g. "SEC enforcement action naming asset X,
  filed on date Y") is closer in risk profile to PlanB's post-parsing than
  to a clean structured-data pull — a naive keyword match will produce both
  false positives (asset mentioned incidentally) and false negatives (asset
  affected by a rule change that doesn't name it directly). Determine what a
  reasonable-effort implementation can actually extract reliably; if
  asset-level attribution can't be done without an unacceptable false-positive
  rate, it's fine to ship a narrower version (e.g. a global/macro-scope feed
  of major crypto-relevant regulatory events, not attributed to any specific
  asset) and mark the fuller per-asset version `NOT_IMPLEMENTED`, same rule
  as the rest of this sub-phase.

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
- Social/narrative sentiment: a spike in aggregate social volume or a
  trending-narrative label is an attention signal, not a fundamental or
  even necessarily a sentiment-direction signal — it can reflect genuine
  organic interest, a manufactured/coordinated pump attempt, or simply
  lagging reaction to a price move that already happened. Never
  auto-convert a social-volume spike into BUY/SELL, and never treat it as
  confirmation of the screening-stage anomaly flag from 3b without the
  Judge explicitly reasoning about which is more likely driving the other.
- Regional exchange premium: a widening premium is commonly read as a
  regional retail speculative-intensity signal, but it also has benign
  structural explanations (capital controls limiting arbitrage, local
  liquidity constraints, FX effects) unrelated to sentiment about the asset
  itself. Store the raw premium and its trend; never auto-convert it into a
  global BUY/SELL signal — it says something about one region's flow
  dynamics, not the asset's fundamentals.
- Regulatory/policy events: like a token unlock, this is a dated fact, not a
  directional signal — an enforcement action or bill's existence doesn't by
  itself say which way price moves (a settlement can remove overhang and
  rally the asset; a new charge can do the opposite; a favorable bill can
  stall in committee for years). Store the event (date, description,
  source, asset attribution if confidently extracted) raw; a
  regulatory event should generally surface in `invalidation_conditions`
  when it's asset-specific and dated near the decision horizon, same
  pattern as 3c's token-unlock schedule, rather than being pre-scored
  bullish/bearish at the collector level.

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

**5a. Forward-looking scheduled macro-event calendar.**
Task 5 above stores macro observations after they're released (actual vs.
consensus, surprise, etc.) — a distinct and useful addition is a **forward-
looking calendar** of known-in-advance release dates (FOMC decisions/
minutes, CPI, PCE, NFP/payrolls) sourced from the same official series
metadata already in reach for task 5 (e.g. FRED's release-date metadata, or
the Fed's own published FOMC schedule), analogous in kind to 3c's token
unlock/vesting calendar and 3f's regulatory event calendar below: a dated,
known-in-advance event distinct from every inferred-from-current-data source
in this project. This lets the Judge and Risk Engine reason about
**upcoming** event-driven volatility risk (e.g. "a FOMC decision falls within
this position's holding horizon") rather than only reacting to prints after
the fact. Store as dated entries, not a new source of the underlying
economic data itself — this is a calendar layer on top of task 5, not a
duplicate collector.

**5b. Global liquidity & cross-asset correlation (`GLOBAL_LIQUIDITY_MACRO`).**
Extend the macro matrix with two additional, genuinely distinct inputs that
crypto-focused macro research treats as more informative over multi-month
horizons than any single data print above:
- **Global liquidity proxies**: M2 money supply growth, the Fed's balance
  sheet (`WALCL`), and reverse repo levels, via FRED (Federal Reserve
  Economic Data) — free, official, documented, and likely already
  accessible with the same request pattern used for other macro series.
  Verify actual series availability/update cadence before committing, same
  rule as every other source.
- **Rolling cross-asset correlation**: BTC's rolling correlation (e.g. 30d/
  90d) against the S&P 500, gold, and DXY, computed from price data you
  already collect (equities/gold need a source — FRED itself carries an S&P
  500 series and several dollar-index series, which keeps this to one
  vendor relationship if it covers what you need; otherwise use another
  documented, free market-data API, and verify it before adding a new
  dependency). This is a derived analytic, not a new raw external
  observation type — compute it deterministically, store the correlation
  value alongside the window and inputs used, and do not editorialize it
  into a signal at the collector level.
**Interpretation constraint:** both of these are regime-context, not
timing signals. Global liquidity expansion is a commonly cited tailwind for
risk assets broadly, not crypto specifically, and a rising BTC-equity
correlation can mean crypto is trading as a macro risk asset (reducing its
diversification value) just as easily as it can mean anything directional
about crypto itself — feed both into `macro_sensitivity` reasoning per
asset rather than a blanket "liquidity up = bullish" rule.

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
  original vision, including social/narrative sentiment, the regulatory
  event calendar, and the regional exchange premium alongside CryptoBubbles,
  CoinAnk, CoinGlass, and PlanB/X.
- A forward-looking scheduled macro-event calendar (FOMC/CPI/PCE/NFP dates)
  is populated and visible as a distinct, dated Judge input, separate from
  the after-the-fact macro observations in task 5.
- `GLOBAL_LIQUIDITY_MACRO` (FRED-based liquidity series plus BTC's rolling
  correlation to equities/gold/DXY) is populated as part of the macro
  matrix, with the correlation window and inputs documented.
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
Phase 3 that was scoped before the 3h/3i gap-analysis addendum. Report the
full before/after calibration comparison, the real availability results
across all sources (including global liquidity/cross-asset correlation, the
regulatory event calendar, and the regional exchange premium), and the
Judge reasoning spot-check findings. Do not present the before/after delta
as a confirmed accuracy improvement — that determination belongs to 3g
(statistical validation: deflated Sharpe / probability of backtest
overfitting, full calibration reporting, and held-out-window results), which
runs next, followed by 3h (adaptive evidence-value weighting and portfolio
stress testing) and 3i (entity-flow intelligence, custody/OTC flow, and
network/developer fundamentals — a second evidence-collection addendum),
before Phase 4 (paper trading execution, benchmarks, and ongoing accuracy
tracking via the decision-outcomes ledger).
