# Phase 3 — Locked decisions (pre-3a)

Two ambiguities were identified while reviewing the 3a–3k prompts before
implementation started. Both are schema/convention decisions, and 3a is the
cheapest point in the whole roadmap to fix them — once 3b–3g start writing
against these tables, changing either becomes a migration with backfill
risk instead of a text edit. Both are now locked and reflected directly in
`doc/prompts/done/PHASE3A_PROMPT.md` / `doc/prompts/done/PHASE3E_PROMPT.md`.

## Decision 1 — Judge decision table

**Problem:** 3a's `decision_outcomes.decision_id` was specified as an FK "to
wherever Judge decisions will live," but no sub-phase actually named or
scheduled that table. `decision_outcomes` itself is a slim outcome-tracker
(horizon, target/stop, realized return) — it was never meant to hold the
full narrative (thesis, key evidence, contradictory evidence, invalidation
conditions) that the Judge's JSON output in 3e actually produces.

**Decision:** Reserve the table now, in 3a, empty — same pattern already
used for `market_regime_snapshots`, `prompt_templates`, and
`calibration_runs`.

- **Name:** `judge_decisions`
- **Suggested columns:** `id, run_id, asset_id, created_at, decision
  (DecisionValue), confidence, target_allocation, expected_return,
  expected_alpha, risk_score, uncertainty, model_agreement,
  source_agreement, investment_horizon_days, key_evidence (JSONB),
  contradictory_evidence (JSONB), key_risks (JSONB),
  invalidation_conditions (JSONB), requires_review (bool), thesis (text),
  regime_id (FK to market_regime_snapshots), prompt_template_id (FK to
  prompt_templates), estimated_cost (numeric)` — the last column per
  Decision 2 below, since every Judge call is a real LLM cost.
- `decision_outcomes.decision_id` now has a real, named FK target instead
  of a placeholder comment.
- Schema only in 3a; 3e populates it (3e is already the sub-phase that
  builds the Judge and writes `decision_outcomes` rows, so this is a
  natural extension of work it already does — see the 3e prompt diff).

## Decision 2 — CostGuard extension convention

**Problem:** CostGuard currently sums `llm_analyses.estimated_cost` only.
3d adds `model_market_assessments` with its own cost column. 3e adds Judge
calls, 3f adds bull/bear/scenario calls, 3g adds reasoning-audit calls —
none of these sub-phases explicitly instructs extending CostGuard's query
to include the new table. If any one of them ships without that extension,
the daily/monthly cap is silently under-enforced: real spend exceeds the
configured cap while CostGuard only ever sees a subset of it.

**Decision:** A naming + registration convention, locked now so every later
sub-phase follows the same pattern instead of inventing its own:

1. **Every table that persists the result of an LLM call must have a
   column named exactly `estimated_cost` (numeric)** — already true of
   `llm_analyses` (Phase 2) and `model_market_assessments` (3d);
   `judge_decisions` (Decision 1) follows the same rule.
2. **A single documented registry of these tables** lives alongside
   CostGuard itself — a constant, e.g. `COST_TRACKED_TABLES` in
   `app/llm/cost.py` — listing every table CostGuard sums across.
   CostGuard's cap check becomes a sum across that registry, not a single
   hardcoded table name.
3. **Any sub-phase that adds a new LLM-call-persisting table must, as part
   of its own exit criteria:**
   - name the table with an `estimated_cost` column,
   - add it to `COST_TRACKED_TABLES`,
   - add a test asserting CostGuard's cumulative sum reflects a row
     inserted into the new table — not just that the table exists.

This turns "extend CostGuard" from an implicit assumption into a checklist
item every relevant sub-phase prompt is now graded against directly, rather
than relying on each one remembering to do it unprompted. All four
LLM-call-persisting tables across the roadmap are now named and wired into
this convention in their own phase prompts:

- `llm_analyses` (Phase 2, pre-existing)
- `model_market_assessments` (3d) — `model_agreement` also added to its
  suggested schema (see "Also resolved" below)
- `judge_decisions` (3e — see Decision 1)
- `adversarial_research` (3f — bull/bear/scenario, one row per candidate
  per run)
- `judge_reasoning_audits` (3g — one row per sampled audited decision)

No table remains unnamed; nothing is deferred to "figure out when we get
there" anymore.

## Also resolved: `model_agreement` placement (3d)

**Problem:** 3d's exit criteria required `model_agreement` to be "computed
and stored, visibly distinct from any single model's confidence," but its
suggested `model_market_assessments` schema never listed the column.

**Decision:** `model_agreement` (numeric) is computed once per asset per
run across all configured models, then denormalized onto every model's row
for that asset/run — the same copy-for-auditability pattern already used
for `market_regime` on the same table. It is never derived as an average of
the row's own `confidence` column, per 3d's existing non-negotiable.

## Still open (not part of this lock-in, flagged for later)

Smart-contract/scam-safety screening for newly-discovered 3b candidates
(GoPlus/TokenSniffer/CertiK-class check) was flagged separately as worth an
explicit in-scope/deferred decision before 3b, not 3a. Not drafted here
since it doesn't touch 3a's schema — revisit when 3b starts.
