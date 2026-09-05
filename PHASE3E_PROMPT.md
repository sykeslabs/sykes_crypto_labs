# AI Crypto Portfolio — Phase 3e: Judge, Risk Engine, Portfolio Construction, Continuous Calibration

## Context

This continues Phase 3. Complete and live-verified so far: 3a (schema/
provenance/registries), 3b (CoinMarketCap/Coinbase/Binance, screening, regime
classifier), 3c (funding rates, options, on-chain/DeFi), 3d (multi-model
assessment with shared regime context and prompt versioning).

**Before writing any code**, inspect what actually exists across 3a–3d,
especially the real shape of `model_market_assessments`, the evidence tables
from 3b/3c, and the empty `decision_outcomes` table from 3a. This sub-phase
turns existing evidence into decisions — it does not add bull/bear research,
scenario modeling, or a macro matrix (that's 3f). Build the Judge so 3f's
additional evidence types can be added as new inputs later without a
rewrite, but do not build 3f's evidence types now.

**This task is 3e only.** Stop after verification and wait for confirmation
before starting 3f.

## Non-negotiables

- PAPER ONLY. No leverage, no shorts, no live orders — Risk Engine enforces
  this regardless of what the Judge outputs.
- Judge, Risk Engine, and Portfolio Construction remain a deterministic
  pipeline of structured LLM/rule-based steps — not an agent framework.
  Agentic tooling (planned for Phase 6's exchange execution layer, where
  bounded interaction with a live/testnet exchange API genuinely benefits
  from an agent loop) is out of scope here; keep this stage's LLM calls to
  single structured request/response, same pattern as Phase 2/3d.
- Keep Judge/Risk/Portfolio output as plain, serializable structures (the
  JSON shapes below, and whatever Portfolio Construction emits) — no design
  requirement to build an API now, but Phase 5's FastAPI dashboard will read
  directly from these tables/shapes later, so avoid anything that would need
  reshaping just to be queryable.
- Judge confidence must be explicitly decoupled from model consensus. A model
  disagreement of 0.58 and a Judge confidence of 0.52 existing simultaneously
  is a valid, unremarkable output — never derive Judge confidence as an
  average of model confidences.
- `NO_TRADE` must be a real, reachable outcome. If in testing the Judge
  almost never outputs it, that's a sign of action bias in the prompt/logic —
  fix it before moving on.
- Risk Engine constraints are deterministic code, not AI-influenced.
- Every `decision_outcomes` row must be tagged with the `market_regime_snapshots`
  row in effect at decision time (`regime_at_decision`, per 3a's schema) and
  with the Judge's own confidence at decision time (`judge_confidence`,
  denormalized). Both exist specifically so accuracy can be reported *per
  regime* and *per confidence bucket*, not only in aggregate — an aggregate
  number that's only accurate because most decisions happened to fall in one
  regime is not a finding, it's a sampling artifact.
- Reserve an explicit **held-out decision window** starting from whenever
  this sub-phase's Judge first runs live: mark those `decision_outcomes` rows
  `in_holdout_window = true` (per 3a's schema) and do not use them to tune
  Judge prompts, Risk Engine formulas, or Portfolio Construction logic going
  forward. This is what lets 3f's and 3g's "did accuracy actually improve"
  comparison mean something instead of being contaminated by however many
  times the system was iterated against its own results.

## Task detail

**1. Judge (`app/judge/`).**
Input: market data + regime snapshot (3b), derivatives/on-chain evidence
(3c), model assessments + `model_agreement` (3d), existing Phase 2
`llm_analyses`/news, current portfolio status (3a). Output strict JSON:

```
{
  "asset": "LINK",
  "decision": "BUY",              // BUY | HOLD | SELL | WATCH | NO_TRADE
  "confidence": 0.67,
  "target_allocation": 0.06,
  "expected_return": 0.18,
  "expected_alpha": 0.09,
  "risk_score": 0.42,
  "uncertainty": 0.33,
  "model_agreement": 0.58,
  "source_agreement": 0.54,
  "investment_horizon_days": 90,
  "key_evidence": [],
  "contradictory_evidence": [],
  "key_risks": [],
  "invalidation_conditions": [],
  "requires_review": false,
  "thesis": "..."
}
```

`target_allocation` here is the Judge's *unconstrained* view; actual position
sizing is finalized by the Risk Engine/Portfolio Construction below, not
taken verbatim.

Add `requires_review` (bool): true whenever confidence is low, model/source
agreement is weak, or the recommended change is unusually large relative to
current exposure. This is a lightweight human-in-the-loop gate — standard
practice even in largely automated systems, especially useful while this is
new and still paper-only. It doesn't need to block anything yet in the
pipeline; it's a flag surfaced in output/logs for you to actually look at.

Instruct the Judge to weigh evidence quality, disagreement, and data
freshness/availability (using 3a's `decay_half_life_hours`, not just the
coarse bucket) — not just summarize majority view. Unavailable sources must
appear as `UNAVAILABLE`, not be silently omitted.

**2. Risk Engine (`app/risk/`).**
Deterministic, configurable via env: `MAX_SINGLE_ASSET_ALLOCATION`,
`MAX_NEW_POSITION_SIZE`, `MAX_WEEKLY_TURNOVER`, `MIN_BUY_CONFIDENCE`,
`MIN_REBALANCE_CONFIDENCE`, `MIN_SELL_CONFIDENCE`. These hard-gate the
Judge's output regardless of what it said.

Add **volatility-adjusted position sizing**: rather than taking the Judge's
`target_allocation` at face value, scale it by the asset's recent realized
volatility (already computable from 3b's screening factors) — e.g. a
capped, simplified Kelly-style or inverse-volatility adjustment, bounded by
`MAX_SINGLE_ASSET_ALLOCATION`/`MAX_NEW_POSITION_SIZE`. Keep the formula
simple and inspectable (this is a paper system, not a production risk desk) —
the goal is that two assets with equal Judge confidence but very different
volatility don't get equal-sized positions by default.

Add a basic **correlation awareness** check: compute a simple correlation
matrix across currently-held + candidate assets from historical
`market_snapshots` returns, and flag (don't necessarily block) proposed
allocations that would concentrate exposure in highly correlated assets
(e.g. multiple high-beta alts moving together) beyond what the raw
per-asset allocation caps would catch individually.

**3. Portfolio Construction (`app/portfolio/`).**
Consumes: held positions, watchlist, 3b's candidates, Judge output
(post-Risk-Engine-adjusted sizing). Can increase / hold / reduce / remove /
initiate new / hold cash — never forces full capital deployment. Implement
replacement logic: a candidate may replace an existing holding only when
`risk_adjusted_alpha(candidate) > risk_adjusted_alpha(existing) +
MIN_REPLACEMENT_ALPHA_ADVANTAGE`, configurable.

**4. Continuous decision-outcome ledger.**
Populate the `decision_outcomes` table from 3a: every Judge decision gets a
row with a defined horizon, target/stop return thresholds (simple, e.g.
symmetric around 0, or derived from the Judge's own `expected_return` and
`risk_score`), and `outcome_label = UNRESOLVED` initially. Add a scheduled or
manually-triggerable evaluation step that, for decisions past their horizon
(or that hit a target/stop earlier), backfills `realized_return` and sets
`outcome_label` to `HIT_TARGET` / `HIT_STOP` / `TIMED_OUT` using actual
subsequent `market_snapshots` data — this is a lightweight version of
triple-barrier labeling, not a full research-grade implementation. This
ledger is what makes accuracy trackable *continuously* going forward, rather
than only via the one-off baseline script below.

**5. Baseline calibration script.**
Using existing historical data already in Supabase (`market_snapshots` +
`llm_analyses` from Phase 1/2), write a script checking whether past
directional calls correlated with subsequent price movement. Report two
distinct things, not one:
- **Directional hit-rate** (was the call right), as before.
- **Calibration**: a Brier score (or log-loss) between stated confidence and
  realized outcome, plus a simple reliability breakdown (e.g. bucket
  decisions into confidence deciles/quintiles and report realized hit-rate
  per bucket). A system can have a fine hit-rate and still be badly
  overconfident or underconfident — that's a different failure mode, and one
  that matters more once position sizing (Risk Engine, above) is reading
  confidence directly.

Persist the result as a row in 3a's `calibration_runs` table (`method`,
`sample_size`, `hit_rate`, `brier_score`, which `prompt_template_ids` were in
effect). This establishes a *counted, reproducible* baseline before 3f adds
more evidence sources — "counted" matters because every future re-run of
this script against a changed prompt/logic is itself a trial, and 3g will
need an honest count of how many times this was tried, not just the final
number reported.

Do not attempt deflated-Sharpe/probability-of-backtest-overfitting
correction here — that requires more `calibration_runs` history than exists
at this point and is 3g's job. Just make sure this script's own invocation
is counted so 3g can do that correction later.

**6. Tests & docs.**
`pytest` passes without live credentials — Judge/Risk/Portfolio logic tested
against fixed input fixtures, not live API/LLM calls, including at least one
fixture that should produce `NO_TRADE` and one that should set
`requires_review = true`. Update `README.md`: mark 3e complete, document the
calibration script's baseline result and the sizing/correlation formulas
chosen.

## Exit criteria

- Live paper run produces Judge decisions — including genuine `NO_TRADE`s and
  at least occasional `requires_review = true` — that respect Risk Engine
  constraints.
- Position sizes visibly differ by volatility, not just by Judge confidence.
- Correlation flag demonstrably triggers on a concentrated/correlated test
  scenario.
- `decision_outcomes` rows are created for real decisions and the evaluation
  step correctly backfills at least a synthetic past-horizon test case.
- Calibration script runs against real historical data and produces a
  documented baseline number for both hit-rate and Brier score, persisted to
  `calibration_runs`.
- `decision_outcomes` rows carry `regime_at_decision`, `judge_confidence`,
  and `in_holdout_window`, and the held-out window's boundary is documented
  in the README.
- `pytest` green without credentials.
- README updated.

Stop here, report the Judge/Risk/Portfolio behavior observed and the baseline
calibration result, and wait for confirmation before starting 3f.
