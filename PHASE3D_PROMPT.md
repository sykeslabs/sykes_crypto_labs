# AI Crypto Portfolio — Phase 3d: Multi-Model Current Market Assessment

## Context

This continues Phase 3. Complete and live-verified so far:
- 3a: schema/provenance/registries, including empty `prompt_templates` table.
- 3b: CoinMarketCap/Coinbase/Binance data, screening, `TOP_CANDIDATES`, and a
  deterministic market-regime snapshot computed once per run.
- 3c: Binance funding rates, Deribit options, DefiLlama/on-chain data.

**Before writing any code**, inspect what actually exists: the real
`TOP_CANDIDATES` shape, the real `market_regime_snapshots` row shape, and the
real evidence tables from 3c. Also re-inspect the existing Phase 2 `app/llm/`
module — the OpenRouter config, batched one-call-per-provider pattern,
Pydantic validation + retry-on-invalid-JSON approach, and `llm_analyses`
persistence. This sub-phase adds a **new**, parallel evidence type — it does
not touch or replace `llm_analyses`.

**This task is 3d only.** Do not begin 3e (Judge/Risk/Portfolio) or 3f
(adversarial research, remaining fragile sources). Stop after 3d is verified
and wait for confirmation.

## Non-negotiables

- PAPER ONLY.
- Every LLM call goes through `CostGuard`, tracked as its own line item,
  separate from Phase 2's `llm_analyses` spend.
- Models may only reason about data actually supplied in their prompt
  context. Sources still `NOT_IMPLEMENTED` per `signal_sources` (CoinAnk,
  CoinGlass, CryptoBubbles, PlanB, until 3f) must not be referenced, and
  `source_assessment` entries must only include sources genuinely present.
- `model_agreement` is computed and stored as a distinct value from any
  individual model's confidence — never conflated or averaged into a "final"
  number here. This stage produces evidence, not a decision.
- Do not hard-code per-model weights. Treat all configured models as
  independent evidence.

## Task detail

**1. Configurable model set.**
Add `OPENROUTER_ASSESSMENT_MODELS` (or similar) so this stage's model list is
configurable independently of Phase 2's `CLAUDE_MODEL`/`OPENAI_MODEL`/
`GEMINI_MODEL`.

**2. Shared, consistent context per run.**
Every asset's prompt must include the **same** `market_regime_snapshots` row
for this run (from 3b) — don't let each model or each asset infer its own
regime label; that inconsistency was exactly what the regime classifier in
3b was built to avoid. Combine this with asset-specific evidence: market
data (CoinGecko/CMC/Coinbase/Binance), funding/options/on-chain data (3c),
existing news (Phase 2), and current portfolio status (3a).

**3. New persistence table**, e.g. `model_market_assessments`, distinct from
`llm_analyses`. Suggested columns: `id, run_id, asset_id, provider, model,
prompt_template_id (FK to 3a's prompt_templates), assessment_timestamp,
data_cutoff_timestamp, short/medium/long_term direction + confidence,
expected_return_7d/30d/90d, risk_score, market_regime (copied from the shared
snapshot for convenience/auditability), thesis, key_drivers (JSONB),
key_risks (JSONB), source_assessment (JSONB), invalidation_conditions
(JSONB), raw_response, estimated_cost, created_at`.

**4. Prompt/template versioning.**
Populate the `prompt_templates` table from 3a: whenever you change the
assessment prompt, insert a new row with an incremented `version` and a hash
of the template text, and record which `prompt_templates.id` produced each
`model_market_assessments` row. This is what makes future prompt A/B
comparisons possible against the decision-outcome ledger built in 3e — don't
skip it just because there's only one version right now.

**5. Strict JSON schema**, validated with Pydantic, following the existing
retry-on-invalid-JSON pattern. Suggested shape:

```
{
  "asset": "SOL",
  "assessment_timestamp": "...",
  "horizon": {"short_term_days": 7, "medium_term_days": 30, "long_term_days": 90},
  "direction": {"short_term": "BULLISH", "medium_term": "NEUTRAL", "long_term": "NEUTRAL"},
  "confidence": {"short_term": 0.6, "medium_term": 0.5, "long_term": 0.45},
  "expected_return": {"7d": 0.03, "30d": 0.05, "90d": 0.08},
  "risk": {"score": 0.5, "level": "MEDIUM"},
  "market_regime": "RISK_ON",
  "key_drivers": [{"factor": "...", "direction": "BULLISH", "importance": 0.7, "reason": "..."}],
  "key_risks": [{"factor": "...", "direction": "BEARISH", "importance": 0.6, "reason": "..."}],
  "source_assessment": [{"source": "BINANCE_FUNDING", "direction": "BEARISH", "importance": 0.5, "reason": "..."}],
  "thesis": "...",
  "invalidation_conditions": ["..."],
  "overall_assessment": "BULLISH"
}
```

**6. Data sanity check before context is built.**
Before assembling a coin-specific context, run a simple outlier check on the
fresh market-data inputs (e.g. a price/volume jump far outside recent
historical range vs. the same source's own recent readings). If an
observation looks like a bad tick, mark it `UNKNOWN`/exclude it rather than
handing a model a poisoned number it will confidently reason about. Keep this
simple (a z-score or percentage-jump threshold is enough) — the goal is
catching obvious feed glitches, not building an anomaly-detection system.

**7. Cost sizing before merging.**
With 3b's `TOP_CANDIDATES` count (N) and configured assessment models (M),
estimate calls/day and cost/day. Compare against `MAX_DAILY_LLM_COST`. Batch
multiple assets per provider call if needed, mirroring the Phase 2 pattern,
rather than raising the cost cap.

**8. Tests & docs.**
`pytest` passes without live credentials (mock OpenRouter responses,
including a malformed-JSON case for the retry path, and a bad-tick case for
the sanity check). Update `README.md`: mark 3d complete, document the
cost/day estimate at your chosen candidate count and model set.

## Exit criteria

- Live run produces validated, persisted assessments per configured model,
  all sharing the same run-level regime snapshot.
- `prompt_templates` populated and referenced from each assessment row.
- `model_agreement` computed and stored, visibly distinct from any single
  model's confidence.
- Sanity check demonstrably excludes/flags at least the synthetic bad-tick
  test case.
- Cost report shows this stage's spend broken out from Phase 2's.
- `pytest` green without credentials.
- README updated with real cost/day figures.

Stop here, report what was built and the actual cost/day observed, and wait
for confirmation before starting 3e.
