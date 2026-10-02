# Build: Decision-level forensic explainability (todo B [HIGH][Trust/Audit])

## Context

Read `doc/todo.md` → "[HIGH][Trust/Audit] Decision-level forensic explainability" and
the reversal note under "Declined / Not Planned" first.

Scope is **part (1) only**: surface already-stored raw LLM data for one past decision.
Part (2), bit-for-bit reproducibility (temperature 0 + seed), is out of scope.

Verified 2026-10-02:

- Raw data already persisted: `model_market_assessments.raw_response` (jsonb, has
  `run_id`), `llm_analyses.response` / `token_usage` (has `run_id`),
  `adversarial_research` (has `run_id`, `asset_id`).
- Existing endpoints: `GET /judge/decisions/{decision_id}` (`app/api/routers/judge.py`),
  `GET /assessments/asset/{asset_id}`, `GET /assessments/adversarial/asset/{asset_id}`
  (latest only), `GET /judge/reasoning-audits/decision/{decision_id}`.
- Temperatures: assessments 0.3 (`app/llm/assessment_provider.py` ~116), Judge 0.2
  (`app/judge/provider.py` ~117), no seed.

## Step 0 — required, then stop

1. Verify **how a Judge decision links to the exact inputs it saw**. Does the Judge
   run's `run_id` equal the assessment/adversarial/llm_analyses `run_id`, or do stages
   get different run_ids? Check `app/judge/service.py`, `app/judge/context.py`, the
   daily runner (`scripts/run_daily.py`), and replay. Check on 2–3 real decisions
   read-only (including both ZEC decisions from 2026-09-05).
2. If the link is ambiguous (e.g. only "latest before decision time"), say so. An
   ambiguous link must be labeled as such in the response, never presented as certain.
3. Is the Judge's own raw response stored anywhere? If not, say so (adding it is a
   separate decision).
   **Pre-answered 2026-10-02** (`doc/reviews/2026-10-02_INVESTMENT_
   VALIDITY_REVIEW.md`, §15.3), re-verify rather than re-derive from
   scratch: **no** — `judge_decisions` has no `raw_response` column.
   `JudgeProviderResult.raw_response` (`app/judge/provider.py:28-34`) is
   held in memory and only reaches a durable store via `logger.error` on
   a **parse failure** (`provider.py:178-179`) — never on a successful
   call, which is the normal case. Decide in Step 0 whether adding a
   `raw_response` column to capture the success path too is in scope for
   this prompt (cheap, additive, matches the assessment layer's existing
   convention) or a separate follow-on — don't silently expand scope
   either way, state the decision.
4. Propose the response shape. **Wait for my OK.**

## Implementation

- One endpoint: `GET /judge/decisions/{decision_id}/forensics` returning: the decision,
  prompt template ids/versions, regime snapshot id, and for that asset + linked run:
  each model's assessment incl. `raw_response`, adversarial research, related
  `llm_analyses`, reasoning audits, and the outcome. Include a `link_method` field
  ("exact run_id" / "nearest-before" etc.).
- Reuse existing repositories; add a by-run_id query only where missing.
- Auth: same as the other routers (`app/api/auth.py`). Raw responses can be large; no
  pagination needed per decision, but say if any field is unexpectedly big.
- Dashboard: a "Forensics" button on decision rows opening a modal with collapsible
  sections and raw JSON in `<pre>`. Reuse existing modal helpers in `dashboard.html`.

## Tests

Endpoint returns linked records for a fixture decision; unknown id → 404; ambiguous link
labeled; auth enforced.

## Docs (show diff first)

`doc/todo.md` (part 1 done, part 2 still open), `doc/history.md`, `doc/architecture.md`
if it lists endpoints, mirror the dashboard todo item.

## Ground rules

Simplest solution. Don't touch unrelated code. Flag uncertainty. Read-only feature: no
schema changes without asking.
